"""NIMBUS_PROD_ProcessFrame — Phase 1+2+3+5 orchestrator.

Phases implemented:
  1. Parse INFER, discard faceCropBase64 (C1), SageMaker invoke, emit GLOSS/EMOTION.
  2. Sentence boundary detection (PROTOCOLS.md §2.2): flush glossBuffer on
     15 tokens / 3s elapsed / [EOS] token / 1.5s pause (SWEEP via EventBridge).
  3. Bedrock interpretation (gloss → English), raw-gloss fallback.
  5. Polly synthesis → S3 presigned URL, emit CAPTION + SIGNAL NEW_CAPTION.

Out of scope until later:
  - SWEEP action (handled in sweep.py, triggered by EventBridge).
  - Phase 6 dashboards, Phase 7 full integration tests, Phase 8 SAM template.
"""

from __future__ import annotations

import json
import os
import time
from typing import Any

import boto3
from botocore.config import Config
from pydantic import ValidationError

from common.emit import post_to_connection
from common.errors import SageMakerError
from common.logger import bind_session, logger
from common.metrics import MetricUnit, metrics
from common.schemas import InferMessage
from common.session import append_gloss, drain_buffer, recent_captions, store_caption
from common.ssml import build_ssml, default_voice, get_prosody_map
from services import sagemaker_inference
from services.bedrock_interpreter import safe_interpret
from services.polly_tts import safe_synthesize

FACE_CROP_INTERVAL = 10   # mirrors PROTOCOLS.md §3.2 cadence
BUFFER_TOKEN_LIMIT = 15   # PROTOCOLS.md §2.2 rule 1
ELAPSED_LIMIT_MS = 3000   # PROTOCOLS.md §2.2 rule 2 (3s since firstTokenAt)

_BROADCAST_ARN = os.environ.get("BROADCAST_CAPTION_ARN", "")
_lambda_cfg = Config(retries={"max_attempts": 1, "mode": "standard"})
_lambda_client = None


def _get_lambda_client():
    global _lambda_client
    if _lambda_client is None:
        _lambda_client = boto3.client("lambda", config=_lambda_cfg)
    return _lambda_client


def _invoke_broadcast(room_id: str, caption: dict) -> None:
    """Fan-out caption to all room connections via Member 1's BroadcastCaption Lambda."""
    if not _BROADCAST_ARN or not room_id:
        return
    try:
        _get_lambda_client().invoke(
            FunctionName=_BROADCAST_ARN,
            InvocationType="Event",  # async — don't block the INFER response
            Payload=json.dumps({"roomId": room_id, "caption": caption}).encode(),
        )
    except Exception:
        logger.exception("broadcast_caption invoke failed; caption still delivered to sender")


def _iso_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime())


def _emit_error(event: dict, conn_id: str, session_id: str, code: str, message: str, **extra) -> None:
    post_to_connection(event, conn_id, {
        "type": "ERROR",
        "sessionId": session_id,
        "timestamp": _iso_now(),
        "payload": {"code": code, "message": message, **extra},
    })


def _emit_signal(event: dict, conn_id: str, session_id: str, room_id: str, sig: str, payload: dict | None = None) -> None:
    post_to_connection(event, conn_id, {
        "type": "SIGNAL",
        "event": sig,
        "sessionId": session_id,
        "roomId": room_id,
        "payload": payload or {},
    })


def _emit_gloss(event: dict, conn_id: str, msg: InferMessage, tokens: list[str], confidence: float) -> None:
    post_to_connection(event, conn_id, {
        "type": "GLOSS",
        "sessionId": msg.sessionId,
        "timestamp": _iso_now(),
        "sequenceNumber": msg.sequenceNumber,
        "payload": {"tokens": tokens, "confidence": confidence},
    })


def _emit_emotion_calm(event: dict, conn_id: str, session_id: str) -> None:
    # Hackathon C1: Rekognition disabled; emit constant CALM to preserve UX contract.
    post_to_connection(event, conn_id, {
        "type": "EMOTION",
        "sessionId": session_id,
        "timestamp": _iso_now(),
        "payload": {"emotion": "CALM", "confidence": 1.0, "allEmotions": {"CALM": 1.0}},
    })


def _emit_caption(
    event: dict,
    conn_id: str,
    session_id: str,
    room_id: str,
    text: str,
    ssml_url: str | None,
    used_fallback: bool,
) -> dict:
    """Send CAPTION to sender and return the caption dict for room broadcast."""
    caption = {
        "type": "CAPTION",
        "sessionId": session_id,
        "roomId": room_id,
        "timestamp": _iso_now(),
        "payload": {
            "text": text,
            "ssmlUrl": ssml_url,
            "emotion": "CALM",
            "rawGlossFallback": used_fallback,
        },
    }
    post_to_connection(event, conn_id, caption)
    _emit_signal(event, conn_id, session_id, room_id, "NEW_CAPTION", {
        "text": text,
        "ssmlUrl": ssml_url,
    })
    return caption


def _should_flush(buf_attrs: dict, new_tokens: list[str]) -> bool:
    """Return True if any PROTOCOLS.md §2.2 boundary condition is met."""
    buf = buf_attrs.get("glossBuffer", [])
    if len(buf) >= BUFFER_TOKEN_LIMIT:
        return True
    if "[EOS]" in new_tokens:
        return True
    first_ms = int(buf_attrs.get("firstTokenAt", 0))
    if first_ms and (int(time.time() * 1000) - first_ms) >= ELAPSED_LIMIT_MS:
        return True
    return False


def _flush_and_caption(
    event: dict,
    conn_id: str,
    session_id: str,
    room_id: str,
) -> None:
    """Drain the STATE buffer and emit CAPTION + NEW_CAPTION SIGNAL. Phase 2+3+5."""
    flush_start = time.perf_counter()
    tokens = drain_buffer(session_id)
    if not tokens:
        return  # already flushed by another invocation (race)

    logger.info("buffer drained", extra={"token_count": len(tokens), "reason": "boundary"})

    context = recent_captions(session_id, limit=3)
    bedrock_start = time.perf_counter()
    text, used_fallback = safe_interpret(tokens, context, emotion="CALM")
    bedrock_ms = (time.perf_counter() - bedrock_start) * 1000
    metrics.add_metric(name="BedrockLatencyMs", unit=MetricUnit.Milliseconds, value=bedrock_ms)
    if used_fallback:
        metrics.add_metric(name="BedrockFallbacks", unit=MetricUnit.Count, value=1)
        logger.warning("bedrock fallback", extra={"token_count": len(tokens)})
    logger.info("bedrock interpret", extra={"latencyMs": bedrock_ms, "usedFallback": used_fallback})

    ssml_url: str | None = None
    polly_start = time.perf_counter()
    try:
        prosody = get_prosody_map()
        ssml = build_ssml(text, emotion="CALM", prosody_map=prosody)
        voice = default_voice(prosody)
        ssml_url = safe_synthesize(ssml, voice, session_id)
        polly_ms = (time.perf_counter() - polly_start) * 1000
        metrics.add_metric(name="PollyLatencyMs", unit=MetricUnit.Milliseconds, value=polly_ms)
        metrics.add_metric(name="PollyCharactersSynthesized", unit=MetricUnit.Count, value=len(text))
        logger.info("polly synthesize", extra={"latencyMs": polly_ms, "charCount": len(text)})
    except Exception:
        logger.exception("ssml/polly step failed; delivering caption without audio")
        metrics.add_metric(name="PollyFailures", unit=MetricUnit.Count, value=1)

    try:
        store_caption(session_id, text)
    except Exception:
        logger.exception("store_caption failed; Bedrock context history may be incomplete")

    caption = _emit_caption(event, conn_id, session_id, room_id, text, ssml_url, used_fallback)
    _invoke_broadcast(room_id, caption)
    metrics.add_metric(name="CaptionsEmitted", unit=MetricUnit.Count, value=1)
    flush_ms = (time.perf_counter() - flush_start) * 1000
    metrics.add_metric(name="FlushLatencyMs", unit=MetricUnit.Milliseconds, value=flush_ms)
    logger.info("caption emitted", extra={"flushLatencyMs": flush_ms, "textLength": len(text)})


@metrics.log_metrics
@logger.inject_lambda_context
def handler(event: dict, _context: Any) -> dict:
    handler_start = time.perf_counter()
    ctx = event.get("requestContext", {})
    connection_id = ctx.get("connectionId", "")
    route_key = ctx.get("routeKey", "")

    try:
        body = json.loads(event.get("body") or "{}")
    except json.JSONDecodeError:
        return {"statusCode": 400, "body": "invalid json"}

    if body.get("action") != "INFER":
        logger.info("ignoring non-INFER", extra={"routeKey": route_key, "action": body.get("action")})
        return {"statusCode": 200}

    try:
        msg = InferMessage.model_validate(body)
    except ValidationError as exc:
        logger.warning("schema invalid", extra={"errors": exc.errors()[:3]})
        return {"statusCode": 400, "body": "schema invalid"}

    bind_session(msg.sessionId, msg.roomId)

    if msg.payload.includeFaceCrop:
        metrics.add_metric(name="FaceCropsDiscarded", unit=MetricUnit.Count, value=1)

    if not _cold_start_checked.get("done"):
        if not sagemaker_inference.is_in_service():
            _emit_signal(event, connection_id, msg.sessionId, msg.roomId, "ENDPOINT_WARMING")
            metrics.add_metric(name="EndpointWarming", unit=MetricUnit.Count, value=1)
            _cold_start_checked["done"] = True
            return {"statusCode": 200}
        _cold_start_checked["done"] = True

    t0 = time.perf_counter()
    try:
        result = sagemaker_inference.invoke(msg.payload.keypoints)
    except SageMakerError as exc:
        metrics.add_metric(name="SageMakerErrors", unit=MetricUnit.Count, value=1)
        logger.exception("sagemaker invoke failed", extra={"stage": "sagemaker"})
        _emit_error(
            event, connection_id, msg.sessionId,
            code="SAGEMAKER_INFERENCE_FAILED",
            message=str(exc)[:200],
            glossFallback="[UNKNOWN_SIGN]",
        )
        return {"statusCode": 200}
    finally:
        sm_ms = (time.perf_counter() - t0) * 1000
        metrics.add_metric(name="SageMakerLatencyMs", unit=MetricUnit.Milliseconds, value=sm_ms)

    tokens = result["tokens"]
    confidence = result["confidence"]
    logger.info("sagemaker invoked", extra={"stage": "sagemaker", "latencyMs": sm_ms, "tokenCount": len(tokens), "confidence": confidence})

    _emit_gloss(event, connection_id, msg, tokens, confidence)
    metrics.add_metric(name="GlossEventsEmitted", unit=MetricUnit.Count, value=1)

    if msg.sequenceNumber % FACE_CROP_INTERVAL == 0:
        _emit_emotion_calm(event, connection_id, msg.sessionId)
        metrics.add_metric(name="EmotionEventsEmitted", unit=MetricUnit.Count, value=1)

    if tokens:
        try:
            buf_attrs = append_gloss(msg.sessionId, tokens, connection_id, msg.roomId)
            buf_size = len(buf_attrs.get("glossBuffer", []))
            logger.info("gloss appended", extra={"bufferSize": buf_size})
            if _should_flush(buf_attrs, tokens):
                _flush_and_caption(event, connection_id, msg.sessionId, msg.roomId)
        except Exception:
            logger.exception("session buffer / flush failed")

    total_ms = (time.perf_counter() - handler_start) * 1000
    metrics.add_metric(name="PipelineLatencyMs", unit=MetricUnit.Milliseconds, value=total_ms)
    logger.info("handler complete", extra={"stage": "complete", "latencyMs": total_ms})
    return {"statusCode": 200}


_cold_start_checked: dict[str, bool] = {}
