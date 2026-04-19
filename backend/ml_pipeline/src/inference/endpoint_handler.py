"""
SageMaker endpoint inference handler for the ASL transformer model.
"""
from __future__ import annotations

import json
import math
import os
from typing import Any

import numpy as np
import torch
import torch.nn as nn

FEATURES_PER_FRAME = 258
UNKNOWN_SIGN = "[UNKNOWN_SIGN]"
PAD_TOKEN = "[PAD]"
EOS_TOKEN = "[EOS]"


class PositionalEncoding(nn.Module):
    def __init__(self, d_model: int, max_len: int = 512, dropout: float = 0.1) -> None:
        super().__init__()
        self.dropout = nn.Dropout(dropout)
        pe = torch.zeros(max_len, d_model)
        pos = torch.arange(max_len).unsqueeze(1).float()
        div = torch.exp(torch.arange(0, d_model, 2).float() * (-math.log(10000.0) / d_model))
        pe[:, 0::2] = torch.sin(pos * div)
        pe[:, 1::2] = torch.cos(pos * div)
        self.register_buffer("pe", pe.unsqueeze(0))

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.dropout(x + self.pe[:, : x.size(1)])


class ASLTransformer(nn.Module):
    def __init__(
        self,
        vocab_size: int,
        d_model: int = 128,
        nhead: int = 4,
        num_layers: int = 3,
        dim_feedforward: int = 256,
        dropout: float = 0.1,
    ) -> None:
        super().__init__()
        self.input_proj = nn.Linear(FEATURES_PER_FRAME, d_model)
        self.pos_enc = PositionalEncoding(d_model, dropout=dropout)
        encoder_layer = nn.TransformerEncoderLayer(
            d_model=d_model,
            nhead=nhead,
            dim_feedforward=dim_feedforward,
            dropout=dropout,
            batch_first=True,
        )
        self.encoder = nn.TransformerEncoder(encoder_layer, num_layers=num_layers)
        self.classifier = nn.Linear(d_model, vocab_size)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        x = self.input_proj(x)
        x = self.pos_enc(x)
        x = self.encoder(x)
        return self.classifier(x)


def _load_checkpoint(checkpoint_path: str, device: torch.device) -> Any:
    try:
        return torch.load(checkpoint_path, map_location=device, weights_only=False)
    except TypeError:
        return torch.load(checkpoint_path, map_location=device)


def _decode_tokens(indices: list[int], label_map: list[str]) -> list[str]:
    tokens: list[str] = []
    previous: str | None = None
    for index in indices:
        if index < 0 or index >= len(label_map):
            token = UNKNOWN_SIGN
        else:
            token = label_map[index]
        if token in {PAD_TOKEN, EOS_TOKEN}:
            continue
        if token == previous:
            continue
        tokens.append(token)
        previous = token
    return tokens or [UNKNOWN_SIGN]


def model_fn(model_dir: str) -> tuple[nn.Module, list[str]]:
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    checkpoint_path = os.path.join(model_dir, "model.pth")
    payload = _load_checkpoint(checkpoint_path, device)

    if isinstance(payload, nn.Module):
        model = payload
        label_map: list[str] = []
    elif isinstance(payload, dict) and "model_state_dict" in payload:
        model_config = payload.get("model_config", {})
        label_map = payload.get("label_map", [])
        model = ASLTransformer(
            vocab_size=model_config.get("vocab_size", len(label_map)),
            d_model=model_config.get("d_model", 128),
            nhead=model_config.get("nhead", 4),
            num_layers=model_config.get("num_layers", 3),
            dim_feedforward=model_config.get("dim_feedforward", 256),
            dropout=model_config.get("dropout", 0.1),
        )
        model.load_state_dict(payload["model_state_dict"])
    else:
        raise TypeError("Unsupported model artifact format.")

    label_map_path = os.path.join(model_dir, "label_map.json")
    if os.path.exists(label_map_path):
        with open(label_map_path, "r", encoding="utf-8") as handle:
            label_map = json.load(handle)
    if not label_map:
        raise ValueError("label_map.json or checkpoint label_map is required for inference.")

    model.to(device)
    model.eval()
    return model, label_map


def input_fn(request_body: str | bytes, content_type: str) -> np.ndarray:
    if content_type != "application/json":
        raise ValueError(f"Unsupported content_type: {content_type}")

    payload = json.loads(request_body if isinstance(request_body, str) else request_body.decode("utf-8"))
    instances = payload.get("instances")
    if not instances:
        raise ValueError("Request body must include a non-empty 'instances' field.")

    first_instance = instances[0]
    if isinstance(first_instance, dict):
        flat = first_instance.get("keypoints")
        if flat is None or len(flat) % FEATURES_PER_FRAME != 0:
            raise ValueError(f"Flat keypoint payload length must be divisible by {FEATURES_PER_FRAME}.")
        frames = len(flat) // FEATURES_PER_FRAME
        return np.asarray(flat, dtype=np.float32).reshape(1, frames, FEATURES_PER_FRAME)

    array = np.asarray(instances, dtype=np.float32)
    if array.ndim == 2 and array.shape[-1] == FEATURES_PER_FRAME:
        return np.expand_dims(array, axis=0)
    if array.ndim == 3 and array.shape[-1] == FEATURES_PER_FRAME:
        return array
    raise ValueError(f"Expected instances with trailing dimension {FEATURES_PER_FRAME}, got shape {array.shape}")


def predict_fn(input_data: np.ndarray, model_bundle: tuple[nn.Module, list[str]]) -> dict[str, Any]:
    model, label_map = model_bundle
    device = next(model.parameters()).device

    try:
        with torch.no_grad():
            tensor = torch.as_tensor(input_data, dtype=torch.float32, device=device)
            logits = model(tensor)
            probabilities = torch.softmax(logits, dim=-1)
            confidence_values, token_indices = probabilities.max(dim=-1)

        decoded = _decode_tokens(token_indices[0].tolist(), label_map)
        confidence = float(confidence_values[0].mean().item())
        return {"tokens": decoded, "confidence": round(confidence, 4)}
    except Exception:
        return {"tokens": [UNKNOWN_SIGN], "confidence": 0.0}


def output_fn(prediction: dict[str, Any], accept: str) -> tuple[str, str]:
    if accept != "application/json":
        raise ValueError(f"Unsupported accept type: {accept}")
    return json.dumps(prediction), "application/json"
