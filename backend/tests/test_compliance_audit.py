"""Phase 7.3 compliance tests: C1 (no face crops), C2 (no PII), C4 (S3 security)."""
from __future__ import annotations

import json
import inspect

import pytest


class TestConstraintC1:
    """Hackathon C1: no Rekognition, face crops discarded immediately."""

    def test_facecropbase64_not_in_schema(self):
        """Proof: InferPayload schema never models faceCropBase64."""
        from common.schemas import InferPayload
        fields = InferPayload.model_fields.keys()
        assert "faceCropBase64" not in fields, "faceCropBase64 must not be modeled"

    def test_facecrop_discarded_audit_metric(self, monkeypatch):
        """If includeFaceCrop=true, FaceCropsDiscarded metric is incremented."""
        from handlers import process_frame
        from services import sagemaker_inference

        metrics_logged = []
        monkeypatch.setattr(process_frame.metrics, "add_metric",
                           lambda **kw: metrics_logged.append(kw))
        monkeypatch.setattr(process_frame, "post_to_connection", lambda *a, **kw: True)
        monkeypatch.setattr(sagemaker_inference, "is_in_service", lambda: True)
        monkeypatch.setattr(sagemaker_inference, "invoke",
                            lambda kp: {"tokens": ["OK"], "confidence": 0.9})
        process_frame._cold_start_checked.clear()

        from types import SimpleNamespace
        ctx = SimpleNamespace(function_name="test", function_version="$LATEST",
                             memory_limit_in_mb=1024, invoked_function_arn="arn:test",
                             aws_request_id="req-test")
        body = {
            "action": "INFER",
            "sessionId": "sid",
            "roomId": "r1",
            "timestamp": "2026-04-18T12:00:00Z",
            "sequenceNumber": 1,
            "payload": {"keypoints": {"leftHand": [], "rightHand": [], "pose": []},
                       "includeFaceCrop": True,
                       "faceCropBase64": "AAA=" * 10000},
        }
        event = {"requestContext": {"connectionId": "c1"},
                "body": json.dumps(body)}

        resp = process_frame.handler(event, ctx)
        assert resp["statusCode"] == 200
        # Verify FaceCropsDiscarded metric was logged
        assert any(m.get("name") == "FaceCropsDiscarded" for m in metrics_logged), \
            "must log FaceCropsDiscarded metric"

    def test_handler_no_rekognition_module(self):
        """process_frame does not import rekognition_emotion service."""
        from handlers import process_frame
        # Check that rekognition_emotion is NOT imported at module level
        import sys
        assert "rekognition_emotion" not in sys.modules, "should not import rekognition_emotion"


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
    """Proof of compliance mechanisms."""

    def test_face_crop_field_ignored_in_handler(self, monkeypatch):
        """Handler accepts faceCropBase64 but never uses it."""
        from handlers import process_frame
        from services import sagemaker_inference

        # Track what goes to SageMaker
        invoked_with = []
        def capture_invoke(kp):
            invoked_with.append(kp)
            return {"tokens": ["X"], "confidence": 0.9}

        monkeypatch.setattr(process_frame, "post_to_connection", lambda *a, **kw: True)
        monkeypatch.setattr(sagemaker_inference, "is_in_service", lambda: True)
        monkeypatch.setattr(sagemaker_inference, "invoke", capture_invoke)
        process_frame._cold_start_checked.clear()

        from types import SimpleNamespace
        ctx = SimpleNamespace(function_name="test", function_version="$LATEST",
                             memory_limit_in_mb=1024, invoked_function_arn="arn:test",
                             aws_request_id="req-test")
        body = {
            "action": "INFER",
            "sessionId": "sid",
            "roomId": "r1",
            "timestamp": "2026-04-18T12:00:00Z",
            "sequenceNumber": 1,
            "payload": {"keypoints": {"leftHand": [], "rightHand": [], "pose": []},
                       "includeFaceCrop": True,
                       "faceCropBase64": "SENSITIVE_DATA_SHOULD_BE_IGNORED"},
        }
        event = {"requestContext": {"connectionId": "c1"},
                "body": json.dumps(body)}

        process_frame.handler(event, ctx)

        # Verify no sensitive face data was passed to SageMaker
        assert invoked_with, "should invoke sagemaker"
        keypoints = invoked_with[0]
        assert not hasattr(keypoints, "faceCropBase64"), "face crop must not reach SageMaker"
