"""Coverage for services.response — shape + status codes only."""
from __future__ import annotations

import json

from services import response


def test_ok_default_body():
    resp = response.ok()
    assert resp["statusCode"] == 200
    assert json.loads(resp["body"]) == {"ok": True}


def test_ok_custom_body_is_serialized():
    resp = response.ok({"delivered": 3, "pruned": 1})
    assert resp["statusCode"] == 200
    assert json.loads(resp["body"]) == {"delivered": 3, "pruned": 1}


def test_bad_request_carries_error():
    resp = response.bad_request("sessionId is required")
    assert resp["statusCode"] == 400
    body = json.loads(resp["body"])
    assert body == {"ok": False, "error": "sessionId is required"}


def test_server_error_carries_error():
    resp = response.server_error("DDB down")
    assert resp["statusCode"] == 500
    body = json.loads(resp["body"])
    assert body == {"ok": False, "error": "DDB down"}
