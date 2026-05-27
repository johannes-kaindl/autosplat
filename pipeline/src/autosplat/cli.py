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

import webbrowser
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from . import __version__
from . import viewer as viewer_mod
from .bisection import rescue_via_bisection
from .compress import CompressorNotAvailable, compress_ply, install_hint_for
from .config import XDG_CONFIG_PATH, apply_override, dump_default_config, load_config
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


def _load_or_die(config_path: Path | None) -> object:
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


def _open_viewer_if_configured(output_ply: Path, cfg: object) -> None:
    """Open the result in the configured viewer, blocking on a local PLY
    server until Ctrl-C. Called by process/resume/add-video/rescue *after*
    the Done summary so the user sees the result first.

    v1.4.2 — moved out of `pipeline.run_pipeline` because the new
    blocking-server behaviour would stall the watch-folder daemon and the
    WebUI's JobRunner between captures. Only CLI commands open the viewer.
    """
    # cfg is typed as `object` because _load_or_die returns object — viewer
    # access is field-by-field so mypy can resolve it via runtime attrs.
    if not cfg.viewer.auto_open or cfg.viewer.target == "none":  # type: ignore[attr-defined]
        return
    viewer_mod.open_in_viewer(output_ply, cfg.viewer)  # type: ignore[attr-defined]


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

    import shutil

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

    def _process(video: Path, *, config_override: dict | None = None) -> dict:
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
        for run in state.failed[-10:]:
            table.add_row(run.path, run.stage or "—", run.reason, run.failed_at)
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


@app.command()
def version() -> None:
    """Print the autosplat version."""
    console.print(__version__)


def main() -> None:  # pragma: no cover
    """Allow `python -m autosplat`."""
    app()


if __name__ == "__main__":  # pragma: no cover
    main()
