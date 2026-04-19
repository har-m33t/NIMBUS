"""Pydantic models for the WebSocket message schema in PROTOCOLS.md §1."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

EmotionLabel = Literal[
    "HAPPY", "SAD", "ANGRY", "CALM", "SURPRISED", "FEAR", "DISGUSTED", "CONFUSED"
]

SignalEvent = Literal[
    "JOIN_ROOM", "LEAVE_ROOM", "ICE_CANDIDATE",
    "SDP_OFFER", "SDP_ANSWER", "NEW_CAPTION", "ENDPOINT_WARMING",
    "PEER_JOINED", "PEER_LEFT",
]


class Landmark(BaseModel):
    model_config = ConfigDict(extra="ignore")
    x: float = Field(ge=0.0, le=1.0)
    y: float = Field(ge=0.0, le=1.0)
    z: float
    visibility: float | None = None


class Keypoints(BaseModel):
    leftHand: list[Landmark] = Field(default_factory=list)
    rightHand: list[Landmark] = Field(default_factory=list)
    pose: list[Landmark] = Field(default_factory=list)


class InferPayload(BaseModel):
    model_config = ConfigDict(extra="ignore")
    keypoints: Keypoints | None = None
    includeFaceCrop: bool = False
    # JPEG face crop, base64-encoded, max 640×480px (PROTOCOLS.md §3.2).
    # Present only when includeFaceCrop=true, once per 10 frames.
    faceCropBase64: str | None = None
    # Edge-inference mode: browser ONNX model sends a single gloss token
    # directly instead of raw keypoints. When present, SageMaker is bypassed.
    token: str | None = None


class InferMessage(BaseModel):
    action: Literal["INFER"]
    sessionId: str
    roomId: str
    timestamp: str
    sequenceNumber: int
    payload: InferPayload


class GlossEvent(BaseModel):
    type: Literal["GLOSS"] = "GLOSS"
    sessionId: str
    timestamp: str
    sequenceNumber: int
    payload: dict  # {"tokens": [...], "confidence": 0.xx}


class EmotionEvent(BaseModel):
    type: Literal["EMOTION"] = "EMOTION"
    sessionId: str
    timestamp: str
    payload: dict  # {"emotion": "CALM", "confidence": 1.0, "allEmotions": {...}}


class CaptionEvent(BaseModel):
    type: Literal["CAPTION"] = "CAPTION"
    sessionId: str
    timestamp: str
    sequenceNumber: int
    payload: dict  # {"text", "emotion", "audioUrl", "latencyMs"}


class ErrorEvent(BaseModel):
    type: Literal["ERROR"] = "ERROR"
    sessionId: str
    timestamp: str
    payload: dict  # {"code", "glossFallback"?, "message"}


class SignalEventMsg(BaseModel):
    type: Literal["SIGNAL"] = "SIGNAL"
    event: SignalEvent
    sessionId: str
    roomId: str
    payload: dict = Field(default_factory=dict)
