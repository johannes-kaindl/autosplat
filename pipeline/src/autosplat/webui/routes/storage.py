# SPDX-License-Identifier: AGPL-3.0-or-later

"""`/storage` — what disk is being used, and what may be reclaimed.

GET renders a preview and never mutates; the apply is a separate POST. That
asymmetry is the same one `migrate-storage` has on the command line, and it
is deliberate: this page's subject is irreversible deletion.

Routes are registered at literal paths (`/storage`, `/storage/reclaim`)
rather than via an `APIRouter(prefix="/storage")` + `"/"` index route, unlike
`captures`/`jobs`/`system`. Those three all pay a 307 when linked without
their trailing slash (`/system` still does — see `base.html`); registering
`/storage` directly avoids that redirect altogether instead of just moving it
to the other direction.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from autosplat import migration
from autosplat.config import Config
from autosplat.logging import get_logger

logger = get_logger(__name__)
router = APIRouter(tags=["storage"])

ReclaimStatus = Literal["running", "done", "failed"]


@dataclass
class ReclaimJob:
    """A reclaim sweep running off-request.

    Deleting multiple GB can take a while, and a WKWebView window with a
    blocked request in flight is indistinguishable from a frozen app — this
    repo has already shipped one of those.
    """

    status: ReclaimStatus = "running"
    reclaimed_bytes: int = 0
    failures: tuple[str, ...] = ()
    error: str | None = None
    thread: threading.Thread | None = field(default=None, repr=False)

    @property
    def is_running(self) -> bool:
        """`status == "running"` alone is not enough: `request.app.state.reclaim_job`
        is published *before* `job.thread.start()` (so the redirect target has
        something to poll immediately), which means a `start()` failure — or
        any other way the thread dies without transitioning `status` — leaves
        a job permanently stuck reporting "running" with nothing backing it.

        One predicate, three consumers (the route's 409 check, the "Reclaim
        now" button's suppression in `storage.html`, and the polling
        attributes in `partials/storage_status.html`) so they cannot drift
        out of sync the way a bare `status == "running"` check in each did.
        """
        return self.status == "running" and self.thread is not None and self.thread.is_alive()


def _templates(request: Request) -> Jinja2Templates:
    templates: Jinja2Templates = request.app.state.templates
    return templates


def _cfg(request: Request) -> Config:
    cfg: Config | None = getattr(request.app.state, "cfg", None)
    if cfg is None:
        raise HTTPException(status_code=503, detail="No config loaded")
    return cfg


def _plan(cfg: Config) -> migration.MigrationPlan:
    return migration.plan_migration(
        cfg.paths.captures_dir, cfg.export.outputs_dir, now=datetime.now(UTC)
    )


@router.get("/storage", response_class=HTMLResponse)
async def storage_page(request: Request) -> HTMLResponse:
    """Preview page. Also runs the unsafe-layout guard — not to protect
    anything here (a `GET` never deletes), but because a preview computed
    over a layout the guard calls catastrophic must say so, in the page,
    before the "Reclaim now" button is anywhere near a click. Rendering the
    plan and the button as if nothing were wrong, and only refusing once the
    POST fires, would make the single most safety-critical message in this
    feature a raw JSON error blob in a WKWebView with no way back.
    """
    cfg = _cfg(request)
    job = getattr(request.app.state, "reclaim_job", None)
    try:
        migration.refuse_if_unsafe_storage_layout(cfg.paths.captures_dir, cfg.export.outputs_dir)
    except migration.UnsafeStorageLayoutError as e:
        return _templates(request).TemplateResponse(
            request,
            "storage.html",
            {"plan": None, "unsafe_layout_error": str(e), "job": job},
        )
    return _templates(request).TemplateResponse(
        request,
        "storage.html",
        {"plan": _plan(cfg), "unsafe_layout_error": None, "job": job},
    )


@router.post("/storage/reclaim")
async def storage_reclaim(request: Request) -> RedirectResponse:
    """Start a reclaim sweep in a background thread.

    The unsafe-layout guard runs here, synchronously, before anything starts
    — the same guard `cli.py`'s `migrate_storage` applies before its own
    sweep. It had exactly one caller before this route became the second;
    fail loudly (an HTTP error, not a silently-skipped sweep) if it trips,
    the same as the CLI does.

    The plan is recomputed inside the thread, not carried over from the
    preview: a preview is a plan of unknown age, and a run that started in
    between must not have its working dirs pulled out from under it.
    `plan_migration`'s `recently_active` check is what knows that.
    """
    cfg = _cfg(request)
    existing: ReclaimJob | None = getattr(request.app.state, "reclaim_job", None)
    if existing is not None and existing.is_running:
        raise HTTPException(status_code=409, detail="A reclaim sweep is already running")

    try:
        migration.refuse_if_unsafe_storage_layout(cfg.paths.captures_dir, cfg.export.outputs_dir)
    except migration.UnsafeStorageLayoutError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    job = ReclaimJob()

    def _run() -> None:
        try:
            result = migration.apply_migration(_plan(cfg))
        except Exception as e:  # surfaced on the job, not raised into nowhere
            # error before status: a poll landing between the two would
            # otherwise render "Reclaim failed: None" — status is what the
            # template branches on, so it must be the last thing set.
            job.error = str(e)
            job.status = "failed"
            logger.error("storage.reclaim_failed", error=str(e))
            return
        job.reclaimed_bytes = result.reclaimed_bytes
        job.failures = result.failures
        job.status = "done"

    job.thread = threading.Thread(target=_run, name="autosplat-reclaim", daemon=True)
    request.app.state.reclaim_job = job
    job.thread.start()
    return RedirectResponse(url="/storage", status_code=303)
