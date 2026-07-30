# SPDX-License-Identifier: AGPL-3.0-or-later

"""`/system` — external tool status and bundled-resource status.

Both halves already existed and were discarded: `desktop.main` runs
`run_doctor` on every launch, then spins in a silent
`while needs_first_run_setup(cfg)` loop, and `webui/app.py` skips the
SuperSplat mount without telling anyone. This page is where that goes.

`system_page` is a plain `def`, not `async def`: `run_doctor` runs ten
checks synchronously, four of them subprocess version probes, measured at
1164 ms. An `async def` handler runs on the event loop, so that would block
every other request — including htmx job-status polling — for over a
second on every click of the `/system` nav entry `base.html` shows on every
page. A plain `def` lets FastAPI run it in its threadpool instead.
"""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from autosplat import __version__, resources
from autosplat.config import Config
from autosplat.doctor import run_doctor

router = APIRouter(prefix="/system")


@router.get("/", response_class=HTMLResponse)
def system_page(request: Request) -> HTMLResponse:
    templates: Jinja2Templates = request.app.state.templates
    cfg: Config | None = request.app.state.cfg
    return templates.TemplateResponse(
        request,
        "system.html",
        {
            "version": __version__,
            "checks": run_doctor(cfg) if cfg is not None else [],
            "viewers": resources.viewer_status(cfg),
        },
    )
