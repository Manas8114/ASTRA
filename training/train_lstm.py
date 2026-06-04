from __future__ import annotations

import os
import json
import pickle
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import torch
from torch import nn
from torch.utils.data import DataLoader, TensorDataset

sys.path.append(str(Path(__file__).resolve().parents[1]))

from xapp.model.anomaly_detector import MinMaxScalerLite
from xapp.model.lstm_autoencoder import LSTMAutoencoder
from xapp.device import get_device, clear_gpu_cache


def make_windows(data: np.ndarray, size: int = 30) -> np.ndarray:
    return np.stack([data[i : i + size] for i in range(len(data) - size + 1)])


def main() -> None:
    data_path = Path("training/data/normal_kpis.csv")
    if not data_path.exists():
        raise SystemExit("Run training/generate_normal_data.py first.")
    df = pd.read_csv(data_path)
    arr = df.to_numpy(dtype=np.float32)
    scaler = MinMaxScalerLite(arr.min(axis=0), arr.max(axis=0))
    scaled = scaler.transform(arr)
    windows = make_windows(scaled)
    split = int(len(windows) * 0.8)
    train = windows[:split]
    val = windows[split:]

    device = get_device()
    print(f"Training on: {device}")
    model = LSTMAutoencoder().to(device)
    optimizer = torch.optim.Adam(model.parameters(), lr=0.001)
    loss_fn = nn.MSELoss()

    # Use AMP for GPU training (halves memory usage)
    use_amp = device.type == "cuda"
    scaler_amp = torch.amp.GradScaler(enabled=use_amp)

    train_loader = DataLoader(
        TensorDataset(torch.from_numpy(train.astype(np.float32))),
        batch_size=64,
        shuffle=True,
        pin_memory=(device.type == "cuda"),
        num_workers=0,
    )
    val_tensor = torch.from_numpy(val.astype(np.float32)).to(device)
    best_val = float("inf")
    patience = 5
    stale = 0
    out_dir = Path("xapp/model/saved_models")
    out_dir.mkdir(parents=True, exist_ok=True)
    model_path = out_dir / "lstm_ae_best.pt"

    _max_epochs = int(os.getenv("ASTRA_LSTM_EPOCHS", "50"))
    for epoch in range(1, _max_epochs + 1):
        model.train()
        train_loss = 0.0
        for (batch,) in train_loader:
            batch = batch.to(device, non_blocking=True)
            optimizer.zero_grad(set_to_none=True)
            with torch.amp.autocast(device_type=device.type, enabled=use_amp):
                recon = model(batch)
                loss = loss_fn(recon, batch)
            scaler_amp.scale(loss).backward()
            scaler_amp.unscale_(optimizer)
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            scaler_amp.step(optimizer)
            scaler_amp.update()
            train_loss += loss.item() * len(batch)
        train_loss /= len(train)

        model.eval()
        with torch.no_grad():
            with torch.amp.autocast(device_type=device.type, enabled=use_amp):
                val_recon = model(val_tensor)
                val_loss = float(loss_fn(val_recon, val_tensor).item())
        print(f"epoch={epoch:02d} train_loss={train_loss:.6f} val_loss={val_loss:.6f}")
        if val_loss < best_val:
            best_val = val_loss
            stale = 0
            torch.save(model.state_dict(), model_path)
        else:
            stale += 1
            if stale >= patience:
                break

    model.load_state_dict(torch.load(model_path, map_location=device, weights_only=True))
    model.eval()
    val_loader = DataLoader(
        TensorDataset(torch.from_numpy(val.astype(np.float32))),
        batch_size=128,
        shuffle=False,
    )
    scores: list[np.ndarray] = []
    with torch.no_grad():
        for (batch,) in val_loader:
            batch = batch.to(device, non_blocking=True)
            with torch.amp.autocast(device_type=device.type, enabled=use_amp):
                recon = model(batch)
            scores.append(((recon - batch) ** 2).mean(dim=(1, 2)).cpu().numpy())
    mse = np.concatenate(scores)
    mean = float(mse.mean())
    std = float(mse.std())
    threshold = mean + 3 * std
    fpr = float((mse > threshold).mean())
    if fpr > 0.03:
        threshold = mean + 3.5 * std
        fpr = float((mse > threshold).mean())

    Path("training/data").mkdir(parents=True, exist_ok=True)
    with Path("training/data/scaler.pkl").open("wb") as handle:
        pickle.dump(scaler, handle)
    threshold_data = {
        "mean": mean,
        "std": std,
        "threshold_3sigma": float(threshold),
        "fpr_on_val": fpr,
    }
    (out_dir / "threshold.json").write_text(json.dumps(threshold_data, indent=2))
    (out_dir / "model_metadata.json").write_text(
        json.dumps(
            {
                "version": "statistical-baseline-v1",
                "trained_at": datetime.now(timezone.utc).isoformat(),
                "n_samples": int(len(arr)),
                "val_loss": best_val,
                "threshold": float(threshold),
                "fpr": fpr,
                "model_path": str(model_path),
            },
            indent=2,
        )
    )
    print(json.dumps(threshold_data, indent=2))


if __name__ == "__main__":
    main()
