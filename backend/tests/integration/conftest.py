"""Shared fixtures for integration tests.

Integration tests hit the real deployed stack. They are skipped entirely when
the required environment variables aren't present, so they won't fail a CI
run against the unit-test suite.

Required env vars (copy these from the `sam deploy` stack outputs):
  NIMBUS_WEBSOCKET_URL     wss://xxxx.execute-api.<region>.amazonaws.com/prod
  NIMBUS_ROOMS_TABLE       NIMBUS_PROD_Rooms
  NIMBUS_SESSIONS_TABLE    NIMBUS_PROD_Sessions
  NIMBUS_BROADCAST_FN      NIMBUS_PROD_BroadcastCaption
  AWS_REGION               e.g. us-east-1
"""
from __future__ import annotations

import os

import pytest

REQUIRED = (
    "NIMBUS_WEBSOCKET_URL",
    "NIMBUS_ROOMS_TABLE",
    "NIMBUS_SESSIONS_TABLE",
    "NIMBUS_BROADCAST_FN",
)


def _missing() -> list[str]:
    return [v for v in REQUIRED if not os.environ.get(v)]


@pytest.fixture(scope="session", autouse=True)
def _skip_if_not_deployed():
    missing = _missing()
    if missing:
        pytest.skip(
            "Integration tests need deployed stack env vars: "
            + ", ".join(missing),
            allow_module_level=True,
        )


@pytest.fixture(scope="session")
def websocket_url() -> str:
    return os.environ["NIMBUS_WEBSOCKET_URL"]


@pytest.fixture(scope="session")
def rooms_table_name() -> str:
    return os.environ["NIMBUS_ROOMS_TABLE"]


@pytest.fixture(scope="session")
def sessions_table_name() -> str:
    return os.environ["NIMBUS_SESSIONS_TABLE"]


@pytest.fixture(scope="session")
def broadcast_function_name() -> str:
    return os.environ["NIMBUS_BROADCAST_FN"]


@pytest.fixture(scope="session")
def aws_region() -> str:
    return os.environ.get("AWS_REGION", "us-east-1")
