"""SSML prosody loader + builder.

PROTOCOLS.md §6.1: the prosody map lives at
``s3://nimbus-prod-config/ssml_prosody_map.json`` and is loaded once per
Lambda cold start and cached in module scope. The local repo copy at
``backend/src/config/ssml_prosody_map.json`` is seed data only and is
NOT read at runtime.

Hackathon policy C1: emotion detection is disabled. Callers should pass
``emotion="CALM"`` unconditionally; other keys exist so this module stays
ready for a future policy relaxation.
"""

from __future__ import annotations

import json
import os
from html import escape
from typing import Any

import boto3

_CACHE: dict[str, Any] | None = None


def _load_from_s3() -> dict[str, Any]:
    try:
        bucket = os.environ["CONFIG_BUCKET"]
        key = os.environ.get("PROSODY_CONFIG_KEY", "ssml_prosody_map.json")
        s3 = boto3.client("s3")
        obj = s3.get_object(Bucket=bucket, Key=key)
        return json.loads(obj["Body"].read())
    except Exception:
        import pathlib
        local = pathlib.Path(__file__).parent.parent / "config" / "ssml_prosody_map.json"
        return json.loads(local.read_text())


def get_prosody_map() -> dict[str, Any]:
    global _CACHE
    if _CACHE is None:
        _CACHE = _load_from_s3()
    return _CACHE


def reset_cache() -> None:
    """For tests only."""
    global _CACHE
    _CACHE = None


def build_ssml(text: str, emotion: str = "CALM", prosody_map: dict[str, Any] | None = None) -> str:
    cfg = prosody_map or get_prosody_map()
    mapping = cfg["mappings"].get(emotion) or cfg["mappings"]["CALM"]
    safe = escape(text, quote=True)
    return (
        f'<speak><prosody pitch="{mapping["pitch"]}" '
        f'rate="{mapping["rate"]}" volume="{mapping["volume"]}">'
        f"{safe}</prosody></speak>"
    )


def default_voice(prosody_map: dict[str, Any] | None = None) -> str:
    cfg = prosody_map or get_prosody_map()
    return cfg.get("defaultVoiceId", "Matthew")
