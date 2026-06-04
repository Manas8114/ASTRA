"""
xapp/device.py
──────────────
Centralized device management for ASTRA.

Provides a single source of truth for PyTorch device selection,
GPU memory management, and safe fallback to CPU on OOM.
"""

from __future__ import annotations

import os
import logging
from functools import lru_cache

log = logging.getLogger("astra.device")

try:
    import torch

    _TORCH = True
except ImportError:
    _TORCH = False
    torch = None  # type: ignore[assignment]


@lru_cache(maxsize=1)
def get_device() -> "torch.device":
    """
    Select the best available device.

    Priority:
      1. CUDA (if available and not disabled via ASTRA_FORCE_CPU=true)
      2. CPU fallback

    Returns a torch.device that is safe to use everywhere.
    """
    if not _TORCH:
        raise RuntimeError("PyTorch is required")

    force_cpu = os.getenv("ASTRA_FORCE_CPU", "false").lower() == "true"

    if not force_cpu and torch.cuda.is_available():
        device = torch.device("cuda")
        gpu_name = torch.cuda.get_device_name(0)
        gpu_mem = torch.cuda.get_device_properties(0).total_memory / (1024 ** 3)
        log.info("GPU selected: %s (%.1f GB)", gpu_name, gpu_mem)

        # Set memory fraction to avoid OOM from competing processes
        mem_fraction = float(os.getenv("ASTRA_GPU_MEM_FRACTION", "0.8"))
        torch.cuda.set_per_process_memory_fraction(mem_fraction, device=0)
        log.info("GPU memory fraction limited to %.0f%%", mem_fraction * 100)

        # Enable TF32 for Ampere+ GPUs (faster, negligible accuracy loss)
        torch.backends.cuda.matmul.allow_tf32 = True
        torch.backends.cudnn.allow_tf32 = True
        torch.backends.cudnn.benchmark = True

        return device

    if not force_cpu:
        log.info("CUDA not available — using CPU")
    else:
        log.info("ASTRA_FORCE_CPU=true — using CPU")

    return torch.device("cpu")


def safe_to_device(tensor_or_module, device=None):
    """Move a tensor or module to the target device with OOM fallback."""
    if not _TORCH:
        return tensor_or_module

    if device is None:
        device = get_device()

    try:
        return tensor_or_module.to(device)
    except torch.cuda.OutOfMemoryError:
        log.warning("GPU OOM — clearing cache and falling back to CPU")
        torch.cuda.empty_cache()
        return tensor_or_module.to("cpu")


def clear_gpu_cache():
    """Safely clear GPU cache if CUDA is available."""
    if _TORCH and torch.cuda.is_available():
        torch.cuda.empty_cache()


def gpu_memory_summary() -> dict:
    """Return current GPU memory stats (for monitoring/dashboard)."""
    if not _TORCH or not torch.cuda.is_available():
        return {"gpu_available": False}

    return {
        "gpu_available": True,
        "gpu_name": torch.cuda.get_device_name(0),
        "memory_allocated_mb": round(torch.cuda.memory_allocated(0) / 1e6, 1),
        "memory_reserved_mb": round(torch.cuda.memory_reserved(0) / 1e6, 1),
        "memory_total_mb": round(
            torch.cuda.get_device_properties(0).total_memory / 1e6, 1
        ),
    }
