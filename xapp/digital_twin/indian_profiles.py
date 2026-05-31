from __future__ import annotations

from pathlib import Path
import sys

import numpy as np
import pandas as pd

sys.path.append(str(Path(__file__).resolve().parents[2]))

from xapp.ingestion.kpi_schema import KPI_NAMES
from training.generate_normal_data import generate


PROFILES = {
    "MONSOON_RF_ATTENUATION": {"rsrp_dbm": -15, "bler_pct": 12, "dl_throughput_mbps_factor": 0.4},
    "BSNL_BACKHAUL_SPIKE": {"latency_ms": 200, "dl_throughput_mbps_factor": 0.3, "bler_pct": 5},
    "PRIVATE_5G_INTERFERENCE": {"rsrp_dbm": -8, "bler_pct": 8, "slice_utilisation_pct": 40},
}


def generate_faults(samples_per_profile: int = 1000) -> pd.DataFrame:
    base = generate(samples_per_profile * len(PROFILES))
    frames = []
    start = 0
    for label, delta in PROFILES.items():
        df = base.iloc[start : start + samples_per_profile].copy()
        start += samples_per_profile
        for key, value in delta.items():
            if key.endswith("_factor"):
                df[key.replace("_factor", "")] *= value
            else:
                df[key] += value
        df["label"] = label
        frames.append(df)

    rural = base.iloc[:samples_per_profile].copy()
    for idx in range(0, len(rural), 240):
        rural.iloc[idx : idx + 30, rural.columns.get_indexer(KPI_NAMES)] = 0
    rural["label"] = "RURAL_POWER_OUTAGE"
    frames.append(rural)

    urban = base.iloc[:samples_per_profile].copy()
    urban["handover_success_rate"] -= 30
    urban["latency_ms"] *= 2.5
    urban["rsrp_dbm"] += np.where(np.arange(len(urban)) % 4 < 2, 20, -20)
    urban["label"] = "DENSE_URBAN_HANDOVER_STORM"
    frames.append(urban)
    return pd.concat(frames, ignore_index=True)


def main() -> None:
    out = Path("training/data/synthetic_faults.csv")
    out.parent.mkdir(parents=True, exist_ok=True)
    generate_faults().to_csv(out, index=False)
    print(f"Wrote {out}")


if __name__ == "__main__":
    main()
