# SPDX-License-Identifier: AGPL-3.0-or-later

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse

from autosplat import __version__
from autosplat.webui.state import get_capture, list_captures

router = APIRouter(prefix="/partials")


def _templates(request: Request):  # type: ignore[return]
    return request.app.state.templates


def _captures_dir(request: Request):
    cfg = request.app.state.cfg
    if cfg is None:
        raise HTTPException(status_code=503, detail="Config not loaded")
    return cfg.paths.captures_dir


@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard_partial(request: Request) -> HTMLResponse:
    captures_dir = _captures_dir(request)
    captures = list_captures(captures_dir)
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


@router.get("/capture/{capture_id}/status", response_class=HTMLResponse)
async def capture_status_partial(request: Request, capture_id: str) -> HTMLResponse:
    captures_dir = _captures_dir(request)
    capture = get_capture(captures_dir, capture_id)
    if capture is None:
        raise HTTPException(status_code=404, detail=f"Capture '{capture_id}' not found")
    return _templates(request).TemplateResponse(
        request,
        "partials/capture_status.html",
        {"capture": capture},
    )
