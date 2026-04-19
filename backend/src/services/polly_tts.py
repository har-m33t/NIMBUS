"""Amazon Polly TTS service.

PROTOCOLS.md §5.1: synthesize SSML → MP3 → upload to S3 → presigned URL.
S3 bucket must have Block Public Access enabled (hackathon constraint C2).
Failure fallback: raise PollyError; caller emits CAPTION without ssmlUrl.
"""

from __future__ import annotations

import os
import uuid

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

from common.errors import PollyError

TTS_BUCKET = os.environ.get("TTS_BUCKET", "nimbus-prod-tts-audio")
PRESIGN_TTL = int(os.environ.get("TTS_PRESIGN_TTL_S", "900"))  # 15 min
DEFAULT_VOICE = os.environ.get("POLLY_VOICE_ID", "Matthew")
OUTPUT_FORMAT = "mp3"
_AWS_REGION = os.environ.get("AWS_REGION", "us-west-2")

_polly = None
_s3 = None


def _polly_client():
    global _polly
    if _polly is None:
        _polly = boto3.client("polly", region_name=_AWS_REGION)
    return _polly


def _s3_client():
    global _s3
    if _s3 is None:
        # SigV4 required: V2 pre-signed URLs with STS temporary credentials fail
        # when the bucket is not in us-east-1, and for Range GET requests on iOS.
        _s3 = boto3.client(
            "s3",
            region_name=_AWS_REGION,
            config=Config(signature_version="s3v4"),
        )
    return _s3


def synthesize(ssml: str, voice_id: str = DEFAULT_VOICE, session_id: str = "unknown") -> str:
    """Synthesize SSML to MP3, upload to S3, return presigned URL. Raises PollyError on failure."""
    try:
        resp = _polly_client().synthesize_speech(
            Text=ssml,
            TextType="ssml",
            OutputFormat=OUTPUT_FORMAT,
            VoiceId=voice_id,
        )
        audio_bytes = resp["AudioStream"].read()
    except Exception as exc:
        raise PollyError(f"Polly synthesis failed: {exc}") from exc

    key = f"tts/{session_id}/{uuid.uuid4()}.mp3"
    try:
        _s3_client().put_object(
            Bucket=TTS_BUCKET,
            Key=key,
            Body=audio_bytes,
            ContentType="audio/mpeg",
        )
        url = _s3_client().generate_presigned_url(
            "get_object",
            Params={"Bucket": TTS_BUCKET, "Key": key},
            ExpiresIn=PRESIGN_TTL,
        )
    except (ClientError, Exception) as exc:
        raise PollyError(f"S3 upload failed: {exc}") from exc

    return url


def safe_synthesize(
    ssml: str,
    voice_id: str = DEFAULT_VOICE,
    session_id: str = "unknown",
) -> str | None:
    """Synthesize with fallback to None (CAPTION delivered without audio)."""
    try:
        return synthesize(ssml, voice_id, session_id)
    except PollyError:
        return None
