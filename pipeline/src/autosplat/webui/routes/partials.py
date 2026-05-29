# SPDX-License-Identifier: AGPL-3.0-or-later

from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse

from autosplat.progress import read_progress
from autosplat.webui.progress_view import build_progress_view
from autosplat.webui.state import get_capture, list_captures, read_log_tail

router = APIRouter(prefix="/partials")


def _templates(request: Request):  # type: ignore[return]
    return request.app.state.templates


def _captures_dir(request: Request):
    cfg = request.app.state.cfg
    if cfg is None:
        raise HTTPException(status_code=503, detail="Config not loaded")
    return cfg.paths.captures_dir


def _job_runner(request: Request):
    return getattr(request.app.state, "job_runner", None)


@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard_partial(request: Request) -> HTMLResponse:
    captures_dir = _captures_dir(request)
    captures = list_captures(captures_dir, _job_runner(request))
    active = next((c for c in captures if c.status == "running"), None)
    queued = [c for c in captures if c.status == "queued"]
    recent = [c for c in captures if c.status in ("done", "failed")][:10]
    stats = {
        "total": len(captures),
        "done": sum(1 for c in captures if c.status == "done"),
        "running": 1 if active else 0,
        "failed": sum(1 for c in captures if c.status == "failed"),
    }
    return _templates(request).TemplateResponse(
        request,
        "partials/dashboard_inner.html",
        {"active_capture": active, "queued": queued, "recent": recent, "stats": stats},
    )


@router.get("/jobs", response_class=HTMLResponse)
async def jobs_partial(request: Request) -> HTMLResponse:
    runner = getattr(request.app.state, "job_runner", None)
    if runner is None:
        active, recent = [], []
    else:
        jobs = runner.all_jobs()
        active = [j for j in jobs if j.status in ("queued", "running")]
        recent = [j for j in jobs if j.status in ("done", "failed", "cancelled")][-20:]
    return _templates(request).TemplateResponse(
        request,
        "partials/jobs_inner.html",
        {"active_jobs": active, "recent_jobs": recent},
    )


@router.get("/captures", response_class=HTMLResponse)
async def captures_list_partial(request: Request) -> HTMLResponse:
    captures_dir = _captures_dir(request)
    from autosplat.webui.state import list_captures as _list

    captures = _list(captures_dir, _job_runner(request))
    return _templates(request).TemplateResponse(
        request,
        "partials/captures_list_inner.html",
        {"captures": captures, "captures_dir": captures_dir},
    )


@router.get("/capture/{capture_id}/status", response_class=HTMLResponse)
async def capture_status_partial(request: Request, capture_id: str) -> HTMLResponse:
    captures_dir = _captures_dir(request)
    capture = get_capture(captures_dir, capture_id, _job_runner(request))
    if capture is None:
        raise HTTPException(status_code=404, detail=f"Capture '{capture_id}' not found")
    return _templates(request).TemplateResponse(
        request,
        "partials/capture_status.html",
        {"capture": capture},
    )


@router.get("/capture/{capture_id}/log", response_class=HTMLResponse)
async def capture_log_partial(request: Request, capture_id: str) -> HTMLResponse:
    captures_dir = _captures_dir(request)
    capture = get_capture(captures_dir, capture_id)
    if capture is None:
        raise HTTPException(status_code=404, detail=f"Capture '{capture_id}' not found")
    lines = read_log_tail(capture.path, max_lines=40) if capture.has_log else []
    rows = (
        "".join(
            f'<div class="as-log-row info"><span class="msg">{line}</span></div>' for line in lines
        )
        or '<div class="as-log-row info"><span class="msg">— no log entries —</span></div>'
    )
    return HTMLResponse(content=rows)


@router.get("/capture/{capture_id}/brush", response_class=HTMLResponse)
async def capture_brush_partial(request: Request, capture_id: str) -> HTMLResponse:
    captures_dir = _captures_dir(request)
    capture = get_capture(captures_dir, capture_id)
    if capture is None:
        raise HTTPException(status_code=404, detail=f"Capture '{capture_id}' not found")
    state = read_progress(capture.path)
    progress = build_progress_view(state, datetime.now(UTC)) if state else None
    return _templates(request).TemplateResponse(
        request,
        "partials/brush_metrics.html",
        {"capture": capture, "progress": progress},
    )
