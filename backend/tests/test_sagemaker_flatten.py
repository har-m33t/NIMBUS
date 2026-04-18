from common.schemas import Keypoints, Landmark
from services.sagemaker_inference import FEATURES, flatten, to_tensor


def test_flatten_empty_hands_produce_258_zero_padded():
    k = Keypoints()
    vec = flatten(k)
    assert len(vec) == FEATURES == 258
    assert all(v == 0.0 for v in vec)


def test_flatten_with_one_left_landmark_pads_rest():
    k = Keypoints(leftHand=[Landmark(x=0.5, y=0.5, z=0.1)])
    vec = flatten(k)
    assert vec[0:3] == [0.5, 0.5, 0.1]
    assert vec[3] == 0.0  # padded
    assert len(vec) == 258


def test_pose_includes_visibility():
    k = Keypoints(pose=[Landmark(x=0.1, y=0.2, z=0.3, visibility=0.9)])
    vec = flatten(k)
    # pose starts at index 126 (63 left + 63 right)
    assert vec[126:130] == [0.1, 0.2, 0.3, 0.9]


def test_to_tensor_shape_1_T_258():
    k = Keypoints()
    t = to_tensor([k])
    assert len(t) == 1 and len(t[0]) == 1 and len(t[0][0]) == 258


def test_extra_landmarks_truncated():
    # 22 landmarks on left hand (1 too many) — must be truncated to 21.
    lots = [Landmark(x=0.0, y=0.0, z=0.0) for _ in range(22)]
    k = Keypoints(leftHand=lots)
    vec = flatten(k)
    assert len(vec) == 258
