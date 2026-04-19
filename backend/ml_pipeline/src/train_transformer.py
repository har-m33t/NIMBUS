"""
NIMBUS ASL - Transformer training and fine-tuning script.

Writes:
  <output_dir>/model.pth               - serialized checkpoint payload
  <output_dir>/label_map.json          - list[str] vocabulary index -> token
  <output_dir>/vocabulary_groups.json  - grouped ontology metadata
  <output_dir>/gloss_to_handshapes.json - seed phonological priors

Input shape:  (batch, T, 258)
Output shape: (batch, T, vocab) frame-level logits

Usage:
  python backend/ml_pipeline/src/train_transformer.py
  python backend/ml_pipeline/src/train_transformer.py --data-dir ./data --epochs 20
  python backend/ml_pipeline/src/train_transformer.py --checkpoint ./model/model.pth --head-only-finetune
"""
from __future__ import annotations

import argparse
import logging
import math
import pathlib
import random
from typing import Any, Optional

import numpy as np
import torch
import torch.nn as nn
from torch.utils.data import DataLoader, Dataset

from data_augmentation import KeypointAugmenter
from vocabulary import GLOSS_VOCAB, write_vocabulary_assets

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

FEATURES_PER_FRAME = 258
DEFAULT_HEAD_ONLY_LR = 1e-4


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
        x = x + self.pe[:, : x.size(1)]
        return self.dropout(x)


class ASLTransformer(nn.Module):
    """
    Keypoint sequence -> per-frame gloss logits.
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
        self.config = {
            "vocab_size": vocab_size,
            "d_model": d_model,
            "nhead": nhead,
            "num_layers": num_layers,
            "dim_feedforward": dim_feedforward,
            "dropout": dropout,
        }
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


class KeypointDataset(Dataset):
    """
    Load pre-extracted keypoint sequences from a directory of .npz files.

    Each .npz must contain:
      keypoints: float32 array (T, 258)
      labels:    int32/int64 array (T,)
    """

    def __init__(
        self,
        data_dir: str,
        augmenter: Optional[KeypointAugmenter] = None,
    ) -> None:
        self.augmenter = augmenter
        self.samples: list[tuple[np.ndarray, np.ndarray]] = []
        for path in sorted(pathlib.Path(data_dir).glob("*.npz")):
            npz = np.load(path)
            kp = npz["keypoints"].astype(np.float32)
            lb = npz["labels"].astype(np.int64)
            if kp.shape[-1] != FEATURES_PER_FRAME:
                logger.warning("Skipping %s: wrong feature dim %d", path, kp.shape[-1])
                continue
            if len(kp) != len(lb):
                logger.warning("Skipping %s: %d keypoint frames != %d labels", path, len(kp), len(lb))
                continue
            self.samples.append((kp, lb))
        if not self.samples:
            raise FileNotFoundError(f"No valid .npz files found in {data_dir}")

    def __len__(self) -> int:
        return len(self.samples)

    def __getitem__(self, idx: int) -> tuple[torch.Tensor, torch.Tensor]:
        keypoints, labels = self.samples[idx]
        if self.augmenter is not None:
            keypoints, labels = self.augmenter(keypoints, labels)
        return torch.from_numpy(keypoints.copy()), torch.from_numpy(labels.copy())


class SyntheticDataset(Dataset):
    """
    Generate synthetic keypoint sequences when no real data directory is provided.
    """

    def __init__(
        self,
        vocab_size: int,
        augmenter: Optional[KeypointAugmenter] = None,
        num_samples: int = 1000,
        min_frames: int = 5,
        max_frames: int = 30,
        seed: int = 42,
    ) -> None:
        self.augmenter = augmenter
        rng = np.random.default_rng(seed)
        self.data: list[tuple[np.ndarray, np.ndarray]] = []
        for _ in range(num_samples):
            frames = int(rng.integers(min_frames, max_frames + 1))
            keypoints = rng.random((frames, FEATURES_PER_FRAME), dtype=np.float32)
            labels = rng.integers(0, vocab_size, size=(frames,), dtype=np.int64)
            self.data.append((keypoints, labels))

    def __len__(self) -> int:
        return len(self.data)

    def __getitem__(self, idx: int) -> tuple[torch.Tensor, torch.Tensor]:
        keypoints, labels = self.data[idx]
        if self.augmenter is not None:
            keypoints, labels = self.augmenter(keypoints, labels)
        return torch.from_numpy(keypoints.copy()), torch.from_numpy(labels.copy())


def collate_fn(
    batch: list[tuple[torch.Tensor, torch.Tensor]],
) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
    """
    Pad variable-length sequences in a batch to the same frame count.
    """

    keypoints, labels = zip(*batch)
    lengths = torch.tensor([sample.size(0) for sample in keypoints], dtype=torch.long)
    max_frames = int(lengths.max().item())
    batch_size = len(keypoints)

    kp_padded = torch.zeros(batch_size, max_frames, FEATURES_PER_FRAME, dtype=torch.float32)
    label_padded = torch.zeros(batch_size, max_frames, dtype=torch.long)
    for index, (kp, lb) in enumerate(zip(keypoints, labels)):
        frames = kp.size(0)
        kp_padded[index, :frames] = kp
        label_padded[index, :frames] = lb

    return kp_padded, label_padded, lengths


def set_random_seed(seed: int) -> None:
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)


def build_augmenter(args: argparse.Namespace) -> Optional[KeypointAugmenter]:
    if args.disable_augmentation:
        return None
    return KeypointAugmenter(
        jitter_std=args.jitter_std,
        scale_range=(args.scale_min, args.scale_max),
        temporal_shift_range=args.temporal_shift_range,
        rotation_range_degrees=args.rotation_range_degrees,
        seed=args.seed,
    )


def load_checkpoint_payload(checkpoint_path: str, device: torch.device) -> Any:
    try:
        return torch.load(checkpoint_path, map_location=device, weights_only=False)
    except TypeError:
        return torch.load(checkpoint_path, map_location=device)


def resolve_model_config(
    checkpoint_path: Optional[str],
    device: torch.device,
    vocab_size: int,
    d_model: int,
    nhead: int,
    num_layers: int,
    dim_feedforward: int,
    dropout: float,
) -> dict[str, Any]:
    config = {
        "vocab_size": vocab_size,
        "d_model": d_model,
        "nhead": nhead,
        "num_layers": num_layers,
        "dim_feedforward": dim_feedforward,
        "dropout": dropout,
    }
    if not checkpoint_path:
        return config

    payload = load_checkpoint_payload(checkpoint_path, device)
    checkpoint_config = payload.get("model_config") if isinstance(payload, dict) else None
    if checkpoint_config:
        config.update(
            {
                "d_model": checkpoint_config.get("d_model", d_model),
                "nhead": checkpoint_config.get("nhead", nhead),
                "num_layers": checkpoint_config.get("num_layers", num_layers),
                "dim_feedforward": checkpoint_config.get("dim_feedforward", dim_feedforward),
                "dropout": checkpoint_config.get("dropout", dropout),
            }
        )
        logger.info("Using checkpoint architecture config from %s", checkpoint_path)
    return config


def extract_state_dict(payload: Any) -> dict[str, torch.Tensor]:
    if isinstance(payload, nn.Module):
        return payload.state_dict()
    if isinstance(payload, dict):
        if "model_state_dict" in payload:
            return payload["model_state_dict"]
        if "state_dict" in payload:
            return payload["state_dict"]
        if all(isinstance(value, torch.Tensor) for value in payload.values()):
            return payload
    raise TypeError("Unsupported checkpoint format; expected module or state_dict payload.")


def load_pretrained_weights(
    model: ASLTransformer,
    checkpoint_path: Optional[str],
    device: torch.device,
) -> None:
    if not checkpoint_path:
        return

    payload = load_checkpoint_payload(checkpoint_path, device)
    loaded_state = extract_state_dict(payload)
    target_state = model.state_dict()

    compatible_state = {
        key: value
        for key, value in loaded_state.items()
        if key in target_state and target_state[key].shape == value.shape
    }
    skipped_keys = sorted(key for key in loaded_state if key not in compatible_state)
    missing_keys = sorted(key for key in target_state if key not in compatible_state)

    model.load_state_dict(compatible_state, strict=False)
    logger.info(
        "Loaded %d/%d checkpoint tensors from %s",
        len(compatible_state),
        len(target_state),
        checkpoint_path,
    )
    if skipped_keys:
        logger.warning("Skipped incompatible checkpoint tensors: %s", ", ".join(skipped_keys))
    if missing_keys:
        logger.info("Model tensors initialized from scratch: %s", ", ".join(missing_keys))


def freeze_module(module: nn.Module) -> None:
    for parameter in module.parameters():
        parameter.requires_grad = False


def configure_fine_tuning(
    model: ASLTransformer,
    freeze_input_projection: bool,
    freeze_positional_encoding: bool,
    head_only_finetune: bool,
) -> list[nn.Parameter]:
    if head_only_finetune:
        freeze_module(model)
        for parameter in model.classifier.parameters():
            parameter.requires_grad = True
        logger.info("Head-only fine-tuning enabled: training classifier head at reduced learning rate.")
    else:
        if freeze_input_projection:
            freeze_module(model.input_proj)
            logger.info("Frozen input projection layer.")
        if freeze_positional_encoding:
            freeze_module(model.pos_enc)
            logger.info("Positional encoding module marked frozen.")

    trainable_parameters = [parameter for parameter in model.parameters() if parameter.requires_grad]
    if not trainable_parameters:
        raise ValueError("No trainable parameters remain after fine-tuning configuration.")

    trainable_count = sum(parameter.numel() for parameter in trainable_parameters)
    total_count = sum(parameter.numel() for parameter in model.parameters())
    logger.info("Trainable parameters: %d / %d", trainable_count, total_count)
    return trainable_parameters


def save_artifacts(model: ASLTransformer, output_dir: str, label_map: list[str]) -> pathlib.Path:
    output_path = pathlib.Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    model_path = output_path / "model.pth"
    payload = {
        "model_state_dict": model.state_dict(),
        "model_config": model.config,
        "feature_dim": FEATURES_PER_FRAME,
        "label_map": label_map,
    }
    torch.save(payload, model_path)
    logger.info("Saved model checkpoint -> %s", model_path)

    asset_paths = write_vocabulary_assets(output_path)
    logger.info("Saved vocabulary assets (%d tokens) -> %s", len(label_map), output_path)
    logger.debug("Vocabulary asset paths: %s", asset_paths)
    return model_path


def train(
    data_dir: Optional[str],
    output_dir: str,
    epochs: int,
    batch_size: int,
    lr: Optional[float],
    checkpoint_path: Optional[str],
    freeze_input_projection: bool,
    freeze_positional_encoding: bool,
    head_only_finetune: bool,
    d_model: int,
    nhead: int,
    num_layers: int,
    dim_feedforward: int,
    dropout: float,
    seed: int,
    augmenter: Optional[KeypointAugmenter],
) -> None:
    set_random_seed(seed)
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    logger.info("Device: %s", device)

    label_map = GLOSS_VOCAB
    pad_index = label_map.index("[PAD]")
    vocab_size = len(label_map)

    if data_dir:
        logger.info("Loading keypoint data from %s", data_dir)
        dataset: Dataset = KeypointDataset(data_dir=data_dir, augmenter=augmenter)
    else:
        logger.info("No --data-dir provided; using synthetic data.")
        dataset = SyntheticDataset(vocab_size=vocab_size, augmenter=augmenter, seed=seed)

    loader = DataLoader(
        dataset,
        batch_size=batch_size,
        shuffle=True,
        collate_fn=collate_fn,
        num_workers=0,
    )

    model_config = resolve_model_config(
        checkpoint_path=checkpoint_path,
        device=device,
        vocab_size=vocab_size,
        d_model=d_model,
        nhead=nhead,
        num_layers=num_layers,
        dim_feedforward=dim_feedforward,
        dropout=dropout,
    )
    model = ASLTransformer(**model_config).to(device)
    load_pretrained_weights(model=model, checkpoint_path=checkpoint_path, device=device)

    trainable_parameters = configure_fine_tuning(
        model=model,
        freeze_input_projection=freeze_input_projection,
        freeze_positional_encoding=freeze_positional_encoding,
        head_only_finetune=head_only_finetune,
    )

    effective_lr = lr if lr is not None else (DEFAULT_HEAD_ONLY_LR if head_only_finetune else 1e-3)
    optimizer = torch.optim.Adam(trainable_parameters, lr=effective_lr)
    criterion = nn.CrossEntropyLoss(ignore_index=pad_index)
    logger.info("Optimizer learning rate: %.6f", effective_lr)

    for epoch in range(1, epochs + 1):
        model.train()
        total_loss = 0.0
        for keypoints, labels, _lengths in loader:
            keypoints = keypoints.to(device)
            labels = labels.to(device)

            logits = model(keypoints)
            loss = criterion(logits.reshape(-1, vocab_size), labels.reshape(-1))

            optimizer.zero_grad()
            loss.backward()
            nn.utils.clip_grad_norm_(trainable_parameters, max_norm=1.0)
            optimizer.step()
            total_loss += loss.item()

        logger.info("Epoch %d/%d loss=%.4f", epoch, epochs, total_loss / len(loader))

    model.eval().cpu()
    save_artifacts(model=model, output_dir=output_dir, label_map=label_map)


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Train or fine-tune the NIMBUS ASL transformer.")
    parser.add_argument("--data-dir", default=None, help="Directory containing .npz keypoint files.")
    parser.add_argument(
        "--output-dir",
        default="./model",
        help="Where to write model.pth plus the shared vocabulary metadata JSON files.",
    )
    parser.add_argument("--checkpoint", default=None, help="Optional pretrained checkpoint to fine-tune from.")
    parser.add_argument("--epochs", type=int, default=10)
    parser.add_argument("--batch-size", type=int, default=32)
    parser.add_argument("--lr", type=float, default=None, help="Optimizer learning rate. Defaults to 1e-4 for head-only fine-tuning, otherwise 1e-3.")
    parser.add_argument("--seed", type=int, default=42)

    parser.add_argument("--freeze-input-projection", action="store_true", help="Freeze the input projection layer during fine-tuning.")
    parser.add_argument("--freeze-positional-encoding", action="store_true", help="Freeze the positional encoding module during fine-tuning.")
    parser.add_argument("--head-only-finetune", action="store_true", help="Train only the classifier head at 1e-4 by default.")

    parser.add_argument("--d-model", type=int, default=128)
    parser.add_argument("--nhead", type=int, default=4)
    parser.add_argument("--num-layers", type=int, default=3)
    parser.add_argument("--dim-feedforward", type=int, default=256)
    parser.add_argument("--dropout", type=float, default=0.1)

    parser.add_argument("--disable-augmentation", action="store_true", help="Disable keypoint augmentation.")
    parser.add_argument("--jitter-std", type=float, default=0.012, help="Stddev for spatial jitter on keypoint coordinates.")
    parser.add_argument("--scale-min", type=float, default=0.9, help="Minimum augmentation scale factor.")
    parser.add_argument("--scale-max", type=float, default=1.1, help="Maximum augmentation scale factor.")
    parser.add_argument("--temporal-shift-range", type=int, default=2, help="Maximum frame shift in either direction.")
    parser.add_argument("--rotation-range-degrees", type=float, default=12.0, help="Maximum absolute in-plane rotation angle.")
    return parser


def main() -> None:
    parser = build_arg_parser()
    args = parser.parse_args()

    if args.scale_min <= 0 or args.scale_max <= 0:
        raise ValueError("Scale bounds must be positive.")
    if args.scale_min > args.scale_max:
        raise ValueError("scale-min cannot exceed scale-max.")

    train(
        data_dir=args.data_dir,
        output_dir=args.output_dir,
        epochs=args.epochs,
        batch_size=args.batch_size,
        lr=args.lr,
        checkpoint_path=args.checkpoint,
        freeze_input_projection=args.freeze_input_projection,
        freeze_positional_encoding=args.freeze_positional_encoding,
        head_only_finetune=args.head_only_finetune,
        d_model=args.d_model,
        nhead=args.nhead,
        num_layers=args.num_layers,
        dim_feedforward=args.dim_feedforward,
        dropout=args.dropout,
        seed=args.seed,
        augmenter=build_augmenter(args),
    )


if __name__ == "__main__":
    main()
