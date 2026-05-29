# SPDX-License-Identifier: AGPL-3.0-or-later

import shutil
import subprocess
from pathlib import Path

from fastapi import APIRouter, Form, HTTPException, Request, Response
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from autosplat import __version__
from autosplat.failure import classify_failure, failure_reason_from_log
from autosplat.webui.jobs_runner import JobRunner
from autosplat.webui.state import (
    get_capture,
    last_activity_age_s,
    list_captures,
    read_log_tail,
)

router = APIRouter(prefix="/captures")


def _templates(request: Request) -> Jinja2Templates:
    templates: Jinja2Templates = request.app.state.templates
    return templates


def _captures_dir(request: Request) -> Path:
    cfg = request.app.state.cfg
    if cfg is None:
        raise HTTPException(status_code=503, detail="Config not loaded")
    captures_dir: Path = cfg.paths.captures_dir
    return captures_dir


def _job_runner(request: Request) -> JobRunner | None:
    runner: JobRunner | None = getattr(request.app.state, "job_runner", None)
    return runner


@router.get("/", response_class=HTMLResponse)
async def captures_list(request: Request) -> HTMLResponse:
    captures_dir = _captures_dir(request)
    captures = list_captures(captures_dir, _job_runner(request))
    active = next((c for c in captures if c.status == "running"), None)
    stats = {
        "total": len(captures),
        "done": sum(1 for c in captures if c.status == "done"),
        "running": 1 if active else 0,
        "failed": sum(1 for c in captures if c.status == "failed"),
    }
    return _templates(request).TemplateResponse(
        request,
        "capture/list.html",
        {
            "captures": captures,
            "captures_dir": str(captures_dir),
            "stats": stats,
            "active_capture": active,
        },
    )


@router.get("/new", response_class=HTMLResponse)
async def capture_new_form(request: Request) -> HTMLResponse:
    """Render the form for starting a pipeline run from a video file path."""
    return _templates(request).TemplateResponse(
        request, "capture/new.html", {"version": __version__}
    )


_VIDEO_SUFFIXES = {".mp4", ".mov", ".m4v"}


def _validate_video_paths(raw_paths: list[str]) -> tuple[list[Path], str | None]:
    """Parse and validate a list of user-supplied paths. Returns (videos, error)."""
    cleaned = [p.strip() for p in raw_paths if p.strip()]
    if not cleaned:
        return [], "Please enter at least one video file path."
    videos: list[Path] = []
    for raw in cleaned:
        v = Path(raw).expanduser()
        if not v.is_file():
            return [], f"No file found at: {v}"
        if v.suffix.lower() not in _VIDEO_SUFFIXES:
            return [], f"Unsupported file type '{v.suffix}' — use .mp4, .mov or .m4v."
        videos.append(v)
    return videos, None


# AppleScript: open a native Finder picker filtered to video files, allow
# multiple selections, and emit one POSIX path per line. `activate` pulls the
# dialog to the foreground so it doesn't open behind the browser window.
_PICK_FILE_SCRIPT = (
    'tell application "System Events" to activate\n'
    "set chosenFiles to choose file "
    'with prompt "Choose video(s) for autosplat" '
    'of type {"mp4", "mov", "m4v"} '
    "with multiple selections allowed\n"
    'set out to ""\n'
    "repeat with f in chosenFiles\n"
    "    set out to out & POSIX path of f & linefeed\n"
    "end repeat\n"
    "return out"
)


def _pick_files_via_finder() -> list[Path]:
    """Open the native macOS Finder file picker and return the chosen paths.

    Returns an empty list if the user cancels (osascript exits non-zero) or if
    osascript is unavailable. The WebUI is Mac-Silicon-only by design, so the
    server always runs on the same Mac whose Finder dialog this opens.
    """
    try:
        result = subprocess.run(
            ["osascript", "-e", _PICK_FILE_SCRIPT],
            capture_output=True,
            text=True,
            timeout=300,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    if result.returncode != 0:
        return []
    return [Path(line) for line in result.stdout.splitlines() if line.strip()]


@router.post("/pick-file")
async def capture_pick_file(request: Request) -> JSONResponse:
    """Open a native Finder picker and return the chosen absolute path(s).

    A browser `<input type="file">` only yields the bare filename, never the
    absolute path the pipeline needs, so the New-capture form calls this local
    endpoint instead. Returns ``{"paths": [...]}`` (empty list if cancelled).
    """
    paths = _pick_files_via_finder()
    return JSONResponse({"paths": [str(p) for p in paths]})


@router.post("/new")
async def capture_new_submit(
    request: Request,
    video_path: str = Form(""),
    video_paths: str = Form(""),
) -> Response:
    """Validate the submitted video path(s) and launch a new pipeline run.

    `video_paths` (newline-separated, multi-video) takes precedence over the
    legacy single-line `video_path` so v1.2.0 forms still work unchanged.
    """
    raw_lines = (
        [line for line in video_paths.splitlines() if line.strip()]
        if video_paths.strip()
        else [video_path]
    )
    videos, error = _validate_video_paths(raw_lines)
    if error is not None:
        return _templates(request).TemplateResponse(
            request,
            "capture/new.html",
            {
                "version": __version__,
                "error": error,
                "video_paths": video_paths or video_path,
            },
            status_code=400,
        )

    job_runner = getattr(request.app.state, "job_runner", None)
    if job_runner is None:
        raise HTTPException(status_code=503, detail="Job runner not available")
    payload: Path | list[Path] = videos if len(videos) > 1 else videos[0]
    job = await job_runner.start_job_from_video(payload, request.app.state.cfg)
    return RedirectResponse(url=f"/captures/{job.capture_id}", status_code=303)


@router.get("/{capture_id}", response_class=HTMLResponse)
async def capture_detail(request: Request, capture_id: str) -> HTMLResponse:
    captures_dir = _captures_dir(request)
    capture = get_capture(captures_dir, capture_id, _job_runner(request))
    if capture is None:
        raise HTTPException(status_code=404, detail=f"Capture '{capture_id}' not found")
    log_lines: list[str] = []
    if capture.has_log and capture.status != "running":
        log_lines = read_log_tail(capture.path, max_lines=40)

    failure = None
    failure_reason = None
    if capture.status == "failed":
        failure_reason = capture.reason or failure_reason_from_log(capture.path)
        failure = classify_failure(failure_reason, capture.stage)

    return _templates(request).TemplateResponse(
        request,
        "capture/detail.html",
        {
            "version": __version__,
            "capture": capture,
            "log_lines": log_lines,
            "age_s": last_activity_age_s(capture.path),
            "failure": failure,
            "failure_reason": failure_reason,
        },
    )


@router.get("/{capture_id}/view", response_class=HTMLResponse)
async def capture_view(request: Request, capture_id: str) -> HTMLResponse:
    captures_dir = _captures_dir(request)
    capture = get_capture(captures_dir, capture_id, _job_runner(request))
    if capture is None:
        raise HTTPException(status_code=404, detail=f"Capture '{capture_id}' not found")

    # Check if SuperSplat is mounted (app.mount sets it in app.routes)
    supersplat_available = any(getattr(r, "name", None) == "supersplat" for r in request.app.routes)

    # Build the iframe embed URL — SuperSplat loads the PLY via ?load=
    embed_url = ""
    if supersplat_available and capture.has_ply:
        # Absolute URL so the iframe can resolve the PLY route correctly
        base = str(request.base_url).rstrip("/")
        embed_url = f"{base}/supersplat/index.html?load={base}/captures/{capture_id}/scene.ply"

    return _templates(request).TemplateResponse(
        request,
        "capture/view.html",
        {
            "version": __version__,
            "capture": capture,
            "supersplat_available": supersplat_available,
            "embed_url": embed_url,
        },
    )


@router.get("/{capture_id}/log")
async def capture_log(request: Request, capture_id: str) -> JSONResponse:
    captures_dir = _captures_dir(request)
    capture = get_capture(captures_dir, capture_id)
    if capture is None:
        raise HTTPException(status_code=404, detail=f"Capture '{capture_id}' not found")
    lines = read_log_tail(capture.path)
    return JSONResponse({"lines": lines})


# Served at a `.ply`-suffixed URL so the embedded SuperSplat viewer can detect
# the file type from the URL extension (it has no `.ply` to parse otherwise —
# closes SF-PIPE-1). The `.ply` suffix also gives browser downloads a real name.
@router.get("/{capture_id}/scene.ply")
async def capture_ply(request: Request, capture_id: str) -> FileResponse:
    captures_dir = _captures_dir(request)
    capture = get_capture(captures_dir, capture_id)
    if capture is None or not capture.has_ply or capture.ply_path is None:
        raise HTTPException(status_code=404, detail="PLY not found")
    return FileResponse(
        capture.ply_path,
        media_type="application/octet-stream",
        headers={
            "Access-Control-Allow-Origin": "*",
            "Accept-Ranges": "bytes",
        },
    )


@router.post("/{capture_id}/process")
async def capture_process(request: Request, capture_id: str) -> RedirectResponse:
    """Stub: enqueue capture for processing. Full job runner wired in P3."""
    captures_dir = _captures_dir(request)
    capture = get_capture(captures_dir, capture_id)
    if capture is None:
        raise HTTPException(status_code=404, detail=f"Capture '{capture_id}' not found")
    job_runner = getattr(request.app.state, "job_runner", None)
    if job_runner is not None:
        await job_runner.start_job(capture_id, capture.path, request.app.state.cfg)
    return RedirectResponse(url=f"/captures/{capture_id}", status_code=303)


@router.post("/{capture_id}/add-video")
async def capture_add_video(
    request: Request,
    capture_id: str,
    video_path: str = Form(...),
) -> Response:
    """Append another source video to an existing capture and rebuild.

    Same `add_video_to_capture` machinery as the `autosplat add-video` CLI,
    just wrapped in a JobRunner thread so the request returns immediately.
    """
    captures_dir = _captures_dir(request)
    capture = get_capture(captures_dir, capture_id, _job_runner(request))
    if capture is None:
        raise HTTPException(status_code=404, detail=f"Capture '{capture_id}' not found")

    raw = video_path.strip()
    video = Path(raw).expanduser() if raw else None
    error: str | None = None
    if not raw:
        error = "Please enter a video file path."
    elif video is None or not video.is_file():
        error = f"No file found at: {video}"
    elif video.suffix.lower() not in _VIDEO_SUFFIXES:
        error = f"Unsupported file type '{video.suffix}' — use .mp4, .mov or .m4v."

    if error is not None:
        # Re-render the detail page with an error banner instead of redirecting,
        # so the user keeps the form state and immediately sees what to fix.
        log_lines: list[str] = []
        return _templates(request).TemplateResponse(
            request,
            "capture/detail.html",
            {
                "version": __version__,
                "capture": capture,
                "log_lines": log_lines,
                "add_video_error": error,
                "add_video_path": raw,
            },
            status_code=400,
        )

    job_runner = getattr(request.app.state, "job_runner", None)
    if job_runner is None:
        raise HTTPException(status_code=503, detail="Job runner not available")
    await job_runner.start_add_video_job(capture_id, capture.path, video, request.app.state.cfg)
    return RedirectResponse(url=f"/captures/{capture_id}", status_code=303)


@router.post("/{capture_id}/resume")
async def capture_resume(request: Request, capture_id: str) -> RedirectResponse:
    """Continue a previous capture from on-disk state via resume_capture.

    Uses the same stage-skipping + adaptive-retry logic as `autosplat resume`,
    just wrapped in a background JobRunner thread so the WebUI stays responsive.
    """
    captures_dir = _captures_dir(request)
    capture = get_capture(captures_dir, capture_id, _job_runner(request))
    if capture is None:
        raise HTTPException(status_code=404, detail=f"Capture '{capture_id}' not found")
    job_runner = getattr(request.app.state, "job_runner", None)
    if job_runner is None:
        raise HTTPException(status_code=503, detail="Job runner not available")
    await job_runner.start_resume_job(capture_id, capture.path, request.app.state.cfg)
    return RedirectResponse(url=f"/captures/{capture_id}", status_code=303)


@router.post("/{capture_id}/cancel")
async def capture_cancel(request: Request, capture_id: str) -> RedirectResponse:
    """Stub: cancel in-progress job. Full cancel wired in P3."""
    job_runner = getattr(request.app.state, "job_runner", None)
    if job_runner is not None:
        await job_runner.cancel_job(capture_id)
    return RedirectResponse(url=f"/captures/{capture_id}", status_code=303)


@router.post("/{capture_id}/delete")
async def capture_delete(request: Request, capture_id: str) -> RedirectResponse:
    captures_dir = _captures_dir(request)
    capture = get_capture(captures_dir, capture_id, _job_runner(request))
    if capture is None:
        raise HTTPException(status_code=404, detail=f"Capture '{capture_id}' not found")
    if capture.status == "running":
        raise HTTPException(status_code=409, detail="Cannot delete a running capture")
    shutil.rmtree(capture.path, ignore_errors=True)
    return RedirectResponse(url="/captures/", status_code=303)
