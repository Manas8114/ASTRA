from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.append(str(Path(__file__).resolve().parents[1]))

from xapp.ingestion.kpi_schema import KPI_NAMES


def generate(samples: int = 21600, seed: int = 42) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    rows = []
    for t in range(samples):
        hour = (t / 3600.0) % 24
        noon_peak = math.exp(-0.5 * ((hour - 12) / 2.4) ** 2)
        evening_peak = math.exp(-0.5 * ((hour - 20) / 2.0) ** 2)
        load = np.clip(0.25 + 0.45 * noon_peak + 0.55 * evening_peak + rng.normal(0, 0.03), 0, 1)
        throughput = 80 + 360 * load + rng.normal(0, 22.5)
        utilisation = 20 + 60 * load + rng.normal(0, 3)
        latency = 6 + 12 * load + rng.normal(0, 0.75)
        bler = 0.4 + 3.5 * load + rng.normal(0, 0.25)
        rsrp = -76 + 12 * (1 - 0.45 * load) + rng.normal(0, 1)
        hsr = 98.8 - 2.2 * load + rng.normal(0, 0.2)
        rows.append([throughput, latency, bler, rsrp, hsr, utilisation])
    return pd.DataFrame(rows, columns=KPI_NAMES)


def main() -> None:
    out_dir = Path("training/data")
    out_dir.mkdir(parents=True, exist_ok=True)
    df = generate()
    df.to_csv(out_dir / "normal_kpis.csv", index=False)
    np.save(out_dir / "normal_kpis.npy", df.to_numpy(dtype=np.float32))
    print(df.agg(["mean", "std", "min", "max"]).round(3).to_string())


if __name__ == "__main__":
    main()
