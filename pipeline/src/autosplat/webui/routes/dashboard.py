# SPDX-License-Identifier: AGPL-3.0-or-later

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from autosplat import __version__
from autosplat.webui.state import list_captures

router = APIRouter()
_templates: Jinja2Templates | None = None


def _get_templates(request: Request) -> Jinja2Templates:
    return request.app.state.templates


@router.get("/", response_class=HTMLResponse)
async def dashboard(request: Request) -> HTMLResponse:
    templates = _get_templates(request)
    cfg = request.app.state.cfg
    captures = list_captures(cfg.paths.captures_dir) if cfg else []
    active = next((c for c in captures if c.status == "running"), None)
    queued = [c for c in captures if c.status == "queued"]
    recent = [c for c in captures if c.status in ("done", "failed")][:10]
    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {"version": __version__, "active_capture": active, "queued": queued, "recent": recent},
    )
