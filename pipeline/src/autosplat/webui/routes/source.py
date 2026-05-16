# SPDX-License-Identifier: AGPL-3.0-or-later

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from autosplat import __version__

router = APIRouter()


@router.get("/source", response_class=HTMLResponse)
async def source(request: Request) -> HTMLResponse:
    return request.app.state.templates.TemplateResponse(
        request, "source.html", {"version": __version__}
    )
