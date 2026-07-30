# SPDX-License-Identifier: AGPL-3.0-or-later

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from starlette.testclient import TestClient


def _capture_with_ply(tmp_path: Path, capture_id: str = "2026-07-19_lgs") -> Path:
    capture_dir = tmp_path / capture_id
    (capture_dir / "output").mkdir(parents=True)
    (capture_dir / "output" / "scene.ply").write_bytes(b"ply\n" + b"x" * 1000)
    return capture_dir


def test_walk_serves_the_viewer_pointed_at_the_capture(app: FastAPI, tmp_path: Path) -> None:
    _capture_with_ply(tmp_path)
    app.state.cfg.paths.captures_dir = tmp_path

    with TestClient(app) as client:
        r = client.get("/captures/2026-07-19_lgs/walk", follow_redirects=False)

    assert r.status_code == 307
    assert r.headers["location"] == (
        "/viewer/viewer.html?src=/captures/2026-07-19_lgs/scene.ply"
    )


def test_walk_404s_for_an_unknown_capture(app: FastAPI, tmp_path: Path) -> None:
    app.state.cfg.paths.captures_dir = tmp_path
    with TestClient(app) as client:
        assert client.get("/captures/nope/walk").status_code == 404


def test_walk_409s_without_a_ply(app: FastAPI, tmp_path: Path) -> None:
    capture_dir = tmp_path / "2026-07-19_empty"
    (capture_dir / "output").mkdir(parents=True)
    app.state.cfg.paths.captures_dir = tmp_path
    with TestClient(app) as client:
        assert client.get("/captures/2026-07-19_empty/walk").status_code == 409


def test_viewer_runtime_is_served(app: FastAPI) -> None:
    """A mount that silently isn't there is the bug this whole branch is about."""
    with TestClient(app) as client:
        r = client.get("/viewer/viewer.html")
    assert r.status_code == 200
    assert "walk" in r.text.lower()


def test_detail_page_offers_walking(app: FastAPI, tmp_path: Path) -> None:
    _capture_with_ply(tmp_path)
    app.state.cfg.paths.captures_dir = tmp_path
    with TestClient(app) as client:
        body = client.get("/captures/2026-07-19_lgs").text
    assert "/walk" in body
