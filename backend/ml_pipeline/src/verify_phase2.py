"""
Validate Phase 2 ONNX artifacts for frontend handoff.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import onnxruntime as ort


SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parents[2]
WEB_PUBLIC_DIR = REPO_ROOT / "web" / "public"
LABELS_PATH = WEB_PUBLIC_DIR / "wlasl_labels.json"
MODEL_SPECS = {
    "wlasl_asl100.onnx": 100,
    "wlasl_asl2000.onnx": 2000,
}


def assert_exists(path: Path) -> None:
    assert path.exists(), f"Missing artifact: {path}"
    assert path.is_file(), f"Artifact path is not a file: {path}"
    assert path.stat().st_size > 0, f"Artifact is empty: {path}"


def resolve_onnx_dim(dim: Any) -> int:
    if isinstance(dim, int):
        assert dim > 0, f"Invalid ONNX dimension: {dim!r}"
        return dim
    if dim in (None, "", 0):
        return 1
    if isinstance(dim, str):
        return 1
    raise AssertionError(f"Unsupported ONNX dimension type: {dim!r}")


def validate_labels(path: Path) -> dict[str, Any]:
    assert_exists(path)

    with path.open("r", encoding="utf-8") as handle:
        labels = json.load(handle)

    assert isinstance(labels, dict), "Labels artifact must parse as a dictionary"
    assert labels, "Labels dictionary is empty"

    for key, value in labels.items():
        assert isinstance(key, str), f"Label key must be a string, got {type(key).__name__}"
        assert key.isdigit(), f"Label key must be a numeric string, got {key!r}"
        assert isinstance(value, str), f"Label value must be a string, got {type(value).__name__}"
        assert value.strip(), f"Label value must be non-empty for key {key!r}"

    numeric_indices = sorted(int(key) for key in labels)
    max_index = numeric_indices[-1]

    assert numeric_indices[0] == 0, f"Expected labels to start at index 0, found {numeric_indices[0]}"
    assert numeric_indices == list(range(max_index + 1)), "Labels must be contiguous from 0 to max index"
    assert max_index == 1999, f"Expected label max index 1999, found {max_index}"

    print(
        f"[labels] ok path={path} entries={len(labels)} max_index={max_index} "
        f"max_label={labels[str(max_index)]!r}"
    )
    return labels


def validate_model(path: Path, expected_output_size: int) -> dict[str, Any]:
    assert_exists(path)

    try:
        session = ort.InferenceSession(str(path), providers=["CPUExecutionProvider"])
    except Exception as exc:  # pragma: no cover - explicit fail path for artifact loading
        raise RuntimeError(f"Failed to load ONNX model {path}: {exc}") from exc

    inputs = session.get_inputs()
    assert inputs, f"ONNX model has no inputs: {path}"
    input_meta = inputs[0]
    input_shape = list(input_meta.shape)
    concrete_shape = [resolve_onnx_dim(dim) for dim in input_shape]

    dummy_input = np.random.rand(*concrete_shape).astype(np.float32)
    outputs = session.run(None, {input_meta.name: dummy_input})

    assert outputs, f"ONNX model returned no outputs: {path}"
    probability_output = outputs[0]
    output_shape = list(probability_output.shape)
    output_size = int(probability_output.size)

    assert output_size == expected_output_size, (
        f"{path.name} produced output size {output_size}, expected {expected_output_size}. "
        f"Output shape: {output_shape}"
    )

    print(
        f"[model] ok path={path} input_name={input_meta.name} input_shape={input_shape} "
        f"dummy_shape={concrete_shape} output_shape={output_shape} output_size={output_size}"
    )
    return {
        "path": str(path),
        "input_name": input_meta.name,
        "input_shape": input_shape,
        "dummy_shape": concrete_shape,
        "output_shape": output_shape,
        "output_size": output_size,
    }


def main() -> None:
    validate_labels(LABELS_PATH)

    model_results = []
    for filename, expected_output_size in MODEL_SPECS.items():
        model_path = WEB_PUBLIC_DIR / filename
        model_results.append(validate_model(model_path, expected_output_size))

    print("[summary] Phase 2 ONNX artifact validation passed.")
    for result in model_results:
        print(
            f"[summary] {Path(result['path']).name} requires input shape metadata "
            f"{result['input_shape']} and was validated with dummy tensor shape {result['dummy_shape']}."
        )


if __name__ == "__main__":
    main()
