# SPDX-License-Identifier: AGPL-3.0-or-later

"""FastAPI application factory for the autosplat WebUI."""

from __future__ import annotations

import datetime
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from autosplat import __version__
from autosplat.config import Config

from .routes import captures, dashboard, health, jobs, partials, source

_WEBUI_DIR = Path(__file__).parent
_TEMPLATES_DIR = _WEBUI_DIR / "templates"
_STATIC_DIR = _WEBUI_DIR / "static"


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
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
    app.state.templates = templates
    app.state.cfg = cfg

    # Routers
    app.include_router(health.router)
    app.include_router(dashboard.router)
    app.include_router(captures.router)
    app.include_router(jobs.router)
    app.include_router(partials.router)
    app.include_router(source.router)

    # Wire up job runner (available for all routes via request.app.state.job_runner)
    from .jobs_runner import JobRunner

    captures_dir = cfg.paths.captures_dir if cfg is not None else None
    runner = JobRunner(captures_dir=captures_dir)
    if captures_dir is not None:
        # Rehydrate recent-jobs view from runs.jsonl on every cold start (V12-2).
        runner.load_history()
    app.state.job_runner = runner

    return app
