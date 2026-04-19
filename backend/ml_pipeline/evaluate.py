"""Automated evaluator for the ASL model backtesting dataset."""
from __future__ import annotations

import argparse
import csv
import json
import os
import subprocess
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean, median
from typing import Iterable, Sequence

import boto3
import numpy as np

from data.ground_truth import (
    DEFAULT_DATA_DIR,
    GroundTruthSample,
    decode_with_prototypes,
    load_ground_truth_dataset,
)

DEFAULT_LOG_PATH = Path(__file__).resolve().parent / "results" / "evaluation_log.csv"
DEFAULT_ENDPOINT = os.environ.get("SAGEMAKER_ENDPOINT", "nimbus-prod-asl-endpoint")
MOCK_ENDPOINT_NAME = "mock://prototype-decoder"


@dataclass(frozen=True)
class Prediction:
    tokens: list[str]
    confidence: float
    endpoint: str


@dataclass(frozen=True)
class SampleEvaluation:
    sample_id: str
    reference: list[str]
    prediction: list[str]
    confidence: float
    wer: float
    cer: float


@dataclass(frozen=True)
class EvaluationSummary:
    timestamp: str
    model_revision: str
    wer: float
    cer: float
    endpoint: str
    notes: str
    dataset_size: int
    sample_results: list[SampleEvaluation]
    substitutions: list[tuple[str, str, int]]


class PrototypeMockPredictor:
    endpoint = MOCK_ENDPOINT_NAME

    def predict(self, keypoints: np.ndarray) -> Prediction:
        tokens = decode_with_prototypes(keypoints)
        confidence = 0.99 if tokens else 0.0
        return Prediction(tokens=tokens, confidence=confidence, endpoint=self.endpoint)


class SageMakerPredictor:
    def __init__(self, endpoint_name: str) -> None:
        self.endpoint_name = endpoint_name
        self.client = boto3.client("sagemaker-runtime")

    def predict(self, keypoints: np.ndarray) -> Prediction:
        last_error: Exception | None = None
        payload_variants = (
            {"instances": [keypoints.tolist()]},
            {"instances": [{"keypoints": keypoints.reshape(-1).tolist()}]},
        )

        for payload in payload_variants:
            try:
                response = self.client.invoke_endpoint(
                    EndpointName=self.endpoint_name,
                    ContentType="application/json",
                    Accept="application/json",
                    Body=json.dumps(payload),
                )
                body = json.loads(response["Body"].read())
                tokens, confidence = _parse_endpoint_response(body)
                return Prediction(tokens=tokens, confidence=confidence, endpoint=self.endpoint_name)
            except Exception as exc:
                last_error = exc

        raise RuntimeError(f"Endpoint invocation failed for {self.endpoint_name}") from last_error


class AutoPredictor:
    def __init__(self, endpoint_name: str | None) -> None:
        self.endpoint_name = endpoint_name
        self.endpoint_predictor = SageMakerPredictor(endpoint_name) if endpoint_name else None
        self.mock_predictor = PrototypeMockPredictor()
        self._fallback_engaged = False

    @property
    def endpoint(self) -> str:
        if self._fallback_engaged and self.endpoint_name:
            return f"{self.endpoint_name} -> {MOCK_ENDPOINT_NAME}"
        if self.endpoint_name:
            return self.endpoint_name
        return MOCK_ENDPOINT_NAME

    def predict(self, keypoints: np.ndarray) -> Prediction:
        if self._fallback_engaged or self.endpoint_predictor is None:
            prediction = self.mock_predictor.predict(keypoints)
            return Prediction(prediction.tokens, prediction.confidence, self.endpoint)

        try:
            return self.endpoint_predictor.predict(keypoints)
        except Exception:
            self._fallback_engaged = True
            prediction = self.mock_predictor.predict(keypoints)
            return Prediction(prediction.tokens, prediction.confidence, self.endpoint)


def _parse_endpoint_response(payload: dict) -> tuple[list[str], float]:
    if "predictions" in payload:
        predictions = payload.get("predictions") or []
        first = predictions[0] if predictions else {}
    else:
        first = payload

    tokens = first.get("tokens")
    confidence = float(first.get("confidence", 0.0) or 0.0)
    return ([str(token) for token in tokens] if tokens else []), confidence


def detect_model_revision(repo_root: Path | None = None) -> str:
    env_revision = os.environ.get("MODEL_REVISION")
    if env_revision:
        return env_revision

    root = repo_root or Path(__file__).resolve().parents[1]
    try:
        commit = subprocess.check_output(
            ["git", "-C", str(root), "rev-parse", "--short", "HEAD"],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
        dirty = subprocess.run(
            ["git", "-C", str(root), "diff", "--quiet"],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        ).returncode
        return f"{commit}-dirty" if dirty else commit
    except Exception:
        return "unknown"


def levenshtein_alignment(reference: Sequence[str], hypothesis: Sequence[str]) -> tuple[int, list[tuple[str, str | None, str | None]]]:
    rows = len(reference) + 1
    cols = len(hypothesis) + 1
    dp = [[0] * cols for _ in range(rows)]
    back: list[list[tuple[str, int, int] | None]] = [[None] * cols for _ in range(rows)]

    for i in range(1, rows):
        dp[i][0] = i
        back[i][0] = ("delete", i - 1, 0)
    for j in range(1, cols):
        dp[0][j] = j
        back[0][j] = ("insert", 0, j - 1)

    for i in range(1, rows):
        for j in range(1, cols):
            if reference[i - 1] == hypothesis[j - 1]:
                dp[i][j] = dp[i - 1][j - 1]
                back[i][j] = ("match", i - 1, j - 1)
                continue

            candidates = (
                (dp[i - 1][j] + 1, "delete"),
                (dp[i][j - 1] + 1, "insert"),
                (dp[i - 1][j - 1] + 1, "substitute"),
            )
            cost, op = min(candidates, key=lambda item: item[0])
            dp[i][j] = cost
            back[i][j] = (op, i - 1, j - 1)

    i = len(reference)
    j = len(hypothesis)
    ops: list[tuple[str, str | None, str | None]] = []
    while i > 0 or j > 0:
        step = back[i][j]
        if step is None:
            break
        op, ref_idx, hyp_idx = step
        if op == "match":
            ops.append((op, reference[ref_idx], hypothesis[hyp_idx]))
            i -= 1
            j -= 1
        elif op == "substitute":
            ops.append((op, reference[ref_idx], hypothesis[hyp_idx]))
            i -= 1
            j -= 1
        elif op == "delete":
            ops.append((op, reference[ref_idx], None))
            i -= 1
        else:
            ops.append((op, None, hypothesis[hyp_idx]))
            j -= 1
    ops.reverse()
    return dp[-1][-1], ops


def word_error_rate(reference_tokens: Sequence[str], predicted_tokens: Sequence[str]) -> float:
    distance, _ = levenshtein_alignment(reference_tokens, predicted_tokens)
    return distance / max(1, len(reference_tokens))


def character_error_rate(reference_text: str, predicted_text: str) -> float:
    distance, _ = levenshtein_alignment(list(reference_text), list(predicted_text))
    return distance / max(1, len(reference_text))


def _substitution_counts(results: Iterable[SampleEvaluation]) -> list[tuple[str, str, int]]:
    counts: Counter[tuple[str, str]] = Counter()
    for result in results:
        _, ops = levenshtein_alignment(result.reference, result.prediction)
        for op, ref, hyp in ops:
            if op == "substitute" and ref is not None and hyp is not None:
                counts[(ref, hyp)] += 1
    return [(ref, hyp, count) for (ref, hyp), count in counts.most_common(10)]


def append_evaluation_log(summary: EvaluationSummary, log_path: Path | str = DEFAULT_LOG_PATH) -> None:
    target = Path(log_path)
    target.parent.mkdir(parents=True, exist_ok=True)

    fieldnames = ["timestamp", "model_revision", "wer", "cer", "endpoint", "dataset_size", "notes"]
    row = {
        "timestamp": summary.timestamp,
        "model_revision": summary.model_revision,
        "wer": f"{summary.wer:.6f}",
        "cer": f"{summary.cer:.6f}",
        "endpoint": summary.endpoint,
        "dataset_size": str(summary.dataset_size),
        "notes": summary.notes,
    }

    existing_rows: list[dict[str, str]] = []
    if target.exists():
        with target.open("r", newline="", encoding="utf-8") as handle:
            existing_rows = list(csv.DictReader(handle))
        if row in existing_rows:
            return

    needs_header = not target.exists() or target.stat().st_size == 0
    with target.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        if needs_header:
            writer.writeheader()
        writer.writerow(row)


def evaluate_dataset(
    samples: Sequence[GroundTruthSample],
    predictor_mode: str = "auto",
    endpoint_name: str | None = DEFAULT_ENDPOINT,
    model_revision: str | None = None,
    notes: str = "",
    log_path: Path | str = DEFAULT_LOG_PATH,
    write_log: bool = True,
) -> EvaluationSummary:
    predictor_mode = predictor_mode.lower()
    if predictor_mode == "endpoint":
        predictor = SageMakerPredictor(endpoint_name or DEFAULT_ENDPOINT)
        summary_endpoint = endpoint_name or DEFAULT_ENDPOINT
    elif predictor_mode == "mock":
        predictor = PrototypeMockPredictor()
        summary_endpoint = MOCK_ENDPOINT_NAME
    elif predictor_mode == "auto":
        predictor = AutoPredictor(endpoint_name)
        summary_endpoint = predictor.endpoint
    else:
        raise ValueError(f"Unsupported predictor_mode {predictor_mode!r}")

    sample_results: list[SampleEvaluation] = []
    for sample in samples:
        prediction = predictor.predict(sample.keypoints)
        reference_text = " ".join(sample.gloss_tokens)
        predicted_text = " ".join(prediction.tokens)
        sample_results.append(
            SampleEvaluation(
                sample_id=sample.sample_id,
                reference=sample.gloss_tokens,
                prediction=prediction.tokens,
                confidence=prediction.confidence,
                wer=word_error_rate(sample.gloss_tokens, prediction.tokens),
                cer=character_error_rate(reference_text, predicted_text),
            )
        )
        summary_endpoint = prediction.endpoint

    summary = EvaluationSummary(
        timestamp=datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        model_revision=model_revision or detect_model_revision(),
        wer=mean(result.wer for result in sample_results),
        cer=mean(result.cer for result in sample_results),
        endpoint=summary_endpoint,
        notes=notes,
        dataset_size=len(sample_results),
        sample_results=sample_results,
        substitutions=_substitution_counts(sample_results),
    )

    if write_log:
        append_evaluation_log(summary, log_path=log_path)
    return summary


def evaluate(
    ground_truth_dir: Path | str | None = None,
    predictor_mode: str = "auto",
    endpoint_name: str | None = DEFAULT_ENDPOINT,
    model_revision: str | None = None,
    notes: str = "",
    log_path: Path | str = DEFAULT_LOG_PATH,
    limit: int | None = None,
    write_log: bool = True,
) -> EvaluationSummary:
    root = Path(ground_truth_dir) if ground_truth_dir is not None else DEFAULT_DATA_DIR
    ensure_minimum = ground_truth_dir is None
    samples = load_ground_truth_dataset(root, ensure_minimum=ensure_minimum)
    if limit is not None:
        samples = samples[:limit]
    return evaluate_dataset(
        samples=samples,
        predictor_mode=predictor_mode,
        endpoint_name=endpoint_name,
        model_revision=model_revision,
        notes=notes,
        log_path=log_path,
        write_log=write_log,
    )


def format_summary(summary: EvaluationSummary, top_k: int = 5) -> str:
    lines = [
        f"Timestamp: {summary.timestamp}",
        f"Model revision: {summary.model_revision}",
        f"Endpoint: {summary.endpoint}",
        f"Dataset size: {summary.dataset_size}",
        f"Mean WER: {summary.wer:.4f}",
        f"Mean CER: {summary.cer:.4f}",
    ]

    if summary.sample_results:
        lines.append(f"Median WER: {median(result.wer for result in summary.sample_results):.4f}")
        lines.append("Worst samples:")
        for result in sorted(summary.sample_results, key=lambda item: (item.wer, item.cer), reverse=True)[:top_k]:
            lines.append(
                f"  {result.sample_id}: wer={result.wer:.4f} cer={result.cer:.4f} "
                f"ref={' '.join(result.reference)} pred={' '.join(result.prediction) or '[EMPTY]'}"
            )

    if summary.substitutions:
        lines.append("Top substitutions:")
        for ref, hyp, count in summary.substitutions[:top_k]:
            lines.append(f"  {ref} -> {hyp}: {count}")
    return "\n".join(lines)


def _build_cli() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Evaluate the ASL model against the ground-truth dataset")
    parser.add_argument("--ground-truth-dir", default=str(DEFAULT_DATA_DIR))
    parser.add_argument("--predictor-mode", choices=("auto", "endpoint", "mock"), default="auto")
    parser.add_argument("--endpoint", default=DEFAULT_ENDPOINT)
    parser.add_argument("--model-revision", default=None)
    parser.add_argument("--notes", default="")
    parser.add_argument("--log-path", default=str(DEFAULT_LOG_PATH))
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--skip-log", action="store_true")
    return parser


def main() -> None:
    parser = _build_cli()
    args = parser.parse_args()
    summary = evaluate(
        ground_truth_dir=args.ground_truth_dir,
        predictor_mode=args.predictor_mode,
        endpoint_name=args.endpoint,
        model_revision=args.model_revision,
        notes=args.notes,
        log_path=args.log_path,
        limit=args.limit,
        write_log=not args.skip_log,
    )
    print(format_summary(summary))


if __name__ == "__main__":
    main()
