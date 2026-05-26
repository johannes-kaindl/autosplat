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

import shutil
import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from . import preprocess as _preprocess_mod
from . import quality as _quality_mod
from . import sfm as _sfm_mod
from .config import Config, apply_override
from .logging import get_logger
from .preprocess import PreprocessResult
from .quality import QualityGateFailure
from .sfm import SfmResult

if TYPE_CHECKING:
    from .pipeline import PipelineResult
    from .watcher import WatcherState

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

    # v1.4.1: also cap preprocess.target_frames for probes — exhaustive
    # matcher's pair-match count scales as n²/2, so going from the
    # pipeline default of 250 to 120 cuts a single probe's matcher cost
    # by ~4×. The threshold is high enough that legitimate sub-clips
    # still register past the 50 %-ratio quality-gate.
    probe_cfg = apply_override(
        cfg,
        {
            "colmap": {"matcher": "exhaustive"},
            "preprocess": {"target_frames": cfg.retry.bisect_probe_target_frames},
        },
    )

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


ProbeFn = Callable[[BisectionClip, Path, Config], bool]


def _clip_path_for(capture_dir: Path, video_stem: str, clip_id: str) -> Path:
    """`<capture_dir>/rescue/clips/<stem>_part_<clip_id>.mp4`."""
    return capture_dir / "rescue" / "clips" / f"{video_stem}_part_{clip_id}.mp4"


def _probe_workspace_for(capture_dir: Path, clip_id: str) -> Path:
    """`<capture_dir>/rescue/probes/<clip_id>/`."""
    return capture_dir / "rescue" / "probes" / clip_id


def bisect_recursively(
    source_video: Path,
    duration_s: float,
    capture_dir: Path,
    cfg: Config,
    *,
    depth: int = 0,
    start_s: float = 0.0,
    clip_id_prefix: str = "",
    _probe_fn: ProbeFn | None = None,
) -> list[BisectionClip]:
    """DFS halt-on-success-per-branch tree walk.

    Splits the (sub-)range `[start_s, start_s + duration_s]` of `source_video`
    at midpoint into two children, then for each child whose duration meets
    `cfg.retry.bisect_min_clip_s`:
      • cut + probe via `_probe_fn` (defaults to the real probe_clip);
      • if probe passes → keep as leaf, do NOT recurse;
      • else if depth + 1 < cfg.retry.bisect_max_depth → recurse into that
        child;
      • else → drop (this branch is terminally failed).

    Returns the flat list of surviving leaves in left-to-right (temporal) order.

    Halts early if the *current* sub-range is shorter than `2 *
    bisect_min_clip_s` — splitting would produce children below the probe
    threshold and waste an ffmpeg cut.

    `_probe_fn` is injected purely for testing; production callers omit it.
    """
    probe_fn = _probe_fn if _probe_fn is not None else probe_clip
    min_s = cfg.retry.bisect_min_clip_s
    max_depth = cfg.retry.bisect_max_depth

    if duration_s < 2 * min_s or depth >= max_depth:
        return []

    half = duration_s / 2.0
    leaves: list[BisectionClip] = []
    for child_idx, child_start in enumerate((start_s, start_s + half)):
        child_id = f"{clip_id_prefix}_{child_idx}" if clip_id_prefix else str(child_idx)
        if half < min_s:
            # Shouldn't happen given the guard above, but be defensive.
            continue
        clip_path = _clip_path_for(capture_dir, source_video.stem, child_id)

        # An ffmpeg failure on a sub-range (corrupt segment, keyframe issue)
        # makes this child unprobeable. Treat it like a failed probe — log,
        # then continue with the sibling. Never crash the whole rescue.
        try:
            cut_video(source_video, child_start, half, clip_path)
        except subprocess.CalledProcessError as exc:
            logger.warning(
                "bisection.cut_aborted_branch",
                clip_id=child_id,
                start_s=child_start,
                duration_s=half,
                returncode=exc.returncode,
            )
            continue

        clip = BisectionClip(
            source_video=source_video,
            clip_id=child_id,
            start_s=child_start,
            duration_s=half,
            path=clip_path,
        )
        probe_ws = _probe_workspace_for(capture_dir, child_id)
        if probe_fn(clip, probe_ws, cfg):
            leaves.append(clip)
            continue
        # Probe failed — recurse only if we still have depth budget.
        if depth + 1 < max_depth:
            leaves.extend(
                bisect_recursively(
                    source_video,
                    duration_s=half,
                    capture_dir=capture_dir,
                    cfg=cfg,
                    depth=depth + 1,
                    start_s=child_start,
                    clip_id_prefix=child_id,
                    _probe_fn=probe_fn,
                )
            )

    return leaves


def _probe_duration_s(video: Path) -> float:
    """Thin wrapper around ffprobe so tests can monkey-patch the duration lookup."""
    return _preprocess_mod.probe_video(video).duration_s


def _run_pipeline_with_adaptive_retry(
    videos: list[Path],
    cfg: Config,
    *,
    capture_dir_override: Path,
    state: WatcherState | None,
    _bisection_already_attempted: bool,
) -> PipelineResult:
    """Lazy-import wrapper to break the pipeline ↔ bisection circular import."""
    from . import pipeline as _pipeline_mod

    return _pipeline_mod.run_pipeline_with_adaptive_retry(
        videos,
        cfg,
        capture_dir_override=capture_dir_override,
        state=state,
        _bisection_already_attempted=_bisection_already_attempted,
    )


def rescue_via_bisection(
    video: Path,
    capture_dir: Path,
    cfg: Config,
    *,
    state: WatcherState | None = None,
) -> PipelineResult:
    """Bisect a failed single-video capture and re-run as multi-video.

    Sequence:
      1. ffprobe the source for total duration.
      2. If duration < 2 * min_clip_s → raise QualityGateFailure (no bisection
         worth attempting; surfaces the structural failure to the user).
      3. Wipe stale frames/, colmap/, training/ from the prior failed attempts
         so the combined re-run starts from a clean slate.
      4. bisect_recursively → flat leaf list (each leaf is a physical .mp4
         already on disk under <capture_dir>/rescue/clips/).
      5. If no leaves survive → raise QualityGateFailure(reason="bisection_exhausted").
      6. Otherwise call run_pipeline_with_adaptive_retry with the leaves as
         the multi-video input, the existing capture_dir, and
         _bisection_already_attempted=True so the wrapper does not re-enter
         bisection on a further failure (preserves the sequential→exhaustive
         swap for the combined run).
    """
    t0 = time.monotonic()
    logger.info("bisection.start", video=str(video), capture_dir=str(capture_dir))

    duration_s = _probe_duration_s(video)
    min_s = cfg.retry.bisect_min_clip_s
    if duration_s < 2 * min_s:
        logger.warning(
            "bisection.too_short",
            duration_s=duration_s,
            min_clip_s=min_s,
        )
        raise QualityGateFailure(
            reason=f"bisection_skipped_too_short: {duration_s:.1f}s < {2 * min_s:.1f}s",
            stage="bisection",
            retry_hint=None,
            metrics={"duration_s": duration_s, "min_clip_s": min_s},
        )

    for sub in ("frames", "colmap", "training"):
        stale = capture_dir / sub
        if stale.exists():
            shutil.rmtree(stale)

    leaves = bisect_recursively(
        video,
        duration_s=duration_s,
        capture_dir=capture_dir,
        cfg=cfg,
    )

    if not leaves:
        logger.warning("bisection.exhausted", duration_s=duration_s)
        raise QualityGateFailure(
            reason="bisection_exhausted",
            stage="bisection",
            retry_hint=None,
            metrics={"duration_s": duration_s, "probed_count": 0},
        )

    logger.info(
        "bisection.combine_start",
        leaf_count=len(leaves),
        leaves=[leaf.clip_id for leaf in leaves],
        duration_s=time.monotonic() - t0,
    )
    return _run_pipeline_with_adaptive_retry(
        [leaf.path for leaf in leaves],
        cfg,
        capture_dir_override=capture_dir,
        state=state,
        _bisection_already_attempted=True,
    )
