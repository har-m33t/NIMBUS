"""Prepare NIMBUS ASL training data from custom videos or ASLLVD scene clips.

Output NPZ contract:
  keypoints:     float32 array shaped (T, 258)
  labels:        int64 array shaped (T,)
  feature_names: unicode array shaped (258,)
  gloss:         unicode scalar
  split:         unicode scalar
  metadata:      JSON string with source, frame range, and ontology metadata
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import importlib
import json
import logging
import pathlib
import sys
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Iterable

import numpy as np

try:
    import pandas as pd
except ImportError:  # pragma: no cover - optional dependency at runtime
    pd = None

CURRENT_DIR = pathlib.Path(__file__).resolve().parent
SRC_DIR = CURRENT_DIR.parent / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from vocabulary import (  # noqa: E402
    TOKEN_TO_INDEX,
    build_gloss_to_handshape_map,
    canonicalize_gloss,
    write_vocabulary_assets,
)

logger = logging.getLogger(__name__)

FEATURES_PER_FRAME = 258
KEYPOINT_SCHEMA_VERSION = "nimbus-mediapipe-258-v1"
DEFAULT_TARGET_FPS = 15.0
DEFAULT_MIN_FRAMES = 4
DEFAULT_ASLLVD_INDEX_URL = (
    "http://www.bu.edu/asllrp/dai-asllvd-BU_glossing_with_variations_"
    "HS_information-extended-urls-RU.xlsx"
)
DEFAULT_ASLLVD_SCENE_URL = (
    "http://csr.bu.edu/ftp/asl/asllvd/asl-data2/quicktime/{session}/scene{scene}-camera{camera}.mov"
)
ASLLVD_TERMS_URL = "https://www.bu.edu/asllrp/av/dai-asllvd.html"

HAND_LANDMARKS = [
    "wrist",
    "thumb_cmc",
    "thumb_mcp",
    "thumb_ip",
    "thumb_tip",
    "index_finger_mcp",
    "index_finger_pip",
    "index_finger_dip",
    "index_finger_tip",
    "middle_finger_mcp",
    "middle_finger_pip",
    "middle_finger_dip",
    "middle_finger_tip",
    "ring_finger_mcp",
    "ring_finger_pip",
    "ring_finger_dip",
    "ring_finger_tip",
    "pinky_mcp",
    "pinky_pip",
    "pinky_dip",
    "pinky_tip",
]

POSE_LANDMARKS = [
    "nose",
    "left_eye_inner",
    "left_eye",
    "left_eye_outer",
    "right_eye_inner",
    "right_eye",
    "right_eye_outer",
    "left_ear",
    "right_ear",
    "mouth_left",
    "mouth_right",
    "left_shoulder",
    "right_shoulder",
    "left_elbow",
    "right_elbow",
    "left_wrist",
    "right_wrist",
    "left_pinky",
    "right_pinky",
    "left_index",
    "right_index",
    "left_thumb",
    "right_thumb",
    "left_hip",
    "right_hip",
    "left_knee",
    "right_knee",
    "left_ankle",
    "right_ankle",
    "left_heel",
    "right_heel",
    "left_foot_index",
    "right_foot_index",
]

HANDSHAPE_PRIORS = build_gloss_to_handshape_map()


def _hand_feature_names(prefix: str) -> list[str]:
    return [
        f"{prefix}.{landmark}.{axis}"
        for landmark in HAND_LANDMARKS
        for axis in ("x", "y", "z")
    ]


def _pose_feature_names() -> list[str]:
    return [
        f"pose.{landmark}.{axis}"
        for landmark in POSE_LANDMARKS
        for axis in ("x", "y", "z", "visibility")
    ]


FEATURE_NAMES: list[str] = _hand_feature_names("left_hand") + _hand_feature_names("right_hand") + _pose_feature_names()


@dataclass
class SequenceRecord:
    sample_id: str
    gloss: str
    video_path: pathlib.Path
    source: str
    start_frame: int | None = None
    end_frame: int | None = None
    signer: str | None = None
    split: str | None = None
    original_gloss: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


def load_optional_dependency(module_name: str, install_hint: str) -> Any:
    try:
        return importlib.import_module(module_name)
    except ImportError as exc:  # pragma: no cover - runtime dependency
        raise RuntimeError(
            f"{module_name} is required for this command. Install {install_hint} first."
        ) from exc


def build_keypoint_schema() -> dict[str, Any]:
    return {
        "version": KEYPOINT_SCHEMA_VERSION,
        "features_per_frame": FEATURES_PER_FRAME,
        "segments": [
            {
                "name": "left_hand",
                "start_index": 0,
                "feature_count": 63,
                "landmarks": [
                    {
                        "name": landmark,
                        "feature_indices": [idx * 3, idx * 3 + 1, idx * 3 + 2],
                        "axes": ["x", "y", "z"],
                    }
                    for idx, landmark in enumerate(HAND_LANDMARKS)
                ],
            },
            {
                "name": "right_hand",
                "start_index": 63,
                "feature_count": 63,
                "landmarks": [
                    {
                        "name": landmark,
                        "feature_indices": [63 + idx * 3, 63 + idx * 3 + 1, 63 + idx * 3 + 2],
                        "axes": ["x", "y", "z"],
                    }
                    for idx, landmark in enumerate(HAND_LANDMARKS)
                ],
            },
            {
                "name": "pose",
                "start_index": 126,
                "feature_count": 132,
                "landmarks": [
                    {
                        "name": landmark,
                        "feature_indices": [
                            126 + idx * 4,
                            126 + idx * 4 + 1,
                            126 + idx * 4 + 2,
                            126 + idx * 4 + 3,
                        ],
                        "axes": ["x", "y", "z", "visibility"],
                    }
                    for idx, landmark in enumerate(POSE_LANDMARKS)
                ],
            },
        ],
        "feature_names": FEATURE_NAMES,
        "notes": (
            "Left hand uses 21 landmarks x 3 axes, right hand uses 21 x 3, "
            "pose uses 33 x 4 including visibility."
        ),
    }


def write_keypoint_schema(path: pathlib.Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(build_keypoint_schema(), indent=2) + "\n", encoding="utf-8")


def normalize_identifier(value: str) -> str:
    normalized = "".join(char.lower() if char.isalnum() else "_" for char in value)
    return "_".join(part for part in normalized.split("_") if part)


def hashed_split(sample_key: str, train_ratio: float, val_ratio: float) -> str:
    bucket = int(hashlib.sha1(sample_key.encode("utf-8")).hexdigest(), 16) % 100
    train_cutoff = int(train_ratio * 100)
    val_cutoff = train_cutoff + int(val_ratio * 100)
    if bucket < train_cutoff:
        return "train"
    if bucket < val_cutoff:
        return "val"
    return "test"


def parse_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    return int(float(value))


def coalesce(mapping: dict[str, Any], candidates: Iterable[str]) -> Any:
    for key in candidates:
        if key in mapping and mapping[key] not in (None, ""):
            return mapping[key]
    return None


def resolve_video_path(raw_path: str, base_dir: pathlib.Path) -> pathlib.Path:
    path = pathlib.Path(raw_path)
    if path.is_absolute():
        return path
    return (base_dir / path).resolve()


def load_custom_manifest(manifest_path: pathlib.Path, video_root: pathlib.Path | None) -> list[SequenceRecord]:
    manifest_base = video_root.resolve() if video_root else manifest_path.parent.resolve()
    suffix = manifest_path.suffix.lower()

    if suffix == ".csv":
        with manifest_path.open("r", encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.DictReader(handle))
    elif suffix in {".json", ".jsonl"}:
        if suffix == ".jsonl":
            with manifest_path.open("r", encoding="utf-8") as handle:
                rows = [json.loads(line) for line in handle if line.strip()]
        else:
            payload = json.loads(manifest_path.read_text(encoding="utf-8"))
            rows = payload["records"] if isinstance(payload, dict) else payload
    else:
        raise ValueError("Manifest must be .csv, .json, or .jsonl")

    records: list[SequenceRecord] = []
    for index, row in enumerate(rows):
        raw_gloss = str(coalesce(row, ("gloss", "label", "token")) or "").strip()
        gloss = canonicalize_gloss(raw_gloss)
        if gloss == "[UNKNOWN_SIGN]":
            logger.info("Skipping custom row %d with unknown gloss %r", index, raw_gloss)
            continue

        raw_video_path = coalesce(row, ("video_path", "video", "path", "file"))
        if not raw_video_path:
            logger.warning("Skipping custom row %d without a video path", index)
            continue

        sample_id = str(coalesce(row, ("sample_id", "clip_id", "id")) or f"{gloss}_{index:04d}")
        signer = coalesce(row, ("signer", "speaker", "consultant"))
        split = coalesce(row, ("split",))

        records.append(
            SequenceRecord(
                sample_id=normalize_identifier(sample_id),
                gloss=gloss,
                video_path=resolve_video_path(str(raw_video_path), manifest_base),
                source="custom-video",
                start_frame=parse_int(coalesce(row, ("start_frame", "frame_start"))),
                end_frame=parse_int(coalesce(row, ("end_frame", "frame_end"))),
                signer=str(signer) if signer else None,
                split=str(split) if split else None,
                original_gloss=raw_gloss or None,
                metadata={key: value for key, value in row.items() if key not in {"video_path", "video", "path", "file"}},
            )
        )
    return records


def normalize_column_name(column: str) -> str:
    normalized = column.strip().lower()
    normalized = normalized.replace("/", " ").replace("-", " ").replace("_", " ")
    return " ".join(normalized.split())


def find_column(columns: Iterable[str], required_fragments: Iterable[str]) -> str | None:
    normalized_pairs = [(column, normalize_column_name(column)) for column in columns]
    for column, normalized in normalized_pairs:
        if all(fragment in normalized for fragment in required_fragments):
            return column
    return None


def load_asllvd_index(index_source: str) -> Any:
    if pd is None:  # pragma: no cover - depends on local environment
        raise RuntimeError("pandas is required to parse the ASLLVD index")

    if index_source.lower().endswith(".csv"):
        return pd.read_csv(index_source)
    return pd.read_excel(index_source)


def download_file(url: str, destination: pathlib.Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    logger.info("Downloading %s -> %s", url, destination)
    with urllib.request.urlopen(url) as response, destination.open("wb") as handle:  # noqa: S310
        handle.write(response.read())


def asllvd_scene_url(session: str, scene: int, camera: int) -> str:
    return DEFAULT_ASLLVD_SCENE_URL.format(session=session, scene=scene, camera=camera)


def build_asllvd_records(
    index_source: str,
    download_dir: pathlib.Path,
    camera: int,
    download_missing: bool,
    gloss_filters: set[str] | None,
    limit: int | None,
) -> list[SequenceRecord]:
    frame_index = load_asllvd_index(index_source)
    columns = list(frame_index.columns)

    gloss_column = (
        find_column(columns, ("variant", "gloss"))
        or find_column(columns, ("main", "gloss"))
        or find_column(columns, ("gloss",))
    )
    session_column = find_column(columns, ("session",))
    scene_column = find_column(columns, ("scene",))
    start_frame_column = find_column(columns, ("start", "frame"))
    end_frame_column = find_column(columns, ("end", "frame"))
    signer_column = find_column(columns, ("signer",)) or find_column(columns, ("consultant",))

    if not all((gloss_column, session_column, scene_column, start_frame_column, end_frame_column)):
        raise ValueError("ASLLVD index is missing one or more required columns")

    handshape_columns = {
        "dominant_start_handshape": find_column(columns, ("dominant", "start", "handshape")),
        "dominant_end_handshape": find_column(columns, ("dominant", "end", "handshape")),
        "nondominant_start_handshape": find_column(columns, ("non", "dominant", "start", "handshape")),
        "nondominant_end_handshape": find_column(columns, ("non", "dominant", "end", "handshape")),
    }

    records: list[SequenceRecord] = []
    for row_index, row in frame_index.iterrows():
        raw_gloss = str(row[gloss_column]).strip()
        gloss = canonicalize_gloss(raw_gloss)
        if gloss == "[UNKNOWN_SIGN]":
            continue
        if gloss_filters and gloss not in gloss_filters:
            continue

        session = str(row[session_column]).strip()
        scene = parse_int(row[scene_column])
        start_frame = parse_int(row[start_frame_column])
        end_frame = parse_int(row[end_frame_column])
        if scene is None or start_frame is None or end_frame is None:
            continue

        local_video = download_dir / session / f"scene{scene}-camera{camera}.mov"
        source_url = asllvd_scene_url(session=session, scene=scene, camera=camera)
        if not local_video.exists():
            if not download_missing:
                logger.info("Skipping ASLLVD row %d because %s is missing", row_index, local_video)
                continue
            download_file(source_url, local_video)

        signer = str(row[signer_column]).strip() if signer_column and row[signer_column] == row[signer_column] else None
        metadata = {
            "dataset": "ASLLVD",
            "index_source": index_source,
            "terms_of_use": ASLLVD_TERMS_URL,
            "session": session,
            "scene": scene,
            "camera": camera,
            "download_url": source_url,
            "row_index": int(row_index),
        }
        for key, column in handshape_columns.items():
            if column and row[column] == row[column]:
                metadata[key] = str(row[column]).strip()

        sample_id = normalize_identifier(f"asllvd_{session}_scene{scene}_{start_frame}_{end_frame}_{row_index}")
        records.append(
            SequenceRecord(
                sample_id=sample_id,
                gloss=gloss,
                video_path=local_video,
                source="asllvd",
                start_frame=start_frame,
                end_frame=end_frame,
                signer=signer,
                original_gloss=raw_gloss,
                metadata=metadata,
            )
        )
        if limit and len(records) >= limit:
            break
    return records


def flatten_landmarks(landmarks: Any, expected_count: int, include_visibility: bool) -> list[float]:
    result: list[float] = []
    if landmarks is not None:
        for landmark in list(landmarks)[:expected_count]:
            result.extend([float(landmark.x), float(landmark.y), float(landmark.z)])
            if include_visibility:
                result.append(float(getattr(landmark, "visibility", 0.0) or 0.0))

    features_per_landmark = 4 if include_visibility else 3
    while len(result) < expected_count * features_per_landmark:
        result.append(0.0)
    return result


def extract_keypoints_from_video(
    record: SequenceRecord,
    target_fps: float,
    min_frames: int,
) -> np.ndarray:
    cv2 = load_optional_dependency("cv2", "`pip install opencv-python`")
    mediapipe = load_optional_dependency("mediapipe", "`pip install mediapipe`")

    capture = cv2.VideoCapture(str(record.video_path))
    if not capture.isOpened():  # pragma: no cover - depends on local video codecs
        raise RuntimeError(f"Unable to open video: {record.video_path}")

    start_frame = record.start_frame or 0
    end_frame = record.end_frame
    source_fps = float(capture.get(cv2.CAP_PROP_FPS) or target_fps or DEFAULT_TARGET_FPS)
    stride = max(1, int(round(source_fps / max(target_fps, 1.0))))
    capture.set(cv2.CAP_PROP_POS_FRAMES, start_frame)

    rows: list[np.ndarray] = []
    absolute_frame = start_frame
    with mediapipe.solutions.holistic.Holistic(
        static_image_mode=False,
        model_complexity=1,
        smooth_landmarks=True,
        min_detection_confidence=0.5,
        min_tracking_confidence=0.5,
    ) as holistic:
        while True:
            if end_frame is not None and absolute_frame > end_frame:
                break

            ok, frame = capture.read()
            if not ok:
                break

            should_sample = (absolute_frame - start_frame) % stride == 0
            if should_sample:
                rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                results = holistic.process(rgb_frame)
                left_hand = flatten_landmarks(
                    getattr(getattr(results, "left_hand_landmarks", None), "landmark", None),
                    expected_count=21,
                    include_visibility=False,
                )
                right_hand = flatten_landmarks(
                    getattr(getattr(results, "right_hand_landmarks", None), "landmark", None),
                    expected_count=21,
                    include_visibility=False,
                )
                pose = flatten_landmarks(
                    getattr(getattr(results, "pose_landmarks", None), "landmark", None),
                    expected_count=33,
                    include_visibility=True,
                )
                rows.append(np.asarray(left_hand + right_hand + pose, dtype=np.float32))
            absolute_frame += 1

    capture.release()

    if len(rows) < min_frames:
        raise RuntimeError(
            f"{record.sample_id} yielded {len(rows)} usable frames, below min_frames={min_frames}"
        )

    keypoints = np.stack(rows)
    if keypoints.shape[1] != FEATURES_PER_FRAME:
        raise RuntimeError(
            f"{record.sample_id} produced {keypoints.shape[1]} features per frame, expected {FEATURES_PER_FRAME}"
        )
    return keypoints


def build_labels(gloss: str, frame_count: int, append_eos: bool) -> np.ndarray:
    labels = np.full(frame_count, TOKEN_TO_INDEX[gloss], dtype=np.int64)
    if append_eos and frame_count > 0:
        labels[-1] = TOKEN_TO_INDEX["[EOS]"]
    return labels


def prepare_metadata(record: SequenceRecord, keypoints: np.ndarray, split: str) -> dict[str, Any]:
    metadata = dict(record.metadata)
    metadata.update(
        {
            "sample_id": record.sample_id,
            "source": record.source,
            "gloss": record.gloss,
            "original_gloss": record.original_gloss,
            "split": split,
            "signer": record.signer,
            "frame_count": int(keypoints.shape[0]),
            "feature_dim": int(keypoints.shape[1]),
            "start_frame": record.start_frame,
            "end_frame": record.end_frame,
            "schema_version": KEYPOINT_SCHEMA_VERSION,
            "handshape_prior": HANDSHAPE_PRIORS[record.gloss],
        }
    )
    return metadata


def write_npz_sample(
    record: SequenceRecord,
    output_dir: pathlib.Path,
    keypoints: np.ndarray,
    append_eos: bool,
    train_ratio: float,
    val_ratio: float,
) -> tuple[pathlib.Path, str]:
    split = record.split or hashed_split(
        sample_key=f"{record.gloss}|{record.signer or 'unknown'}|{record.sample_id}",
        train_ratio=train_ratio,
        val_ratio=val_ratio,
    )
    labels = build_labels(record.gloss, keypoints.shape[0], append_eos=append_eos)
    metadata = prepare_metadata(record, keypoints=keypoints, split=split)

    destination = output_dir / split / f"{record.sample_id}.npz"
    destination.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        destination,
        keypoints=keypoints.astype(np.float32),
        labels=labels,
        feature_names=np.asarray(FEATURE_NAMES),
        gloss=np.asarray(record.gloss),
        split=np.asarray(split),
        metadata=np.asarray(json.dumps(metadata, sort_keys=True)),
    )
    return destination, split


def summarize_handshape_observations(records: Iterable[SequenceRecord]) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    handshape_keys = (
        "dominant_start_handshape",
        "dominant_end_handshape",
        "nondominant_start_handshape",
        "nondominant_end_handshape",
    )
    for record in records:
        observed = {
            key: record.metadata.get(key)
            for key in handshape_keys
            if record.metadata.get(key)
        }
        if not observed:
            continue

        entry = summary.setdefault(
            record.gloss,
            {
                "samples": 0,
                "dominant_start_handshape": set(),
                "dominant_end_handshape": set(),
                "nondominant_start_handshape": set(),
                "nondominant_end_handshape": set(),
            },
        )
        entry["samples"] += 1
        for key, value in observed.items():
            entry[key].add(value)

    materialized: dict[str, Any] = {}
    for gloss, payload in summary.items():
        materialized[gloss] = {
            "samples": payload["samples"],
            "dominant_start_handshape": sorted(payload["dominant_start_handshape"]),
            "dominant_end_handshape": sorted(payload["dominant_end_handshape"]),
            "nondominant_start_handshape": sorted(payload["nondominant_start_handshape"]),
            "nondominant_end_handshape": sorted(payload["nondominant_end_handshape"]),
        }
    return materialized


def run_preparation(
    records: list[SequenceRecord],
    output_dir: pathlib.Path,
    target_fps: float,
    min_frames: int,
    append_eos: bool,
    train_ratio: float,
    val_ratio: float,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    write_vocabulary_assets(output_dir)
    write_keypoint_schema(output_dir / "keypoint_schema.json")

    counts_by_split = {"train": 0, "val": 0, "test": 0}
    counts_by_gloss: dict[str, int] = {}
    written_paths: list[str] = []
    skipped: list[dict[str, Any]] = []

    for record in records:
        try:
            keypoints = extract_keypoints_from_video(record, target_fps=target_fps, min_frames=min_frames)
            destination, split = write_npz_sample(
                record=record,
                output_dir=output_dir,
                keypoints=keypoints,
                append_eos=append_eos,
                train_ratio=train_ratio,
                val_ratio=val_ratio,
            )
        except Exception as exc:  # pragma: no cover - runtime path depends on local videos
            skipped.append({"sample_id": record.sample_id, "reason": str(exc)})
            logger.warning("Skipping %s: %s", record.sample_id, exc)
            continue

        counts_by_split[split] += 1
        counts_by_gloss[record.gloss] = counts_by_gloss.get(record.gloss, 0) + 1
        written_paths.append(str(destination))

    summary = {
        "schema_version": KEYPOINT_SCHEMA_VERSION,
        "feature_dim": FEATURES_PER_FRAME,
        "target_fps": target_fps,
        "min_frames": min_frames,
        "total_sequences": len(written_paths),
        "unique_glosses": len(counts_by_gloss),
        "counts_by_split": counts_by_split,
        "counts_by_gloss": dict(sorted(counts_by_gloss.items())),
        "mvp_ground_truth_goal": {
            "target_sequences": 500,
            "met": len(written_paths) >= 500,
        },
        "skipped": skipped,
    }

    (output_dir / "dataset_manifest.json").write_text(
        json.dumps(summary, indent=2) + "\n",
        encoding="utf-8",
    )

    observed = summarize_handshape_observations(records)
    if observed:
        (output_dir / "asllvd_observed_handshapes.json").write_text(
            json.dumps(observed, indent=2) + "\n",
            encoding="utf-8",
        )

    return summary


def add_common_generation_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--output-dir", required=True, help="Directory where prepared NPZ files are written.")
    parser.add_argument("--target-fps", type=float, default=DEFAULT_TARGET_FPS)
    parser.add_argument("--min-frames", type=int, default=DEFAULT_MIN_FRAMES)
    parser.add_argument("--append-eos", action="store_true", help="Overwrite the last frame label with [EOS].")
    parser.add_argument("--train-ratio", type=float, default=0.8)
    parser.add_argument("--val-ratio", type=float, default=0.1)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Prepare ASL keypoint training data for NIMBUS.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    schema_parser = subparsers.add_parser("write-schema", help="Write keypoint_schema.json to a target directory.")
    schema_parser.add_argument(
        "--output-dir",
        default=str(CURRENT_DIR),
        help="Directory where keypoint_schema.json is written.",
    )

    custom_parser = subparsers.add_parser("custom-video", help="Prepare NPZ clips from a custom annotation manifest.")
    custom_parser.add_argument("--annotations", required=True, help="CSV/JSON/JSONL manifest with gloss and video paths.")
    custom_parser.add_argument("--video-root", default=None, help="Optional base directory for relative video paths.")
    add_common_generation_args(custom_parser)

    asllvd_parser = subparsers.add_parser("asllvd", help="Prepare NPZ clips from the ASLLVD spreadsheet plus scene videos.")
    asllvd_parser.add_argument("--index", default=DEFAULT_ASLLVD_INDEX_URL, help="Local path or URL to the ASLLVD spreadsheet.")
    asllvd_parser.add_argument("--download-dir", required=True, help="Directory for downloaded ASLLVD scene videos.")
    asllvd_parser.add_argument("--camera", type=int, default=1, help="ASLLVD camera number. Camera 1 is the most available QuickTime view.")
    asllvd_parser.add_argument("--download-missing", action="store_true", help="Download missing scene videos from the official BU/Rutgers mirror.")
    asllvd_parser.add_argument("--limit", type=int, default=None, help="Optional cap on the number of records to process.")
    asllvd_parser.add_argument("--gloss", action="append", default=None, help="Optional canonical gloss filter; repeat to add multiple.")
    add_common_generation_args(asllvd_parser)
    return parser


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    parser = build_parser()
    args = parser.parse_args()

    if args.command == "write-schema":
        output_dir = pathlib.Path(args.output_dir).resolve()
        write_keypoint_schema(output_dir / "keypoint_schema.json")
        return

    if args.train_ratio <= 0 or args.val_ratio < 0 or args.train_ratio + args.val_ratio >= 1:
        raise ValueError("train-ratio and val-ratio must leave a positive remainder for test.")
    if args.min_frames <= 0:
        raise ValueError("min-frames must be positive.")

    output_dir = pathlib.Path(args.output_dir).resolve()
    if args.command == "custom-video":
        records = load_custom_manifest(
            manifest_path=pathlib.Path(args.annotations).resolve(),
            video_root=pathlib.Path(args.video_root) if args.video_root else None,
        )
    else:
        gloss_filters = {canonicalize_gloss(value) for value in (args.gloss or [])}
        gloss_filters.discard("[UNKNOWN_SIGN]")
        records = build_asllvd_records(
            index_source=args.index,
            download_dir=pathlib.Path(args.download_dir).resolve(),
            camera=args.camera,
            download_missing=args.download_missing,
            gloss_filters=gloss_filters or None,
            limit=args.limit,
        )

    summary = run_preparation(
        records=records,
        output_dir=output_dir,
        target_fps=args.target_fps,
        min_frames=args.min_frames,
        append_eos=args.append_eos,
        train_ratio=args.train_ratio,
        val_ratio=args.val_ratio,
    )
    logger.info("Prepared %d sequences across %d glosses", summary["total_sequences"], summary["unique_glosses"])


if __name__ == "__main__":
    main()
