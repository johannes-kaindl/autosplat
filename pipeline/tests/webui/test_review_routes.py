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


def test_upload_valid_ply_saves_reviewed_file_and_marker(app: FastAPI, tmp_path: Path) -> None:
    capture_dir = _make_capture(tmp_path)
    app.state.cfg.paths.captures_dir = tmp_path

    with TestClient(app) as client:
        r = client.post(
            "/captures/2026-07-19_lgs/review/upload",
            files={"reviewed_ply": ("cleaned.ply", b"ply\ncleaned-data", "application/octet-stream")},
            follow_redirects=False,
        )

    assert r.status_code == 303
    assert r.headers["location"] == "/captures/2026-07-19_lgs"
    reviewed = capture_dir / "output" / "scene_reviewed.ply"
    assert reviewed.exists()
    assert reviewed.read_bytes() == b"ply\ncleaned-data"
    marker = capture_dir / "output" / ".review.json"
    assert json.loads(marker.read_text())["status"] == "reviewed"


def test_upload_rejects_non_ply_extension(app: FastAPI, tmp_path: Path) -> None:
    _make_capture(tmp_path)
    app.state.cfg.paths.captures_dir = tmp_path

    with TestClient(app) as client:
        r = client.post(
            "/captures/2026-07-19_lgs/review/upload",
            files={"reviewed_ply": ("cleaned.txt", b"ply\ndata", "text/plain")},
        )

    assert r.status_code == 400
    assert "Unsupported file type" in r.text


def test_upload_rejects_missing_ply_header(app: FastAPI, tmp_path: Path) -> None:
    _make_capture(tmp_path)
    app.state.cfg.paths.captures_dir = tmp_path

    with TestClient(app) as client:
        r = client.post(
            "/captures/2026-07-19_lgs/review/upload",
            files={"reviewed_ply": ("cleaned.ply", b"not a ply file", "application/octet-stream")},
        )

    assert r.status_code == 400
    assert "PLY" in r.text


def test_upload_rejects_empty_file(app: FastAPI, tmp_path: Path) -> None:
    _make_capture(tmp_path)
    app.state.cfg.paths.captures_dir = tmp_path

    with TestClient(app) as client:
        r = client.post(
            "/captures/2026-07-19_lgs/review/upload",
            files={"reviewed_ply": ("cleaned.ply", b"", "application/octet-stream")},
        )

    assert r.status_code == 400
    assert "empty" in r.text.lower()


def test_view_page_shows_review_panel_when_unreviewed(app: FastAPI, tmp_path: Path) -> None:
    _make_capture(tmp_path)
    app.state.cfg.paths.captures_dir = tmp_path

    with TestClient(app) as client:
        body = client.get("/captures/2026-07-19_lgs/view").text

    assert 'action="/captures/2026-07-19_lgs/review/upload"' in body
    assert 'action="/captures/2026-07-19_lgs/review/confirm"' in body
    assert "Confirm unchanged" in body


def test_view_page_hides_review_panel_when_reviewed(app: FastAPI, tmp_path: Path) -> None:
    capture_dir = _make_capture(tmp_path)
    scene_ply = capture_dir / "output" / "scene.ply"
    (capture_dir / "output" / ".review.json").write_text(
        json.dumps(
            {
                "status": "reviewed",
                "reviewed_at": "2026-07-19T00:00:00",
                "source_ply_mtime": scene_ply.stat().st_mtime,
            }
        )
    )
    app.state.cfg.paths.captures_dir = tmp_path

    with TestClient(app) as client:
        body = client.get("/captures/2026-07-19_lgs/view").text

    assert 'action="/captures/2026-07-19_lgs/review/upload"' not in body
