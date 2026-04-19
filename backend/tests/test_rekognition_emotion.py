"""Unit tests for services.rekognition_emotion."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from services import rekognition_emotion


def _rek_response(emotions: list[dict]) -> dict:
    return {"FaceDetails": [{"Emotions": emotions}]}


def test_happy_detection():
    resp = _rek_response([
        {"Type": "HAPPY", "Confidence": 93.0},
        {"Type": "CALM",  "Confidence": 5.0},
        {"Type": "SAD",   "Confidence": 2.0},
    ])
    with patch.object(rekognition_emotion, "_get_client") as mock_client:
        mock_client.return_value.detect_faces.return_value = resp
        label, conf, all_emo = rekognition_emotion.detect_emotion(b"JPEG" * 500)

    assert label == "HAPPY"
    assert abs(conf - 0.93) < 1e-4
    assert all_emo["HAPPY"] == pytest.approx(0.93, abs=1e-4)
    assert all_emo["CALM"] == pytest.approx(0.05, abs=1e-4)


def test_label_mapping_all_eight():
    rek_types = ["HAPPY", "SAD", "ANGRY", "CALM", "SURPRISED", "FEAR", "DISGUSTED", "CONFUSED"]
    for t in rek_types:
        resp = _rek_response([{"Type": t, "Confidence": 99.0}])
        with patch.object(rekognition_emotion, "_get_client") as mock_client:
            mock_client.return_value.detect_faces.return_value = resp
            label, _, _ = rekognition_emotion.detect_emotion(b"JPEG" * 500)
        assert label == t, f"label mapping failed for {t}"


def test_fallback_on_api_exception():
    with patch.object(rekognition_emotion, "_get_client") as mock_client:
        mock_client.return_value.detect_faces.side_effect = RuntimeError("throttled")
        label, conf, all_emo = rekognition_emotion.detect_emotion(b"JPEG" * 500)

    assert label == "CALM"
    assert conf == 1.0
    assert all_emo == {"CALM": 1.0}


def test_fallback_on_no_faces():
    with patch.object(rekognition_emotion, "_get_client") as mock_client:
        mock_client.return_value.detect_faces.return_value = {"FaceDetails": []}
        label, conf, _ = rekognition_emotion.detect_emotion(b"JPEG" * 500)

    assert label == "CALM"
    assert conf == 1.0


def test_fallback_on_empty_bytes():
    label, conf, _ = rekognition_emotion.detect_emotion(b"")
    assert label == "CALM"


def test_fallback_on_small_payload():
    label, conf, _ = rekognition_emotion.detect_emotion(b"tiny")
    assert label == "CALM"


def test_unknown_rekognition_type_ignored():
    resp = _rek_response([
        {"Type": "UNKNOWN_FUTURE_TYPE", "Confidence": 80.0},
        {"Type": "HAPPY", "Confidence": 20.0},
    ])
    with patch.object(rekognition_emotion, "_get_client") as mock_client:
        mock_client.return_value.detect_faces.return_value = resp
        label, _, all_emo = rekognition_emotion.detect_emotion(b"JPEG" * 500)

    assert label == "HAPPY"
    assert "UNKNOWN_FUTURE_TYPE" not in all_emo
