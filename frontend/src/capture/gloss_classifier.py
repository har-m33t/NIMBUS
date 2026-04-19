from __future__ import annotations

import json
from pathlib import Path
from typing import Callable

import numpy as np

try:
    from capture.adapter import adapt_features
except ImportError:  # pragma: no cover - optional until agent 1 artifacts land
    adapt_features = None

try:
    import onnxruntime as rt
except ImportError:  # pragma: no cover - exercised via constructor guard
    rt = None


AdapterFn = Callable[[np.ndarray], np.ndarray]

# Labels that represent "no sign" / meta-classes in typical ASL alphabet models.
# These should never be emitted as gloss tokens.
_DEFAULT_NO_EMIT_LABELS = frozenset({"NOTHING", "NULL", "NONE", "UNKNOWN"})

# If the summed absolute feature energy of a frame is below this, the hand is
# effectively absent. Skipping classification on empty frames prevents the
# model's no-signal prior (e.g. "M" at 0.91 for the alphabet ONNX) from
# repeatedly firing when the user has their hand out of frame.
_MIN_FRAME_ENERGY = 1e-3


class GlossClassifierError(RuntimeError):
    """Raised when the ONNX classifier cannot be initialized safely."""


class GlossClassifier:
    """Wraps a pretrained WLASL ONNX model with a rolling temporal window."""

    def __init__(
        self,
        model_path: str,
        label_map_path: str,
        threshold: float = 0.60,
        *,
        adapter: AdapterFn | None = None,
        window_size: int | None = None,
        ignore_labels: frozenset[str] | set[str] | None = None,
    ) -> None:
        if rt is None:
            raise GlossClassifierError(
                "onnxruntime is not installed. Add frontend requirements before running the classifier."
            )

        self._session = rt.InferenceSession(str(model_path))
        with Path(label_map_path).open(encoding="utf-8") as handle:
            loaded_labels = json.load(handle)
        if isinstance(loaded_labels, list):
            self._labels = {str(index): str(label) for index, label in enumerate(loaded_labels)}
        else:
            self._labels = {str(key): str(value) for key, value in dict(loaded_labels).items()}

        self._threshold = float(threshold)
        model_input = self._session.get_inputs()[0]
        self._input_name = model_input.name
        input_shape = list(getattr(model_input, "shape", []) or [])
        self._feature_dim = self._coerce_positive_int(input_shape[2] if len(input_shape) > 2 else None)
        self._T = self._resolve_window_size(input_shape[1] if len(input_shape) > 1 else None, window_size)
        self._adapter = adapter or self._build_auto_adapter()
        self._window: list[np.ndarray] = []
        self._ignore_labels = frozenset(
            (label.upper() for label in (ignore_labels or _DEFAULT_NO_EMIT_LABELS))
        )

    @property
    def feature_dim(self) -> int | None:
        return self._feature_dim

    @property
    def window_size(self) -> int:
        return self._T

    def update(self, keypoints: np.ndarray) -> str | None:
        """Push one frame. Returns a gloss token when confident, else None."""
        frame = np.asarray(keypoints, dtype=np.float32).reshape(-1)
        if self._adapter is not None:
            frame = np.asarray(self._adapter(frame), dtype=np.float32).reshape(-1)
        if self._feature_dim is not None and frame.shape[-1] != self._feature_dim:
            raise ValueError(
                f"Classifier expected {self._feature_dim} features per frame, got {frame.shape[-1]}."
            )

        # Skip classification when no hand is visible — otherwise the model's
        # no-signal prior (e.g. the alphabet ONNX collapsing to "M" at 0.91)
        # floods the buffer while the user has their hand out of frame.
        if float(np.abs(frame).sum()) < _MIN_FRAME_ENERGY:
            self._window.clear()
            return None

        self._window.append(frame)
        if len(self._window) > self._T:
            self._window.pop(0)
        if len(self._window) < self._T:
            return None

        tensor = np.array([self._window], dtype=np.float32)
        probs = np.asarray(self._session.run(None, {self._input_name: tensor})[0], dtype=np.float32).reshape(-1)
        if probs.size == 0:
            return None

        conf = float(probs.max())
        idx = int(probs.argmax())
        if conf < self._threshold:
            return None
        label = self._labels.get(str(idx))
        if label is None or label.upper() in self._ignore_labels:
            return None
        return label

    @staticmethod
    def _coerce_positive_int(value: object) -> int | None:
        if isinstance(value, bool):
            return None
        if isinstance(value, (int, np.integer)) and int(value) > 0:
            return int(value)
        return None

    @classmethod
    def _resolve_window_size(cls, value: object, fallback: int | None) -> int:
        resolved = cls._coerce_positive_int(value)
        if resolved is not None:
            return resolved
        if fallback is not None and int(fallback) > 0:
            return int(fallback)
        raise GlossClassifierError(
            "The ONNX model uses a dynamic temporal dimension. Set NIMBUS_CLASSIFIER_WINDOW_SIZE "
            "or pass window_size explicitly."
        )

    def _build_auto_adapter(self) -> AdapterFn | None:
        if self._feature_dim in (63, 225) and adapt_features is not None:
            target_width = int(self._feature_dim)
            return lambda vec: adapt_features(vec, target_width)
        return None
