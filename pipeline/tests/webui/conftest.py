# SPDX-License-Identifier: AGPL-3.0-or-later

"""Shared fixtures for WebUI tests."""

from __future__ import annotations

import pytest
from fastapi import FastAPI

from autosplat.config import load_config
from autosplat.webui import create_app


@pytest.fixture()
def app(tmp_path_factory: pytest.TempPathFactory) -> FastAPI:
    """FastAPI app built from the packaged default config.

    captures_dir is redirected to a temp dir: tests must never read — let alone
    reclaim — the real ~/AutoSplat/captures. Individual tests still override it
    with their own tmp_path where they need to place fixtures.
    """
    cfg = load_config(include_xdg=False)
    cfg.paths.captures_dir = tmp_path_factory.mktemp("captures")
    return create_app(cfg)
