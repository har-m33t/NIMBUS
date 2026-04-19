"""Coverage for services.dynamo.list_room_peers."""
from __future__ import annotations

from unittest.mock import patch


def test_list_room_peers_returns_connection_and_session():
    with patch("services.dynamo._rooms") as mock_rooms:
        mock_rooms.query.return_value = {
            "Items": [
                {"connectionId": "conn-A", "sessionId": "sess-A"},
                {"connectionId": "conn-B", "sessionId": "sess-B"},
            ],
            "LastEvaluatedKey": None,
        }

        from services import dynamo
        result = list(dynamo.list_room_peers("room-1"))

    assert result == [
        {"connectionId": "conn-A", "sessionId": "sess-A"},
        {"connectionId": "conn-B", "sessionId": "sess-B"},
    ]


def test_list_room_peers_paginates():
    with patch("services.dynamo._rooms") as mock_rooms:
        mock_rooms.query.side_effect = [
            {
                "Items": [{"connectionId": "conn-A", "sessionId": "sess-A"}],
                "LastEvaluatedKey": {"roomId": "room-1", "connectionId": "conn-A"},
            },
            {
                "Items": [{"connectionId": "conn-B", "sessionId": "sess-B"}],
                "LastEvaluatedKey": None,
            },
        ]

        from services import dynamo
        result = list(dynamo.list_room_peers("room-1"))

    assert len(result) == 2
    assert result[0]["connectionId"] == "conn-A"
    assert result[1]["connectionId"] == "conn-B"
