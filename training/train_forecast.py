"""
training/train_forecast.py
───────────────────────────
Train the ForecastHead on the existing normal_kpis.csv.

Does NOT retrain the LSTM Autoencoder — loads its weights frozen
and trains only the ForecastHead weights on top.

Strategy:
  For each 30-step input window from the training data,
  the target is the NEXT 300 steps (5 minutes).
  We create (input_window, future_window) pairs by sliding a
  window of size 30 + 300 = 330 across the CSV.

  Loss: MSE(predicted_future, actual_future)
  Epochs: 30 (fast convergence — encoder is already good)
  LR: 0.0005

Output:
  xapp/model/saved_models/forecast_head.pt
  training/data/forecast_eval.json  (val loss, horizon accuracy per KPI)
"""

import os
import sys
sys.path.insert(0, ".")

import torch
import torch.nn as nn
import numpy as np
import pandas as pd
import joblib
import json
import logging
from pathlib import Path
from torch.utils.data import DataLoader, TensorDataset

from xapp.device import get_device

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(name)s  %(levelname)s  %(message)s",
)
log = logging.getLogger("train_forecast")

# ── Config (overrideable via env vars for fast Docker builds) ─────────────────
INPUT_LEN      = 30
FORECAST_LEN   = int(os.getenv("ASTRA_FORECAST_LEN", "300"))   # 30 for Docker, 300 for full
BATCH_SIZE     = 32
EPOCHS         = int(os.getenv("ASTRA_FORECAST_EPOCHS", "30"))
LR             = 5e-4
VAL_SPLIT      = 0.15
PATIENCE       = min(3, EPOCHS)   # patience scales with epoch budget
DEVICE         = get_device()

DATA_PATH      = Path("training/data/normal_kpis.csv")
SCALER_PATH    = Path("training/data/scaler.pkl")
AE_MODEL_PATH  = Path("xapp/model/saved_models/lstm_ae_best.pt")
OUT_PATH       = Path("xapp/model/saved_models/forecast_head.pt")
EVAL_PATH      = Path("training/data/forecast_eval.json")

KPI_COLS = [
    "dl_throughput_mbps", "latency_ms", "bler_pct",
    "rsrp_dbm", "handover_success_rate", "slice_utilisation_pct"
]


def build_pairs(data: np.ndarray, in_len: int, out_len: int):
    """
    Create (input_window, future_window) pairs by sliding window.
    data: (N, 6) normalised
    Returns X: (M, in_len, 6), Y: (M, out_len, 6)
    """
    total = in_len + out_len
    M = len(data) - total + 1
    X = np.stack([data[i : i + in_len]       for i in range(M)])
    Y = np.stack([data[i + in_len : i + total] for i in range(M)])
    return X.astype(np.float32), Y.astype(np.float32)


def main():
    log.info("=== ASTRA ForecastHead Training ===")
    log.info("Device: %s", DEVICE)

    # ── Load data ────────────────────────────────────────────────────────
    if not DATA_PATH.exists():
        log.error("Run training/generate_normal_data.py first.")
        sys.exit(1)

    df = pd.read_csv(DATA_PATH)[KPI_COLS]
    scaler = joblib.load(SCALER_PATH)
    data = scaler.transform(df.values).astype(np.float32)  # (N, 6) in [0,1]
    log.info("Loaded %d KPI samples", len(data))

    # ── Build pairs ──────────────────────────────────────────────────────
    X, Y = build_pairs(data, INPUT_LEN, FORECAST_LEN)
    log.info("Pairs: %d  X:%s  Y:%s", len(X), X.shape, Y.shape)

    # Train/val split (time-ordered, no shuffle)
    split = int(len(X) * (1 - VAL_SPLIT))
    X_tr, X_va = X[:split], X[split:]
    Y_tr, Y_va = Y[:split], Y[split:]

    use_pin = DEVICE.type == "cuda"
    tr_ds = TensorDataset(torch.from_numpy(X_tr), torch.from_numpy(Y_tr))
    va_ds = TensorDataset(torch.from_numpy(X_va), torch.from_numpy(Y_va))
    tr_dl = DataLoader(tr_ds, batch_size=BATCH_SIZE, shuffle=True, pin_memory=use_pin)
    va_dl = DataLoader(va_ds, batch_size=BATCH_SIZE, pin_memory=use_pin)

    # ── Load frozen autoencoder ──────────────────────────────────────────────────
    from xapp.model.lstm_autoencoder import LSTMAutoencoder  # existing model
    ae = LSTMAutoencoder().to(DEVICE)
    ae.load_state_dict(torch.load(AE_MODEL_PATH, map_location=DEVICE, weights_only=True))
    ae.eval()
    for p in ae.parameters():
        p.requires_grad = False
    log.info("Autoencoder loaded + frozen from %s", AE_MODEL_PATH)

    # ── Build forecast head ──────────────────────────────────────────────
    from xapp.prediction.forecast_head import ForecastHeadNet
    head = ForecastHeadNet(latent_dim=8, hidden=32, n_kpis=6,
                           horizon=FORECAST_LEN).to(DEVICE)
    opt = torch.optim.Adam(head.parameters(), lr=LR)
    sched = torch.optim.lr_scheduler.ReduceLROnPlateau(
        opt, patience=3, factor=0.5
    )
    loss_fn = nn.MSELoss()

    # ── Training loop (with AMP for GPU) ────────────────────────────────────
    use_amp = DEVICE.type == "cuda"
    scaler_amp = torch.amp.GradScaler(enabled=use_amp)
    best_val = float("inf")
    patience_counter = 0
    history = {"train_loss": [], "val_loss": []}

    for epoch in range(1, EPOCHS + 1):
        # --- train ---
        head.train()
        tr_loss = 0.0
        for xb, yb in tr_dl:
            xb, yb = xb.to(DEVICE, non_blocking=True), yb.to(DEVICE, non_blocking=True)
            with torch.no_grad():
                latent = ae.encode(xb)              # (B, 8)
            last_kpi = xb[:, -1, :]                 # (B, 6)
            with torch.amp.autocast(device_type=DEVICE.type, enabled=use_amp):
                pred = head(latent, last_kpi)            # (B, 300, 6)
                loss = loss_fn(pred, yb)
            opt.zero_grad(set_to_none=True)
            scaler_amp.scale(loss).backward()
            scaler_amp.unscale_(opt)
            torch.nn.utils.clip_grad_norm_(head.parameters(), 1.0)
            scaler_amp.step(opt)
            scaler_amp.update()
            tr_loss += loss.item() * len(xb)
        tr_loss /= len(tr_ds)

        # --- validate ---
        head.eval()
        va_loss = 0.0
        with torch.no_grad():
            for xb, yb in va_dl:
                xb, yb = xb.to(DEVICE, non_blocking=True), yb.to(DEVICE, non_blocking=True)
                with torch.amp.autocast(device_type=DEVICE.type, enabled=use_amp):
                    latent = ae.encode(xb)
                    last_kpi = xb[:, -1, :]
                    pred = head(latent, last_kpi)
                    va_loss += loss_fn(pred, yb).item() * len(xb)
        va_loss /= len(va_ds)

        sched.step(va_loss)
        history["train_loss"].append(tr_loss)
        history["val_loss"].append(va_loss)

        log.info("Epoch %02d/%02d  train=%.5f  val=%.5f", epoch, EPOCHS, tr_loss, va_loss)

        if va_loss < best_val:
            best_val = va_loss
            patience_counter = 0
            torch.save(head.state_dict(), OUT_PATH)
            log.info("  ✓ New best val loss — saved to %s", OUT_PATH)
        else:
            patience_counter += 1
            if patience_counter >= PATIENCE:
                log.info("Early stopping at epoch %d", epoch)
                break

    # ── Per-KPI horizon accuracy ─────────────────────────────────────────
    head.eval()
    head.load_state_dict(torch.load(OUT_PATH, map_location=DEVICE, weights_only=True))

    all_preds, all_trues = [], []
    with torch.no_grad():
        for xb, yb in va_dl:
            xb = xb.to(DEVICE, non_blocking=True)
            with torch.amp.autocast(device_type=DEVICE.type, enabled=use_amp):
                latent = ae.encode(xb)
                pred = head(latent, xb[:, -1, :]).cpu().numpy()
            all_preds.append(pred)
            all_trues.append(yb.numpy())

    all_preds = np.concatenate(all_preds)   # (M, 300, 6)
    all_trues = np.concatenate(all_trues)   # (M, 300, 6)

    # MAE per KPI per horizon bucket
    buckets = {"30s": 30, "60s": 60, "120s": 120, "300s": 300}
    per_kpi_mae = {}
    for col_i, name in enumerate(KPI_COLS):
        per_kpi_mae[name] = {}
        for label, hor in buckets.items():
            mae = float(np.mean(np.abs(
                all_preds[:, :hor, col_i] - all_trues[:, :hor, col_i]
            )))
            per_kpi_mae[name][label] = round(mae, 5)

    eval_data = {
        "best_val_loss": round(best_val, 6),
        "epochs_trained": len(history["train_loss"]),
        "per_kpi_mae_by_horizon": per_kpi_mae,
        "model_path": str(OUT_PATH),
    }
    EVAL_PATH.write_text(json.dumps(eval_data, indent=2))

    log.info("\n=== Training Complete ===")
    log.info("Best val loss:  %.6f", best_val)
    log.info("Model saved to: %s", OUT_PATH)
    log.info("Eval saved to:  %s", EVAL_PATH)
    log.info("\nPer-KPI MAE @ 60s horizon:")
    for name, vals in per_kpi_mae.items():
        log.info("  %-35s  MAE_60s=%.5f", name, vals["60s"])


if __name__ == "__main__":
    main()
