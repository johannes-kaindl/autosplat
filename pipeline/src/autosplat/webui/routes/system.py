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
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from autosplat import __version__, desktop, resources
from autosplat.config import Config
from autosplat.doctor import run_doctor

router = APIRouter(prefix="/system")


@router.get("/", response_class=HTMLResponse)
def system_page(request: Request) -> HTMLResponse:
    templates: Jinja2Templates = request.app.state.templates
    cfg: Config | None = request.app.state.cfg
    checks = run_doctor(cfg) if cfg is not None else []
    # Derived from the same `checks` this request already computed, not a second
    # `missing_required_tools(cfg)` call — that would rerun all ten doctor
    # checks (four of them subprocess probes, ~1.2s) a second time on every
    # load, and could disagree with `checks` if a tool finished installing
    # between the two runs.
    missing_tools = [c.name for c in checks if c.name in desktop._INSTALLABLE_TOOLS and not c.ok]
    return templates.TemplateResponse(
        request,
        "system.html",
        {
            "version": __version__,
            "checks": checks,
            "viewers": resources.viewer_status(cfg),
            "missing_tools": missing_tools,
            "setup_result": request.query_params.get("setup"),
        },
    )


@router.post("/setup")
def system_setup(request: Request) -> RedirectResponse:
    """Re-run first-run setup: the same `desktop.run_first_run_setup` path
    the launcher takes automatically when a required tool is missing at
    startup, triggered here on demand instead.

    Fire-and-forget: `run_first_run_setup` hands the install script to
    Terminal via `osascript` and returns immediately — the install itself
    runs outside this process, so there is nothing here to poll or block on.
    Result is carried back as a `?setup=` query param rather than app state:
    it is momentary UI feedback about the *trigger*, not a job, and nothing
    else on this page needs to read it.
    """
    script = desktop._bundled_install_script()
    if script is None:
        # "a missing resource is displayed, never silently hidden" — a
        # `None` here must not make this button quietly do nothing.
        return RedirectResponse(url="/system/?setup=missing_script", status_code=303)
    desktop.run_first_run_setup(script)
    return RedirectResponse(url="/system/?setup=started", status_code=303)
