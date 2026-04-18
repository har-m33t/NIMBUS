"""
NIMBUS ASL — Transformer training script.
Trains a keypoint-to-gloss sequence model and writes:
  <output_dir>/model.pth       — full saved model (torch.save)
  <output_dir>/label_map.json  — list[str] vocabulary index → token

Input shape:  (batch, T, 258)   258 = left_hand(63) + right_hand(63) + pose(132)
Output shape: (batch, T, vocab) frame-level logits; inference.py argmax-decodes these

Usage:
  python src/train_transformer.py                     # synthetic data, saves to ./model
  python src/train_transformer.py --data-dir ./data   # real NPZ data
  python src/train_transformer.py --epochs 20 --output-dir ./artifacts
"""
from __future__ import annotations

import argparse
import json
import logging
import math
import os
import pathlib
from typing import Optional

import numpy as np
import torch
import torch.nn as nn
from torch.utils.data import DataLoader, Dataset

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Vocabulary — common ASL gloss tokens
# ---------------------------------------------------------------------------

GLOSS_VOCAB: list[str] = [
    "[PAD]", "[EOS]", "[UNKNOWN_SIGN]",
    "HELLO", "THANK-YOU", "PLEASE", "SORRY", "YES", "NO", "HELP",
    "I", "YOU", "WE", "THEY", "HE", "SHE",
    "WANT", "NEED", "LIKE", "LOVE", "KNOW", "THINK", "GO", "COME",
    "GOOD", "BAD", "MORE", "LESS", "BIG", "SMALL", "NEW", "OLD",
    "TODAY", "TOMORROW", "YESTERDAY", "NOW", "LATER", "WHEN", "WHERE",
    "WHAT", "WHO", "WHY", "HOW",
    "HOME", "WORK", "SCHOOL", "STORE", "HOSPITAL", "BATHROOM",
    "EAT", "DRINK", "SLEEP", "WALK", "RUN", "SIT", "STAND",
    "HAPPY", "SAD", "ANGRY", "SCARED", "TIRED", "SICK", "FINE",
    "MOTHER", "FATHER", "SISTER", "BROTHER", "FRIEND", "DOCTOR",
    "WATER", "FOOD", "MONEY", "TIME", "CAR", "BOOK", "PHONE",
    "MORNING", "AFTERNOON", "NIGHT",
    "ONE", "TWO", "THREE", "FOUR", "FIVE",
    "CAN", "CANNOT", "WILL", "SHOULD", "MUST",
    "GIVE", "TAKE", "SHOW", "TELL", "ASK", "ANSWER",
    "UNDERSTAND", "REPEAT", "SLOW", "FAST",
    "MEETING", "CAPTION", "SIGN", "INTERPRET",
]

FEATURES_PER_FRAME = 258


# ---------------------------------------------------------------------------
# Model
# ---------------------------------------------------------------------------

class PositionalEncoding(nn.Module):
    def __init__(self, d_model: int, max_len: int = 512, dropout: float = 0.1) -> None:
        super().__init__()
        self.dropout = nn.Dropout(dropout)
        pe = torch.zeros(max_len, d_model)
        pos = torch.arange(max_len).unsqueeze(1).float()
        div = torch.exp(torch.arange(0, d_model, 2).float() * (-math.log(10000.0) / d_model))
        pe[:, 0::2] = torch.sin(pos * div)
        pe[:, 1::2] = torch.cos(pos * div)
        self.register_buffer("pe", pe.unsqueeze(0))  # (1, max_len, d_model)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        x = x + self.pe[:, : x.size(1)]
        return self.dropout(x)


class ASLTransformer(nn.Module):
    """
    Keypoint-sequence → per-frame gloss logits.
    input:  (batch, T, 258)
    output: (batch, T, vocab_size)
    """

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


# ---------------------------------------------------------------------------
# Dataset
# ---------------------------------------------------------------------------

class KeypointDataset(Dataset):
    """
    Loads pre-extracted keypoint sequences from a directory of .npz files.

    Each .npz must contain:
      keypoints: float32 array (T, 258)
      labels:    int32 array  (T,)  — vocab index per frame
    """

    def __init__(self, data_dir: str, label_map: list[str]) -> None:
        self.samples: list[tuple[np.ndarray, np.ndarray]] = []
        token_to_idx = {tok: i for i, tok in enumerate(label_map)}
        for path in pathlib.Path(data_dir).glob("*.npz"):
            npz = np.load(path)
            kp = npz["keypoints"].astype(np.float32)
            lb = npz["labels"].astype(np.int64)
            if kp.shape[-1] != FEATURES_PER_FRAME:
                logger.warning("Skipping %s: wrong feature dim %d", path, kp.shape[-1])
                continue
            self.samples.append((kp, lb))
        if not self.samples:
            raise FileNotFoundError(f"No valid .npz files found in {data_dir}")

    def __len__(self) -> int:
        return len(self.samples)

    def __getitem__(self, idx: int) -> tuple[torch.Tensor, torch.Tensor]:
        kp, lb = self.samples[idx]
        return torch.tensor(kp), torch.tensor(lb)


class SyntheticDataset(Dataset):
    """
    Generates random keypoint sequences with plausible label assignments.
    Used when no real data directory is provided.
    """

    def __init__(
        self,
        vocab_size: int,
        num_samples: int = 1000,
        min_frames: int = 5,
        max_frames: int = 30,
    ) -> None:
        self.vocab_size = vocab_size
        self.num_samples = num_samples
        self.min_frames = min_frames
        self.max_frames = max_frames
        rng = np.random.default_rng(42)
        self.data: list[tuple[np.ndarray, np.ndarray]] = []
        for _ in range(num_samples):
            t = rng.integers(min_frames, max_frames + 1)
            kp = rng.random((t, FEATURES_PER_FRAME), dtype=np.float32)
            lb = rng.integers(0, vocab_size, size=(t,), dtype=np.int64)
            self.data.append((kp, lb))

    def __len__(self) -> int:
        return self.num_samples

    def __getitem__(self, idx: int) -> tuple[torch.Tensor, torch.Tensor]:
        kp, lb = self.data[idx]
        return torch.tensor(kp), torch.tensor(lb)


def collate_fn(
    batch: list[tuple[torch.Tensor, torch.Tensor]],
) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
    """Pad variable-length sequences in a batch to the same T."""
    keypoints, labels = zip(*batch)
    lengths = torch.tensor([k.size(0) for k in keypoints])
    max_t = int(lengths.max().item())
    B = len(keypoints)

    kp_padded = torch.zeros(B, max_t, FEATURES_PER_FRAME)
    lb_padded = torch.full((B, max_t), fill_value=0, dtype=torch.long)  # 0 = [PAD]
    for i, (k, l) in enumerate(zip(keypoints, labels)):
        t = k.size(0)
        kp_padded[i, :t] = k
        lb_padded[i, :t] = l

    return kp_padded, lb_padded, lengths


# ---------------------------------------------------------------------------
# Training loop
# ---------------------------------------------------------------------------

def train(
    data_dir: Optional[str],
    output_dir: str,
    epochs: int,
    batch_size: int,
    lr: float,
) -> None:
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    logger.info("Device: %s", device)

    label_map = GLOSS_VOCAB
    vocab_size = len(label_map)
    PAD_IDX = label_map.index("[PAD]")

    if data_dir:
        logger.info("Loading real data from %s", data_dir)
        dataset = KeypointDataset(data_dir, label_map)
    else:
        logger.info("No --data-dir given — using synthetic data (1000 samples)")
        dataset = SyntheticDataset(vocab_size)

    loader = DataLoader(
        dataset,
        batch_size=batch_size,
        shuffle=True,
        collate_fn=collate_fn,
        num_workers=0,
    )

    model = ASLTransformer(vocab_size=vocab_size).to(device)
    optimizer = torch.optim.Adam(model.parameters(), lr=lr)
    criterion = nn.CrossEntropyLoss(ignore_index=PAD_IDX)

    for epoch in range(1, epochs + 1):
        model.train()
        total_loss = 0.0
        for kp, labels, lengths in loader:
            kp, labels = kp.to(device), labels.to(device)
            logits = model(kp)  # (B, T, vocab)
            # reshape for CrossEntropyLoss: (B*T, vocab) vs (B*T,)
            loss = criterion(logits.reshape(-1, vocab_size), labels.reshape(-1))
            optimizer.zero_grad()
            loss.backward()
            nn.utils.clip_grad_norm_(model.parameters(), max_norm=1.0)
            optimizer.step()
            total_loss += loss.item()
        logger.info("Epoch %d/%d  loss=%.4f", epoch, epochs, total_loss / len(loader))

    # Save artifacts
    out = pathlib.Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    model_path = out / "model.pth"
    torch.save(model.eval().cpu(), model_path)
    logger.info("Saved model → %s", model_path)

    label_map_path = out / "label_map.json"
    with open(label_map_path, "w") as fh:
        json.dump(label_map, fh, indent=2)
    logger.info("Saved label_map (%d tokens) → %s", vocab_size, label_map_path)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Train NIMBUS ASL Transformer")
    parser.add_argument("--data-dir", default=None, help="Directory of .npz keypoint files")
    parser.add_argument("--output-dir", default="./model", help="Where to write model.pth and label_map.json")
    parser.add_argument("--epochs", type=int, default=10)
    parser.add_argument("--batch-size", type=int, default=32)
    parser.add_argument("--lr", type=float, default=1e-3)
    args = parser.parse_args()

    train(
        data_dir=args.data_dir,
        output_dir=args.output_dir,
        epochs=args.epochs,
        batch_size=args.batch_size,
        lr=args.lr,
    )


if __name__ == "__main__":
    main()
