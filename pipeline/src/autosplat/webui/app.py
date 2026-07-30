# SPDX-License-Identifier: AGPL-3.0-or-later

"""FastAPI application factory for the autosplat WebUI."""

from __future__ import annotations

import datetime
import sys
import threading
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from autosplat import __version__, cleanup
from autosplat.config import Config
from autosplat.failure import classify_failure
from autosplat.logging import get_logger

from .routes import captures, dashboard, health, jobs, partials, source, storage, system

logger = get_logger(__name__)


def _webui_dir() -> Path:
    """templates/static location — frozen-aware (build_app.sh stages them under
    `autosplat/webui/` in the PyInstaller bundle)."""
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS) / "autosplat" / "webui"  # type: ignore[attr-defined]
    return Path(__file__).parent


_WEBUI_DIR = _webui_dir()
_TEMPLATES_DIR = _WEBUI_DIR / "templates"
_STATIC_DIR = _WEBUI_DIR / "static"


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Run the unreviewed-grace sweep in the background on startup.

    A background thread on purpose: reclaiming must never delay or prevent the
    UI from coming up, and a failure inside the sweep must not surface as a
    failed start.
    """
    cfg: Config | None = app.state.cfg
    if cfg is not None and cfg.lifecycle.unreviewed_grace_days > 0:
        captures_dir = cfg.paths.captures_dir
        grace_days = cfg.lifecycle.unreviewed_grace_days

        def _sweep() -> None:
            try:
                results = cleanup.sweep_expired(
                    captures_dir, grace_days=grace_days, now=datetime.datetime.now(UTC)
                )
            except Exception as e:  # startup must never fail here
                logger.error("lifecycle.sweep_failed", error=str(e))
                return
            if results:
                total = sum(r.bytes_reclaimed for r in results)
                logger.info("lifecycle.sweep_done", captures=len(results), bytes_reclaimed=total)

        threading.Thread(target=_sweep, name="autosplat-grace-sweep", daemon=True).start()
    yield


def create_app(cfg: Config | None = None) -> FastAPI:
    """Return a configured FastAPI application.

    `cfg` is optional so uvicorn --factory mode can call create_app()
    without arguments; the CLI command passes a loaded Config.
    """
    app = FastAPI(
        title="autosplat WebUI",
        version=__version__,
        lifespan=_lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Static files
    app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")

    # SuperSplat dist/ — only mount if built
    if cfg is not None:
        dist = cfg.viewer.supersplat_dist_path
        if not dist.is_absolute():
            dist = Path.cwd() / dist
        if (dist / "index.html").exists():
            app.mount("/supersplat", StaticFiles(directory=str(dist)), name="supersplat")

    # Jinja2 templates
    templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))
    templates.env.globals["version"] = __version__
    templates.env.globals["now"] = datetime.datetime.now
    templates.env.globals["classify_failure"] = classify_failure
    app.state.templates = templates
    app.state.cfg = cfg

    # Routers
    app.include_router(health.router)
    app.include_router(dashboard.router)
    app.include_router(captures.router)
    app.include_router(jobs.router)
    app.include_router(partials.router)
    app.include_router(source.router)
    app.include_router(system.router)
    app.include_router(storage.router)

    # Wire up job runner (available for all routes via request.app.state.job_runner)
    from .jobs_runner import JobRunner

    captures_dir = cfg.paths.captures_dir if cfg is not None else None
    runner = JobRunner(captures_dir=captures_dir)
    if captures_dir is not None:
        # Rehydrate recent-jobs view from runs.jsonl on every cold start (V12-2).
        runner.load_history()
    app.state.job_runner = runner

    from .share_runner import ShareJobRunner

    app.state.share_runner = ShareJobRunner(cfg) if cfg is not None else None

    # No reclaim sweep has run yet in this process.
    app.state.reclaim_job = None

    return app
