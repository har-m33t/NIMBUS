"""NIMBUS_PROD_ProcessFrame — AI pipeline orchestrator.

Phases implemented:
  1. Parse INFER, run SageMaker ASL inference, emit GLOSS.
  2. Sentence boundary detection (PROTOCOLS.md §2.2): flush glossBuffer on
     15 tokens / 3s elapsed / [EOS] token / 1.5s pause (SWEEP via EventBridge).
  3. Bedrock interpretation (gloss → English), raw-gloss fallback.
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
from common.errors import SageMakerError
from common.logger import bind_session, logger
from common.metrics import MetricUnit, metrics
from common.schemas import InferMessage
from common.session import append_gloss, drain_buffer, recent_captions, store_caption, update_emotion
from common.ssml import build_ssml, default_voice, get_prosody_map
from services import rekognition_emotion, sagemaker_inference, translate_service
from services.bedrock_interpreter import safe_interpret
from services.polly_tts import safe_synthesize

FACE_CROP_INTERVAL = 10   # PROTOCOLS.md §3.2: face crop every 10 frames
BUFFER_TOKEN_LIMIT = 15   # PROTOCOLS.md §2.2 rule 1
ELAPSED_LIMIT_MS = 3000   # PROTOCOLS.md §2.2 rule 2 (3s since firstTokenAt)

_BROADCAST_ARN = os.environ.get("BROADCAST_CAPTION_ARN", "")
_USER_PREFS_TABLE = os.environ.get("USER_PREFS_TABLE", "")
_lambda_cfg = Config(retries={"max_attempts": 1, "mode": "standard"})
_lambda_client = None
_prefs_table = None

# Per-Lambda-instance emotion cache — avoids a DDB read on non-face-crop 10th
# frames. Falls back to "CALM" until the first Rekognition detection.
_session_emotion: dict[str, str] = {}


def _get_lambda_client():
    global _lambda_client
    if _lambda_client is None:
        _lambda_client = boto3.client("lambda", config=_lambda_cfg)
    return _lambda_client


def _get_user_voice(user_id: str | None, fallback: str) -> str:
    """Look up per-user preferred Polly voice from DynamoDB. Returns fallback on any error."""
    if not user_id or not _USER_PREFS_TABLE:
        return fallback
    global _prefs_table
    try:
        if _prefs_table is None:
            _prefs_table = boto3.resource("dynamodb").Table(_USER_PREFS_TABLE)
        resp = _prefs_table.get_item(Key={"userId": user_id})
        return resp.get("Item", {}).get("preferredVoiceId", fallback)
    except Exception:
        logger.exception("user preference lookup failed; using default voice")
        return fallback


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
    target_language: str | None = None,
    user_id: str | None = None,
) -> None:
    """Drain the STATE buffer and emit CAPTION + NEW_CAPTION SIGNAL."""
    flush_start = time.perf_counter()
    tokens = drain_buffer(session_id)
    if not tokens:
        return

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

    # Translate to target language when requested (fallback: keep English text).
    effective_lang = target_language if (target_language and target_language != "en") else None
    if effective_lang:
        try:
            text = translate_service.translate_text(text, effective_lang)
            logger.info("translate applied", extra={"targetLanguage": effective_lang})
        except Exception:
            logger.exception("translate failed; delivering English caption")
            effective_lang = None  # keep English voice

    ssml_url: str | None = None
    polly_start = time.perf_counter()
    try:
        prosody = get_prosody_map()
        ssml = build_ssml(text, emotion=emotion, prosody_map=prosody)
        if effective_lang:
            voice = translate_service.voice_for_language(effective_lang)
        else:
            voice = _get_user_voice(user_id, default_voice(prosody))
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
                _flush_and_caption(
                    event, connection_id, msg.sessionId, msg.roomId,
                    emotion=current_emotion,
                    target_language=msg.targetLanguage,
                    user_id=msg.userId,
                )
        except Exception:
            logger.exception("session buffer / flush failed")

    total_ms = (time.perf_counter() - handler_start) * 1000
    metrics.add_metric(name="PipelineLatencyMs", unit=MetricUnit.Milliseconds, value=total_ms)
    logger.info("handler complete", extra={"stage": "complete", "latencyMs": total_ms})
    return {"statusCode": 200}


_cold_start_checked: dict[str, bool] = {}
