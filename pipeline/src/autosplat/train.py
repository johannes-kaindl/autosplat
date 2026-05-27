# SPDX-License-Identifier: AGPL-3.0-or-later

"""Gaussian Splat training via Brush.

Brush is a Rust binary using WebGPU — Mac-native, no CUDA stack required.
This module wraps the binary as a subprocess and parses training progress.

Brush v0.3.0 expects a COLMAP-style dataset root containing:
  <root>/images/   — frames (any image format Brush can read)
  <root>/sparse/0/ — COLMAP SfM output

We build that root as a staging directory with symlinks into the capture-dir
layout (`frames/`, `colmap/sparse/`) so we don't have to copy frame data.
"""

from __future__ import annotations

import math
import shutil
import subprocess
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np

from .config import BrushConfig
from .logging import get_logger

logger = get_logger(__name__)


@dataclass
class TrainResult:
    training_dir: Path
    final_ply: Path | None
    steps_completed: int
    duration_s: float


# Spec §9.2: detect Brush OOM (or close-equivalent) in stderr so the watcher
# can retry with a halved resolution_cap.
_OOM_PATTERNS = (
    "out of memory",
    "oom",
    "memory allocation failed",
    "alloc failed",
    "wgpu memory",
    "device lost",
)


class BrushOOMError(RuntimeError):
    """Raised when Brush's stderr indicates an out-of-memory condition.

    Carries the resolution_cap that was attempted so the retry-hint policy
    can halve it for the next attempt (per spec §9.2 recovery table).
    """

    def __init__(self, resolution_cap_attempted: int, tail: str):
        self.resolution_cap_attempted = resolution_cap_attempted
        self.tail = tail
        super().__init__(f"Brush OOM at resolution_cap={resolution_cap_attempted}. Tail:\n{tail}")


def _looks_like_oom(text: str) -> bool:
    lowered = text.lower()
    return any(pat in lowered for pat in _OOM_PATTERNS)


def build_brush_command(
    brush_binary: Path,
    dataset_root: Path,
    output_dir: Path,
    cfg: BrushConfig,
    *,
    export_name: str = "scene.ply",
) -> list[str]:
    """Construct the Brush invocation for v0.3.x.

    Source is positional (`brush <PATH_OR_URL>`). All other params are flags.
    """
    cmd: list[str] = [
        str(brush_binary),
        str(dataset_root),
        "--total-steps",
        str(cfg.max_steps),
        "--max-resolution",
        str(cfg.resolution_cap),
        "--sh-degree",
        str(cfg.sh_degree),
        "--growth-stop-iter",
        str(cfg.densify_until_iter),
        "--export-path",
        str(output_dir),
        "--export-name",
        export_name,
        "--export-every",
        str(cfg.max_steps),  # only export at the very end
    ]
    cmd.extend(cfg.extra_args)
    return cmd


def stage_dataset(frames_dir: Path, sparse_dir: Path, staging_dir: Path) -> Path:
    """Build a brush-compatible dataset root via symlinks.

    Result layout:
        <staging>/images  -> frames_dir
        <staging>/sparse  -> sparse_dir
    """
    staging_dir.mkdir(parents=True, exist_ok=True)

    for name, target in (("images", frames_dir), ("sparse", sparse_dir)):
        link = staging_dir / name
        if link.is_symlink() or link.exists():
            if link.is_symlink() or link.is_file():
                link.unlink()
            else:
                shutil.rmtree(link)
        link.symlink_to(target.resolve(), target_is_directory=True)

    return staging_dir


def _psnr_for_pair(render: np.ndarray, original: np.ndarray) -> float:
    """PSNR (dB) between two same-shape uint8 BGR images.

    PSNR = 10 · log10(255² / MSE). When the two images are identical
    (MSE == 0) the formula diverges; we return a very high but finite
    number so the plateau-monitor's arithmetic doesn't blow up.
    """
    if render.shape != original.shape:
        raise ValueError(
            f"PSNR shape mismatch: render={render.shape} original={original.shape}"
        )
    diff = render.astype(np.float64) - original.astype(np.float64)
    mse = float(np.mean(diff * diff))
    if mse <= 1e-12:
        return 100.0  # sentinel "as good as it gets"
    return 10.0 * math.log10((255.0 * 255.0) / mse)


def compute_eval_psnr(eval_dir: Path, frames_dir: Path) -> float | None:
    """Mean PSNR across all rendered eval images vs their originals.

    Brush writes `eval_<step>/<original_filename>.png` for every held-out
    frame. We pair by **filename stem** so renders (.png) match frames
    (.jpg) of the same name. Originals are downscaled (cv2.INTER_AREA) to
    the render resolution before MSE — Brush trains at `resolution_cap`,
    not at the source resolution.

    Returns None when no pairs survive (eval_dir empty, originals missing,
    all loads fail). The PlateauMonitor treats None as "eval incomplete,
    skip this step" — never aborts training.
    """
    if not eval_dir.is_dir():
        return None

    renders = sorted(eval_dir.glob("*.png"))
    if not renders:
        return None

    psnrs: list[float] = []
    for render_path in renders:
        # Match by stem — render is e.g. `<stem>_frame_00051.png`,
        # original is `<stem>_frame_00051.jpg`.
        candidates = list(frames_dir.glob(f"{render_path.stem}.*"))
        if not candidates:
            logger.warning("train.eval_no_match", render=str(render_path))
            continue
        original_path = candidates[0]

        render = cv2.imread(str(render_path))
        original = cv2.imread(str(original_path))
        if render is None or original is None:
            logger.warning(
                "train.eval_imread_failed",
                render=str(render_path),
                original=str(original_path),
            )
            continue

        # Downscale original to render resolution for like-for-like MSE.
        if original.shape != render.shape:
            target_h, target_w = render.shape[:2]
            original = cv2.resize(
                original, (target_w, target_h), interpolation=cv2.INTER_AREA
            )

        try:
            psnrs.append(_psnr_for_pair(render, original))
        except ValueError as exc:
            logger.warning("train.eval_psnr_failed", error=str(exc))
            continue

    if not psnrs:
        return None
    return float(np.mean(psnrs))


def estimate_wall_time_s(cfg: BrushConfig) -> float:
    """Phase-7 heuristic: estimated Brush training wall-time (seconds).

    Calibrated from Phase-0 + burgstall real-runs:
      - bench_chill: 5000 steps × resolution_cap=1600 → 282 s (~56 ms/step)
      - burgstall:   30000 steps × resolution_cap=1600 → 3001 s (~100 ms/step)
        (more sparse points → more gaussians → slower per-step)

    Heuristic: ~80 ms per step at resolution_cap=1600, scales linearly with
    (resolution_cap / 1600). Conservative — under-estimates rather than over.
    """
    ms_per_step_at_1600 = 80
    resolution_factor = (cfg.resolution_cap / 1600.0) ** 2  # area scaling
    ms_per_step = ms_per_step_at_1600 * max(0.3, resolution_factor)
    return cfg.max_steps * ms_per_step / 1000.0


# Progress callback signature: (elapsed_s, estimated_pct) → None
ProgressCallback = Callable[[float, float], None]


def _find_latest_ply(directory: Path) -> Path | None:
    """Return newest .ply in directory (recursive), or None."""
    candidates = list(directory.rglob("*.ply"))
    if not candidates:
        return None
    return max(candidates, key=lambda p: p.stat().st_mtime)


def run_brush(
    brush_binary: Path,
    frames_dir: Path,
    sparse_dir: Path,
    output_dir: Path,
    cfg: BrushConfig,
    *,
    export_name: str = "scene.ply",
    progress_callback: ProgressCallback | None = None,
) -> TrainResult:
    """Invoke Brush against a staged COLMAP dataset, stream its output.

    `progress_callback(elapsed_s, est_pct)` is called every ~2 s on a heartbeat
    thread while training runs. Use this to drive a Rich Progress bar from
    the caller. Phase-7: we estimate progress from wall-time, not step counter,
    because Brush v0.3's TUI renderer doesn't expose iteration markers on stdout.
    """
    t0 = time.monotonic()
    output_dir.mkdir(parents=True, exist_ok=True)

    if not brush_binary.exists():
        raise FileNotFoundError(
            f"Brush binary missing: {brush_binary} — run scripts/fetch_brush.sh"
        )

    # Stage dataset root next to the training output
    staging_dir = output_dir.parent / "brush_dataset"
    dataset_root = stage_dataset(frames_dir, sparse_dir, staging_dir)

    cmd = build_brush_command(brush_binary, dataset_root, output_dir, cfg, export_name=export_name)
    eta_s = estimate_wall_time_s(cfg)
    logger.info(
        "train.brush.start",
        cmd=cmd,
        max_steps=cfg.max_steps,
        estimated_wall_time_s=round(eta_s, 1),
    )

    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )

    # Heartbeat thread for progress callback — fires every 2 s while training.
    # Brush v0.3 doesn't emit step counts on stdout, so we estimate from
    # wall-time against `eta_s`.
    stop_heartbeat = threading.Event()

    def _heartbeat() -> None:
        while not stop_heartbeat.wait(2.0):
            elapsed = time.monotonic() - t0
            est_pct = min(0.99, elapsed / eta_s) if eta_s > 0 else 0.0
            if progress_callback is not None:
                try:
                    progress_callback(elapsed, est_pct)
                except Exception as cb_err:
                    logger.warning("train.brush.progress_cb_error", error=str(cb_err))

    if progress_callback is not None:
        heartbeat_thread: threading.Thread | None = threading.Thread(
            target=_heartbeat, name="brush-progress", daemon=True
        )
        heartbeat_thread.start()
    else:
        heartbeat_thread = None
    steps_completed = 0
    output_tail: list[str] = []  # last 50 lines for OOM diagnosis
    assert proc.stdout is not None
    for raw_line in proc.stdout:
        line = raw_line.rstrip()
        if not line:
            continue
        output_tail.append(line)
        if len(output_tail) > 50:
            output_tail.pop(0)
        lowered = line.lower()
        if "step" in lowered or "iter" in lowered:
            logger.info("train.brush.progress", line=line)
        else:
            logger.debug("train.brush.out", line=line)
    proc.wait()
    stop_heartbeat.set()
    if heartbeat_thread is not None:
        heartbeat_thread.join(timeout=3)
        # Final 100% tick so the bar lands clean.
        if progress_callback is not None:
            import contextlib

            with contextlib.suppress(Exception):
                progress_callback(time.monotonic() - t0, 1.0)

    if proc.returncode != 0:
        tail = "\n".join(output_tail)
        if _looks_like_oom(tail):
            logger.warning(
                "train.brush.oom_detected",
                resolution_cap=cfg.resolution_cap,
                returncode=proc.returncode,
            )
            raise BrushOOMError(cfg.resolution_cap, tail)
        raise subprocess.CalledProcessError(proc.returncode, cmd, output=tail)

    final_ply = _find_latest_ply(output_dir)
    result = TrainResult(
        training_dir=output_dir,
        final_ply=final_ply,
        steps_completed=steps_completed,
        duration_s=time.monotonic() - t0,
    )
    logger.info(
        "train.done",
        final_ply=str(final_ply) if final_ply else None,
        duration_s=result.duration_s,
    )
    return result
