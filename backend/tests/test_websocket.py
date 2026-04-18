"""Coverage for services.websocket — fan-out + GoneException handling."""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest
from botocore.exceptions import ClientError

from services import websocket


def _gone_error() -> ClientError:
    return ClientError(
        error_response={"Error": {"Code": "GoneException", "Message": "gone"}},
        operation_name="PostToConnection",
    )


def _other_error() -> ClientError:
    return ClientError(
        error_response={"Error": {"Code": "InternalServerError"}},
        operation_name="PostToConnection",
    )


@patch.object(websocket, "_client")
def test_post_to_connection_success_returns_true(mock_factory):
    mock_client = MagicMock()
    mock_factory.return_value = mock_client

    assert websocket.post_to_connection("conn-1", {"hello": "world"}) is True

    args = mock_client.post_to_connection.call_args.kwargs
    assert args["ConnectionId"] == "conn-1"
    assert json.loads(args["Data"].decode("utf-8")) == {"hello": "world"}


@patch.object(websocket, "_client")
def test_post_to_connection_gone_returns_false(mock_factory):
    mock_client = MagicMock()
    mock_client.post_to_connection.side_effect = _gone_error()
    mock_factory.return_value = mock_client

    assert websocket.post_to_connection("stale", {"hi": 1}) is False


@patch.object(websocket, "_client")
def test_post_to_connection_other_errors_raise(mock_factory):
    mock_client = MagicMock()
    mock_client.post_to_connection.side_effect = _other_error()
    mock_factory.return_value = mock_client

    with pytest.raises(ClientError):
        websocket.post_to_connection("c", {})


@patch.object(websocket, "post_to_connection")
def test_broadcast_returns_empty_when_all_succeed(mock_post):
    mock_post.return_value = True
    assert websocket.broadcast(["a", "b", "c"], {}) == []
    assert mock_post.call_count == 3


@patch.object(websocket, "post_to_connection")
def test_broadcast_collects_stale_connections(mock_post):
    mock_post.side_effect = [True, False, True, False]
    stale = websocket.broadcast(["a", "b", "c", "d"], {"type": "CAPTION"})
    assert stale == ["b", "d"]


@patch.object(websocket, "post_to_connection")
def test_broadcast_empty_connection_list_is_noop(mock_post):
    assert websocket.broadcast([], {}) == []
    mock_post.assert_not_called()


def test_client_without_endpoint_raises(monkeypatch):
    monkeypatch.setattr(websocket, "_WS_ENDPOINT", "")
    with pytest.raises(RuntimeError, match="WEBSOCKET_ENDPOINT"):
        websocket._client()
