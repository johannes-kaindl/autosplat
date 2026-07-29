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

    Protection by convention — the structural backstop that enforces it for the
    whole suite lives in `tests/conftest.py`.

    supersplat_dist_path is pointed at a stub `index.html` so the `/supersplat`
    mount (and `supersplat_available` in the view template) is deterministic —
    it must not depend on whether *this* machine happens to have a SuperSplat
    dist built on disk.
    """
    cfg = load_config(include_xdg=False)
    cfg.paths.captures_dir = tmp_path_factory.mktemp("captures")
    dist = tmp_path_factory.mktemp("supersplat_dist")
    (dist / "index.html").write_text("<!doctype html><title>stub</title>")
    cfg.viewer.supersplat_dist_path = dist
    return create_app(cfg)
