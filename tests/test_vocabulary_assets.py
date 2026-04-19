from __future__ import annotations

import json
import pathlib
import sys


ROOT = pathlib.Path(__file__).resolve().parents[1]
ML_SRC = ROOT / "backend" / "ml_pipeline" / "src"
if str(ML_SRC) not in sys.path:
    sys.path.insert(0, str(ML_SRC))

import vocabulary  # noqa: E402


def test_vocabulary_size_and_categories():
    assert len(vocabulary.GLOSS_VOCAB) == 150
    assert vocabulary.TOKEN_TO_CATEGORY["THANK-YOU"] == "Courtesy"
    assert vocabulary.TOKEN_TO_CATEGORY["INTERPRET"] == "Verbs"
    assert vocabulary.TOKEN_TO_CATEGORY["WEEK"] == "Time"


def test_canonicalize_gloss_handles_aliases():
    assert vocabulary.canonicalize_gloss("thank you") == "THANK-YOU"
    assert vocabulary.canonicalize_gloss("good bye") == "GOODBYE"
    assert vocabulary.canonicalize_gloss("cell phone") == "PHONE"
    assert vocabulary.canonicalize_gloss("does-not-exist") == "[UNKNOWN_SIGN]"


def test_committed_handshape_asset_matches_vocab():
    asset_path = ROOT / "backend" / "ml_pipeline" / "data" / "gloss_to_handshapes.json"
    payload = json.loads(asset_path.read_text(encoding="utf-8"))

    assert list(payload) == vocabulary.GLOSS_VOCAB
    assert payload["HELLO"]["profile_id"] == "greeting-salute"
    assert payload["WATER"]["handshape_configurations"]["dominant_start"] == "W"
    assert payload["[PAD]"]["category"] == "Special"
