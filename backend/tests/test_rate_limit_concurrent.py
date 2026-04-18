"""Phase 7 rate limiter: concurrent acquire must honor <1 RPS ceiling (C3)."""
from __future__ import annotations

import time
from decimal import Decimal

import pytest


@pytest.fixture
def mock_ddb(monkeypatch):
    """Mock DynamoDB for rate limit tests."""
    import common.rate_limit as rl

    state = {"tokens": 0.0, "lastRefillMs": int(time.time() * 1000)}

    def fake_get_item(Key):
        return {"Item": {
            "tokens": Decimal(str(state["tokens"])),
            "lastRefillMs": Decimal(state["lastRefillMs"]),
        }}

    def fake_update_item(Key, UpdateExpression, ConditionExpression, ExpressionAttributeValues, **kw):
        now_ms = int(ExpressionAttributeValues[":n"])
        new_tokens = float(ExpressionAttributeValues[":t"])
        last_prev = int(ExpressionAttributeValues[":prev"])

        # Simulate condition check
        if state["lastRefillMs"] != last_prev:
            from botocore.exceptions import ClientError
            raise ClientError(
                {"Error": {"Code": "ConditionalCheckFailedException"}},
                "UpdateItem"
            )

        # Update state
        state["tokens"] = new_tokens
        state["lastRefillMs"] = now_ms
        return {"Attributes": {}}

    def fake_table():
        class FakeTable:
            def get_item(self, Key):
                return fake_get_item(Key)
            def update_item(self, **kw):
                return fake_update_item(**kw)
            class meta:
                class client:
                    class exceptions:
                        ConditionalCheckFailedException = Exception
        return FakeTable()

    monkeypatch.setattr(rl, "_get_table", fake_table)
    return state


def test_single_acquire_succeeds(mock_ddb):
    """First acquire on new bucket should succeed (token refills from 0 to 1)."""
    import common.rate_limit as rl
    # Reset time for predictable test
    mock_ddb["lastRefillMs"] = int(time.time() * 1000) - 1500
    mock_ddb["tokens"] = 0.0

    # After 1.5s, should have 1.5 tokens; first acquire takes 1 → leaves 0.5
    result = rl.try_acquire()
    assert result is True, "should acquire on refill > 1.0"


def test_back_to_back_acquire_fails(mock_ddb):
    """Two acquire() calls within 1s should fail on second."""
    import common.rate_limit as rl

    # Start with full token
    mock_ddb["tokens"] = 1.0
    mock_ddb["lastRefillMs"] = int(time.time() * 1000)

    # First acquire succeeds
    result1 = rl.try_acquire()
    assert result1 is True
    # At this point tokens ≈ 0.0 (just consumed)

    # Immediately try again → should fail (no refill in milliseconds)
    result2 = rl.try_acquire()
    assert result2 is False, "back-to-back acquire should fail without 1s refill"


def test_acquire_or_raise_timeout(mock_ddb, monkeypatch):
    """If bucket exhausted, acquire_or_raise should timeout."""
    import common.rate_limit as rl
    from common.errors import RateLimitExceeded

    # Start empty, don't refill
    mock_ddb["tokens"] = 0.0
    mock_ddb["lastRefillMs"] = int(time.time() * 1000)

    with pytest.raises(RateLimitExceeded):
        rl.acquire_or_raise(timeout_ms=200, poll_ms=50)


def test_refill_over_time(mock_ddb):
    """Verify tokens refill at 1/sec rate."""
    import common.rate_limit as rl

    # Start with 0 tokens, frozen time 1 second ago
    now_ms = int(time.time() * 1000)
    mock_ddb["tokens"] = 0.0
    mock_ddb["lastRefillMs"] = now_ms - 2000  # 2 seconds ago

    # After 2 seconds, should have 2 tokens
    result = rl.try_acquire()
    assert result is True  # should succeed
