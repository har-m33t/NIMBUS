import json
from pathlib import Path

from common.ssml import build_ssml, default_voice

SEED = json.loads(
    (Path(__file__).parents[1] / "src" / "config" / "ssml_prosody_map.json").read_text()
)


def test_calm_wraps_prosody():
    out = build_ssml("Hello there.", emotion="CALM", prosody_map=SEED)
    assert out.startswith("<speak><prosody ")
    assert 'pitch="+0%"' in out
    assert 'rate="95%"' in out
    assert "Hello there." in out


def test_xml_escape():
    out = build_ssml("Tom & Jerry <3", emotion="CALM", prosody_map=SEED)
    assert "&amp;" in out
    assert "&lt;3" in out


def test_unknown_emotion_falls_back_to_calm():
    out = build_ssml("hi", emotion="MYSTERY", prosody_map=SEED)
    assert 'pitch="+0%"' in out


def test_default_voice_from_seed():
    assert default_voice(SEED) == "Matthew"
