# SPDX-License-Identifier: AGPL-3.0-or-later

import json
from pathlib import Path

from fastapi import FastAPI
from starlette.testclient import TestClient


def _make_capture(tmp_path: Path, capture_id: str = "2026-07-19_lgs") -> Path:
    capture_dir = tmp_path / capture_id
    (capture_dir / "output").mkdir(parents=True)
    (capture_dir / "output" / "scene.ply").write_bytes(b"ply\n" + b"x" * 1000)
    (capture_dir / "pipeline.log").write_text("done\n")
    return capture_dir


def test_confirm_writes_review_marker(app: FastAPI, tmp_path: Path) -> None:
    capture_dir = _make_capture(tmp_path)
    app.state.cfg.paths.captures_dir = tmp_path

    with TestClient(app) as client:
        r = client.post(
            "/captures/2026-07-19_lgs/review/confirm", follow_redirects=False
        )

    assert r.status_code == 303
    assert r.headers["location"] == "/captures/2026-07-19_lgs"
    marker = capture_dir / "output" / ".review.json"
    assert marker.exists()
    data = json.loads(marker.read_text())
    assert data["status"] == "reviewed"
    assert data["source_ply_mtime"] == (capture_dir / "output" / "scene.ply").stat().st_mtime
    assert not (capture_dir / "output" / "scene_reviewed.ply").exists()


def test_confirm_unknown_capture_404s(app: FastAPI, tmp_path: Path) -> None:
    app.state.cfg.paths.captures_dir = tmp_path
    with TestClient(app) as client:
        r = client.post("/captures/does-not-exist/review/confirm")
    assert r.status_code == 404


def test_confirm_no_ply_at_all_409s(app: FastAPI, tmp_path: Path) -> None:
    """Test that confirm returns 409 when capture has no PLY (not even legacy)."""
    capture_id = "2026-07-19_no_ply"
    capture_dir = tmp_path / capture_id
    capture_dir.mkdir(parents=True)
    (capture_dir / "pipeline.log").write_text("done\n")
    app.state.cfg.paths.captures_dir = tmp_path

    with TestClient(app) as client:
        r = client.post(f"/captures/{capture_id}/review/confirm", follow_redirects=False)

    assert r.status_code == 409
    assert "output/scene.ply" in r.json()["detail"]


def test_confirm_legacy_layout_409s(app: FastAPI, tmp_path: Path) -> None:
    """Test that confirm returns 409 for legacy layout (scene.ply at root, no output/)."""
    capture_id = "2026-07-19_legacy"
    capture_dir = tmp_path / capture_id
    capture_dir.mkdir(parents=True)
    # Legacy layout: PLY at root, not in output/
    (capture_dir / "scene.ply").write_bytes(b"ply\n" + b"x" * 1000)
    (capture_dir / "pipeline.log").write_text("done\n")
    app.state.cfg.paths.captures_dir = tmp_path

    with TestClient(app) as client:
        r = client.post(f"/captures/{capture_id}/review/confirm", follow_redirects=False)

    # Should return 409, not 500 (unhandled FileNotFoundError)
    assert r.status_code == 409
    assert "output/scene.ply" in r.json()["detail"]
