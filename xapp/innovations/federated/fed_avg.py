from __future__ import annotations


def fed_avg(gradients: list[dict[str, list]]) -> dict[str, list]:
    return gradients[0] if gradients else {}
