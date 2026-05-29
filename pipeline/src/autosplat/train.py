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

    v1.5.0 — when `cfg.plateau_enabled`, also append `--eval-split-every`,
    `--eval-every`, `--eval-save-to-disk`, and override `--export-every`
    to the eval cadence so every eval checkpoint has a fresh PLY in case
    SIGTERM fires mid-iteration.
    """
    export_every = cfg.plateau_eval_every if cfg.plateau_enabled else cfg.max_steps
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
        str(export_every),
    ]
    if cfg.plateau_enabled:
        cmd.extend(
            [
                "--eval-split-every",
                str(cfg.plateau_eval_split_every),
                "--eval-every",
                str(cfg.plateau_eval_every),
                "--eval-save-to-disk",
            ]
        )
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
        raise ValueError(f"PSNR shape mismatch: render={render.shape} original={original.shape}")
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
            original = cv2.resize(original, (target_w, target_h), interpolation=cv2.INTER_AREA)

        try:
            psnrs.append(_psnr_for_pair(render, original))
        except ValueError as exc:
            logger.warning("train.eval_psnr_failed", error=str(exc))
            continue

    if not psnrs:
        return None
    return float(np.mean(psnrs))


PsnrFn = Callable[[Path, Path], "float | None"]


@dataclass
class PlateauMonitor:
    """v1.5.0 — watches `<output_dir>/eval_<step>/` directories and decides
    when Brush training should stop.

    Construction is pure config; `poll_once()` does the work — call it
    periodically from a thread. `should_stop` is True once the last
    `patience` consecutive Δ-PSNR values are all below `min_delta_psnr`
    *and* the last evaluated step is ≥ `min_steps`.

    `psnr_fn` is injectable for tests; production uses `compute_eval_psnr`.
    """

    output_dir: Path
    frames_dir: Path
    min_steps: int
    patience: int
    min_delta_psnr: float
    psnr_fn: PsnrFn = field(default=compute_eval_psnr)

    history: list[tuple[int, float]] = field(default_factory=list)
    _seen_steps: set[int] = field(default_factory=set)
    _stop: bool = False

    @property
    def should_stop(self) -> bool:
        return self._stop

    def poll_once(self) -> None:
        """Scan for new eval_<N>/ dirs, compute PSNR for each new one,
        update history + plateau decision. Idempotent — running on the
        same state is a no-op."""
        if not self.output_dir.is_dir():
            return

        new_steps = sorted(
            step
            for d in self.output_dir.glob("eval_*")
            if d.is_dir()
            and (step := _parse_eval_step(d)) is not None
            and step not in self._seen_steps
        )
        for step in new_steps:
            psnr = self.psnr_fn(self.output_dir / f"eval_{step}", self.frames_dir)
            self._seen_steps.add(step)
            if psnr is None:
                # Step incomplete; try again on the next poll.
                self._seen_steps.discard(step)
                continue
            self.history.append((step, psnr))
            logger.info(
                "train.eval",
                step=step,
                psnr=round(psnr, 3),
                n_pairs=len(list((self.output_dir / f"eval_{step}").glob("*.png"))),
            )
            self._update_stop_decision()

    def _update_stop_decision(self) -> None:
        """Set _stop=True iff (a) last step ≥ min_steps, AND (b) the last
        `patience` Δ-PSNR values are all below `min_delta_psnr`."""
        if self._stop:
            return
        if len(self.history) < self.patience + 1:
            return  # need patience+1 evals to compute patience deltas
        last_step, _ = self.history[-1]
        if last_step < self.min_steps:
            return
        # Last `patience` deltas
        tail = self.history[-(self.patience + 1) :]
        deltas = [tail[i + 1][1] - tail[i][1] for i in range(self.patience)]
        if all(d < self.min_delta_psnr for d in deltas):
            self._stop = True


def _parse_eval_step(eval_dir: Path) -> int | None:
    """`eval_1000` → 1000. Returns None on malformed names."""
    name = eval_dir.name
    if not name.startswith("eval_"):
        return None
    suffix = name[len("eval_") :]
    return int(suffix) if suffix.isdigit() else None


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
# Eval callback signature: (step, eval_psnr_dB) → None — fired per new eval point
EvalCallback = Callable[[int, float], None]


def _drain_eval_history(
    monitor: PlateauMonitor, cursor: int, eval_callback: EvalCallback
) -> int:
    """Emit each (step, psnr) in `monitor.history` beyond `cursor` and return
    the new cursor. Lets the plateau loop forward fresh eval points to a
    progress sink without ever re-emitting old ones."""
    for step, psnr in monitor.history[cursor:]:
        eval_callback(step, psnr)
    return len(monitor.history)


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
    eval_callback: EvalCallback | None = None,
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

    # v1.5.0 — Plateau monitor thread (only when plateau_enabled). Polls
    # eval_<step>/ dirs every 5 s; when monitor.should_stop fires we send
    # SIGTERM and use the most-recent exported scene.ply as the final.
    monitor: PlateauMonitor | None = None
    plateau_thread: threading.Thread | None = None
    plateau_stop = threading.Event()
    plateau_triggered_at_step: int | None = None
    if cfg.plateau_enabled:
        monitor = PlateauMonitor(
            output_dir=output_dir,
            frames_dir=frames_dir,
            min_steps=cfg.plateau_min_steps,
            patience=cfg.plateau_patience,
            min_delta_psnr=cfg.plateau_min_delta_psnr,
        )

        def _plateau_loop() -> None:
            nonlocal plateau_triggered_at_step
            assert monitor is not None
            eval_cursor = 0
            while not plateau_stop.wait(5.0):
                try:
                    monitor.poll_once()
                except Exception as e:
                    logger.warning("train.plateau_poll_failed", error=str(e))
                    continue
                if eval_callback is not None:
                    eval_cursor = _drain_eval_history(monitor, eval_cursor, eval_callback)
                if monitor.should_stop:
                    plateau_triggered_at_step = monitor.history[-1][0] if monitor.history else None
                    logger.warning(
                        "train.plateau_detected",
                        triggering_at_step=plateau_triggered_at_step,
                        history=monitor.history,
                    )
                    proc.terminate()
                    return

        plateau_thread = threading.Thread(
            target=_plateau_loop, name="brush-plateau-monitor", daemon=True
        )
        plateau_thread.start()

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

    heartbeat_thread: threading.Thread | None = None
    if progress_callback is not None:
        heartbeat_thread = threading.Thread(
            target=_heartbeat, name="brush-progress", daemon=True
        )
        heartbeat_thread.start()
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
    plateau_stop.set()
    if plateau_thread is not None:
        plateau_thread.join(timeout=5)
    if heartbeat_thread is not None:
        heartbeat_thread.join(timeout=3)
        # Final 100% tick so the bar lands clean.
        if progress_callback is not None:
            import contextlib

            with contextlib.suppress(Exception):
                progress_callback(time.monotonic() - t0, 1.0)

    # v1.5.0 — a non-zero returncode caused by *our* SIGTERM (plateau hit)
    # is expected, not a failure. The most-recent exported scene.ply is the
    # final PLY. Anything else still goes through OOM / CalledProcessError.
    if proc.returncode != 0 and plateau_triggered_at_step is None:
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
    if plateau_triggered_at_step is not None and final_ply is None:
        # SIGTERM fired before Brush exported anything — surface as a real
        # failure (the user will see the train.plateau_detected event in
        # the log followed by this error).
        raise RuntimeError(
            "Brush terminated by plateau-monitor before any checkpoint was "
            f"written (triggered at step {plateau_triggered_at_step}). "
            "Consider lowering plateau_eval_every or raising plateau_min_steps."
        )

    result = TrainResult(
        training_dir=output_dir,
        final_ply=final_ply,
        steps_completed=plateau_triggered_at_step or steps_completed,
        duration_s=time.monotonic() - t0,
    )
    logger.info(
        "train.done",
        final_ply=str(final_ply) if final_ply else None,
        duration_s=result.duration_s,
    )
    return result
