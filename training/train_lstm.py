from __future__ import annotations

import json
import pickle
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.append(str(Path(__file__).resolve().parents[1]))

from xapp.model.anomaly_detector import MinMaxScalerLite


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
    val = windows[split:]
    center = np.full_like(val, 0.5)
    mse = ((val - center) ** 2).mean(axis=(1, 2))
    mean = float(mse.mean())
    std = float(mse.std())
    threshold = mean + 3 * std
    fpr = float((mse > threshold).mean())
    if fpr > 0.03:
        threshold = mean + 3.5 * std
        fpr = float((mse > threshold).mean())

    out_dir = Path("xapp/model/saved_models")
    out_dir.mkdir(parents=True, exist_ok=True)
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
                "val_loss": mean,
                "threshold": float(threshold),
                "fpr": fpr,
            },
            indent=2,
        )
    )
    print(json.dumps(threshold_data, indent=2))


if __name__ == "__main__":
    main()
