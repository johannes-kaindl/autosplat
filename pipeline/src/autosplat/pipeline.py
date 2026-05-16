# SPDX-License-Identifier: AGPL-3.0-or-later

"""End-to-end pipeline orchestrator.

Glues the per-stage modules into a single `run_pipeline(...)` call used by
both the one-shot `process` CLI command and the `watch` daemon.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import date
from pathlib import Path

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


def run_pipeline(
    video: Path,
    config: Config,
    *,
    output_dir_override: Path | None = None,
    skip_stages: set[str] | None = None,
    dry_run: bool = False,
    config_override: dict | None = None,
) -> PipelineResult:
    """Run the full pipeline on a single video.

    Stages are idempotent — re-running on the same capture-dir should resume
    where stages have already produced their outputs.

    `config_override` is a nested dict (e.g. `{"colmap": {"matcher": "exhaustive"}}`)
    deep-merged into `config` before any work — used by Phase-3 adaptive retry.
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

    # ── Pre-flight (Phase 6 / Spec §5 + §9.2) ──────────────────────────
    # ffprobe-validate + duration/resolution/fps plausibility. Fails fast
    # on corrupt or implausible inputs before any extraction work.
    preflight_mod.run_preflight(video)

    # ── Preprocess ─────────────────────────────────────────────────────
    if "preprocess" in skip:
        kept = len(list(frames_dir.glob("frame_*.jpg")))
        extracted = kept
        logger.info("pipeline.skip", stage="preprocess", kept=kept)
    else:
        pp = preprocess_mod.extract_frames(video, frames_dir, config.preprocess)
        extracted = pp.extracted_count
        kept = pp.kept_count

    # ── SfM ────────────────────────────────────────────────────────────
    if "sfm" in skip:
        cams = points = 0
        logger.info("pipeline.skip", stage="sfm")
    else:
        sfm_res = sfm_mod.run_colmap(frames_dir, colmap_dir, config.colmap)
        cams = sfm_res.cameras_registered
        points = sfm_res.points

        # ── Quality-Gate (Phase 3, spec §11.3) ─────────────────────────
        # Bails out *before* the expensive Brush stage when SfM output is
        # too thin to produce a usable splat. Raises QualityGateFailure with
        # a structured retry-hint that the watcher can apply on the next try.
        quality_mod.check_sfm_quality(
            sfm_res, frames_kept=kept, cfg=config.quality_gate, colmap_cfg=config.colmap
        )

    # ── Training ───────────────────────────────────────────────────────
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

    return PipelineResult(
        capture_name=capture_name,
        capture_dir=capture_dir,
        output_ply=exp.output_ply,
        metadata_path=exp.metadata_path,
        duration_s=duration,
    )
