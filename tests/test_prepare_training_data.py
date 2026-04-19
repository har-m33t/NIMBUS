from __future__ import annotations

import json
import pathlib
import sys
import tempfile

import numpy as np


ROOT = pathlib.Path(__file__).resolve().parents[1]
ML_SRC = ROOT / "backend" / "ml_pipeline" / "src"
ML_DATA = ROOT / "backend" / "ml_pipeline" / "data"
for path in (ML_SRC, ML_DATA):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import prepare_training_data as prep  # noqa: E402


def test_keypoint_schema_has_expected_feature_layout():
    schema = prep.build_keypoint_schema()

    assert schema["features_per_frame"] == 258
    assert len(schema["feature_names"]) == 258
    assert schema["segments"][0]["name"] == "left_hand"
    assert schema["segments"][1]["start_index"] == 63
    assert schema["segments"][2]["feature_count"] == 132


def test_write_npz_sample_includes_uniform_metadata():
    scratch_root = ROOT / "test_data"
    scratch_root.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(dir=scratch_root) as temp_dir:
        tmp_path = pathlib.Path(temp_dir)
        record = prep.SequenceRecord(
            sample_id="hello_clip",
            gloss="HELLO",
            video_path=tmp_path / "hello.mov",
            source="custom-video",
            signer="signer-a",
        )
        keypoints = np.zeros((4, prep.FEATURES_PER_FRAME), dtype=np.float32)

        destination, split = prep.write_npz_sample(
            record=record,
            output_dir=tmp_path,
            keypoints=keypoints,
            append_eos=False,
            train_ratio=0.8,
            val_ratio=0.1,
        )

        assert destination.exists()
        assert split in {"train", "val", "test"}

        with np.load(destination) as npz:
            metadata = json.loads(npz["metadata"].item())

            assert npz["keypoints"].shape == (4, 258)
            assert npz["labels"].tolist() == [prep.TOKEN_TO_INDEX["HELLO"]] * 4
            assert len(npz["feature_names"]) == 258
            assert npz["gloss"].item() == "HELLO"
            assert npz["split"].item() == split
            assert metadata["schema_version"] == prep.KEYPOINT_SCHEMA_VERSION
            assert metadata["handshape_prior"]["profile_id"] == "greeting-salute"


def test_handshape_observation_summary_collects_unique_annotations():
    records = [
        prep.SequenceRecord(
            sample_id="a",
            gloss="HELLO",
            video_path=pathlib.Path("a.mov"),
            source="asllvd",
            metadata={"dominant_start_handshape": "B", "dominant_end_handshape": "B"},
        ),
        prep.SequenceRecord(
            sample_id="b",
            gloss="HELLO",
            video_path=pathlib.Path("b.mov"),
            source="asllvd",
            metadata={"dominant_start_handshape": "B", "dominant_end_handshape": "5"},
        ),
    ]

    summary = prep.summarize_handshape_observations(records)
    assert summary["HELLO"]["samples"] == 2
    assert summary["HELLO"]["dominant_start_handshape"] == ["B"]
    assert summary["HELLO"]["dominant_end_handshape"] == ["5", "B"]
