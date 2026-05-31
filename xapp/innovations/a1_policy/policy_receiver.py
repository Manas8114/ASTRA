from __future__ import annotations


def apply_policy(config: dict, policy: dict) -> dict:
    merged = dict(config)
    merged.update(policy)
    return merged
