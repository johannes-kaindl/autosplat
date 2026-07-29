# SPDX-License-Identifier: AGPL-3.0-or-later

"""Smoke tests for the FastAPI app — healthz and basic app wiring."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from starlette.testclient import TestClient

from autosplat import __version__


def test_healthz_returns_ok(app: FastAPI) -> None:
    with TestClient(app) as client:
        response = client.get("/healthz")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["version"] == __version__


def test_source_route_returns_200(app: FastAPI) -> None:
    with TestClient(app) as client:
        response = client.get("/source")
    assert response.status_code == 200
    assert "codeberg.org" in response.text
    assert "AGPL" in response.text


def test_lifespan_starts_grace_sweep(tmp_path: Path, monkeypatch) -> None:
    from fastapi.testclient import TestClient

    from autosplat.config import load_config
    from autosplat.webui import app as app_mod

    called: list[int] = []

    def fake_sweep(captures_dir, *, grace_days, now):
        called.append(grace_days)
        return []

    monkeypatch.setattr(app_mod.cleanup, "sweep_expired", fake_sweep)

    cfg = load_config(include_xdg=False)
    cfg.paths.captures_dir = tmp_path
    app = app_mod.create_app(cfg)

    with TestClient(app):
        pass

    assert called == [cfg.lifecycle.unreviewed_grace_days]


def test_lifespan_skips_sweep_when_grace_disabled(tmp_path: Path, monkeypatch) -> None:
    from fastapi.testclient import TestClient

    from autosplat.config import load_config
    from autosplat.webui import app as app_mod

    called: list[int] = []
    monkeypatch.setattr(
        app_mod.cleanup,
        "sweep_expired",
        lambda captures_dir, *, grace_days, now: called.append(grace_days) or [],
    )

    cfg = load_config(include_xdg=False)
    cfg.paths.captures_dir = tmp_path
    cfg.lifecycle.unreviewed_grace_days = 0
    app = app_mod.create_app(cfg)

    with TestClient(app):
        pass

    assert called == []
