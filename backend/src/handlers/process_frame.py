"""NIMBUS_PROD_ProcessFrame — AI pipeline orchestrator.

Phases implemented:
  1. Parse INFER. Browser ONNX model classifies hand landmarks into ASL letters (A–Z)
     and sends them as `token`. Held-letter runs are deduplicated in Lambda memory;
     low-confidence frames insert word-boundary space markers.
  2. Letter buffer accumulation in DynamoDB. Flush when 20 unique letters are stored,
     3s elapsed since first letter, or 1.5s pause (SWEEP via EventBridge).
  3. On flush: reconstruct words from letters + space markers, then call Bedrock
     (Claude) to produce a fluent English sentence with emotion-matched tone.
  4. Rekognition emotion detection from face-crop JPEG every 10th frame (§3.2).
  5. Polly synthesis → S3 presigned URL, emit CAPTION + SIGNAL NEW_CAPTION.
"""

from __future__ import annotations

import base64
import json
import os
import time
from typing import Any

import boto3
from botocore.config import Config
from pydantic import ValidationError

from common.emit import post_to_connection
from common.logger import bind_session, logger
from common.metrics import MetricUnit, metrics
from common.schemas import InferMessage
from common.session import append_gloss, drain_buffer, recent_captions, store_caption, update_emotion
from common.ssml import build_ssml, default_voice, get_prosody_map
from services import rekognition_emotion
from services.bedrock_interpreter import safe_interpret
from services.polly_tts import safe_synthesize

FACE_CROP_INTERVAL = 10   # PROTOCOLS.md §3.2: face crop every 10 frames
BUFFER_TOKEN_LIMIT = 20   # unique letters before flush (held-letter dedup means each slot = one distinct letter)
ELAPSED_LIMIT_MS = 3000   # PROTOCOLS.md §2.2 rule 2 (3s since firstTokenAt)

_BROADCAST_ARN = os.environ.get("BROADCAST_CAPTION_ARN", "")
_lambda_cfg = Config(retries={"max_attempts": 1, "mode": "standard"})
_lambda_client = None

# Per-Lambda-instance emotion cache — avoids a DDB read on non-face-crop 10th
# frames. Falls back to "CALM" until the first Rekognition detection.
_session_emotion: dict[str, str] = {}

# Per-Lambda-instance last-letter cache for held-letter deduplication.
# Prevents the same letter being appended every frame while the hand is held still.
_last_token: dict[str, str] = {}


def _get_lambda_client():
    global _lambda_client
    if _lambda_client is None:
        _lambda_client = boto3.client("lambda", config=_lambda_cfg)
    return _lambda_client


def _invoke_broadcast(room_id: str, caption: dict) -> None:
    if not _BROADCAST_ARN or not room_id:
        return
    try:
        _get_lambda_client().invoke(
            FunctionName=_BROADCAST_ARN,
            InvocationType="Event",
            Payload=json.dumps({"roomId": room_id, "caption": caption}).encode(),
        )
    except Exception:
        logger.exception("broadcast_caption invoke failed; caption still delivered to sender")


def _iso_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime())


def _decode_face_crop(b64: str) -> bytes | None:
    """Decode base64 face crop; return None on malformed input."""
    try:
        return base64.b64decode(b64)
    except Exception:
        return None


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


def _emit_emotion(
    event: dict,
    conn_id: str,
    session_id: str,
    label: str,
    confidence: float,
    all_emotions: dict[str, float],
) -> None:
    post_to_connection(event, conn_id, {
        "type": "EMOTION",
        "sessionId": session_id,
        "timestamp": _iso_now(),
        "payload": {"emotion": label, "confidence": confidence, "allEmotions": all_emotions},
    })


def _emit_caption(
    event: dict,
    conn_id: str,
    session_id: str,
    room_id: str,
    text: str,
    ssml_url: str | None,
    used_fallback: bool,
    emotion: str,
) -> dict:
    caption = {
        "type": "CAPTION",
        "sessionId": session_id,
        "roomId": room_id,
        "timestamp": _iso_now(),
        "payload": {
            "text": text,
            "ssmlUrl": ssml_url,
            "emotion": emotion,
            "rawGlossFallback": used_fallback,
        },
    }
    post_to_connection(event, conn_id, caption)
    _emit_signal(event, conn_id, session_id, room_id, "NEW_CAPTION", {
        "text": text,
        "ssmlUrl": ssml_url,
    })
    return caption


def _letters_to_words(raw: list[str]) -> list[str]:
    """Reconstruct words from a raw letter buffer that may contain space markers (" ").

    Example: ["H","E","L","L","O"," ","W","O","R","L","D"] → ["HELLO", "WORLD"]
    """
    joined = "".join(raw).strip()
    return [w for w in joined.split() if w]


def _should_flush(buf_attrs: dict, new_tokens: list[str]) -> bool:
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
    emotion: str = "CALM",
) -> None:
    """Drain the STATE buffer and emit CAPTION + NEW_CAPTION SIGNAL."""
    flush_start = time.perf_counter()
    raw_tokens = drain_buffer(session_id)
    if not raw_tokens:
        return

    # Fingerspelling mode: buffer holds individual letters + " " word-boundary markers.
    # Reconstruct words before sending to Bedrock.
    if all(len(t) <= 1 for t in raw_tokens):
        tokens = _letters_to_words(raw_tokens)
        if not tokens:
            logger.info("letter buffer drained but produced no words; skipping caption")
            return
        logger.info("letters reconstructed to words", extra={"raw_count": len(raw_tokens), "words": tokens})
    else:
        tokens = raw_tokens

    logger.info("buffer drained", extra={"token_count": len(tokens), "reason": "boundary"})

    context = recent_captions(session_id, limit=3)
    bedrock_start = time.perf_counter()
    text, used_fallback = safe_interpret(tokens, context, emotion=emotion)
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
        ssml = build_ssml(text, emotion=emotion, prosody_map=prosody)
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

    caption = _emit_caption(event, conn_id, session_id, room_id, text, ssml_url, used_fallback, emotion)
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

    # ── Edge-inference mode: browser ONNX classifies hand landmarks into letters ──
    # token = letter ("A"–"Z") when confident, "" when below confidence threshold.
    tokens: list[str] = []
    raw_token = msg.payload.token
    if raw_token is None:
        logger.warning("INFER message missing token field")
        return {"statusCode": 400, "body": "missing token"}

    if raw_token == "":
        # Low-confidence frame → word boundary. Insert a space marker so words
        # are separable when the buffer is later flushed and reconstructed.
        last = _last_token.get(msg.sessionId)
        if last and last != " ":
            _last_token[msg.sessionId] = " "
            tokens = [" "]
    else:
        # Deduplicate held-letter runs: holding "H" still for 5 frames stores
        # only one "H" in DynamoDB instead of five.
        last = _last_token.get(msg.sessionId)
        _last_token[msg.sessionId] = raw_token
        if raw_token != last:
            tokens = [raw_token]
            _emit_gloss(event, connection_id, msg, tokens, confidence=1.0)
            metrics.add_metric(name="GlossEventsEmitted", unit=MetricUnit.Count, value=1)
            metrics.add_metric(name="EdgeInferTokens", unit=MetricUnit.Count, value=1)
            logger.info("edge letter received", extra={"letter": raw_token})

    # Emotion detection — every FACE_CROP_INTERVAL frames (PROTOCOLS.md §3.2)
    if msg.sequenceNumber % FACE_CROP_INTERVAL == 0:
        face_bytes: bytes | None = None
        if msg.payload.faceCropBase64:
            face_bytes = _decode_face_crop(msg.payload.faceCropBase64)

        if face_bytes:
            rek_start = time.perf_counter()
            label, rek_conf, all_emotions = rekognition_emotion.detect_emotion(face_bytes)
            rek_ms = (time.perf_counter() - rek_start) * 1000
            metrics.add_metric(name="RekognitionLatencyMs", unit=MetricUnit.Milliseconds, value=rek_ms)
            _session_emotion[msg.sessionId] = label
            try:
                update_emotion(msg.sessionId, label)
            except Exception:
                logger.exception("update_emotion DDB write failed; in-memory cache still current")
            logger.info("rekognition detection", extra={"emotion": label, "latencyMs": rek_ms})
        else:
            # No face crop this frame — emit cached emotion, no Rekognition call
            label = _session_emotion.get(msg.sessionId, "CALM")
            rek_conf = 1.0
            all_emotions = {label: 1.0}

        _emit_emotion(event, connection_id, msg.sessionId, label, rek_conf, all_emotions)
        metrics.add_metric(name="EmotionEventsEmitted", unit=MetricUnit.Count, value=1)

    current_emotion = _session_emotion.get(msg.sessionId, "CALM")

    if tokens:
        try:
            buf_attrs = append_gloss(msg.sessionId, tokens, connection_id, msg.roomId, emotion=current_emotion)
            buf_size = len(buf_attrs.get("glossBuffer", []))
            logger.info("gloss appended", extra={"bufferSize": buf_size})
            if _should_flush(buf_attrs, tokens):
                _flush_and_caption(event, connection_id, msg.sessionId, msg.roomId, emotion=current_emotion)
        except Exception:
            logger.exception("session buffer / flush failed")

    total_ms = (time.perf_counter() - handler_start) * 1000
    metrics.add_metric(name="PipelineLatencyMs", unit=MetricUnit.Milliseconds, value=total_ms)
    logger.info("handler complete", extra={"stage": "complete", "latencyMs": total_ms})
    return {"statusCode": 200}


