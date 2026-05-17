# SPDX-License-Identifier: AGPL-3.0-or-later

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from autosplat.webui.state import list_captures

router = APIRouter()
_templates: Jinja2Templates | None = None


def _get_templates(request: Request) -> Jinja2Templates:
    return request.app.state.templates


@router.get("/", response_class=HTMLResponse)
async def dashboard(request: Request) -> HTMLResponse:
    templates = _get_templates(request)
    cfg = request.app.state.cfg
    job_runner = getattr(request.app.state, "job_runner", None)
    captures = list_captures(cfg.paths.captures_dir, job_runner) if cfg else []
    active = next((c for c in captures if c.status == "running"), None)
    queued = [c for c in captures if c.status == "queued"]
    recent = [c for c in captures if c.status in ("done", "failed")][:10]
    stats = {
        "total": len(captures),
        "done": sum(1 for c in captures if c.status == "done"),
        "running": 1 if active else 0,
        "failed": sum(1 for c in captures if c.status == "failed"),
    }
    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {"active_capture": active, "queued": queued, "recent": recent, "stats": stats},
    )
