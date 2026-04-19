from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np

try:
    import onnxruntime as rt
except ModuleNotFoundError as exc:  # pragma: no cover - import guard
    print(
        "onnxruntime is required to validate ONNX files. "
        "Install it in the active environment before running this script.",
        file=sys.stderr,
    )
    raise SystemExit(2) from exc


DEFAULT_MODEL_PATHS = (
    Path("wlasl_lite.onnx"),
    Path("frontend/src/capture/wlasl_lite.onnx"),
)

TIME_DIM_HINTS = {
    "t",
    "time",
    "time_steps",
    "timesteps",
    "seq",
    "sequence",
    "frames",
    "frame_count",
    "window",
}


def _resolve_model_path(model_arg: str | None) -> Path:
    if model_arg:
        model_path = Path(model_arg)
        if model_path.exists():
            return model_path
        raise FileNotFoundError(f"Model file not found: {model_path}")

    for candidate in DEFAULT_MODEL_PATHS:
        if candidate.exists():
            return candidate

    searched = ", ".join(str(path) for path in DEFAULT_MODEL_PATHS)
    raise FileNotFoundError(f"No model file found. Checked: {searched}")


def _materialize_dim(dim: object, axis: int, time_steps: int, fallback: int) -> int:
    if isinstance(dim, int) and dim > 0:
        return dim
    if axis == 0:
        return 1
    if isinstance(dim, str):
        normalized = dim.strip().lower()
        if "batch" in normalized:
            return 1
        if normalized in TIME_DIM_HINTS or "frame" in normalized or "seq" in normalized:
            return time_steps
    return fallback


def _dummy_input_shape(input_shape: list[object], time_steps: int, fallback: int) -> tuple[int, ...]:
    return tuple(
        _materialize_dim(dim, axis=axis, time_steps=time_steps, fallback=fallback)
        for axis, dim in enumerate(input_shape)
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate an ONNX model input contract.")
    parser.add_argument(
        "--model",
        help="Path to the ONNX model. Defaults to wlasl_lite.onnx or frontend/src/capture/wlasl_lite.onnx.",
    )
    parser.add_argument(
        "--time-steps",
        type=int,
        default=16,
        help="Fallback size for dynamic temporal dimensions during dummy inference.",
    )
    parser.add_argument(
        "--dynamic-dim-default",
        type=int,
        default=1,
        help="Fallback size for other dynamic dimensions during dummy inference.",
    )
    args = parser.parse_args()

    model_path = _resolve_model_path(args.model)
    session = rt.InferenceSession(str(model_path))

    inp = session.get_inputs()[0]
    out = session.get_outputs()[0]
    print(f"Model path:  {model_path}")
    print(f"Input name:  {inp.name}")
    print(f"Input shape: {inp.shape}")
    print(f"Output name: {out.name}")
    print(f"Output shape: {out.shape}")

    materialized_shape = _dummy_input_shape(
        list(inp.shape),
        time_steps=args.time_steps,
        fallback=args.dynamic_dim_default,
    )
    print(f"Dummy shape: {materialized_shape}")

    dummy = np.zeros(materialized_shape, dtype=np.float32)
    result = session.run([out.name], {inp.name: dummy})[0]
    sample = np.asarray(result).reshape(-1)[:5]
    print(f"Output sample: {sample.tolist()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
