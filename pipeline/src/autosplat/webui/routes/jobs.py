# SPDX-License-Identifier: AGPL-3.0-or-later

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from autosplat import __version__

router = APIRouter(prefix="/jobs")


def _templates(request: Request):  # type: ignore[return]
    return request.app.state.templates


def _split_jobs(request: Request) -> tuple[list, list]:
    runner = getattr(request.app.state, "job_runner", None)
    if runner is None:
        return [], []
    jobs = runner.all_jobs()
    active = [j for j in jobs if j.status in ("queued", "running")]
    recent = [j for j in jobs if j.status in ("done", "failed", "cancelled")][-20:]
    return active, recent


@router.get("/", response_class=HTMLResponse)
async def jobs_view(request: Request) -> HTMLResponse:
    active, recent = _split_jobs(request)
    return _templates(request).TemplateResponse(
        request,
        "jobs.html",
        {"version": __version__, "active_jobs": active, "recent_jobs": recent},
    )
