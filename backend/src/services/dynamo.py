"""DynamoDB access helpers for NIMBUS signaling Lambdas.

Tables (PROTOCOLS.md §5.3):
  NIMBUS_PROD_Sessions       PK=sessionId, SK=sk
  NIMBUS_PROD_Rooms          PK=roomId,    SK=connectionId
  NIMBUS_PROD_UserPreferences PK=userId

The Sessions table also stores a reverse-lookup item keyed by
PK="CONN#<connectionId>", SK="INDEX" so $disconnect can resolve
connectionId back to sessionId / roomId without a table scan.
"""
from __future__ import annotations

import os
import time
from typing import Iterable, Optional

import boto3
from botocore.config import Config

_SESSION_TTL_SECONDS = 4 * 60 * 60  # matches PROTOCOLS.md §2.1

_boto_config = Config(retries={"max_attempts": 3, "mode": "standard"})
_dynamodb = boto3.resource("dynamodb", config=_boto_config)

SESSIONS_TABLE = os.environ["SESSIONS_TABLE"]
ROOMS_TABLE = os.environ["ROOMS_TABLE"]

_sessions = _dynamodb.Table(SESSIONS_TABLE)
_rooms = _dynamodb.Table(ROOMS_TABLE)


def _ttl() -> int:
    return int(time.time()) + _SESSION_TTL_SECONDS


def _iso_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def put_session_state(
    session_id: str,
    connection_id: str,
    room_id: Optional[str] = None,
) -> None:
    # Member 1 only seeds fields it owns (connection + room linkage). Other
    # pipeline state (glossBuffer, lastEmotion, etc.) is additive — the
    # ProcessFrame Lambda writes those on first flush, and they may be
    # removed entirely if the corresponding feature is dropped.
    _sessions.put_item(
        Item={
            "sessionId": session_id,
            "sk": "STATE",
            "connectionId": connection_id,
            "roomId": room_id or "",
            "createdAt": _iso_now(),
            "ttl": _ttl(),
        }
    )


def put_connection_index(
    connection_id: str,
    session_id: str,
    room_id: Optional[str] = None,
) -> None:
    _sessions.put_item(
        Item={
            "sessionId": f"CONN#{connection_id}",
            "sk": "INDEX",
            "connectionId": connection_id,
            "sessionIdRef": session_id,
            "roomId": room_id or "",
            "ttl": _ttl(),
        }
    )


def get_connection_index(connection_id: str) -> Optional[dict]:
    resp = _sessions.get_item(
        Key={"sessionId": f"CONN#{connection_id}", "sk": "INDEX"}
    )
    return resp.get("Item")


def delete_connection_index(connection_id: str) -> None:
    _sessions.delete_item(
        Key={"sessionId": f"CONN#{connection_id}", "sk": "INDEX"}
    )


def update_session_room(session_id: str, room_id: str) -> None:
    _sessions.update_item(
        Key={"sessionId": session_id, "sk": "STATE"},
        UpdateExpression="SET roomId = :r, #t = :t",
        ExpressionAttributeNames={"#t": "ttl"},
        ExpressionAttributeValues={":r": room_id, ":t": _ttl()},
    )


def join_room(room_id: str, connection_id: str, session_id: str) -> None:
    _rooms.put_item(
        Item={
            "roomId": room_id,
            "connectionId": connection_id,
            "sessionId": session_id,
            "joinedAt": _iso_now(),
            "ttl": _ttl(),
        }
    )


def leave_room(room_id: str, connection_id: str) -> None:
    _rooms.delete_item(Key={"roomId": room_id, "connectionId": connection_id})


def list_room_connections(room_id: str) -> Iterable[str]:
    """Yield every connectionId currently in a room.

    Paginates through Query responses so large rooms don't silently truncate.
    """
    last_key = None
    while True:
        kwargs = {
            "KeyConditionExpression": "roomId = :r",
            "ExpressionAttributeValues": {":r": room_id},
            "ProjectionExpression": "connectionId",
        }
        if last_key is not None:
            kwargs["ExclusiveStartKey"] = last_key
        resp = _rooms.query(**kwargs)
        for item in resp.get("Items", []):
            yield item["connectionId"]
        last_key = resp.get("LastEvaluatedKey")
        if not last_key:
            return
