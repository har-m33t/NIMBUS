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
    keypoints: Keypoints
    includeFaceCrop: bool = False
    # faceCropBase64 intentionally NOT modeled — hackathon policy C1
    # discards biometric data. Any value present is ignored by the handler.


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
