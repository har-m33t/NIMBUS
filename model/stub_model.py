import torch
import torch.nn as nn

class StubASLTransformer(nn.Module):
    def __init__(self, features: int, vocab_size: int) -> None:
        super().__init__()
        self.proj = nn.Linear(features, vocab_size)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.proj(x)
