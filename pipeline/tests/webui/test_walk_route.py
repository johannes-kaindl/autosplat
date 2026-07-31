# SPDX-License-Identifier: AGPL-3.0-or-later

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

from autosplat.config import load_config
from autosplat.webui import create_app


def _capture_with_ply(tmp_path: Path, capture_id: str = "2026-07-19_lgs") -> Path:
    capture_dir = tmp_path / capture_id
    (capture_dir / "output").mkdir(parents=True)
    (capture_dir / "output" / "scene.ply").write_bytes(b"ply\n" + b"x" * 1000)
    return capture_dir


def _app_with_missing_viewer(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> FastAPI:
    """Build an app the way the `app` fixture does, except the bundle root
    has no viewer/ — the actual shape a missing bundled resource takes (a
    build that failed to stage viewer/), not a special case bolted onto the
    mount loop just for this test.

    `resources._root_for` has no config override for "viewer" (unlike
    supersplat/embed), so absence has to be simulated via
    `resources.bundled_path`'s frozen branch — same technique as
    `test_resources.py::test_frozen_bundle_resolves_against_meipass` — rather
    than a cfg field, and the mount loop must run *after* the patch, so this
    builds a fresh app instead of reusing the `app` fixture.
    """
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path / "meipass"), raising=False)
    cfg = load_config(include_xdg=False)
    dist = tmp_path / "supersplat_dist"
    dist.mkdir()
    (dist / "index.html").write_text("<!doctype html><title>stub</title>")
    cfg.viewer.supersplat_dist_path = dist
    cfg.paths.captures_dir = tmp_path
    return create_app(cfg)


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


def test_walk_offers_a_readable_fallback_when_the_viewer_is_absent(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The review finding this fixes: a missing /viewer mount used to redirect
    into a bare browser 404, indistinguishable from a wrong capture id. It
    must instead read like `capture_view`'s SuperSplat-unavailable card:
    explained at the point of failure, with a pointer to /system."""
    app = _app_with_missing_viewer(monkeypatch, tmp_path)
    _capture_with_ply(tmp_path)

    with TestClient(app) as client:
        r = client.get("/captures/2026-07-19_lgs/walk", follow_redirects=False)

    assert r.status_code == 503
    assert "unavailable" in r.text.lower()
    assert "/system" in r.text


def test_detail_page_hides_walk_through_when_the_viewer_is_absent(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The page must not offer an action that cannot work."""
    app = _app_with_missing_viewer(monkeypatch, tmp_path)
    _capture_with_ply(tmp_path)

    with TestClient(app) as client:
        body = client.get("/captures/2026-07-19_lgs").text

    assert "/walk" not in body
    assert "View splat" in body  # the working sibling action is still offered
