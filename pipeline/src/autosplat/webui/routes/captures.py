# SPDX-License-Identifier: AGPL-3.0-or-later

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse

from autosplat import __version__
from autosplat.webui.state import get_capture, list_captures, read_log_tail

router = APIRouter(prefix="/captures")


def _templates(request: Request):  # type: ignore[return]
    return request.app.state.templates


def _captures_dir(request: Request):
    cfg = request.app.state.cfg
    if cfg is None:
        raise HTTPException(status_code=503, detail="Config not loaded")
    return cfg.paths.captures_dir


@router.get("/", response_class=HTMLResponse)
async def captures_list(request: Request) -> HTMLResponse:
    captures_dir = _captures_dir(request)
    captures = list_captures(captures_dir)
    return _templates(request).TemplateResponse(
        request,
        "capture/list.html",
        {"version": __version__, "captures": captures, "captures_dir": str(captures_dir)},
    )


@router.get("/{capture_id}", response_class=HTMLResponse)
async def capture_detail(request: Request, capture_id: str) -> HTMLResponse:
    captures_dir = _captures_dir(request)
    capture = get_capture(captures_dir, capture_id)
    if capture is None:
        raise HTTPException(status_code=404, detail=f"Capture '{capture_id}' not found")
    return _templates(request).TemplateResponse(
        request,
        "capture/detail.html",
        {"version": __version__, "capture": capture},
    )


@router.get("/{capture_id}/log")
async def capture_log(request: Request, capture_id: str) -> JSONResponse:
    captures_dir = _captures_dir(request)
    capture = get_capture(captures_dir, capture_id)
    if capture is None:
        raise HTTPException(status_code=404, detail=f"Capture '{capture_id}' not found")
    lines = read_log_tail(capture.path)
    return JSONResponse({"lines": lines})


@router.get("/{capture_id}/ply")
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


@router.post("/{capture_id}/cancel")
async def capture_cancel(request: Request, capture_id: str) -> RedirectResponse:
    """Stub: cancel in-progress job. Full cancel wired in P3."""
    job_runner = getattr(request.app.state, "job_runner", None)
    if job_runner is not None:
        await job_runner.cancel_job(capture_id)
    return RedirectResponse(url=f"/captures/{capture_id}", status_code=303)
