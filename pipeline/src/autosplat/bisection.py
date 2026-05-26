# SPDX-License-Identifier: AGPL-3.0-or-later

"""v1.4 — Auto-Bisection-Rescue.

When the standard adaptive-retry path (sequential → exhaustive matcher swap)
exhausts itself with retry_hint=None, the pipeline can binary-subdivide the
source video, probe each leaf clip with a cheap preprocess+SfM-only run, and
combine the surviving leaves through the existing multi-video pipeline path.

See docs/superpowers/specs/2026-05-26-v14-bisection-rescue-design.md for the
full design and docs/CAPTURE-GUIDE.md for the user-facing explanation.

This module is built up across multiple slices:
  Slice 1 — build_ffmpeg_cut_command + BisectionClip   (this commit)
  Slice 2 — cut_video subprocess wrapper
  Slice 3 — probe_clip (preprocess + SfM-only)
  Slice 4 — bisect_recursively (DFS halt-on-success)
  Slice 5 — rescue_via_bisection (orchestrator)
  Slice 6 — pipeline.py integration
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

from . import preprocess as _preprocess_mod
from . import quality as _quality_mod
from . import sfm as _sfm_mod
from .config import Config, apply_override
from .logging import get_logger
from .preprocess import PreprocessResult
from .quality import QualityGateFailure
from .sfm import SfmResult

logger = get_logger(__name__)

# Module-private aliases so tests can monkey-patch the unit under test without
# also clobbering the real preprocess/sfm entries used elsewhere.
_run_preprocess = _preprocess_mod.extract_frames
_run_sfm = _sfm_mod.run_colmap


@dataclass(frozen=True)
class BisectionClip:
    """A single sub-clip in the bisection tree.

    `clip_id` is a depth-encoded path: '0', '0_1', '0_1_0'. Used as the
    filename suffix and as the probe-workspace directory name so a partial
    run is debuggable (which clips were tried, which passed).
    """

    source_video: Path
    clip_id: str
    start_s: float
    duration_s: float
    path: Path


def build_ffmpeg_cut_command(
    video: Path,
    start_s: float,
    duration_s: float,
    output: Path,
) -> list[str]:
    """Stream-copy ffmpeg command — no re-encode, fast cuts.

    `-ss` is placed before `-i` for fast seek; stream-copy (`-c copy`) skips
    re-encoding so the cut is near-instant and bit-exact in the kept range.

    Negative `start_s` is clamped to 0 (no-op on a normal video).
    """
    start = max(0.0, float(start_s))
    duration = max(0.0, float(duration_s))
    return [
        "ffmpeg",
        "-y",
        "-ss",
        f"{start:.3f}",
        "-i",
        str(video),
        "-t",
        f"{duration:.3f}",
        "-c",
        "copy",
        str(output),
    ]


def cut_video(
    video: Path,
    start_s: float,
    duration_s: float,
    output: Path,
) -> Path:
    """Run the ffmpeg cut. Raises subprocess.CalledProcessError on failure.

    Output's parent is created if missing. On non-zero exit the stderr tail
    is logged at error level before re-raising so the failure is observable
    in the structured log even when stderr would otherwise be swallowed.
    """
    output.parent.mkdir(parents=True, exist_ok=True)
    cmd = build_ffmpeg_cut_command(video, start_s, duration_s, output)
    logger.info(
        "bisection.cut",
        video=str(video),
        start_s=start_s,
        duration_s=duration_s,
        output=str(output),
    )
    try:
        subprocess.run(cmd, capture_output=True, text=True, check=True)
    except subprocess.CalledProcessError as exc:
        logger.error(
            "bisection.cut_failed",
            cmd=cmd,
            returncode=exc.returncode,
            stderr=(exc.stderr or "")[-2000:],
        )
        raise
    return output


def probe_clip(
    clip: BisectionClip,
    probe_workspace: Path,
    cfg: Config,
) -> bool:
    """Run preprocess + SfM-only against one sub-clip; return True if QG passes.

    Probes always use `cfg.colmap.matcher='exhaustive'` — sequential is
    unreliable on short segments and we've already spent two attempts on it
    in the parent capture's adaptive-retry path.

    Artifacts (frames/, colmap/) stay on disk under `probe_workspace` for
    forensic debugging (which clips passed, which didn't, why). The final
    combined run still re-extracts everything cleanly via run_pipeline.

    Failures are caught (subprocess errors, ffprobe parsing) and treated as
    "probe failed" → returns False. Only programming bugs propagate.
    """
    probe_workspace.mkdir(parents=True, exist_ok=True)
    frames_dir = probe_workspace / "frames"
    colmap_dir = probe_workspace / "colmap"

    probe_cfg = apply_override(cfg, {"colmap": {"matcher": "exhaustive"}})

    try:
        pp: PreprocessResult = _run_preprocess(clip.path, frames_dir, probe_cfg.preprocess)
    except Exception as exc:
        logger.warning("bisection.probe_preprocess_failed", clip_id=clip.clip_id, error=str(exc))
        return False

    try:
        sfm_res: SfmResult = _run_sfm(frames_dir, colmap_dir, probe_cfg.colmap)
    except Exception as exc:
        logger.warning("bisection.probe_sfm_failed", clip_id=clip.clip_id, error=str(exc))
        return False

    try:
        _quality_mod.check_sfm_quality(
            sfm_res,
            frames_kept=pp.kept_count,
            cfg=probe_cfg.quality_gate,
            colmap_cfg=probe_cfg.colmap,
        )
    except QualityGateFailure as exc:
        logger.info(
            "bisection.probe",
            clip_id=clip.clip_id,
            cameras_registered=sfm_res.cameras_registered,
            ratio=exc.metrics.get("ratio"),
            points=sfm_res.points,
            passed=False,
            reason=exc.reason,
        )
        return False

    logger.info(
        "bisection.probe",
        clip_id=clip.clip_id,
        cameras_registered=sfm_res.cameras_registered,
        frames_kept=pp.kept_count,
        points=sfm_res.points,
        passed=True,
    )
    return True
