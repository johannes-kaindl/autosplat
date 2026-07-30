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
    cfg = _cfg(request)
    return _templates(request).TemplateResponse(
        request,
        "storage.html",
        {"plan": _plan(cfg), "job": getattr(request.app.state, "reclaim_job", None)},
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
    if existing is not None and existing.status == "running":
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
            job.status = "failed"
            job.error = str(e)
            logger.error("storage.reclaim_failed", error=str(e))
            return
        job.reclaimed_bytes = result.reclaimed_bytes
        job.failures = result.failures
        job.status = "done"

    job.thread = threading.Thread(target=_run, name="autosplat-reclaim", daemon=True)
    request.app.state.reclaim_job = job
    job.thread.start()
    return RedirectResponse(url="/storage", status_code=303)
