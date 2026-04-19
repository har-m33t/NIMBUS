"""Amazon Bedrock (Claude) interpreter: gloss tokens → fluent English.

PROTOCOLS.md §3.1: input is glossBuffer tokens + last 3 captions for context.
Hackathon C3: all calls gated by the global DDB token bucket (< 1 RPS).
Failure fallback: return raw gloss joined by spaces (never crash silently).
"""

from __future__ import annotations

import json
import os

import boto3
from botocore.config import Config

from common.errors import BedrockError, RateLimitExceeded
from common.rate_limit import acquire_or_raise

BEDROCK_MODEL_ID = os.environ.get("BEDROCK_MODEL_ID", "anthropic.claude-3-haiku-20240307-v1:0")
MAX_TOKENS = int(os.environ.get("BEDROCK_MAX_TOKENS", "256"))
BEDROCK_TIMEOUT_MS = int(os.environ.get("BEDROCK_TIMEOUT_MS", "4000"))

_client = None


def _bedrock():
    global _client
    if _client is None:
        cfg = Config(
            read_timeout=BEDROCK_TIMEOUT_MS / 1000,
            connect_timeout=2.0,
            retries={"max_attempts": 0},
        )
        _client = boto3.client("bedrock-runtime", config=cfg)
    return _client


def _build_prompt(tokens: list[str], recent: list[str], emotion: str) -> str:
    words = " ".join(tokens)
    context = ""
    if recent:
        joined = "\n".join(f"- {c}" for c in recent[-3:])
        context = f"\nPrevious captions for context:\n{joined}\n"
    return (
        "You are an ASL interpreter. The following words were spelled letter-by-letter "
        "using ASL fingerspelling. Convert them into a single, fluent English sentence. "
        f"The signer's detected mood is {emotion}, so match the tone accordingly — "
        "a happy mood should sound warm and upbeat, angry should sound direct and firm, etc.\n"
        f"{context}\n"
        f"Fingerspelled words: {words}\n\n"
        "Respond with only the English sentence, no explanation."
    )


def interpret(
    tokens: list[str],
    recent_captions: list[str] | None = None,
    emotion: str = "CALM",
    rate_limit_timeout_ms: int = 2000,
) -> str:
    """Convert gloss tokens to English. Raises BedrockError on failure after rate-limit wait."""
    acquire_or_raise(timeout_ms=rate_limit_timeout_ms)

    prompt = _build_prompt(tokens, recent_captions or [], emotion)
    body = json.dumps({
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": MAX_TOKENS,
        "messages": [{"role": "user", "content": prompt}],
    })

    try:
        resp = _bedrock().invoke_model(
            modelId=BEDROCK_MODEL_ID,
            contentType="application/json",
            accept="application/json",
            body=body,
        )
        result = json.loads(resp["body"].read())
        return result["content"][0]["text"].strip()
    except Exception as exc:
        raise BedrockError(str(exc)[:200]) from exc


def safe_interpret(
    tokens: list[str],
    recent_captions: list[str] | None = None,
    emotion: str = "CALM",
) -> tuple[str, bool]:
    """Interpret with fallback to raw gloss. Returns (text, used_fallback)."""
    try:
        text = interpret(tokens, recent_captions, emotion)
        return text, False
    except (BedrockError, RateLimitExceeded):
        return " ".join(tokens), True
