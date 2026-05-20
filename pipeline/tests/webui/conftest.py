# SPDX-License-Identifier: AGPL-3.0-or-later

"""Shared fixtures for WebUI tests."""

from __future__ import annotations

import pytest
from fastapi import FastAPI

from autosplat.config import load_config
from autosplat.webui import create_app


@pytest.fixture()
def app() -> FastAPI:
    """FastAPI app instance built from the packaged default config."""
    cfg = load_config(include_xdg=False)
    return create_app(cfg)
