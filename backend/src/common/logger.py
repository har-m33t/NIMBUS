"""Structured logger. correlation_id is sessionId per PROTOCOLS.md §2.1."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

try:
    from aws_lambda_powertools import Logger as _PowertoolsLogger
except ImportError:
    _PowertoolsLogger = None


class _FallbackLogger:
    def __init__(self) -> None:
        self._logger = logging.getLogger("nimbus-process-frame")
        if not self._logger.handlers:
            logging.basicConfig(level=logging.INFO)
        self._context: dict[str, Any] = {}

    def append_keys(self, **kwargs: Any) -> None:
        self._context.update({k: v for k, v in kwargs.items() if v is not None})

    def inject_lambda_context(self, func: Callable):
        return func

    def info(self, msg: str, *args: Any, **kwargs: Any) -> None:
        self._logger.info(msg, *args)

    def warning(self, msg: str, *args: Any, **kwargs: Any) -> None:
        self._logger.warning(msg, *args)

    def exception(self, msg: str, *args: Any, **kwargs: Any) -> None:
        self._logger.exception(msg, *args)


logger = (
    _PowertoolsLogger(service="nimbus-process-frame")
    if _PowertoolsLogger is not None
    else _FallbackLogger()
)


def bind_session(session_id: str, room_id: str | None = None) -> None:
    logger.append_keys(sessionId=session_id, roomId=room_id)
