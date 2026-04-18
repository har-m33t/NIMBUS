"""Lightweight response helpers for WebSocket Lambda route handlers."""
from __future__ import annotations

import json


def ok(body: dict | None = None) -> dict:
    return {
        "statusCode": 200,
        "body": json.dumps(body or {"ok": True}),
    }


def bad_request(message: str) -> dict:
    return {
        "statusCode": 400,
        "body": json.dumps({"ok": False, "error": message}),
    }


def server_error(message: str) -> dict:
    return {
        "statusCode": 500,
        "body": json.dumps({"ok": False, "error": message}),
    }
