# SPDX-License-Identifier: AGPL-3.0-or-later

"""End-to-end pipeline orchestrator.

Glues the per-stage modules into a single `run_pipeline(...)` call used by
both the one-shot `process` CLI command and the `watch` daemon.
"""

from __future__ import annotations

import json
import shutil
import time
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING

from . import compress as compress_mod
from . import export as export_mod
from . import obsidian as obsidian_mod
from . import preflight as preflight_mod
from . import preprocess as preprocess_mod
from . import quality as quality_mod
from . import sfm as sfm_mod
from . import train as train_mod
from . import viewer as viewer_mod
from .config import Config, apply_override
from .logging import configure_logging, get_logger
from .quality import QualityGateFailure

if TYPE_CHECKING:
    from .watcher import WatcherState

logger = get_logger(__name__)


@dataclass
class PipelineResult:
    capture_name: str
    capture_dir: Path
    output_ply: Path
    metadata_path: Path
    duration_s: float


SKIPPABLE_STAGES = {"preprocess", "sfm", "train", "export"}


def _make_capture_name(video: Path) -> str:
    """`{date}_{video_stem}` — recommended in spec §12.2."""
    return f"{date.today().isoformat()}_{video.stem}"


def detect_completed_stages(capture_dir: Path) -> set[str]:
    """Return the subset of SKIPPABLE_STAGES whose outputs already exist.

    Powers `autosplat resume`: each stage is detected by the artifact it
    leaves on disk, so a half-finished run can pick up where the previous
    process died (host sleep, OOM, Ctrl-C) without redoing work.

    Detection rules:
      preprocess — any `frames/frame_*.jpg`
      sfm        — `colmap/sparse/0/images.{bin,txt}` (mapper output)
      train      — any `*.ply` under `training/`
      export     — `output/scene.ply` (or legacy `scene.ply` at capture root)
    """
    done: set[str] = set()

    frames_dir = capture_dir / "frames"
    if frames_dir.is_dir() and any(frames_dir.glob("frame_*.jpg")):
        done.add("preprocess")

    sparse_zero = capture_dir / "colmap" / "sparse" / "0"
    if sparse_zero.is_dir() and (
        (sparse_zero / "images.bin").exists() or (sparse_zero / "images.txt").exists()
    ):
        done.add("sfm")

    training_dir = capture_dir / "training"
    if training_dir.is_dir() and any(training_dir.rglob("*.ply")):
        done.add("train")

    if (capture_dir / "output" / "scene.ply").exists() or (capture_dir / "scene.ply").exists():
        done.add("export")

    return done


def read_source_video_from_log(capture_dir: Path) -> Path | None:
    """Recover the source video path from the capture's `pipeline.log`.

    Scans for the first `pipeline.start` JSON event and returns its `video`
    field as a Path. Returns None when the log is absent, no `pipeline.start`
    event is present, or the recorded path field is missing — callers should
    fall back to a user-supplied `--video` override.
    """
    log_path = capture_dir / "pipeline.log"
    if not log_path.is_file():
        return None

    for raw in log_path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("event") == "pipeline.start" and event.get("video"):
            return Path(event["video"])
    return None


def run_pipeline(
    video: Path,
    config: Config,
    *,
    output_dir_override: Path | None = None,
    capture_dir_override: Path | None = None,
    skip_stages: set[str] | None = None,
    dry_run: bool = False,
    config_override: dict | None = None,
    state: WatcherState | None = None,
) -> PipelineResult:
    """Run the full pipeline on a single video.

    Stages are idempotent — re-running on the same capture-dir should resume
    where stages have already produced their outputs.

    `config_override` is a nested dict (e.g. `{"colmap": {"matcher": "exhaustive"}}`)
    deep-merged into `config` before any work — used by Phase-3 adaptive retry.

    `capture_dir_override`, when given, adopts the existing capture directory
    instead of computing `<today>_<video.stem>`. Used by `autosplat resume`
    to continue a previous (possibly cross-day) run without renaming its dir.

    `state`, when given, is a WatcherState the pipeline reports progress into:
    in_progress at start, the stage on each transition, and a completed entry on
    success — all keyed by the capture directory so the WebUI can track the run
    regardless of trigger path (CLI-direct, watch-daemon, WebUI). On failure the
    in_progress entry is left intact (stage = the failing stage) for the caller
    to resolve (retry vs. mark_failed).
    """
    if config_override:
        config = apply_override(config, config_override)
        logger.info("pipeline.config_override_applied", override=config_override)

    skip = skip_stages or set()
    unknown = skip - SKIPPABLE_STAGES
    if unknown:
        raise ValueError(f"Unknown stages to skip: {unknown}")

    if not video.exists():
        raise FileNotFoundError(f"Video not found: {video}")

    if capture_dir_override is not None:
        capture_dir = capture_dir_override
        capture_name = capture_dir.name
    else:
        capture_name = _make_capture_name(video)
        captures_root = output_dir_override or config.paths.captures_dir
        capture_dir = captures_root / capture_name

    capture_dir.mkdir(parents=True, exist_ok=True)
    (capture_dir / "source").mkdir(exist_ok=True)
    frames_dir = capture_dir / "frames"
    colmap_dir = capture_dir / "colmap"
    training_dir = capture_dir / "training"

    log_file = capture_dir / "pipeline.log"
    configure_logging(
        level=config.logging.level,
        console=config.logging.console,
        log_file=log_file if config.logging.log_to_file else None,
    )

    logger.info(
        "pipeline.start",
        capture_name=capture_name,
        capture_dir=str(capture_dir),
        video=str(video),
        skip=list(skip),
        dry_run=dry_run,
    )

    if dry_run:
        logger.info("pipeline.dry_run_exit")
        return PipelineResult(
            capture_name=capture_name,
            capture_dir=capture_dir,
            output_ply=capture_dir / "output" / "scene.ply",
            metadata_path=capture_dir / "output" / "metadata.json",
            duration_s=0.0,
        )

    t0 = time.monotonic()

    if state is not None:
        state.begin(capture_dir, source_video=video)
        state.update_stage("preflight")

    # ── Pre-flight (Phase 6 / Spec §5 + §9.2) ──────────────────────────
    # ffprobe-validate + duration/resolution/fps plausibility. Fails fast
    # on corrupt or implausible inputs before any extraction work.
    preflight_mod.run_preflight(video)

    # ── Preprocess ─────────────────────────────────────────────────────
    if state is not None:
        state.update_stage("preprocess")
    if "preprocess" in skip:
        kept = len(list(frames_dir.glob("frame_*.jpg")))
        extracted = kept
        logger.info("pipeline.skip", stage="preprocess", kept=kept)
    else:
        pp = preprocess_mod.extract_frames(video, frames_dir, config.preprocess)
        extracted = pp.extracted_count
        kept = pp.kept_count

    # ── SfM ────────────────────────────────────────────────────────────
    if state is not None:
        state.update_stage("sfm")
    if "sfm" in skip:
        # Resume path: re-parse the existing sparse model so quality_gate can
        # still validate it (without this, a previous low-camera SfM would
        # silently sail through and Brush would train on garbage).
        cams, points = sfm_mod._parse_mapper_stats(colmap_dir / "sparse")
        sfm_res = sfm_mod.SfmResult(
            workspace=colmap_dir,
            database_path=colmap_dir / "database.db",
            sparse_dir=colmap_dir / "sparse",
            cameras_registered=cams,
            points=points,
            duration_s=0.0,
        )
        logger.info("pipeline.skip", stage="sfm", cameras=cams, points=points)
    else:
        sfm_res = sfm_mod.run_colmap(frames_dir, colmap_dir, config.colmap)
        cams = sfm_res.cameras_registered
        points = sfm_res.points

    # ── Quality-Gate (Phase 3, spec §11.3) ─────────────────────────────
    # Bails out *before* the expensive Brush stage when SfM output is too
    # thin to produce a usable splat. Runs whether SfM was just produced or
    # resumed from disk — the latter is critical for `autosplat resume` on
    # a capture whose prior matcher run only registered a handful of frames.
    quality_mod.check_sfm_quality(
        sfm_res, frames_kept=kept, cfg=config.quality_gate, colmap_cfg=config.colmap
    )

    # ── Training ───────────────────────────────────────────────────────
    if state is not None:
        state.update_stage("train")
    if "train" in skip:
        steps = 0
        training_duration = 0.0
        candidate_ply = train_mod._find_latest_ply(training_dir)
        if candidate_ply is None:
            raise RuntimeError(
                "skip-stage=train but no .ply found in training dir — cannot continue"
            )
        logger.info("pipeline.skip", stage="train", ply=str(candidate_ply))
    else:
        # Phase 7: Rich progress-bar driven by run_brush's heartbeat callback.
        # Only attached when we're in an interactive (TTY) context — daemon
        # mode prints structured logs instead.
        from rich.console import Console
        from rich.progress import (
            BarColumn,
            Progress,
            TextColumn,
            TimeElapsedColumn,
            TimeRemainingColumn,
        )

        progress_console = Console(stderr=True)
        if progress_console.is_terminal:
            with Progress(
                TextColumn("[bold blue]Brush training"),
                BarColumn(),
                TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
                TimeElapsedColumn(),
                TextColumn("·"),
                TimeRemainingColumn(),
                console=progress_console,
                transient=False,
            ) as progress:
                task_id = progress.add_task("brush", total=100)

                def _cb(elapsed_s: float, est_pct: float) -> None:
                    progress.update(task_id, completed=est_pct * 100)

                tr = train_mod.run_brush(
                    config.paths.brush_binary,
                    frames_dir,
                    colmap_dir / "sparse",
                    training_dir,
                    config.brush,
                    progress_callback=_cb,
                )
        else:
            tr = train_mod.run_brush(
                config.paths.brush_binary,
                frames_dir,
                colmap_dir / "sparse",
                training_dir,
                config.brush,
            )
        if tr.final_ply is None:
            raise RuntimeError("Brush completed but produced no .ply")
        candidate_ply = tr.final_ply
        steps = tr.steps_completed
        training_duration = tr.duration_s

    if config.viewer.notify_on_complete:
        from . import notification as notif_mod

        notif_mod.notify_training_complete(
            capture_name=_make_capture_name(video),
            duration_s=training_duration,
        )

    # ── Export ─────────────────────────────────────────────────────────
    if state is not None:
        state.update_stage("export")
    if "export" in skip:
        raise ValueError("Cannot skip the final export stage")
    exp = export_mod.export_capture(
        capture_dir,
        candidate_ply,
        config.export,
        capture_name=capture_name,
        source_video=video,
        frames_extracted=extracted,
        frames_kept=kept,
        colmap_cameras_registered=cams,
        colmap_points=points,
        training_steps=steps,
        training_duration_s=training_duration,
    )

    # ── Compress (Phase 5, opt-in) ─────────────────────────────────────
    # Runs before Viewer because the user may want to open the compressed
    # variant. Failure of a single format doesn't abort the pipeline — the
    # canonical PLY is already written.
    if config.compress.enabled:
        for fmt in config.compress.formats:
            try:
                compress_mod.compress_ply(
                    exp.output_ply,
                    exp.output_ply.parent,
                    fmt=fmt,
                    quality=config.compress.quality,
                )
            except (compress_mod.CompressorNotAvailable, RuntimeError) as e:
                logger.warning(
                    "pipeline.compress_failed",
                    fmt=fmt,
                    error=str(e),
                )

    # ── Viewer (opt-in) ────────────────────────────────────────────────
    if config.viewer.auto_open and config.viewer.target != "none":
        viewer_mod.open_in_viewer(exp.output_ply, config.viewer)

    # ── Obsidian (opt-in, Phase 4) ─────────────────────────────────────
    # Build embed_url for supersplat-local target — auto-fills the Obsidian note.
    embed_url: str | None = None
    if config.obsidian.enabled and config.viewer.target == "supersplat-local":
        embed_url = (
            f"http://localhost:{config.viewer.supersplat_local_port}"
            f"?load=http://127.0.0.1:{config.viewer.local_http_port}/{exp.output_ply.name}"
        )

    if config.obsidian.enabled:
        ply_meta = obsidian_mod.read_ply_header(exp.output_ply)
        note_data = obsidian_mod.CaptureNoteData(
            capture_date=date.today().isoformat(),
            capture_name=capture_name,
            source_video=str(video),
            video_stem=video.stem,
            frame_count_extracted=extracted,
            frame_count_kept=kept,
            cameras_registered=cams,
            points3d=points,
            gaussians=ply_meta["gaussians"],
            sh_degree=ply_meta["sh_degree"],
            training_duration_s=training_duration,
            total_duration_s=time.monotonic() - t0,
            output_ply=str(exp.output_ply),
            output_ply_size_bytes=exp.size_bytes,
            embed_url=embed_url,
            tags=list(config.obsidian.default_tags),
            frontmatter_type=config.obsidian.frontmatter_type,
        )
        obsidian_mod.write_capture_note(config.obsidian, note_data)

    duration = time.monotonic() - t0
    logger.info("pipeline.done", duration_s=duration, output_ply=str(exp.output_ply))

    if state is not None:
        state.mark_done(exp.output_ply, duration, max_history=config.status.max_history)

    return PipelineResult(
        capture_name=capture_name,
        capture_dir=capture_dir,
        output_ply=exp.output_ply,
        metadata_path=exp.metadata_path,
        duration_s=duration,
    )


def run_pipeline_with_adaptive_retry(
    video: Path,
    config: Config,
    *,
    output_dir_override: Path | None = None,
    capture_dir_override: Path | None = None,
    skip_stages: set[str] | None = None,
    dry_run: bool = False,
    state: WatcherState | None = None,
) -> PipelineResult:
    """run_pipeline + in-process Phase-3 adaptive retry on QualityGateFailure.

    The watch-folder daemon already has its own daemon-level retry (persistent
    state, queue re-enqueue). This wrapper provides the same loop for one-shot
    callers (CLI `process`, WebUI JobRunner) that don't carry daemon state.

    On a QualityGateFailure carrying a structured `retry_hint`, the wrapper:
      1. wipes `<capture_dir>/colmap/` (the matcher swap invalidates feature
         matches and the sparse model — leaving them around mixes data from
         two matchers in one DB)
      2. adds `preprocess` to skip_stages (frames are still valid — cheap win)
      3. re-runs `run_pipeline` with `config_override=hint`

    Stops when (a) the hint is None, (b) `cfg.retry.enabled=False`, or
    (c) `cfg.retry.max_retries` is reached — then re-raises the last failure.
    """
    max_attempts = config.retry.max_retries if config.retry.enabled else 1
    override: dict | None = None
    skip = set(skip_stages) if skip_stages else None

    if capture_dir_override is not None:
        capture_dir = capture_dir_override
    else:
        captures_root = output_dir_override or config.paths.captures_dir
        capture_dir = captures_root / _make_capture_name(video)

    attempts = 0
    while True:
        attempts += 1
        try:
            return run_pipeline(
                video,
                config,
                output_dir_override=output_dir_override,
                capture_dir_override=capture_dir_override,
                skip_stages=skip,
                dry_run=dry_run,
                config_override=override,
                state=state,
            )
        except QualityGateFailure as e:
            if e.retry_hint is None or attempts >= max_attempts:
                raise
            colmap_dir = capture_dir / "colmap"
            if colmap_dir.exists():
                shutil.rmtree(colmap_dir)
            override = e.retry_hint
            skip = set(skip) if skip else set()
            skip.add("preprocess")
            # If we got here via resume (sfm skipped), drop it so the retry
            # actually re-runs SfM with the new matcher — otherwise we'd
            # wipe colmap/ and then try to parse a non-existent sparse model.
            skip.discard("sfm")
            logger.warning(
                "pipeline.adaptive_retry",
                reason=e.reason,
                retry_hint=override,
                attempt=attempts,
                max_attempts=max_attempts,
            )


def resume_capture(
    capture_dir: Path,
    config: Config,
    *,
    video_override: Path | None = None,
    state: WatcherState | None = None,
) -> PipelineResult:
    """Continue a previous capture from wherever it stopped.

    Powers `autosplat resume`. Resolves the source video (explicit override
    wins, otherwise scrape `pipeline.log`), inspects which stages already
    have outputs, then runs `run_pipeline_with_adaptive_retry` against the
    existing capture directory — never a new date-stamped one.

    Refuses early when the capture's export stage has already completed
    (output/scene.ply present) — the user is meant to delete the output
    and start over in that case, not silently redo everything.
    """
    video = video_override or read_source_video_from_log(capture_dir)
    if video is None:
        raise ValueError(
            f"Cannot resume {capture_dir}: no source video recorded in "
            "pipeline.log — pass --video to point at the original file."
        )

    completed = detect_completed_stages(capture_dir)
    if "export" in completed:
        raise ValueError(
            f"{capture_dir} is already complete (output/scene.ply exists) — "
            "delete the output to re-run or use `autosplat process`."
        )

    return run_pipeline_with_adaptive_retry(
        video,
        config,
        capture_dir_override=capture_dir,
        skip_stages=completed or None,
        state=state,
    )
