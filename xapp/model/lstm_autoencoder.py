from __future__ import annotations

try:
    import torch
    from torch import nn
except Exception:  # pragma: no cover - keeps REST demo runnable before deps install.
    torch = None
    nn = object

from xapp.ingestion.kpi_schema import KPI_NAMES


if torch:

    class LSTMAutoencoder(nn.Module):
        def __init__(self, sequence_length: int = 30, n_features: int = 6) -> None:
            super().__init__()
            self.sequence_length = sequence_length
            self.encoder_1 = nn.LSTM(n_features, 32, batch_first=True)
            self.encoder_2 = nn.LSTM(32, 16, batch_first=True)
            self.bottleneck = nn.Linear(16, 8)
            self.decoder_1 = nn.LSTM(8, 16, batch_first=True)
            self.decoder_2 = nn.LSTM(16, 32, batch_first=True)
            self.output = nn.Linear(32, n_features)
            self._attention: dict[str, float] = {name: 1.0 / n_features for name in KPI_NAMES}

            def hook(_module, _inputs, output):
                weights = torch.softmax(output.detach().abs().mean(dim=0), dim=0)
                expanded = torch.zeros(len(KPI_NAMES))
                expanded[: min(len(weights), len(KPI_NAMES))] = weights[: len(KPI_NAMES)]
                if expanded.sum() == 0:
                    expanded[:] = 1.0 / len(KPI_NAMES)
                else:
                    expanded = expanded / expanded.sum()
                self._attention = {
                    name: float(expanded[i].item()) for i, name in enumerate(KPI_NAMES)
                }

            self.bottleneck.register_forward_hook(hook)

        def encode(self, x):
            encoded, _ = self.encoder_1(x)
            encoded, (hidden, _) = self.encoder_2(encoded)
            return self.bottleneck(hidden[-1])

        def decode(self, z):
            repeated = z.unsqueeze(1).repeat(1, self.sequence_length, 1)
            decoded, _ = self.decoder_1(repeated)
            decoded, _ = self.decoder_2(decoded)
            return self.output(decoded)

        def forward(self, x):
            return self.decode(self.encode(x))

        def anomaly_score(self, x):
            with torch.no_grad():
                reconstruction = self.forward(x)
                per_feature = ((reconstruction - x) ** 2).mean(dim=(0, 1))
                total = per_feature.mean()
            return per_feature.cpu().numpy(), float(total.item())

        def get_attention_weights(self) -> dict[str, float]:
            return dict(self._attention)

else:

    class LSTMAutoencoder:  # type: ignore[no-redef]
        def __init__(self, *_args, **_kwargs) -> None:
            raise RuntimeError("PyTorch is required for LSTMAutoencoder")
