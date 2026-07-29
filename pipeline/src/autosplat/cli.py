# SPDX-License-Identifier: AGPL-3.0-or-later

"""autosplat — Typer-based CLI.

Commands (spec §7):
  autosplat process <video>
  autosplat resume <capture_dir>
  autosplat watch <folder>
  autosplat status
  autosplat config show | init
  autosplat doctor
  autosplat version
"""

from __future__ import annotations

import os
import shutil
import webbrowser
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import typer
from rich.console import Console
from rich.table import Table

from . import __version__
from . import cleanup as cleanup_mod
from . import viewer as viewer_mod
from .bisection import rescue_via_bisection
from .compress import CompressorNotAvailable, compress_ply, install_hint_for
from .config import XDG_CONFIG_PATH, Config, apply_override, dump_default_config, load_config
from .doctor import all_required_passed, run_doctor
from .logging import configure_logging, get_logger
from .pipeline import (
    PipelineResult,
    _make_capture_name,
    add_video_to_capture,
    detect_completed_stages,
    read_source_video_from_log,
    resume_capture,
    run_pipeline,
    run_pipeline_with_adaptive_retry,
)
from .watcher import STATE_FILE, WatchDaemon, WatcherState, recover_state

app = typer.Typer(
    name="autosplat",
    help="Drone-video → Gaussian Splat pipeline (Apple Silicon).",
    add_completion=False,
    no_args_is_help=True,
)

config_app = typer.Typer(help="Inspect or initialise configuration.")
app.add_typer(config_app, name="config")

console = Console()
err_console = Console(stderr=True)
logger = get_logger(__name__)


# Exit codes per spec §7
EXIT_OK = 0
EXIT_USER_ERROR = 1
EXIT_PIPELINE_FAILURE = 2
EXIT_DEP_MISSING = 3


def _load_or_die(config_path: Path | None) -> Config:
    try:
        return load_config(config_path)
    except FileNotFoundError as e:
        err_console.print(f"[red]Config error:[/red] {e}")
        raise typer.Exit(EXIT_USER_ERROR) from e
    except Exception as e:
        err_console.print(f"[red]Config invalid:[/red] {e}")
        raise typer.Exit(EXIT_USER_ERROR) from e


def _remote_supersplat_url_for(ply_url: str) -> str:
    """Wrap a local PLY URL in the remote SuperSplat editor's `?load=` param.

    Used by `autosplat serve` (without `--with-supersplat`) to avoid the
    browser-download dialog that fires when the raw `.ply` URL is opened —
    `.ply` has no native browser MIME handler, so the browser offers the
    file as a download instead of rendering it. The remote SuperSplat
    editor fetches the same URL itself and renders the splat in a canvas.
    """
    import urllib.parse

    return f"{viewer_mod.SUPERSPLAT_URL}?load={urllib.parse.quote(ply_url, safe='')}"


def _warn_if_viewer_misconfigured(cfg: Config) -> None:
    """v1.4.6 — fail loudly at the *start* of a pipeline run if the viewer
    is configured for supersplat-local but the dist isn't built. Otherwise
    the user only finds out after the ~5 h run finishes and the auto-open
    silently falls back to a hint message. We print, but don't exit — the
    user might want to set up the dist during the run, or accept the
    fallback. `autosplat doctor` covers the same check independently.
    """
    if not cfg.viewer.auto_open:
        return
    if cfg.viewer.target != "supersplat-local":
        return
    dist = cfg.viewer.supersplat_dist_path
    if not dist.is_absolute():
        dist = Path.cwd() / dist
    if (dist / "index.html").is_file():
        return
    err_console.print(
        "[yellow]Warning:[/yellow] [viewer] target='supersplat-local' but no "
        f"SuperSplat dist at {dist}. Auto-open at the end of the run will "
        "fall back to a hint message instead of opening the editor.\n"
        "[dim]Fix during this run with: [bold]bash scripts/setup_supersplat.sh[/bold] "
        "— or set [bold][viewer] auto_open = false[/bold] to silence this.[/dim]"
    )


def _open_viewer_if_configured(output_ply: Path, cfg: Config) -> None:
    """Open the result in the configured viewer, blocking on a local PLY
    server until Ctrl-C. Called by process/resume/add-video/rescue *after*
    the Done summary so the user sees the result first.

    v1.4.2 — moved out of `pipeline.run_pipeline` because the new
    blocking-server behaviour would stall the watch-folder daemon and the
    WebUI's JobRunner between captures. Only CLI commands open the viewer.
    """
    if not cfg.viewer.auto_open or cfg.viewer.target == "none":
        return
    viewer_mod.open_in_viewer(output_ply, cfg.viewer)


def _find_ply(capture_dir: Path) -> Path | None:
    """Find scene.ply in capture_dir or capture_dir/output/."""
    for candidate in [
        capture_dir / "scene.ply",
        capture_dir / "output" / "scene.ply",
    ]:
        if candidate.exists():
            return candidate
    # Fallback: first .ply found in capture_dir
    plys = sorted(capture_dir.glob("*.ply"))
    return plys[0] if plys else None


@app.command()
def process(
    videos: list[Path] = typer.Argument(
        ...,
        exists=False,
        help="Path to one or more video files. Multiple paths produce a single "
        "multi-video capture (frames from each are combined for SfM).",
    ),
    config: Path | None = typer.Option(None, "--config", "-c", help="Override config file."),
    output_dir: Path | None = typer.Option(
        None, "--output-dir", "-o", help="Override captures_dir."
    ),
    skip_stage: list[str] = typer.Option(
        [], "--skip-stage", help="Stages to skip when resuming. Repeatable."
    ),
    target_frames: int | None = typer.Option(
        None,
        "--target-frames",
        help="Override preprocess.target_frames for this run "
        "(useful for long videos where the default 250 subsamples too aggressively).",
    ),
    dry_run: bool = typer.Option(False, "--dry-run", help="Print plan, do not run."),
) -> None:
    """Run the full pipeline on one or more videos.

    Single video: classic capture-from-one-pass.
    Multiple videos: each is preprocessed with a per-source prefix, then COLMAP
    solves the combined frame set — useful for rescuing rotation-heavy footage
    that can't be reconstructed from a single pass (see docs/CAPTURE-GUIDE.md).
    """
    for v in videos:
        if not v.exists():
            err_console.print(f"[red]Video not found:[/red] {v}")
            raise typer.Exit(EXIT_USER_ERROR)

    cfg = _load_or_die(config)
    if target_frames is not None:
        cfg = apply_override(cfg, {"preprocess": {"target_frames": target_frames}})
    configure_logging(level=cfg.logging.level, console=cfg.logging.console)
    _warn_if_viewer_misconfigured(cfg)

    # Report status into WatcherState so the WebUI can track this CLI-direct run.
    state = WatcherState.load()
    try:
        result = run_pipeline_with_adaptive_retry(
            videos if len(videos) > 1 else videos[0],
            cfg,
            output_dir_override=output_dir,
            skip_stages=set(skip_stage) if skip_stage else None,
            dry_run=dry_run,
            state=state,
        )
    except FileNotFoundError as e:
        err_console.print(f"[red]Missing input:[/red] {e}")
        raise typer.Exit(EXIT_USER_ERROR) from e
    except Exception as e:
        # Any pipeline failure (RuntimeError, quality-gate, Brush OOM, …):
        # record it in WatcherState before exiting so the run doesn't linger
        # as a stale in_progress entry in the WebUI.
        if state.in_progress is not None:
            state.mark_failed(reason=str(e), stage=state.in_progress.stage)
        err_console.print(f"[red]Pipeline failure:[/red] {e}")
        raise typer.Exit(EXIT_PIPELINE_FAILURE) from e

    console.print(f"[green]Done:[/green] {result.output_ply}")
    console.print(f"[dim]Capture dir:[/dim] {result.capture_dir}")
    console.print(f"[dim]Duration:[/dim] {result.duration_s:.1f}s")
    _open_viewer_if_configured(result.output_ply, cfg)


@app.command()
def resume(
    capture_dir: Path = typer.Argument(
        ..., exists=True, file_okay=False, help="Capture directory to resume."
    ),
    video: Path | None = typer.Option(
        None,
        "--video",
        "-v",
        help="Override the source video (otherwise scraped from pipeline.log).",
    ),
    target_frames: int | None = typer.Option(
        None,
        "--target-frames",
        help="Override preprocess.target_frames. Only takes effect if "
        "preprocess hasn't already run (i.e. frames/ is empty).",
    ),
    config: Path | None = typer.Option(None, "--config", "-c", help="Override config file."),
) -> None:
    """Continue a previous capture from wherever it stopped.

    Re-uses the existing frames / SfM / training artifacts on disk and only
    re-runs the stages that didn't complete. Adaptive retry (matcher swap on
    low camera ratio, etc.) is applied the same way as `process`.
    """
    cfg = _load_or_die(config)
    if target_frames is not None:
        cfg = apply_override(cfg, {"preprocess": {"target_frames": target_frames}})
    configure_logging(level=cfg.logging.level, console=cfg.logging.console)
    _warn_if_viewer_misconfigured(cfg)

    completed = detect_completed_stages(capture_dir)
    if completed:
        console.print(f"[dim]Stages already complete:[/dim] {sorted(completed)}")
    else:
        console.print("[dim]No prior stage outputs detected — running everything.[/dim]")

    state = WatcherState.load()
    try:
        result = resume_capture(capture_dir, cfg, video_override=video, state=state)
    except ValueError as e:
        err_console.print(f"[red]Cannot resume:[/red] {e}")
        raise typer.Exit(EXIT_USER_ERROR) from e
    except FileNotFoundError as e:
        err_console.print(f"[red]Missing input:[/red] {e}")
        raise typer.Exit(EXIT_USER_ERROR) from e
    except Exception as e:
        if state.in_progress is not None:
            state.mark_failed(reason=str(e), stage=state.in_progress.stage)
        err_console.print(f"[red]Pipeline failure:[/red] {e}")
        raise typer.Exit(EXIT_PIPELINE_FAILURE) from e

    console.print(f"[green]Done:[/green] {result.output_ply}")
    console.print(f"[dim]Capture dir:[/dim] {result.capture_dir}")
    console.print(f"[dim]Duration:[/dim] {result.duration_s:.1f}s")
    _open_viewer_if_configured(result.output_ply, cfg)


@app.command("add-video")
def add_video(
    capture_dir: Path = typer.Argument(
        ..., exists=True, file_okay=False, help="Capture directory to extend."
    ),
    video: Path = typer.Argument(
        ..., exists=True, help="Additional source video to combine into this capture."
    ),
    config: Path | None = typer.Option(None, "--config", "-c", help="Override config file."),
) -> None:
    """Append another video to an existing capture and rebuild SfM/training.

    Useful for rescuing rotation-heavy captures that didn't reconstruct from
    a single pass — shoot a second pass with more translation and combine
    the two into one capture. Reads the existing capture's source video(s)
    from pipeline.log, wipes frames/colmap/training, then re-runs the full
    pipeline with the combined video list (see docs/CAPTURE-GUIDE.md).
    """
    cfg = _load_or_die(config)
    configure_logging(level=cfg.logging.level, console=cfg.logging.console)
    _warn_if_viewer_misconfigured(cfg)

    state = WatcherState.load()
    try:
        result = add_video_to_capture(capture_dir, video, cfg, state=state)
    except ValueError as e:
        err_console.print(f"[red]Cannot add video:[/red] {e}")
        raise typer.Exit(EXIT_USER_ERROR) from e
    except FileNotFoundError as e:
        err_console.print(f"[red]Missing input:[/red] {e}")
        raise typer.Exit(EXIT_USER_ERROR) from e
    except Exception as e:
        if state.in_progress is not None:
            state.mark_failed(reason=str(e), stage=state.in_progress.stage)
        err_console.print(f"[red]Pipeline failure:[/red] {e}")
        raise typer.Exit(EXIT_PIPELINE_FAILURE) from e

    console.print(f"[green]Done:[/green] {result.output_ply}")
    console.print(f"[dim]Capture dir:[/dim] {result.capture_dir}")
    console.print(f"[dim]Duration:[/dim] {result.duration_s:.1f}s")
    _open_viewer_if_configured(result.output_ply, cfg)


@app.command()
def rescue(
    target: Path = typer.Argument(
        ...,
        exists=True,
        help="Either a source video (.mp4 / .mov) or an existing capture directory "
        "whose original source failed structurally.",
    ),
    video: Path | None = typer.Option(
        None,
        "--video",
        "-v",
        help="When TARGET is a capture-dir, the original source video to bisect. "
        "Defaults to scraping pipeline.log if not provided.",
    ),
    output_dir: Path | None = typer.Option(
        None, "--output-dir", "-o", help="Override captures_dir (when TARGET is a video)."
    ),
    config: Path | None = typer.Option(None, "--config", "-c", help="Override config file."),
) -> None:
    """Manually trigger the v1.4 auto-bisection-rescue path.

    Two modes:
      • TARGET is a video file: a fresh capture_dir is created, frames/colmap
        are wiped if they exist, and bisection runs immediately — bypassing
        the sequential and exhaustive matcher attempts.
      • TARGET is a capture directory: the original source is recovered from
        pipeline.log (or --video override), and bisection runs against the
        existing capture_dir, preserving any rescue/ artefacts already present.

    Useful when you already know a single-pass video is structurally hostile
    (rotation-heavy footage, 180° turn) and you'd rather pay the bisection
    cost up-front than wait ~30 min for sequential + exhaustive to fail.
    Bisection respects all `[retry] bisect_*` config knobs.
    """
    cfg = _load_or_die(config)
    configure_logging(level=cfg.logging.level, console=cfg.logging.console)
    _warn_if_viewer_misconfigured(cfg)

    if target.is_file():
        # Mode A: fresh video.
        source_video = target
        captures_root = output_dir or cfg.paths.captures_dir
        capture_dir = captures_root / _make_capture_name(source_video)
        capture_dir.mkdir(parents=True, exist_ok=True)
        console.print(f"[blue]Rescue mode:[/blue] fresh capture for {source_video.name}")
    else:
        # Mode B: existing capture-dir.
        capture_dir = target
        if video is not None:
            source_video = video
        else:
            sources = read_source_video_from_log(capture_dir)
            if not sources:
                err_console.print(
                    f"[red]Cannot rescue:[/red] no source video recorded in "
                    f"{capture_dir}/pipeline.log — pass --video to point at it."
                )
                raise typer.Exit(EXIT_USER_ERROR)
            # Bisection only handles single-video; if a multi-video capture
            # ended up here, the user has to nominate one explicitly.
            if len(sources) > 1:
                err_console.print(
                    f"[red]Cannot rescue:[/red] {capture_dir} has {len(sources)} "
                    "source videos recorded; bisection is single-video only. "
                    "Pass --video <one-of-them> to choose."
                )
                raise typer.Exit(EXIT_USER_ERROR)
            source_video = sources[0]
        console.print(f"[blue]Rescue mode:[/blue] existing capture {capture_dir.name}")

    state = WatcherState.load()
    try:
        result: PipelineResult = rescue_via_bisection(source_video, capture_dir, cfg, state=state)
    except FileNotFoundError as e:
        err_console.print(f"[red]Missing input:[/red] {e}")
        raise typer.Exit(EXIT_USER_ERROR) from e
    except Exception as e:
        if state.in_progress is not None:
            state.mark_failed(reason=str(e), stage=state.in_progress.stage)
        err_console.print(f"[red]Rescue failure:[/red] {e}")
        raise typer.Exit(EXIT_PIPELINE_FAILURE) from e

    console.print(f"[green]Done:[/green] {result.output_ply}")
    console.print(f"[dim]Capture dir:[/dim] {result.capture_dir}")
    console.print(f"[dim]Duration:[/dim] {result.duration_s:.1f}s")
    _open_viewer_if_configured(result.output_ply, cfg)


@app.command("cleanup-rescue")
def cleanup_rescue(
    capture_dir: Path = typer.Argument(
        ...,
        exists=True,
        file_okay=False,
        help="Capture directory whose rescue/ artefacts you want to reclaim.",
    ),
    keep_clips: bool = typer.Option(
        True,
        "--keep-clips/--remove-clips",
        help="Keep the rescue/clips/*.mp4 sub-clips (default true — they're "
        "the source-of-truth in pipeline.log and resume/add-video need them). "
        "--remove-clips drops them too; only safe after the capture is fully "
        "done and you don't intend to resume.",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Print what would be removed without touching disk.",
    ),
) -> None:
    """Delete bisection probe artefacts to reclaim disk space.

    Each bisection probe leaves a `<capture_dir>/rescue/probes/<clip_id>/`
    folder with frames + a colmap workspace — useful for forensic
    debugging when a probe failed, but typically ~1-3 GB per capture
    after a successful rescue. This command removes them.

    `rescue/clips/*.mp4` (the leaf-clip sources) are kept by default
    because pipeline.log references them and `autosplat resume` /
    `autosplat add-video` re-extract from them. Pass `--remove-clips` to
    drop those too once you're sure you won't touch the capture again.
    """
    rescue_dir = capture_dir / "rescue"
    if not rescue_dir.is_dir():
        console.print(f"[dim]No rescue/ directory in {capture_dir} — nothing to clean.[/dim]")
        return

    targets: list[Path] = []
    probes_dir = rescue_dir / "probes"
    if probes_dir.is_dir():
        targets.append(probes_dir)
    if not keep_clips:
        clips_dir = rescue_dir / "clips"
        if clips_dir.is_dir():
            targets.append(clips_dir)

    if not targets:
        console.print(f"[dim]Nothing to remove in {rescue_dir}.[/dim]")
        return

    total_bytes = 0
    for target in targets:
        for p in target.rglob("*"):
            if p.is_file():
                total_bytes += p.stat().st_size

    mb = total_bytes / (1024 * 1024)
    action = "Would remove" if dry_run else "Removing"
    console.print(f"[yellow]{action}:[/yellow] {len(targets)} dir(s), ~{mb:.1f} MB")
    for target in targets:
        console.print(f"  • {target}")

    if dry_run:
        console.print("[dim]Dry-run — no changes made.[/dim]")
        return

    for target in targets:
        shutil.rmtree(target)
    console.print(f"[green]Done.[/green] Reclaimed ~{mb:.1f} MB.")


@app.command("cleanup-intermediates")
def cleanup_intermediates(
    capture_dir: Path = typer.Argument(
        ...,
        exists=True,
        file_okay=False,
        help="Capture directory whose frames/colmap/training working dirs you want to reclaim.",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Print what would be removed without touching disk.",
    ),
) -> None:
    """Delete frames/, colmap/, training/ once a capture has finished exporting.

    These are the SfM/training working directories — once `output/scene.ply`
    exists they're pure disk cost (typically 1-2 GB per capture). Nothing
    downstream needs them: `autosplat add-video` always wipes and
    re-extracts them from scratch from the original source videos (recorded
    in pipeline.log), it never reuses their contents.

    Refuses when `output/scene.ply` is missing — an unfinished capture still
    needs these for `autosplat resume`.
    """
    targets = cleanup_mod.prunable_targets(capture_dir)
    try:
        # Peek dry-run first so we can report before touching disk either way.
        preview = cleanup_mod.prune_intermediates(capture_dir, dry_run=True)
    except cleanup_mod.NotExported:
        err_console.print(
            f"[red]Refusing:[/red] {capture_dir} has no output/scene.ply yet — "
            "this capture hasn't finished exporting. `autosplat resume` still "
            "needs frames/colmap/training to continue."
        )
        raise typer.Exit(EXIT_USER_ERROR) from None

    if not targets:
        console.print(f"[dim]Nothing to remove in {capture_dir}.[/dim]")
        return

    mb = preview.bytes_reclaimed / (1024 * 1024)
    action = "Would remove" if dry_run else "Removing"
    console.print(f"[yellow]{action}:[/yellow] {len(targets)} dir(s), ~{mb:.1f} MB")
    for target in targets:
        console.print(f"  • {target}")

    if dry_run:
        console.print("[dim]Dry-run — no changes made.[/dim]")
        return

    cleanup_mod.prune_intermediates(capture_dir)
    console.print(f"[green]Done.[/green] Reclaimed ~{mb:.1f} MB.")


@app.command("migrate-storage")
def migrate_storage(
    config: Path | None = typer.Option(None, "--config", "-c"),
    apply: bool = typer.Option(
        False, "--apply", help="Actually reclaim. Without this flag, only a preview is printed."
    ),
) -> None:
    """Bring an existing captures/ + outputs/ tree onto the lifecycle retention policy.

    Relaxed rule for the backlog: a finished PLY is enough — review status is
    not required, otherwise no legacy capture would ever qualify.

    Skips a capture that looks like it has an in-flight `add-video`/`resume`
    run — a reclaimable target or pipeline.log touched within the last hour
    (see `lifecycle.recently_active`). The old `output/scene.ply` keeps its
    stale mtime for the whole duration of such a rebuild while frames/colmap
    are rewritten from scratch, so reclaim eligibility alone can't tell a
    finished capture from one mid-rebuild.

    An `outputs/<name>` entry is only ever deleted when a capture of that
    name still exists AND that capture has its own exported PLY — otherwise
    it is the last surviving copy of a scene whose capture directory is gone
    (or never finished), and is kept, unconditionally, no matter how long it
    has sat there.

    Every capture and outputs entry this command looked at and chose not to
    touch is still listed in the preview, with a label saying why, rather
    than silently disappearing.
    """
    from autosplat import cleanup as cleanup_mod
    from autosplat import lifecycle

    cfg = _load_or_die(config)
    captures_dir = cfg.paths.captures_dir
    outputs_dir = cfg.export.outputs_dir
    now = datetime.now(UTC)

    _refuse_if_unsafe_storage_layout(captures_dir, outputs_dir)

    # Fixed, generous width rather than the ambient terminal size: capture
    # paths are long (nested legacy layouts especially) and truncating them
    # with an ellipsis defeats the point of a report the user must be able
    # to read in full. A real terminal narrower than this just soft-wraps.
    table_console = Console(width=200)
    table = Table(title="migrate-storage" + ("" if apply else " — preview (nothing is deleted)"))
    table.add_column("Path")
    table.add_column("What")
    table.add_column("Size", justify="right")

    total = 0
    skipped = 0  # deliberately-kept rows: active/failed captures, protected outputs/
    planned: list[tuple[Path, list[Path]]] = []

    capture_dirs = lifecycle.find_capture_dirs(captures_dir)

    # Deliberate last-wins on a basename collision (the real backlog has
    # repeated names, e.g. two unrelated captures both called
    # "2026-05-25_A_vor1" under different parents) — flagged below rather
    # than silently letting an outputs/<name> match resolve against
    # whichever capture happened to be enumerated last.
    capture_by_name: dict[str, Path] = {}
    duplicate_names: set[str] = set()
    for c in capture_dirs:
        if c.name in capture_by_name:
            duplicate_names.add(c.name)
        capture_by_name[c.name] = c

    for capture_dir in capture_dirs:
        rel = capture_dir.relative_to(captures_dir)
        ply = lifecycle.find_ply(capture_dir)
        if ply is None:
            # Failed/unfinished capture — colmap/rescue are still needed for
            # diagnosis or `resume`. Listed (not skipped silently) so the
            # user can see why it's absent from the reclaim total.
            skipped += 1
            table.add_row(str(rel), "[dim]failed — kept (no scene.ply)[/dim]", "—")
            continue

        raw_targets = lifecycle.reclaimable_targets(capture_dir)
        if not raw_targets:
            continue  # genuinely nothing there — nothing to explain
        protected = [t for t in raw_targets if _holds_ply(t, ply) or _contains_nested_export(t)]
        targets = [t for t in raw_targets if t not in protected]
        protected_note = (
            f" (kept: {_target_labels(capture_dir, protected)} — holds a nested capture)"
            if protected
            else ""
        )
        if not targets:
            # Something was there, but every single target is protected
            # (e.g. a nested capture buried in rescue/) — list it as kept,
            # by name, instead of letting the capture vanish from the table
            # with no explanation.
            skipped += 1
            table.add_row(str(rel), f"[dim]kept{protected_note}[/dim]", "—")
            continue
        size = lifecycle.bytes_in(targets)

        if lifecycle.recently_active(capture_dir, now=now):
            skipped += 1
            table.add_row(
                str(rel),
                f"[yellow]active — skipped (in-flight run)[/yellow]{protected_note}",
                _human_bytes(size),
            )
            continue

        total += size
        planned.append((capture_dir, targets))
        # A target can be protected even while others on this same capture
        # are reclaimed normally (a probe that succeeded sits next to
        # abandoned ones under rescue/) — protected_note names it instead
        # of letting it disappear from this row with no trace, which is
        # exactly what hid the round-2 regression until real data surfaced
        # it.
        table.add_row(
            str(rel), f"{_target_labels(capture_dir, targets)}{protected_note}", _human_bytes(size)
        )

    to_delete: list[Path] = []
    if outputs_dir.is_dir():
        for entry in sorted(outputs_dir.iterdir()):
            if entry.is_symlink() or not entry.is_dir():
                continue
            size = lifecycle.bytes_in([entry])
            owning_capture = capture_by_name.get(entry.name)
            if owning_capture is not None and lifecycle.find_ply(owning_capture) is not None:
                total += size
                to_delete.append(entry)
                table.add_row(f"outputs/{entry.name}", "duplicate — reclaimed", _human_bytes(size))
                continue
            skipped += 1
            reason = (
                "orphaned — kept (no capture holds this scene)"
                if owning_capture is None
                else "duplicate — kept (capture has no scene.ply yet)"
            )
            table.add_row(f"outputs/{entry.name}", f"[dim]{reason}[/dim]", _human_bytes(size))

    table_console.print(table)
    console.print(f"[bold]Reclaimable: {_human_bytes(total)}[/bold]")
    if skipped:
        console.print(
            "[dim]Sizes shown for kept/skipped rows above are informational only — "
            "they are excluded from Reclaimable.[/dim]"
        )
    if duplicate_names:
        console.print(
            f"[yellow]Warning:[/yellow] {len(duplicate_names)} capture name(s) appear more than "
            f"once under captures/ ({', '.join(sorted(duplicate_names))}) — outputs/ matching by "
            "name used whichever one was found last. An outputs/<name> entry may have been "
            "judged redundant (or kept) on the strength of the wrong same-named capture."
        )

    if not apply:
        console.print("Run again with [bold]--apply[/bold] to reclaim.")
        return

    reclaimed = 0
    failures = 0
    for capture_dir, targets in planned:
        try:
            result = cleanup_mod.prune_intermediates(capture_dir, targets=targets)
        except Exception as e:  # one failure must not stop the rest of the sweep
            console.print(f"[red]failed:[/red] {capture_dir} — {e}")
            failures += 1
            continue
        reclaimed += result.bytes_reclaimed
        if result.failed:
            failures += len(result.failed)
            for failed_target in result.failed:
                console.print(f"[red]failed:[/red] {failed_target}")
    for entry in to_delete:
        try:
            size = lifecycle.bytes_in([entry])
            shutil.rmtree(entry)
        except OSError as e:
            console.print(f"[red]failed:[/red] {entry} — {e}")
            failures += 1
            continue
        reclaimed += size

    console.print(
        f"[green]Reclaimed {_human_bytes(reclaimed)}[/green], "
        f"{skipped} skipped, {failures} failure(s)."
    )
    if failures:
        raise typer.Exit(EXIT_PIPELINE_FAILURE)


def _same_directory(a: Path, b: Path) -> bool:
    """True if `a` and `b` refer to the same directory on disk.

    Compares filesystem identity (`os.path.samefile` — device + inode)
    rather than string equality. `Path.resolve()` does NOT case-normalise on
    macOS's default APFS (case-insensitive but case-preserving): a config
    typo like `outputs_dir = "/Users/Johannes"` against a real
    `/Users/johannes` would compare unequal as strings while being the exact
    same directory on disk — `==` (or `os.path.normcase`, which is a no-op
    on POSIX platforms including macOS) would miss that; `samefile` doesn't.
    Falls back to plain equality only when one side doesn't exist yet
    (`samefile` requires both to), which is safe: there's nothing on disk
    yet for a nonexistent path to alias with.
    """
    try:
        return os.path.samefile(a, b)
    except OSError:
        return a == b


def _is_same_or_inside(outer: Path, inner: Path) -> bool:
    """True if `inner` is `outer` itself, or nested inside it — by
    filesystem identity (`_same_directory`), so this holds even across a
    case-insensitive filesystem alias."""
    if _same_directory(outer, inner):
        return True
    return any(_same_directory(outer, ancestor) for ancestor in inner.parents)


def _refuse_if_unsafe_storage_layout(captures_dir: Path, outputs_dir: Path) -> None:
    """Refuse rather than let a config typo turn `--apply` into an `rm -rf`.

    Every direct child of `outputs_dir` is a deletion candidate once it
    matches a fully-exported capture name, so a config where `outputs_dir`
    resolves to `captures_dir` itself (or an ancestor of it), to $HOME, or to
    a filesystem root would make this command delete far more than
    deprecated export copies. `config.py` documents "distinct from
    captures_dir" as an invariant on `export.outputs_dir`, but nothing
    enforced it before this check.
    """
    captures_resolved = captures_dir.resolve()
    outputs_resolved = outputs_dir.resolve()

    if _is_same_or_inside(outputs_resolved, captures_resolved):
        err_console.print(
            "[red]Refusing:[/red] paths.captures_dir "
            f"({captures_resolved}) is the same as, or inside, export.outputs_dir "
            f"({outputs_resolved}). migrate-storage would delete the captures tree "
            "itself while treating it as deprecated 'outputs/' copies."
        )
        raise typer.Exit(EXIT_USER_ERROR)

    home_resolved = Path.home().resolve()
    if (
        _same_directory(outputs_resolved, home_resolved)
        or outputs_resolved == outputs_resolved.parent
    ):
        err_console.print(
            f"[red]Refusing:[/red] export.outputs_dir ({outputs_resolved}) resolves to your "
            "home directory or a filesystem root — deleting its children would be catastrophic."
        )
        raise typer.Exit(EXIT_USER_ERROR)


def _holds_ply(target: Path, ply: Path) -> bool:
    """True if `target` is, or contains, the capture's own published PLY.

    Structurally this can't currently happen — `lifecycle.find_ply` only
    ever returns `output/scene.ply`, a top-level `scene.ply`, or a glob
    match directly in `capture_dir`, none of which sit inside a named
    `RECLAIMABLE_SUBDIRS` target — but the capture's own PLY is exactly the
    one thing this command must never delete, so the check stays explicit
    rather than resting entirely on that structural coincidence.
    """
    return ply == target or target in ply.parents


def _contains_nested_export(target: Path) -> bool:
    """True if `target` holds a directory that has produced an exported
    result of its own — `output/scene.ply`, or a top-level `scene.ply`.

    Deliberately NOT `lifecycle.is_capture_dir`'s full signature (which also
    matches a directory holding just `frames/` + `colmap/`, no PLY) — that
    is exactly the shape `bisection._probe_workspace_for` writes for every
    bisection probe, and an abandoned probe workspace is pure intermediate,
    not a result worth protecting. Round 2 reused `is_capture_dir` wholesale
    and it silently withheld 3.1 GB of probe workspaces under `rescue/`,
    diverging from `cleanup-intermediates`/`sweep_expired` (which still
    reclaim them) exactly the way a loose `training/scene.ply` diverged
    before that. `lifecycle.is_capture_dir` itself is intentionally left
    alone here — it answers a different question (what `find_capture_dirs`
    should treat as a capture) and `find_capture_dirs` needs its current,
    broader behaviour (an unfinished capture still counts, for `resume`).

    What must actually stay protected is a genuinely nested capture that
    produced a real result — a complete sub-reconstruction buried one or
    more levels inside what is otherwise a reclaimable subdir of some
    *other* capture (e.g. a successful rescue probe under `rescue/`).
    `find_capture_dirs` deliberately does not surface that nested capture on
    its own (its whole subtree is reclaimed as one unit for the *outer*
    capture otherwise), so this is what actually holds at the deletion
    site: filtering `reclaimable_targets` by it, then passing the filtered
    list through to `cleanup.prune_intermediates(..., targets=...)` instead
    of letting that function re-derive an unfiltered list.
    """
    for p in target.rglob("*"):
        if not p.is_dir():
            continue
        if (p / "output" / "scene.ply").exists() or (p / "scene.ply").exists():
            return True
    return False


def _target_labels(capture_dir: Path, targets: list[Path]) -> str:
    """Name reclaim targets by their path relative to the capture.

    A bare `.name` is ambiguous now that targets can be nested: `share/_tmp`
    and `rescue/probes` would both read as a single opaque leaf ("_tmp",
    "probes") in a table whose whole purpose is telling the user exactly what
    is about to be deleted.
    """
    return ", ".join(t.relative_to(capture_dir).as_posix() for t in targets)


def _human_bytes(n: int) -> str:
    size = float(n)
    for unit in ("B", "KB", "MB"):
        if size < 1024:
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} GB"


@app.command()
def watch(
    folder: Path = typer.Argument(..., help="Folder to watch for new videos."),
    config: Path | None = typer.Option(None, "--config", "-c"),
    once: bool = typer.Option(False, "--once", help="Process existing files, then exit."),
) -> None:
    """Start the watch-folder daemon. Sequential processing; one capture at a time."""
    cfg = _load_or_die(config)
    configure_logging(level=cfg.logging.level, console=cfg.logging.console)

    state = WatcherState.load()
    recovered = recover_state(state, retry_cfg=cfg.retry)
    if recovered:
        console.print(
            f"[yellow]Recovered {recovered} in-progress entry from previous run.[/yellow]"
        )

    def _process(video: Path, *, config_override: dict[str, Any] | None = None) -> dict[str, Any]:
        if config_override:
            console.print(f"[blue]Processing (retry, override={config_override}):[/blue] {video}")
        else:
            console.print(f"[blue]Processing:[/blue] {video}")
        result = run_pipeline(video, cfg, config_override=config_override, state=state)
        return {"output_ply": str(result.output_ply), "duration_s": result.duration_s}

    daemon = WatchDaemon(folder, state, _process, retry_cfg=cfg.retry, status_cfg=cfg.status)
    daemon.start(process_existing=True)

    if once:
        daemon.wait_until_idle(timeout=None)
        daemon.stop()
        return

    console.print(f"[cyan]Watching:[/cyan] {folder} (Ctrl-C to stop)")
    try:
        daemon.wait_for_shutdown()
    finally:
        console.print("[yellow]Stopping watcher...[/yellow]")
        daemon.stop()


@app.command()
def status() -> None:
    """Show the watcher queue, recent completed runs, and any failures."""
    if not STATE_FILE.exists():
        console.print("[dim]No state file yet — nothing to show.[/dim]")
        return

    state = WatcherState.load()

    if state.in_progress:
        console.print(
            f"[yellow]In progress:[/yellow] {state.in_progress.path} "
            f"(stage: {state.in_progress.stage}, started: {state.in_progress.started_at})"
        )
    else:
        console.print("[dim]No active run.[/dim]")

    if state.queue:
        console.print(f"[cyan]Queue ({len(state.queue)}):[/cyan]")
        for q in state.queue:
            console.print(f"  • {q}")

    if state.completed:
        table = Table(title="Recent completed", show_lines=False)
        table.add_column("Video")
        table.add_column("Output")
        table.add_column("Duration", justify="right")
        table.add_column("Finished")
        for run in state.completed[-10:]:
            table.add_row(
                run.path,
                run.output_ply or "—",
                f"{run.duration_s:.1f}s",
                run.finished_at,
            )
        console.print(table)

    if state.failed:
        table = Table(title="Recent failures", show_lines=False, style="red")
        table.add_column("Video")
        table.add_column("Stage")
        table.add_column("Reason", overflow="fold")
        table.add_column("Failed at")
        for failed_run in state.failed[-10:]:
            table.add_row(
                failed_run.path, failed_run.stage or "—", failed_run.reason, failed_run.failed_at
            )
        console.print(table)


@config_app.command("show")
def config_show(config_path: Path | None = typer.Option(None, "--config", "-c")) -> None:
    """Print the effective config after layering defaults + user overrides."""
    cfg = _load_or_die(config_path)
    console.print(cfg.model_dump_json(indent=2))


@config_app.command("init")
def config_init(
    target: Path = typer.Option(XDG_CONFIG_PATH, "--target", "-t", help="Output path."),
    force: bool = typer.Option(False, "--force", help="Overwrite existing file."),
) -> None:
    """Write the default config to ~/.config/autosplat/config.toml (or --target)."""
    target = target.expanduser()
    if target.exists() and not force:
        err_console.print(f"[red]Refusing to overwrite[/red] {target} (use --force).")
        raise typer.Exit(EXIT_USER_ERROR)
    dump_default_config(target)
    console.print(f"[green]Wrote default config to[/green] {target}")


@app.command()
def doctor(config: Path | None = typer.Option(None, "--config", "-c")) -> None:
    """Run preflight checks for ffmpeg, colmap, brush, and the platform."""
    cfg = _load_or_die(config)
    configure_logging(level=cfg.logging.level, console=cfg.logging.console)

    results = run_doctor(cfg)
    table = Table(title="autosplat doctor", show_lines=False)
    table.add_column("Check")
    table.add_column("Status")
    table.add_column("Detail", overflow="fold")
    for r in results:
        status_color = "green" if r.ok else ("red" if r.required else "yellow")
        table.add_row(r.name, f"[{status_color}]{r.status_emoji}[/{status_color}]", r.detail)
    console.print(table)

    if not all_required_passed(results):
        raise typer.Exit(EXIT_DEP_MISSING)


@app.command()
def compress(
    ply: Path = typer.Argument(..., help="PLY file to compress."),
    fmt: str = typer.Option("sog", "--format", "-f", help="Target format: sog | spz | ksplat."),
    quality: str = typer.Option("medium", "--quality", "-q", help="low | medium | high."),
    output_dir: Path | None = typer.Option(
        None, "--output-dir", "-o", help="Defaults to the PLY's own directory."
    ),
) -> None:
    """Compress a Brush PLY into a web-optimal splat format (Phase 5 skeleton).

    Requires an installed backend (`splat-transform`, `spz`, or `ksplat-compress`).
    Run `autosplat doctor` to see which are detected on your system.
    """
    if not ply.exists():
        err_console.print(f"[red]PLY not found:[/red] {ply}")
        raise typer.Exit(EXIT_USER_ERROR)
    if fmt not in ("sog", "spz", "ksplat"):
        err_console.print(f"[red]Unknown format:[/red] {fmt}")
        raise typer.Exit(EXIT_USER_ERROR)

    target_dir = output_dir or ply.parent
    try:
        result = compress_ply(ply, target_dir, fmt=fmt, quality=quality)  # type: ignore[arg-type]
    except CompressorNotAvailable as e:
        err_console.print(f"[yellow]No compressor available:[/yellow] {e}")
        err_console.print(install_hint_for(fmt))  # type: ignore[arg-type]
        raise typer.Exit(EXIT_DEP_MISSING) from e
    except (FileNotFoundError, RuntimeError) as e:
        err_console.print(f"[red]Compress failure:[/red] {e}")
        raise typer.Exit(EXIT_PIPELINE_FAILURE) from e

    console.print(f"[green]Done:[/green] {result.output_path}")
    console.print(f"[dim]Backend:[/dim] {result.backend_used}")
    console.print(f"[dim]Duration:[/dim] {result.duration_s:.1f}s")


@app.command()
def serve(
    capture_dir: Path = typer.Argument(
        ..., help="Directory containing scene.ply (output of a pipeline run)."
    ),
    with_supersplat: bool = typer.Option(
        False, "--with-supersplat", help="Also start local SuperSplat server."
    ),
    ply_port: int | None = typer.Option(
        None, "--ply-port", help="PLY server port (default from config)."
    ),
    supersplat_port: int | None = typer.Option(
        None, "--supersplat-port", help="SuperSplat server port (default from config)."
    ),
    no_open_browser: bool = typer.Option(
        False, "--no-open-browser", help="Don't open browser automatically."
    ),
    config: Path | None = typer.Option(None, "--config", "-c", help="Override config file."),
) -> None:
    """Serve a PLY capture in the browser (optionally with local SuperSplat)."""
    cfg = _load_or_die(config)

    ply = _find_ply(capture_dir)
    if ply is None:
        console.print(f"[red]No .ply file found in {capture_dir}[/red]")
        raise typer.Exit(EXIT_USER_ERROR)

    effective_ply_port = ply_port or cfg.viewer.local_http_port
    effective_ss_port = supersplat_port or cfg.viewer.supersplat_local_port

    import signal
    import threading

    stop_event = threading.Event()

    def _handle_signal(signum: int, frame: object) -> None:
        stop_event.set()

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    if with_supersplat:
        dist_path = cfg.viewer.supersplat_dist_path
        if not dist_path.is_absolute():
            dist_path = Path.cwd() / dist_path
        if not (dist_path / "index.html").exists():
            console.print(
                f"[red]SuperSplat dist not found at {dist_path}. Run: bash scripts/setup_supersplat.sh[/red]"
            )
            raise typer.Exit(EXIT_USER_ERROR)

        # v1.4.5 — share the local-serve-and-block helper with the auto-open
        # path that runs at the end of `process` / `rescue`. The CLI passes
        # its own stop_event so SIGINT is handled by the existing signal-
        # handler installed above (no duplicate handlers).
        try:
            viewer_mod._serve_local_and_block(
                ply,
                cfg.viewer.model_copy(
                    update={
                        "local_http_port": effective_ply_port,
                        "supersplat_local_port": effective_ss_port,
                    }
                ),
                dist_path,
                stop_event,
                open_browser=not no_open_browser,
            )
        except RuntimeError as exc:
            err_console.print(f"[red]{exc}[/red]")
            raise typer.Exit(EXIT_USER_ERROR) from None
    else:
        try:
            with viewer_mod.serve_directory(ply.parent, effective_ply_port) as ply_base:
                ply_url = f"{ply_base}/{ply.name}"
                # v1.4.3 — opening ply_url directly triggers a browser
                # download (.ply has no MIME handler). Route through the
                # remote SuperSplat editor with ?load=<our-server-url>.
                viewer_url = _remote_supersplat_url_for(ply_url)
                if not no_open_browser:
                    webbrowser.open(viewer_url)
                console.print(f"[green]Viewer:[/green] {viewer_url}")
                console.print(f"[green]PLY server:[/green] {ply_url}")
                console.print("Press Ctrl+C to stop.")
                while not stop_event.wait(timeout=1.0):
                    pass
        except RuntimeError as exc:
            err_console.print(f"[red]{exc}[/red]")
            raise typer.Exit(EXIT_USER_ERROR) from None


@app.command()
def webui(
    host: str = typer.Option("127.0.0.1", "--host", help="Bind address."),
    port: int = typer.Option(8080, "--port", "-p", help="HTTP port."),
    reload: bool = typer.Option(False, "--reload", help="Enable auto-reload (dev mode)."),
    config: Path | None = typer.Option(None, "--config", "-c", help="Override config file."),
) -> None:
    """Start the autosplat WebUI (FastAPI + HTMX). Check http://HOST:PORT/healthz to verify."""
    import uvicorn

    from .webui import create_app

    cfg = _load_or_die(config)
    app_instance = create_app(cfg)
    uvicorn.run(app_instance, host=host, port=port, reload=reload)


@app.command(name="app")
def app_launcher() -> None:
    """Launch the AutoSplat desktop app (menubar + browser WebUI).

    Same entry the bundled AutoSplat.app uses: runs first-run setup if external
    tools are missing, serves the WebUI, opens the browser, and shows a menubar.
    """
    from .desktop import main as desktop_main

    desktop_main()


@app.command()
def version() -> None:
    """Print the autosplat version."""
    console.print(__version__)


def main() -> None:  # pragma: no cover
    """Allow `python -m autosplat`."""
    app()


if __name__ == "__main__":  # pragma: no cover
    main()
