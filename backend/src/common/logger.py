"""Structured logger. correlation_id is sessionId per PROTOCOLS.md §2.1."""

from aws_lambda_powertools import Logger

logger = Logger(service="nimbus-process-frame")


def bind_session(session_id: str, room_id: str | None = None) -> None:
    logger.append_keys(sessionId=session_id, roomId=room_id)
