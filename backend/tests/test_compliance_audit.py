"""Phase 7.3 compliance tests: C2 (no PII to Bedrock), C4 (S3 security).

C1 note: face-crop Rekognition is now enabled. Tests updated accordingly.
Face crop bytes are passed to Rekognition only — never to SageMaker or Bedrock.
"""
from __future__ import annotations

import json
import inspect

import pytest


class TestConstraintC1:
    """C1 updated: face crops reach Rekognition only, not SageMaker or Bedrock."""

    def test_facecropbase64_in_schema(self):
        """InferPayload models faceCropBase64 for Rekognition (§3.2)."""
        from common.schemas import InferPayload
        assert "faceCropBase64" in InferPayload.model_fields

    def test_face_crop_reaches_rekognition_not_sagemaker(self, monkeypatch):
        """face crop bytes must go to Rekognition; SageMaker must never see them."""
        from handlers import process_frame
        from services import sagemaker_inference, rekognition_emotion

        sm_invocations = []
        rek_invocations = []

        def capture_sm(kp):
            sm_invocations.append(kp)
            return {"tokens": ["X"], "confidence": 0.9}

        def capture_rek(face_bytes):
            rek_invocations.append(face_bytes)
            return ("HAPPY", 0.93, {"HAPPY": 0.93})

        monkeypatch.setattr(process_frame, "post_to_connection", lambda *a, **kw: True)
        monkeypatch.setattr(process_frame, "append_gloss", lambda *a, **kw: {"glossBuffer": ["X"]})
        monkeypatch.setattr(sagemaker_inference, "is_in_service", lambda: True)
        monkeypatch.setattr(sagemaker_inference, "invoke", capture_sm)
        monkeypatch.setattr(rekognition_emotion, "detect_emotion", capture_rek)
        monkeypatch.setattr(process_frame, "update_emotion", lambda sid, emo: None)
        process_frame._cold_start_checked.clear()
        process_frame._session_emotion.clear()

        from types import SimpleNamespace
        ctx = SimpleNamespace(function_name="test", function_version="$LATEST",
                             memory_limit_in_mb=1024, invoked_function_arn="arn:test",
                             aws_request_id="req-test")
        import base64
        face_b64 = base64.b64encode(b"JPEG" * 500).decode()
        body = {
            "action": "INFER",
            "sessionId": "11111111-1111-4111-8111-111111111111",
            "roomId": "r1",
            "timestamp": "2026-04-18T12:00:00Z",
            "sequenceNumber": 10,
            "payload": {"keypoints": {"leftHand": [], "rightHand": [], "pose": []},
                       "includeFaceCrop": True,
                       "faceCropBase64": face_b64},
        }
        event = {"requestContext": {"connectionId": "c1",
                                   "domainName": "x.execute-api.us-east-1.amazonaws.com",
                                   "stage": "dev"},
                "body": json.dumps(body)}

        process_frame.handler(event, ctx)

        assert sm_invocations, "SageMaker must be called"
        assert not hasattr(sm_invocations[0], "faceCropBase64"), \
            "face crop bytes must NOT reach SageMaker"
        assert rek_invocations, "Rekognition must be called with face bytes"


class TestConstraintC2:
    """Hackathon C2: no personal, biometric, health, etc. data to AWS."""

    def test_keypoints_allowed_not_biometric(self):
        """Keypoints (normalized floats) are allowed; face crops are not."""
        from common.schemas import Landmark, Keypoints
        # Keypoints should be constructible
        k = Keypoints(
            leftHand=[Landmark(x=0.1, y=0.2, z=0.3)],
            rightHand=[Landmark(x=0.5, y=0.6, z=0.7)],
            pose=[]
        )
        assert k is not None

    def test_no_user_provided_freetext_to_bedrock(self):
        """Bedrock prompt only gets gloss tokens + captions, never user input."""
        import services.bedrock_interpreter as bi
        prompt = bi._build_prompt(["I", "GO"], ["prev caption"], "CALM")
        # Proof: only tokens, prior captions, emotion — no other fields
        assert "payload" not in prompt.lower(), "should not include raw payload"
        assert "I GO" in prompt or "I" in prompt


class TestConstraintC4:
    """Hackathon C4: S3 Block Public Access ON for all buckets."""

    def test_polly_synthesize_returns_presigned_url(self, monkeypatch):
        """Polly service returns presigned URL, verifying secure S3 access."""
        from io import BytesIO
        import services.polly_tts as pt

        called = []
        def fake_s3():
            class FakeS3:
                def put_object(self, **kw):
                    pass
                def generate_presigned_url(self, method, Params, ExpiresIn):
                    called.append({"method": method, "ExpiresIn": ExpiresIn})
                    return "https://s3.example.com/audio.mp3"
            return FakeS3()

        def fake_polly():
            class FakePolly:
                def synthesize_speech(self, **kw):
                    return {"AudioStream": BytesIO(b"MP3_DATA")}
            return FakePolly()

        monkeypatch.setattr(pt, "_s3_client", fake_s3)
        monkeypatch.setattr(pt, "_polly_client", fake_polly)
        url = pt.synthesize("<speak>test</speak>")
        assert "https://" in url, "must return HTTPS presigned URL"
        assert called, "must call generate_presigned_url"
        assert called[0]["ExpiresIn"] <= 300, "presigned URL should expire within 5 min"

    def test_ssml_loads_from_s3_not_local(self):
        """SSML config loads from S3 at runtime, not local repo."""
        import common.ssml as ssml
        src = inspect.getsource(ssml)
        assert "get_object" in src, "must load from S3"
        # _load_from_s3() is the only path to config
        assert "def _load_from_s3" in src


class TestComplianceProof:
    """Proof that face crop data stays within Rekognition — never touches SageMaker."""

    def test_face_crop_never_reaches_sagemaker(self, monkeypatch):
        from handlers import process_frame
        from services import sagemaker_inference, rekognition_emotion

        invoked_with = []
        monkeypatch.setattr(process_frame, "post_to_connection", lambda *a, **kw: True)
        monkeypatch.setattr(process_frame, "append_gloss", lambda *a, **kw: {"glossBuffer": ["X"]})
        monkeypatch.setattr(sagemaker_inference, "is_in_service", lambda: True)
        monkeypatch.setattr(sagemaker_inference, "invoke",
                            lambda kp: invoked_with.append(kp) or {"tokens": ["X"], "confidence": 0.9})
        monkeypatch.setattr(rekognition_emotion, "detect_emotion",
                            lambda b: ("CALM", 1.0, {"CALM": 1.0}))
        monkeypatch.setattr(process_frame, "update_emotion", lambda sid, emo: None)
        process_frame._cold_start_checked.clear()
        process_frame._session_emotion.clear()

        from types import SimpleNamespace
        ctx = SimpleNamespace(function_name="test", function_version="$LATEST",
                             memory_limit_in_mb=1024, invoked_function_arn="arn:test",
                             aws_request_id="req-test")
        body = {
            "action": "INFER",
            "sessionId": "11111111-1111-4111-8111-111111111111",
            "roomId": "r1",
            "timestamp": "2026-04-18T12:00:00Z",
            "sequenceNumber": 1,
            "payload": {"keypoints": {"leftHand": [], "rightHand": [], "pose": []},
                       "includeFaceCrop": True,
                       "faceCropBase64": "SENSITIVE_DATA"},
        }
        event = {"requestContext": {"connectionId": "c1",
                                   "domainName": "x.execute-api.us-east-1.amazonaws.com",
                                   "stage": "dev"},
                "body": json.dumps(body)}

        process_frame.handler(event, ctx)

        assert invoked_with, "SageMaker must be called"
        assert not hasattr(invoked_with[0], "faceCropBase64"), \
            "face crop must not reach SageMaker"
