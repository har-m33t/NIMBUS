from __future__ import annotations

import csv
import sys
from pathlib import Path
import shutil
import uuid

import pytest

ML_PIPELINE = Path(__file__).resolve().parent.parent / "ml_pipeline"
if str(ML_PIPELINE) not in sys.path:
    sys.path.insert(0, str(ML_PIPELINE))

from data.ground_truth import (  # noqa: E402
    ALLOWED_GLOSS_TOKEN_SET,
    build_bootstrap_dataset,
    load_ground_truth_dataset,
)
import evaluate as evaluator  # noqa: E402


@pytest.fixture
def workspace_tmp_path() -> Path:
    base = ML_PIPELINE / "results" / "_tmp_ml_backtesting"
    base.mkdir(parents=True, exist_ok=True)
    path = base / f"case_{uuid.uuid4().hex}"
    path.mkdir(parents=True, exist_ok=True)
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)


def test_bootstrap_ground_truth_dataset_has_minimum_shape_and_vocab(workspace_tmp_path):
    build_bootstrap_dataset(workspace_tmp_path, num_samples=50)
    samples = load_ground_truth_dataset(workspace_tmp_path, ensure_minimum=False)

    assert len(samples) == 50
    assert all(sample.keypoints.ndim == 2 and sample.keypoints.shape[1] == 258 for sample in samples)
    assert all(sample.keypoints.dtype.name == "float32" for sample in samples)
    assert all(token in ALLOWED_GLOSS_TOKEN_SET for sample in samples for token in sample.gloss_tokens)


def test_word_error_rate_and_character_error_rate():
    wer = evaluator.word_error_rate(["HELLO", "GO"], ["HELLO", "NO"])
    cer = evaluator.character_error_rate("HELLO GO", "HELLO NO")

    assert wer == pytest.approx(0.5)
    assert cer == pytest.approx(1 / 8)


def test_mock_evaluation_logs_results(workspace_tmp_path):
    build_bootstrap_dataset(workspace_tmp_path, num_samples=4)
    log_path = workspace_tmp_path / "evaluation_log.csv"

    summary = evaluator.evaluate(
        ground_truth_dir=workspace_tmp_path,
        predictor_mode="mock",
        model_revision="test-rev",
        notes="unit-test",
        log_path=log_path,
    )

    assert summary.dataset_size == 4
    assert summary.endpoint == evaluator.MOCK_ENDPOINT_NAME
    assert summary.wer == pytest.approx(0.0)
    assert summary.cer == pytest.approx(0.0)

    with log_path.open("r", newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))

    assert len(rows) == 1
    assert rows[0]["model_revision"] == "test-rev"
    assert rows[0]["notes"] == "unit-test"


def test_auto_mode_falls_back_to_mock_when_endpoint_fails(workspace_tmp_path, monkeypatch):
    build_bootstrap_dataset(workspace_tmp_path, num_samples=3)
    monkeypatch.setattr(evaluator.SageMakerPredictor, "predict", lambda self, keypoints: (_ for _ in ()).throw(RuntimeError("boom")))

    summary = evaluator.evaluate(
        ground_truth_dir=workspace_tmp_path,
        predictor_mode="auto",
        endpoint_name="nimbus-prod-asl-endpoint",
        write_log=False,
    )

    assert summary.dataset_size == 3
    assert "mock://prototype-decoder" in summary.endpoint
