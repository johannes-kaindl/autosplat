# SPDX-License-Identifier: AGPL-3.0-or-later

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from autosplat import __version__

router = APIRouter()


@router.get("/source", response_class=HTMLResponse)
async def source(request: Request) -> HTMLResponse:
    templates: Jinja2Templates = request.app.state.templates
    return templates.TemplateResponse(request, "source.html", {"version": __version__})
