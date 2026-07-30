# SPDX-License-Identifier: AGPL-3.0-or-later

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from starlette.testclient import TestClient


def test_system_page_lists_external_tools(app: FastAPI) -> None:
    with TestClient(app) as client:
        r = client.get("/system")
    assert r.status_code == 200
    body = r.text
    for tool in ("ffmpeg", "colmap", "brush"):
        assert tool in body


def test_system_page_reports_a_missing_bundled_viewer(app: FastAPI, tmp_path: Path) -> None:
    """The defect this page exists for: a missing viewer used to be invisible."""
    app.state.cfg.viewer.supersplat_dist_path = tmp_path / "nope"
    with TestClient(app) as client:
        r = client.get("/system")
    assert r.status_code == 200
    assert "supersplat" in r.text.lower()
    assert "missing" in r.text.lower()


def test_system_page_names_the_role_of_each_viewer(app: FastAPI) -> None:
    with TestClient(app) as client:
        body = client.get("/system").text
    # The charter, rendered: three viewers, three jobs.
    assert "clean up" in body.lower()
    assert "share" in body.lower()
    assert "walk" in body.lower()


def test_nav_links_to_system(app: FastAPI) -> None:
    """Trailing slash matches `/system`'s canonical `APIRouter(prefix="/system")`
    + `"/"` route — same shape as `/captures/` and `/jobs/` in this nav, which
    both already carry it. Linking the bare path costs an extra 307 per click."""
    with TestClient(app) as client:
        body = client.get("/").text
    assert 'href="/system/"' in body
