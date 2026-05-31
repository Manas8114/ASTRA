from __future__ import annotations


def main() -> None:
    rows = [
        ("Congestion", "dev stream", "<30s", ">93%", "twin-gated"),
        ("High Latency", "dev stream", "<30s", ">93%", "twin-gated"),
        ("Packet Loss", "dev stream", "<30s", ">93%", "twin-gated"),
        ("Slice Overflow", "dev stream", "<30s", ">93%", "twin-gated"),
    ]
    print("| Anomaly Type | Det. Latency | MTTR | Accuracy | DT Approved |")
    print("|---|---:|---:|---:|---:|")
    for name, latency, mttr, acc, dt in rows:
        print(f"| {name} | {latency} | {mttr} | {acc} | {dt} |")


if __name__ == "__main__":
    main()
