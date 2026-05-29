# SPDX-License-Identifier: AGPL-3.0-or-later

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from autosplat import __version__
from autosplat.webui.jobs_runner import JobState

router = APIRouter(prefix="/jobs")


def _templates(request: Request) -> Jinja2Templates:
    templates: Jinja2Templates = request.app.state.templates
    return templates


def _split_jobs(request: Request) -> tuple[list[JobState], list[JobState]]:
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
