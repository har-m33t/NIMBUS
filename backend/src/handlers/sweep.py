"""NIMBUS_PROD_WS_Sweep — EventBridge-triggered boundary check.

PROTOCOLS.md §2.2 rule 3: flush glossBuffer if 1.5s has elapsed without a
new INFER frame. EventBridge fires this every 1s; each open session is checked.

Event shape (EventBridge detail):
    {"sessionId": "...", "sortKey": "...", "connectionId": "...",
     "roomId": "...", "domainName": "...", "stage": "..."}
"""

from __future__ import annotations

import os
import time
from typing import Any

import boto3

from common.emit import post_to_connection
from common.logger import logger
from common.metrics import MetricUnit, metrics
from common.session import drain_buffer, get_session, recent_captions, store_caption
from common.ssml import build_ssml, default_voice, get_prosody_map
from services.bedrock_interpreter import safe_interpret
from services.polly_tts import safe_synthesize

PAUSE_LIMIT_MS = int(os.environ.get("SWEEP_PAUSE_MS", "1500"))  # §2.2 rule 3
SESSIONS_TABLE = os.environ.get("SESSIONS_TABLE", "NIMBUS_PROD_Sessions")

_table = None


def _get_table():
    global _table
    if _table is None:
        _table = boto3.resource("dynamodb").Table(SESSIONS_TABLE)
    return _table


def _scan_active_sessions() -> list[dict]:
    """Return all STATE items that have a non-empty glossBuffer."""
    resp = _get_table().scan(
        FilterExpression="attribute_exists(glossBuffer) AND size(glossBuffer) > :zero",
        ExpressionAttributeValues={":zero": 0},
        ProjectionExpression="sessionId, sk, connectionId, roomId, domainName, #st, lastTokenAt",
        ExpressionAttributeNames={"#st": "stage"},
    )
    return resp.get("Items", [])


def _iso_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime())


def _make_apigw_event(domain: str, stage: str) -> dict:
    return {"requestContext": {"domainName": domain, "stage": stage}}


def _process_session(session_id: str, sort_key: str, connection_id: str,
                      room_id: str, domain: str, stage: str) -> None:
    """Check one session and flush if stale. Called from both scan and direct modes."""
    try:
        sess = get_session(session_id, sort_key)
    except Exception:
        logger.exception("sweep: get_session failed", extra={"stage": "sweep"})
        return

    if not sess:
        return

    buf = sess.get("glossBuffer", [])
    if not buf:
        return

    last_ms = int(sess.get("lastTokenAt", 0))
    now_ms = int(time.time() * 1000)
    stale_ms = now_ms - last_ms
    if stale_ms < PAUSE_LIMIT_MS:
        return

    logger.info("sweep: buffer stale", extra={"staleMs": stale_ms, "tokenCount": len(buf), "stage": "sweep"})
    tokens = drain_buffer(session_id, sort_key)
    if not tokens:
        return  # already flushed (race)

    apigw_event = _make_apigw_event(domain, stage)
    emotion = str(sess.get("lastEmotion", "CALM"))
    context = recent_captions(session_id, limit=3)
    text, used_fallback = safe_interpret(tokens, context, emotion=emotion)
    try:
        store_caption(session_id, text)
    except Exception:
        logger.exception("sweep: store_caption failed; context history may be incomplete")
    if used_fallback:
        metrics.add_metric(name="BedrockFallbacks", unit=MetricUnit.Count, value=1)

    ssml_url: str | None = None
    try:
        prosody = get_prosody_map()
        ssml = build_ssml(text, emotion=emotion, prosody_map=prosody)
        voice = default_voice(prosody)
        ssml_url = safe_synthesize(ssml, voice, session_id)
    except Exception:
        logger.exception("sweep: ssml/polly failed; caption without audio")

    post_to_connection(apigw_event, connection_id, {
        "type": "CAPTION",
        "sessionId": session_id,
        "roomId": room_id,
        "timestamp": _iso_now(),
        "payload": {"text": text, "ssmlUrl": ssml_url, "emotion": emotion, "rawGlossFallback": used_fallback},
    })
    post_to_connection(apigw_event, connection_id, {
        "type": "SIGNAL",
        "event": "NEW_CAPTION",
        "sessionId": session_id,
        "roomId": room_id,
        "payload": {"text": text, "ssmlUrl": ssml_url},
    })
    metrics.add_metric(name="SweepFlushes", unit=MetricUnit.Count, value=1)


@metrics.log_metrics
@logger.inject_lambda_context
def handler(event: dict, _context: Any) -> dict:
    handler_start = time.perf_counter()
    detail = event.get("detail", event)  # EventBridge wraps payload in "detail"
    session_id = detail.get("sessionId")
    sort_key = detail.get("sortKey")
    connection_id = detail.get("connectionId")
    room_id = detail.get("roomId", "")
    domain = detail.get("domainName", "")
    stage = detail.get("stage", "prod")

    # Scheduled invocation (no session detail) → scan all active sessions
    if not (session_id and sort_key and connection_id):
        sessions = _scan_active_sessions()
        for item in sessions:
            _process_session(
                session_id=item.get("sessionId", ""),
                sort_key=item.get("sk", "STATE"),
                connection_id=item.get("connectionId", ""),
                room_id=item.get("roomId", ""),
                domain=item.get("domainName", ""),
                stage=item.get("stage", "prod"),
            )
        elapsed_ms = (time.perf_counter() - handler_start) * 1000
        metrics.add_metric(name="SweepLatencyMs", unit=MetricUnit.Milliseconds, value=elapsed_ms)
        logger.info("sweep scan complete", extra={"scanned": len(sessions), "latencyMs": elapsed_ms})
        return {"statusCode": 200}

    # Direct invocation with specific session detail
    _process_session(session_id, sort_key, connection_id, room_id, domain, stage)
    elapsed_ms = (time.perf_counter() - handler_start) * 1000
    metrics.add_metric(name="SweepLatencyMs", unit=MetricUnit.Milliseconds, value=elapsed_ms)
    logger.info("sweep complete", extra={"stage": "sweep", "latencyMs": elapsed_ms})
    return {"statusCode": 200}
