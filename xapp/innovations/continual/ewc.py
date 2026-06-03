"""
xapp/innovations/continual/ewc.py
─────────────────────────────────────────────────────────────────────────────
Elastic Weight Consolidation (EWC) for Continual Learning

Prevents catastrophic forgetting when ASTRA fine-tunes its LSTM autoencoder
on new network conditions. Uses the Fisher Information Matrix to identify
which weights are critical for previously-learned anomaly patterns and
penalises large deviations from those weights.

Reference: Kirkpatrick et al. (2017) — "Overcoming catastrophic forgetting
in neural networks", PNAS.

Usage:
    ewc = EWCPenalty(model, reference_dataloader, lambda_=1000)
    ...
    loss = reconstruction_loss + ewc.penalty(model)
"""

from __future__ import annotations

import os
from copy import deepcopy
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass

try:
    import torch
    from torch import nn, Tensor
    from torch.utils.data import DataLoader, TensorDataset

    _TORCH = True
except ImportError:
    _TORCH = False

import numpy as np


class EWCPenalty:
    """
    Computes and stores Fisher Information for a trained model, then provides
    a regularisation penalty during fine-tuning.

    Args:
        model: The trained PyTorch model (LSTMAutoencoder).
        reference_data: numpy array of shape (N, seq_len, n_features) — the
            "old task" data the model was trained on.
        lambda_: Regularisation strength. Higher = more resistance to forgetting.
            Default 1000 as per Kirkpatrick et al.
        n_samples: Number of samples to use for Fisher estimation. -1 = all.
    """

    def __init__(
        self,
        model: "nn.Module",
        reference_data: np.ndarray | None = None,
        lambda_: float | None = None,
        n_samples: int = 200,
    ) -> None:
        if not _TORCH:
            raise RuntimeError("PyTorch is required for EWC")

        self.lambda_ = lambda_ or float(os.getenv("EWC_LAMBDA", "1000"))
        self.n_samples = n_samples

        # Snapshot of the trained weights θ*
        self._reference_params: dict[str, Tensor] = {}
        # Diagonal Fisher Information F_ii for each parameter
        self._fisher: dict[str, Tensor] = {}

        if reference_data is not None:
            self.consolidate(model, reference_data)

    def consolidate(self, model: "nn.Module", reference_data: np.ndarray) -> None:
        """
        Compute and store θ* and diagonal Fisher from the reference dataset.

        Fisher diagonal is estimated as:
            F_ii = E[ (∂L/∂θ_i)² ]
        where L is the reconstruction loss on old-task data.
        """
        model.eval()

        # Store reference weights
        self._reference_params = {
            name: param.detach().clone()
            for name, param in model.named_parameters()
            if param.requires_grad
        }

        # Prepare data
        tensor_data = torch.tensor(reference_data, dtype=torch.float32)
        if self.n_samples > 0 and len(tensor_data) > self.n_samples:
            indices = torch.randperm(len(tensor_data))[: self.n_samples]
            tensor_data = tensor_data[indices]

        dataset = TensorDataset(tensor_data)
        loader = DataLoader(dataset, batch_size=32, shuffle=False)

        # Accumulate squared gradients
        fisher_accum: dict[str, Tensor] = {
            name: torch.zeros_like(param)
            for name, param in model.named_parameters()
            if param.requires_grad
        }
        total_samples = 0

        criterion = nn.MSELoss()

        for (batch,) in loader:
            model.zero_grad()
            reconstruction = model(batch)
            loss = criterion(reconstruction, batch)
            loss.backward()

            for name, param in model.named_parameters():
                if param.requires_grad and param.grad is not None:
                    fisher_accum[name] += param.grad.detach() ** 2 * len(batch)
            total_samples += len(batch)

        # Normalise
        self._fisher = {
            name: accum / max(total_samples, 1)
            for name, accum in fisher_accum.items()
        }

        model.zero_grad()

    def penalty(self, model: "nn.Module") -> "Tensor":
        """
        EWC penalty term: Σ_i  (λ/2) * F_ii * (θ_i - θ*_i)²

        Add this to the reconstruction loss during fine-tuning.
        """
        if not self._fisher or not self._reference_params:
            return torch.tensor(0.0)

        total = torch.tensor(0.0, device=next(model.parameters()).device)

        for name, param in model.named_parameters():
            if name in self._fisher:
                fisher = self._fisher[name].to(param.device)
                ref = self._reference_params[name].to(param.device)
                total = total + (fisher * (param - ref) ** 2).sum()

        return (self.lambda_ / 2.0) * total

    @property
    def is_consolidated(self) -> bool:
        return len(self._fisher) > 0


# ── Backward-compatible function API ──────────────────────────────────────

_global_ewc: EWCPenalty | None = None


def ewc_init(model: "nn.Module", reference_data: np.ndarray, lambda_: float = 1000) -> None:
    """Initialise the global EWC state from a trained model + reference data."""
    global _global_ewc
    _global_ewc = EWCPenalty(model, reference_data, lambda_)


def ewc_penalty(model: "nn.Module" = None, **_kwargs) -> float:
    """
    Return the EWC penalty as a float. If EWC hasn't been initialised or
    model is None, returns 0.0 (safe no-op for backward compatibility).
    """
    if _global_ewc is None or model is None:
        return 0.0
    p = _global_ewc.penalty(model)
    return float(p.item())
