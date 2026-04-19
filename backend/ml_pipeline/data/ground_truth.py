"""Bootstrap ground-truth dataset builder and parser for ASL backtesting.

The repository does not yet contain annotated validation clips, so this module
seeds a deterministic bootstrap set of `.npz` samples with realistic `(T, 258)`
keypoint tensors and gloss-token targets. The format is compatible with future
real annotated clips: as long as a file contains `keypoints` and `gloss`, the
loader will parse it.
"""
from __future__ import annotations

import argparse
import sys
import zlib
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Iterable, Sequence

import numpy as np

ML_PIPELINE_ROOT = Path(__file__).resolve().parents[1]
if str(ML_PIPELINE_ROOT) not in sys.path:
    sys.path.insert(0, str(ML_PIPELINE_ROOT))

try:
    from src.train_transformer import FEATURES_PER_FRAME, GLOSS_VOCAB
except Exception:
    FEATURES_PER_FRAME = 258
    GLOSS_VOCAB = [
        "[PAD]",
        "[EOS]",
        "[UNKNOWN_SIGN]",
        "HELLO",
        "THANK-YOU",
        "PLEASE",
        "SORRY",
        "YES",
        "NO",
        "HELP",
        "I",
        "YOU",
        "WE",
        "THEY",
        "HE",
        "SHE",
        "WANT",
        "NEED",
        "LIKE",
        "LOVE",
        "KNOW",
        "THINK",
        "GO",
        "COME",
        "GOOD",
        "BAD",
        "MORE",
        "LESS",
        "BIG",
        "SMALL",
        "NEW",
        "OLD",
        "TODAY",
        "TOMORROW",
        "YESTERDAY",
        "NOW",
        "LATER",
        "WHEN",
        "WHERE",
        "WHAT",
        "WHO",
        "WHY",
        "HOW",
        "HOME",
        "WORK",
        "SCHOOL",
        "STORE",
        "HOSPITAL",
        "BATHROOM",
        "EAT",
        "DRINK",
        "SLEEP",
        "WALK",
        "RUN",
        "SIT",
        "STAND",
        "HAPPY",
        "SAD",
        "ANGRY",
        "SCARED",
        "TIRED",
        "SICK",
        "FINE",
        "MOTHER",
        "FATHER",
        "SISTER",
        "BROTHER",
        "FRIEND",
        "DOCTOR",
        "WATER",
        "FOOD",
        "MONEY",
        "TIME",
        "CAR",
        "BOOK",
        "PHONE",
        "MORNING",
        "AFTERNOON",
        "NIGHT",
        "ONE",
        "TWO",
        "THREE",
        "FOUR",
        "FIVE",
        "CAN",
        "CANNOT",
        "WILL",
        "SHOULD",
        "MUST",
        "GIVE",
        "TAKE",
        "SHOW",
        "TELL",
        "ASK",
        "ANSWER",
        "UNDERSTAND",
        "REPEAT",
        "SLOW",
        "FAST",
        "MEETING",
        "CAPTION",
        "SIGN",
        "INTERPRET",
    ]

BOOTSTRAP_SEED = 20260418
DEFAULT_BOOTSTRAP_SAMPLE_COUNT = 60
DEFAULT_DATA_DIR = Path(__file__).resolve().parent / "ground_truth"
SPECIAL_TOKENS = {"[PAD]"}
ALLOWED_GLOSS_TOKENS = tuple(token for token in GLOSS_VOCAB if token not in SPECIAL_TOKENS)
ALLOWED_GLOSS_TOKEN_SET = set(ALLOWED_GLOSS_TOKENS)

BOOTSTRAP_GLOSS_SEQUENCES: tuple[tuple[str, ...], ...] = (
    ("HELLO",),
    ("THANK-YOU",),
    ("PLEASE", "HELP"),
    ("I", "NEED", "HELP"),
    ("YOU", "NEED", "WATER"),
    ("WE", "WANT", "FOOD"),
    ("THEY", "LIKE", "SCHOOL"),
    ("I", "GO", "HOME"),
    ("YOU", "COME", "WORK"),
    ("WE", "GO", "STORE"),
    ("THEY", "COME", "HOSPITAL"),
    ("I", "WANT", "BATHROOM"),
    ("I", "EAT", "FOOD"),
    ("YOU", "DRINK", "WATER"),
    ("WE", "SLEEP", "HOME"),
    ("THEY", "WALK", "SCHOOL"),
    ("I", "RUN", "WORK"),
    ("YOU", "SIT", "HOME"),
    ("WE", "STAND", "NOW"),
    ("I", "HAPPY", "TODAY"),
    ("YOU", "SAD", "TODAY"),
    ("WE", "ANGRY", "NOW"),
    ("THEY", "SCARED", "NIGHT"),
    ("I", "TIRED", "AFTERNOON"),
    ("YOU", "SICK", "MORNING"),
    ("WE", "FINE", "TODAY"),
    ("MOTHER", "NEED", "DOCTOR"),
    ("FATHER", "GO", "HOSPITAL"),
    ("SISTER", "LOVE", "BOOK"),
    ("BROTHER", "WANT", "PHONE"),
    ("FRIEND", "COME", "HOME"),
    ("DOCTOR", "HELP", "YOU"),
    ("I", "NEED", "MONEY"),
    ("YOU", "WANT", "MONEY"),
    ("WE", "NEED", "TIME"),
    ("THEY", "LIKE", "CAR"),
    ("I", "TAKE", "BOOK"),
    ("YOU", "SHOW", "PHONE"),
    ("WE", "ASK", "WHO"),
    ("THEY", "ANSWER", "HOW"),
    ("I", "UNDERSTAND", "NOW"),
    ("YOU", "REPEAT", "SLOW"),
    ("WE", "GO", "FAST"),
    ("THEY", "SIGN", "CAPTION"),
    ("I", "INTERPRET", "CAPTION"),
    ("WE", "MEETING", "TODAY"),
    ("I", "WILL", "COME", "TOMORROW"),
    ("YOU", "SHOULD", "GO", "NOW"),
    ("WE", "MUST", "WORK", "TODAY"),
    ("THEY", "CANNOT", "COME", "TODAY"),
    ("I", "CAN", "HELP", "YOU"),
    ("YOU", "KNOW", "WHERE", "STORE"),
    ("WE", "THINK", "WHY"),
    ("THEY", "ASK", "WHEN"),
    ("I", "SHOW", "WHAT"),
    ("YOU", "TELL", "WHO"),
    ("WE", "GIVE", "FOOD"),
    ("THEY", "TAKE", "WATER"),
    ("I", "MORE", "TIME"),
    ("YOU", "LESS", "MONEY"),
)


@dataclass(frozen=True)
class GroundTruthSample:
    sample_id: str
    keypoints: np.ndarray
    gloss_tokens: list[str]
    path: Path
    source: str = "bootstrap-synthetic"


def _token_seed(token: str) -> int:
    return zlib.crc32(token.encode("utf-8")) & 0xFFFFFFFF


@lru_cache(maxsize=None)
def token_prototype(token: str) -> np.ndarray:
    """Return a deterministic canonical frame for one gloss token."""
    if token not in ALLOWED_GLOSS_TOKEN_SET:
        raise ValueError(f"Token {token!r} is not in the training vocabulary")

    rng = np.random.default_rng(BOOTSTRAP_SEED + _token_seed(token))
    left = np.concatenate(
        [rng.uniform(0.05, 0.95, size=(21, 2)), rng.uniform(-0.25, 0.25, size=(21, 1))],
        axis=1,
    )
    right = np.concatenate(
        [rng.uniform(0.05, 0.95, size=(21, 2)), rng.uniform(-0.25, 0.25, size=(21, 1))],
        axis=1,
    )
    pose = np.concatenate(
        [
            rng.uniform(0.05, 0.95, size=(33, 2)),
            rng.uniform(-0.35, 0.35, size=(33, 1)),
            rng.uniform(0.55, 1.0, size=(33, 1)),
        ],
        axis=1,
    )
    return np.concatenate([left.reshape(-1), right.reshape(-1), pose.reshape(-1)]).astype(np.float32)


@lru_cache(maxsize=None)
def _token_motion_axis(token: str) -> np.ndarray:
    rng = np.random.default_rng(BOOTSTRAP_SEED ^ _token_seed(f"{token}-motion"))
    axis = rng.normal(0.0, 1.0, size=FEATURES_PER_FRAME).astype(np.float32)
    axis /= np.linalg.norm(axis) + 1e-6
    return axis


def _clip_frame(frame: np.ndarray) -> np.ndarray:
    frame = frame.astype(np.float32, copy=True)

    left = frame[:63].reshape(21, 3)
    right = frame[63:126].reshape(21, 3)
    pose = frame[126:].reshape(33, 4)

    left[:, :2] = np.clip(left[:, :2], 0.0, 1.0)
    right[:, :2] = np.clip(right[:, :2], 0.0, 1.0)
    pose[:, :2] = np.clip(pose[:, :2], 0.0, 1.0)

    left[:, 2] = np.clip(left[:, 2], -1.0, 1.0)
    right[:, 2] = np.clip(right[:, 2], -1.0, 1.0)
    pose[:, 2] = np.clip(pose[:, 2], -1.0, 1.0)
    pose[:, 3] = np.clip(pose[:, 3], 0.0, 1.0)

    return np.concatenate([left.reshape(-1), right.reshape(-1), pose.reshape(-1)]).astype(np.float32)


def _render_token_frames(token: str, frame_count: int, rng: np.random.Generator) -> np.ndarray:
    base = token_prototype(token)
    motion = _token_motion_axis(token)
    style = rng.normal(0.0, 0.015, size=FEATURES_PER_FRAME).astype(np.float32)
    phase = np.linspace(0.0, np.pi, frame_count, dtype=np.float32)

    frames = []
    for step in phase:
        frame = base.copy()
        frame += np.sin(step) * 0.030 * motion
        frame += np.cos(step * 1.7) * style
        frame += rng.normal(0.0, 0.004, size=FEATURES_PER_FRAME).astype(np.float32)
        frames.append(_clip_frame(frame))
    return np.stack(frames, axis=0)


def render_gloss_sequence(gloss_tokens: Sequence[str], sample_seed: int | None = None) -> np.ndarray:
    """Create a synthetic `(T, 258)` tensor for a sequence of gloss tokens."""
    if not gloss_tokens:
        raise ValueError("gloss_tokens must not be empty")

    unknown = [token for token in gloss_tokens if token not in ALLOWED_GLOSS_TOKEN_SET]
    if unknown:
        raise ValueError(f"Unknown gloss tokens: {unknown}")

    seed = BOOTSTRAP_SEED if sample_seed is None else sample_seed
    rng = np.random.default_rng(seed)

    frames: list[np.ndarray] = []
    for token in gloss_tokens:
        token_frames = int(rng.integers(4, 8))
        frames.append(_render_token_frames(token, token_frames, rng))
    return np.concatenate(frames, axis=0).astype(np.float32)


def build_bootstrap_dataset(
    output_dir: Path | str | None = None,
    num_samples: int = DEFAULT_BOOTSTRAP_SAMPLE_COUNT,
    overwrite: bool = False,
) -> list[Path]:
    """Materialise deterministic bootstrap `.npz` samples to disk."""
    out_dir = Path(output_dir or DEFAULT_DATA_DIR)
    out_dir.mkdir(parents=True, exist_ok=True)

    max_samples = min(num_samples, len(BOOTSTRAP_GLOSS_SEQUENCES))
    written: list[Path] = []
    for index, gloss_tokens in enumerate(BOOTSTRAP_GLOSS_SEQUENCES[:max_samples], start=1):
        slug = "-".join(token.lower().replace("[", "").replace("]", "") for token in gloss_tokens[:4])
        path = out_dir / f"bootstrap_{index:03d}_{slug}.npz"
        if path.exists() and not overwrite:
            written.append(path)
            continue

        keypoints = render_gloss_sequence(gloss_tokens, sample_seed=BOOTSTRAP_SEED + index)
        np.savez_compressed(
            path,
            keypoints=keypoints,
            gloss=np.asarray(gloss_tokens, dtype="<U32"),
            source=np.asarray("bootstrap-synthetic"),
        )
        written.append(path)
    return written


def ensure_ground_truth_dataset(
    output_dir: Path | str | None = None,
    min_samples: int = DEFAULT_BOOTSTRAP_SAMPLE_COUNT,
) -> list[Path]:
    """Ensure there are at least `min_samples` parsable `.npz` samples on disk."""
    out_dir = Path(output_dir or DEFAULT_DATA_DIR)
    out_dir.mkdir(parents=True, exist_ok=True)

    existing = sorted(out_dir.glob("*.npz"))
    if len(existing) < min_samples:
        target = min(max(min_samples, DEFAULT_BOOTSTRAP_SAMPLE_COUNT), len(BOOTSTRAP_GLOSS_SEQUENCES))
        build_bootstrap_dataset(out_dir, num_samples=target, overwrite=False)
        existing = sorted(out_dir.glob("*.npz"))
    return existing


def _coerce_gloss_tokens(npz: np.lib.npyio.NpzFile) -> list[str]:
    if "gloss" in npz.files:
        gloss_raw = np.asarray(npz["gloss"]).tolist()
        if isinstance(gloss_raw, str):
            return [gloss_raw]
        return [str(token) for token in gloss_raw]

    if "gloss_tokens" in npz.files:
        tokens_raw = np.asarray(npz["gloss_tokens"]).tolist()
        return [str(token) for token in tokens_raw]

    if "labels" in npz.files:
        label_indices = np.asarray(npz["labels"], dtype=np.int64).tolist()
        return [GLOSS_VOCAB[int(index)] for index in label_indices]

    raise ValueError("Sample missing `gloss`, `gloss_tokens`, or `labels` array")


def parse_ground_truth_file(path: Path | str) -> GroundTruthSample:
    file_path = Path(path)
    with np.load(file_path, allow_pickle=False) as npz:
        keypoints = np.asarray(npz["keypoints"], dtype=np.float32)
        gloss_tokens = _coerce_gloss_tokens(npz)
        source = str(np.asarray(npz["source"]).item()) if "source" in npz.files else "unknown"

    if keypoints.ndim != 2 or keypoints.shape[1] != FEATURES_PER_FRAME:
        raise ValueError(f"{file_path} must have shape (T, {FEATURES_PER_FRAME}); got {keypoints.shape}")
    if not gloss_tokens:
        raise ValueError(f"{file_path} has an empty gloss target")

    invalid = [token for token in gloss_tokens if token not in ALLOWED_GLOSS_TOKEN_SET]
    if invalid:
        raise ValueError(f"{file_path} contains tokens outside the vocabulary: {invalid}")

    return GroundTruthSample(
        sample_id=file_path.stem,
        keypoints=keypoints,
        gloss_tokens=gloss_tokens,
        path=file_path,
        source=source,
    )


def load_ground_truth_dataset(
    data_dir: Path | str | None = None,
    ensure_minimum: bool = True,
    min_samples: int = DEFAULT_BOOTSTRAP_SAMPLE_COUNT,
) -> list[GroundTruthSample]:
    """Load all parsable `.npz` samples from `data_dir`."""
    root = Path(data_dir or DEFAULT_DATA_DIR)
    if ensure_minimum:
        ensure_ground_truth_dataset(root, min_samples=min_samples)
    elif not root.exists():
        raise FileNotFoundError(f"Ground-truth directory does not exist: {root}")

    samples = [parse_ground_truth_file(path) for path in sorted(root.glob("*.npz"))]
    if not samples:
        raise FileNotFoundError(f"No ground-truth `.npz` samples found in {root}")
    return samples


def decode_with_prototypes(keypoints: np.ndarray) -> list[str]:
    """Nearest-prototype decoder used by the local mock evaluator."""
    if keypoints.ndim != 2 or keypoints.shape[1] != FEATURES_PER_FRAME:
        raise ValueError(f"Expected (T, {FEATURES_PER_FRAME}) keypoints, got {keypoints.shape}")

    vocab = [token for token in ALLOWED_GLOSS_TOKENS if token not in {"[EOS]", "[UNKNOWN_SIGN]"}]
    prototype_matrix = np.stack([token_prototype(token) for token in vocab], axis=0)
    distances = np.linalg.norm(keypoints[:, None, :] - prototype_matrix[None, :, :], axis=2)
    frame_tokens = [vocab[int(index)] for index in np.argmin(distances, axis=1)]

    decoded: list[str] = []
    for token in frame_tokens:
        if not decoded or decoded[-1] != token:
            decoded.append(token)
    return decoded


def validate_samples(samples: Iterable[GroundTruthSample]) -> None:
    for sample in samples:
        if sample.keypoints.dtype != np.float32:
            raise ValueError(f"{sample.sample_id} keypoints must be float32")
        if sample.keypoints.shape[1] != FEATURES_PER_FRAME:
            raise ValueError(f"{sample.sample_id} has wrong feature width: {sample.keypoints.shape}")
        invalid = [token for token in sample.gloss_tokens if token not in ALLOWED_GLOSS_TOKEN_SET]
        if invalid:
            raise ValueError(f"{sample.sample_id} contains invalid tokens: {invalid}")


def _build_cli() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build or inspect the bootstrap ground-truth dataset")
    parser.add_argument("--output-dir", default=str(DEFAULT_DATA_DIR))
    parser.add_argument("--min-samples", type=int, default=DEFAULT_BOOTSTRAP_SAMPLE_COUNT)
    parser.add_argument("--overwrite", action="store_true")
    return parser


def main() -> None:
    parser = _build_cli()
    args = parser.parse_args()
    build_bootstrap_dataset(args.output_dir, num_samples=args.min_samples, overwrite=args.overwrite)
    samples = load_ground_truth_dataset(args.output_dir, ensure_minimum=False)
    validate_samples(samples)
    print(f"Built {len(samples)} ground-truth samples in {Path(args.output_dir).resolve()}")


if __name__ == "__main__":
    main()
