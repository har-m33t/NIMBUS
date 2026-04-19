"""NIMBUS_PROD_SavePreferences — save per-user Polly voice preference.

POST /preferences  { userId: string, preferredVoiceId: string }
Writes to NIMBUS_PROD_UserPreferences DynamoDB table.
"""

from __future__ import annotations

import json
import os

import boto3

_TABLE = os.environ.get("USER_PREFS_TABLE", "")
_ddb_table = None

ALLOWED_VOICES = {
    "Matthew", "Joanna", "Kendra", "Joey", "Ivy",
    "Amy", "Brian", "Emma",
    "Olivia", "Russell",
    "Aditi", "Raveena",
    "Salli", "Kimberly", "Stephen",
}

_CORS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Headers": "Content-Type,Authorization",
    "Access-Control-Allow-Methods": "POST,OPTIONS",
}


def _table():
    global _ddb_table
    if _ddb_table is None:
        _ddb_table = boto3.resource("dynamodb").Table(_TABLE)
    return _ddb_table


def handler(event: dict, _context) -> dict:
    # Pre-flight CORS
    if event.get("requestContext", {}).get("http", {}).get("method") == "OPTIONS":
        return {"statusCode": 204, "headers": _CORS, "body": ""}

    try:
        body = json.loads(event.get("body") or "{}")
    except (json.JSONDecodeError, TypeError):
        return {"statusCode": 400, "headers": _CORS, "body": json.dumps({"error": "invalid json"})}

    user_id = (body.get("userId") or "").strip()
    voice_id = (body.get("preferredVoiceId") or "").strip()

    if not user_id:
        return {"statusCode": 400, "headers": _CORS, "body": json.dumps({"error": "userId required"})}
    if not voice_id or voice_id not in ALLOWED_VOICES:
        return {
            "statusCode": 400,
            "headers": _CORS,
            "body": json.dumps({"error": f"preferredVoiceId must be one of: {sorted(ALLOWED_VOICES)}"}),
        }

    try:
        _table().put_item(Item={"userId": user_id, "preferredVoiceId": voice_id})
    except Exception as exc:
        return {"statusCode": 500, "headers": _CORS, "body": json.dumps({"error": str(exc)[:200]})}

    return {
        "statusCode": 200,
        "headers": _CORS,
        "body": json.dumps({"saved": True, "preferredVoiceId": voice_id}),
    }
