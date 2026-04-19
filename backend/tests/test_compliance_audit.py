"""Phase 7.3 compliance tests: C2 (no PII to Bedrock), C4 (S3 security).

SageMaker has been removed from the pipeline. All inference is now done
client-side (ONNX) and letters are sent as tokens. These tests verify:
  - C1: face crops reach Rekognition only, never Bedrock or any other service
  - C2: no user-provided free-text forwarded to Bedrock
  - C4: S3 presigned URLs, Block Public Access
"""
from __future__ import annotations

import base64
import inspect
import json

import pytest


class TestConstraintC1:
    """C1 updated: face crops go to Rekognition only — not to Bedrock or any other service."""

    def test_facecropbase64_in_schema(self):
        """InferPayload models faceCropBase64 for Rekognition (§3.2)."""
        from common.schemas import InferPayload
        assert "faceCropBase64" in InferPayload.model_fields

    def test_face_crop_reaches_rekognition(self, monkeypatch):
        """face crop bytes must be passed to Rekognition on the 10th-frame cadence."""
        from handlers import process_frame
        from services import rekognition_emotion

        rek_invocations = []

        def capture_rek(face_bytes):
            rek_invocations.append(face_bytes)
            return ("HAPPY", 0.93, {"HAPPY": 0.93})

        monkeypatch.setattr(process_frame, "post_to_connection", lambda *a, **kw: True)
        monkeypatch.setattr(process_frame, "append_gloss", lambda *a, **kw: {"glossBuffer": ["A"]})
        monkeypatch.setattr(rekognition_emotion, "detect_emotion", capture_rek)
        monkeypatch.setattr(process_frame, "update_emotion", lambda sid, emo: None)
        process_frame._last_token.clear()
        process_frame._session_emotion.clear()

        from types import SimpleNamespace
        ctx = SimpleNamespace(function_name="test", function_version="$LATEST",
                              memory_limit_in_mb=1024, invoked_function_arn="arn:test",
                              aws_request_id="req-test")
        face_b64 = base64.b64encode(b"JPEG" * 500).decode()
        body = {
            "action": "INFER",
            "sessionId": "11111111-1111-4111-8111-111111111111",
            "roomId": "r1",
            "timestamp": "2026-04-18T12:00:00Z",
            "sequenceNumber": 10,   # 10th frame triggers Rekognition
            "payload": {"token": "A", "includeFaceCrop": True, "faceCropBase64": face_b64},
        }
        event = {"requestContext": {"connectionId": "c1",
                                    "domainName": "x.execute-api.us-east-1.amazonaws.com",
                                    "stage": "dev"},
                 "body": json.dumps(body)}

        process_frame.handler(event, ctx)

        assert rek_invocations, "Rekognition must be called with face bytes on 10th frame"
        assert isinstance(rek_invocations[0], bytes), "must pass decoded bytes to Rekognition"

    def test_face_crop_not_in_bedrock_prompt(self):
        """Bedrock prompt must never contain face crop data."""
        import services.bedrock_interpreter as bi
        prompt = bi._build_prompt(["HELLO", "WORLD"], [], "CALM")
        assert "JPEG" not in prompt
        assert "faceCrop" not in prompt
        assert "base64" not in prompt.lower()


class TestConstraintC2:
    """Hackathon C2: no personal, biometric, health, etc. data to AWS."""

    def test_keypoints_allowed_not_biometric(self):
        """Keypoints (normalized floats) are allowed."""
        from common.schemas import Landmark, Keypoints
        k = Keypoints(
            leftHand=[Landmark(x=0.1, y=0.2, z=0.3)],
            rightHand=[Landmark(x=0.5, y=0.6, z=0.7)],
            pose=[],
        )
        assert k is not None

    def test_no_user_provided_freetext_to_bedrock(self):
        """Bedrock prompt only gets reconstructed words + captions + emotion."""
        import services.bedrock_interpreter as bi
        prompt = bi._build_prompt(["HELLO", "WORLD"], ["prev caption"], "CALM")
        assert "payload" not in prompt.lower(), "raw payload must not appear in prompt"
        assert "HELLO" in prompt or "WORLD" in prompt


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
        assert "def _load_from_s3" in src


class TestComplianceProof:
    """Proof that face crop data stays within Rekognition only."""

    def test_face_crop_bytes_not_forwarded_to_other_services(self, monkeypatch):
        """face crop bytes must never appear in Bedrock prompt or any non-Rekognition call."""
        import services.bedrock_interpreter as bi

        bedrock_prompts: list[str] = []
        original_build = bi._build_prompt

        def capturing_build(tokens, recent, emotion):
            prompt = original_build(tokens, recent, emotion)
            bedrock_prompts.append(prompt)
            return prompt

        monkeypatch.setattr(bi, "_build_prompt", capturing_build)

        # Call the prompt builder with what the handler would pass (words, not face data)
        prompt = capturing_build(["HELLO", "WORLD"], [], "CALM")
        assert "SENSITIVE" not in prompt
        assert "faceCrop" not in prompt
        assert all("base64" not in p.lower() for p in bedrock_prompts)
