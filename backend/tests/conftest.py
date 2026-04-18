"""Shared pytest setup for backend/.

Ensures the env vars that handler modules read at import time are present,
and puts backend/src/ on sys.path so imports like `from services import dynamo`
resolve the same way they do inside a Lambda deployment package.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

# Handler modules under backend/src/ are packaged as top-level in Lambda
# (CodeUri: src/). Mirror that here.
_SRC = Path(__file__).resolve().parent.parent / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

# Env vars required by services/dynamo.py and services/websocket.py at import.
os.environ.setdefault("SESSIONS_TABLE", "NIMBUS_TEST_Sessions")
os.environ.setdefault("ROOMS_TABLE", "NIMBUS_TEST_Rooms")
os.environ.setdefault("USER_PREFS_TABLE", "NIMBUS_TEST_UserPreferences")
os.environ.setdefault(
    "WEBSOCKET_ENDPOINT",
    "https://test.execute-api.us-east-1.amazonaws.com/prod",
)
os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")
