"""Keep Radeon 780M separations inside the memory Windows will actually commit.

HIP reports the shared-GPU pool (about 14.43 GiB on the reference machine) as device
memory. Task Manager's dedicated carveout is only 3.9 GB; the rest is system RAM the
driver can refuse. PyTorch will fill that pool and then fail a large contiguous
activation — the observed failure is a 1.63 GiB alloc after 15.05 GiB is already live.
"""

from __future__ import annotations

import os
from contextvars import ContextVar
from pathlib import Path
from typing import Any

# 8 seconds at 44.1 kHz. Release notes already call this the largest BS-RoFormer
# chunk that fits in 780M shared memory.
SAFE_CHUNK_SAMPLES = 352800
MIN_CHUNK_SAMPLES = 88200
_HEADROOM_BYTES = 2 * 1024 ** 3

# Architectures whose peak is dominated by chunk_size. VR uses window_size instead.
_CHUNKED_MODEL_TYPES = {
    "",
    "auto",
    "apollo",
    "bandit",
    "bandit_v2",
    "bs_conformer",
    "bs_roformer",
    "bs_roformer_hyperace",
    "htdemucs",
    "mdx23c",
    "mel_band_conformer",
    "mel_band_roformer",
    "scnet",
}

vram_task_id: ContextVar[str | None] = ContextVar("vram_task_id", default=None)

_chunk_cap = SAFE_CHUNK_SAMPLES
_force_no_tta = False
_fraction_applied = False


def reset_vram_budget_for_tests() -> None:
    global _chunk_cap, _force_no_tta, _fraction_applied
    _chunk_cap = SAFE_CHUNK_SAMPLES
    _force_no_tta = False
    _fraction_applied = False


def current_chunk_cap() -> int:
    return _chunk_cap


def note_oom_retry() -> int | None:
    """Shrink the chunk cap after a CUDA OOM. None means the floor was already reached."""
    global _chunk_cap, _force_no_tta
    _force_no_tta = True
    nxt = max(MIN_CHUNK_SAMPLES, _chunk_cap // 2)
    if nxt >= _chunk_cap:
        return None
    _chunk_cap = nxt
    return nxt


def gpu_budget_applies(device: Any) -> bool:
    text = str(device or "auto").strip().lower() or "auto"
    return text in {"auto", "cuda", "rocm"} or text.startswith("cuda:")


def memory_fraction(total_bytes: int) -> float:
    """Leave enough of the HIP-reported pool unreserved for a ~1.6 GiB spike."""
    if total_bytes <= 0:
        return 1.0
    headroom = max(_HEADROOM_BYTES, total_bytes * 15 // 100)
    cap = total_bytes - headroom
    if cap < total_bytes // 2:
        cap = total_bytes // 2
    return cap / total_bytes


def configure_allocator_env() -> None:
    """Set allocator flags before the first torch import.

    ``expandable_segments`` is the flag named by the CUDA OOM text.
    ``garbage_collection_threshold`` releases cached blocks before the allocator
    grows into the last of the shared pool.
    """
    merged = _merge_alloc_conf(
        os.environ.get("PYTORCH_CUDA_ALLOC_CONF", ""),
        os.environ.get("PYTORCH_HIP_ALLOC_CONF", ""),
    )
    os.environ["PYTORCH_CUDA_ALLOC_CONF"] = merged
    os.environ["PYTORCH_HIP_ALLOC_CONF"] = merged


def _merge_alloc_conf(*values: str) -> str:
    parts: list[str] = []
    seen: set[str] = set()
    for value in values:
        for raw in str(value or "").split(","):
            part = raw.strip()
            if not part:
                continue
            key = part.split(":", 1)[0].split("=", 1)[0]
            if key in seen:
                continue
            seen.add(key)
            parts.append(part)
    for required in ("expandable_segments:True", "garbage_collection_threshold:0.6"):
        key = required.split(":", 1)[0]
        if key not in seen:
            seen.add(key)
            parts.append(required)
    return ",".join(parts)


def apply_cuda_memory_budget(device_index: int = 0) -> float | None:
    """Cap the caching allocator once, before the first CUDA allocation."""
    global _fraction_applied
    if _fraction_applied:
        return None
    try:
        import torch
    except ImportError:
        return None
    if not torch.cuda.is_available():
        return None
    try:
        props = torch.cuda.get_device_properties(device_index)
        total = int(getattr(props, "total_memory", 0) or 0)
    except Exception:
        return None
    if total <= 0:
        return None
    fraction = memory_fraction(total)
    try:
        torch.cuda.set_per_process_memory_fraction(fraction, device_index)
    except Exception:
        return None
    _fraction_applied = True
    return fraction


def release_cuda_cache() -> None:
    import gc

    gc.collect()
    try:
        import torch
    except ImportError:
        return
    if not torch.cuda.is_available():
        return
    try:
        torch.cuda.empty_cache()
    except Exception:
        return
    gc.collect()


def is_cuda_oom(exc: BaseException) -> bool:
    if type(exc).__name__ == "OutOfMemoryError":
        return True
    message = str(exc).lower()
    return "out of memory" in message and ("cuda" in message or "hip" in message)


def read_model_budget(config_path: Any) -> dict[str, int]:
    path = Path(str(config_path)) if config_path else None
    if path is None or not path.is_file():
        return {}
    try:
        import yaml
    except ImportError:
        return {}
    try:
        loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    if not isinstance(loaded, dict):
        return {}
    inference = loaded.get("inference") if isinstance(loaded.get("inference"), dict) else {}
    audio = loaded.get("audio") if isinstance(loaded.get("audio"), dict) else {}
    budget: dict[str, int] = {}
    chunk = _positive_int(inference.get("chunk_size"))
    if chunk is None:
        chunk = _positive_int(audio.get("chunk_size"))
    if chunk is not None:
        budget["chunk_size"] = chunk
    overlap = _non_negative_int(inference.get("overlap_size"))
    if overlap is not None:
        budget["overlap_size"] = overlap
    batch = _positive_int(inference.get("batch_size"))
    if batch is not None:
        budget["batch_size"] = batch
    return budget


def fit_inference_budget(
    params: Any,
    *,
    model_type: Any,
    config_chunk: int | None,
    config_overlap: int | None,
    config_batch: int | None,
    chunk_cap: int,
) -> tuple[dict[str, Any], list[str]]:
    """Clamp a GPU separation so one forward cannot fill the shared pool.

    Overlap is scaled by the same ratio as the chunk so a config written for a
    larger window does not become ``overlap >= chunk`` after the cap.
    """
    fitted = dict(params or {})
    notes: list[str] = []
    model = str(model_type or "").strip().lower()
    if model == "vr" or model not in _CHUNKED_MODEL_TYPES:
        return _cap_batch(fitted, notes, config_batch, limit=2 if model == "vr" else 1)

    user_chunk = _positive_int(fitted.get("chunk_size"))
    basis = user_chunk or _positive_int(config_chunk)
    capped_chunk = basis
    if basis is not None and basis > chunk_cap:
        capped_chunk = chunk_cap
        fitted["chunk_size"] = chunk_cap
        notes.append(f"chunk_size {basis} -> {chunk_cap}")

    overlap = _non_negative_int(fitted.get("overlap_size"))
    overlap_from_config = False
    if overlap is None:
        overlap = _non_negative_int(config_overlap)
        overlap_from_config = overlap is not None
    if overlap is not None and capped_chunk is not None and overlap >= capped_chunk:
        scale_basis = basis or capped_chunk
        scaled = overlap * capped_chunk // scale_basis
        if scaled >= capped_chunk:
            scaled = capped_chunk // 2
        if overlap_from_config or "overlap_size" in fitted:
            fitted["overlap_size"] = scaled
            notes.append(f"overlap_size {overlap} -> {scaled}")

    _cap_batch(fitted, notes, config_batch, limit=1)
    stem_batch = _positive_int(fitted.get("stem_batch_size"))
    if stem_batch is None:
        fitted["stem_batch_size"] = 1
    elif stem_batch > 1:
        fitted["stem_batch_size"] = 1
        notes.append(f"stem_batch_size {stem_batch} -> 1")
    return fitted, notes




def _cap_batch(params: dict[str, Any], notes: list[str], config_batch: int | None, *, limit: int) -> tuple[dict[str, Any], list[str]]:
    batch = _positive_int(params.get("batch_size"))
    if batch is None:
        batch = _positive_int(config_batch)
        if batch is None or batch <= limit:
            return params, notes
        params["batch_size"] = limit
        notes.append(f"batch_size {batch} -> {limit}")
        return params, notes
    if batch > limit:
        params["batch_size"] = limit
        notes.append(f"batch_size {batch} -> {limit}")
    return params, notes


def install_separator_vram_guard() -> None:
    """Clamp every GPU ``MSSeparator`` construction, including workflow graphs."""
    configure_allocator_env()
    try:
        from pymss import MSSeparator  # type: ignore
    except ImportError:
        return

    if getattr(MSSeparator, "_studio_vram_guard", False):
        return
    original = MSSeparator.__init__

    def guarded(self: Any, *args: Any, **kwargs: Any) -> None:
        device = kwargs.get("device", "auto")
        if gpu_budget_applies(device):
            device_ids = kwargs.get("device_ids") or [0]
            try:
                device_index = int(device_ids[0])
            except (TypeError, ValueError, IndexError):
                device_index = 0
            apply_cuda_memory_budget(device_index)
            config = read_model_budget(kwargs.get("config_path"))
            fitted, notes = fit_inference_budget(
                kwargs.get("inference_params"),
                model_type=kwargs.get("model_type"),
                config_chunk=config.get("chunk_size"),
                config_overlap=config.get("overlap_size"),
                config_batch=config.get("batch_size"),
                chunk_cap=current_chunk_cap(),
            )
            kwargs["inference_params"] = fitted
            if _force_no_tta and kwargs.get("use_tta"):
                kwargs["use_tta"] = False
                notes.append("use_tta disabled after GPU OOM")
            if notes:
                _announce(kwargs.get("logger"), "780M VRAM budget: " + "; ".join(notes))
        original(self, *args, **kwargs)

    MSSeparator.__init__ = guarded
    MSSeparator._studio_vram_guard = True


def _announce(logger: Any, message: str) -> None:
    task_id = vram_task_id.get()
    if task_id:
        from worker_protocol import emit

        emit("task_log", {"level": "warning", "message": message}, task_id=task_id)
        return
    warning = getattr(logger, "warning", None)
    if callable(warning):
        warning(message)


def _positive_int(value: Any) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _non_negative_int(value: Any) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number >= 0 else None
