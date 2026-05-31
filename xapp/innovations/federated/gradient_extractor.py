from __future__ import annotations


def extract_gradients(model) -> dict:
    payload = {}
    for name, param in getattr(model, "named_parameters", lambda: [])():
        grad = getattr(param, "grad", None)
        if grad is not None:
            payload[name] = grad.detach().cpu().numpy().tolist()
    return payload
