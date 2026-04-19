"""
Augmentation utilities for keypoint-based ASL training.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np

FEATURES_PER_FRAME = 258


@dataclass(frozen=True)
class KeypointSlice:
    name: str
    start: int
    end: int
    landmarks: int
    dims: int
    coord_dims: int


LEFT_HAND = KeypointSlice("left_hand", 0, 63, 21, 3, 3)
RIGHT_HAND = KeypointSlice("right_hand", 63, 126, 21, 3, 3)
POSE = KeypointSlice("pose", 126, 258, 33, 4, 3)
KEYPOINT_GROUPS = (LEFT_HAND, RIGHT_HAND, POSE)


class KeypointAugmenter:
    """
    Sequence-level augmentation tuned for hand + pose landmark spaces.

    Supported perturbations:
      - spatial jittering
      - scale adjustment
      - temporal shifting
      - in-plane keypoint rotation
    """

    def __init__(
        self,
        jitter_std: float = 0.012,
        scale_range: tuple[float, float] = (0.9, 1.1),
        temporal_shift_range: int = 2,
        rotation_range_degrees: float = 12.0,
        seed: Optional[int] = None,
    ) -> None:
        self.jitter_std = max(0.0, float(jitter_std))
        self.scale_range = scale_range
        self.temporal_shift_range = max(0, int(temporal_shift_range))
        self.rotation_range_radians = np.deg2rad(max(0.0, float(rotation_range_degrees)))
        self.rng = np.random.default_rng(seed)

    def __call__(
        self,
        keypoints: np.ndarray,
        labels: Optional[np.ndarray] = None,
    ) -> tuple[np.ndarray, np.ndarray]:
        if keypoints.ndim != 2 or keypoints.shape[1] != FEATURES_PER_FRAME:
            raise ValueError(f"Expected keypoints with shape (T, {FEATURES_PER_FRAME}), got {keypoints.shape}")

        augmented = np.asarray(keypoints, dtype=np.float32).copy()
        if labels is None:
            augmented_labels = np.zeros((len(augmented),), dtype=np.int64)
        else:
            augmented_labels = np.asarray(labels, dtype=np.int64).copy()

        augmented, augmented_labels = self._apply_temporal_shift(augmented, augmented_labels)
        self._apply_spatial_jitter(augmented)
        self._apply_scale(augmented)
        self._apply_rotation(augmented)
        return augmented, augmented_labels

    def _apply_temporal_shift(
        self,
        keypoints: np.ndarray,
        labels: np.ndarray,
    ) -> tuple[np.ndarray, np.ndarray]:
        if self.temporal_shift_range <= 0 or len(keypoints) == 0:
            return keypoints, labels

        shift = int(self.rng.integers(-self.temporal_shift_range, self.temporal_shift_range + 1))
        if shift == 0:
            return keypoints, labels

        if shift > 0:
            kp_pad = np.repeat(keypoints[:1], shift, axis=0)
            lb_pad = np.repeat(labels[:1], shift, axis=0)
            return (
                np.concatenate([kp_pad, keypoints[:-shift]], axis=0),
                np.concatenate([lb_pad, labels[:-shift]], axis=0),
            )

        shift = abs(shift)
        kp_pad = np.repeat(keypoints[-1:], shift, axis=0)
        lb_pad = np.repeat(labels[-1:], shift, axis=0)
        return (
            np.concatenate([keypoints[shift:], kp_pad], axis=0),
            np.concatenate([labels[shift:], lb_pad], axis=0),
        )

    def _apply_spatial_jitter(self, keypoints: np.ndarray) -> None:
        if self.jitter_std <= 0:
            return

        global_xy_shift = self.rng.normal(0.0, self.jitter_std, size=(1, 1, 2)).astype(np.float32)
        depth_shift = np.array([self.rng.normal(0.0, self.jitter_std * 0.5)], dtype=np.float32)

        for group in KEYPOINT_GROUPS:
            group_view = keypoints[:, group.start : group.end].reshape(-1, group.landmarks, group.dims)
            coords = group_view[..., : group.coord_dims]
            valid = np.any(np.abs(coords) > 1e-6, axis=-1, keepdims=True)
            local_noise = self.rng.normal(0.0, self.jitter_std * 0.35, size=coords.shape).astype(np.float32)
            if group.coord_dims >= 2:
                coords[..., :2] = np.where(valid, coords[..., :2] + global_xy_shift + local_noise[..., :2], coords[..., :2])
            if group.coord_dims == 3:
                coords[..., 2:3] = np.where(valid, coords[..., 2:3] + depth_shift + local_noise[..., 2:3], coords[..., 2:3])
            group_view[..., : group.coord_dims] = coords

    def _apply_scale(self, keypoints: np.ndarray) -> None:
        min_scale, max_scale = self.scale_range
        if min_scale == 1.0 and max_scale == 1.0:
            return

        scale = float(self.rng.uniform(min_scale, max_scale))
        depth_scale = 1.0 + (scale - 1.0) * 0.5

        for group in KEYPOINT_GROUPS:
            group_view = keypoints[:, group.start : group.end].reshape(-1, group.landmarks, group.dims)
            coords = group_view[..., : group.coord_dims]
            valid = np.any(np.abs(coords) > 1e-6, axis=-1)
            if not np.any(valid):
                continue
            center = coords[valid].mean(axis=0)
            coords[..., :2] = np.where(
                valid[..., None],
                center[:2] + (coords[..., :2] - center[:2]) * scale,
                coords[..., :2],
            )
            if group.coord_dims == 3:
                coords[..., 2] = np.where(valid, center[2] + (coords[..., 2] - center[2]) * depth_scale, coords[..., 2])
            group_view[..., : group.coord_dims] = coords

    def _apply_rotation(self, keypoints: np.ndarray) -> None:
        if self.rotation_range_radians <= 0:
            return

        angle = float(self.rng.uniform(-self.rotation_range_radians, self.rotation_range_radians))
        cos_theta = np.cos(angle).astype(np.float32)
        sin_theta = np.sin(angle).astype(np.float32)
        rotation_matrix = np.array([[cos_theta, -sin_theta], [sin_theta, cos_theta]], dtype=np.float32)

        for group in KEYPOINT_GROUPS:
            group_view = keypoints[:, group.start : group.end].reshape(-1, group.landmarks, group.dims)
            coords = group_view[..., : group.coord_dims]
            valid = np.any(np.abs(coords[..., :2]) > 1e-6, axis=-1)
            if not np.any(valid):
                continue
            center = coords[..., :2][valid].mean(axis=0)
            centered = coords[..., :2] - center
            rotated = centered @ rotation_matrix.T + center
            coords[..., :2] = np.where(valid[..., None], rotated, coords[..., :2])
            group_view[..., : group.coord_dims] = coords
