"""Gesture vocabulary mapping for NIMBUS Option 2 fallback.

Maps MediaPipe GestureRecognizer category names to ASL demo gloss tokens.
Unknown gestures return None — no token is emitted.
"""
from __future__ import annotations

# MediaPipe built-in gesture labels → ASL demo gloss tokens
GESTURE_TO_GLOSS: dict[str, str] = {
    "Victory":      "WIN",
    "Open_Palm":    "HELLO",
    "Closed_Fist":  "STOP",
    "Pointing_Up":  "ATTENTION",
    "Thumb_Up":     "YES",
    "Thumb_Down":   "NO",
    "ILoveYou":     "LOVE",
}


def map_gesture(label: str) -> str | None:
    """Return the ASL gloss token for a MediaPipe gesture label, or None."""
    return GESTURE_TO_GLOSS.get(label)
