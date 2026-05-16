# SPDX-License-Identifier: AGPL-3.0-or-later

"""FastAPI application factory for the autosplat WebUI."""

from __future__ import annotations

from contextlib import asynccontextmanager
from collections.abc import AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from autosplat import __version__
from autosplat.config import Config

from .routes import health


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    yield


def create_app(cfg: Config | None = None) -> FastAPI:
    """Return a configured FastAPI application.

    `cfg` is optional here so uvicorn --factory mode can call create_app()
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

    app.include_router(health.router)

    # Stash config on app.state for route handlers to access.
    app.state.cfg = cfg

    return app
