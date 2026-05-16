# SPDX-License-Identifier: AGPL-3.0-or-later

"""Smoke tests for the FastAPI app — healthz and basic app wiring."""

from __future__ import annotations

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
