# SPDX-License-Identifier: AGPL-3.0-or-later

"""Tests for capture discovery and detail routes."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from fastapi import FastAPI
from starlette.testclient import TestClient

from autosplat.webui.state import list_captures


def test_list_captures_empty_dir(tmp_path: Path) -> None:
    captures = list_captures(tmp_path)
    assert captures == []


def test_list_captures_with_fixture(tmp_path: Path) -> None:
    capture_dir = tmp_path / "2026-05-16_test_video"
    capture_dir.mkdir()
    (capture_dir / "output").mkdir()
    ply = capture_dir / "output" / "scene.ply"
    ply.write_bytes(b"ply\n")

    captures = list_captures(tmp_path)
    assert len(captures) == 1
    assert captures[0].id == "2026-05-16_test_video"
    assert captures[0].has_ply is True
    assert captures[0].ply_size_bytes == 4


def test_capture_ply_route_returns_200(app: FastAPI, tmp_path: Path) -> None:
    capture_dir = tmp_path / "2026-05-16_ply_smoke"
    capture_dir.mkdir()
    output_dir = capture_dir / "output"
    output_dir.mkdir()
    ply = output_dir / "scene.ply"
    ply.write_bytes(b"ply\nformat binary 1.0\n")

    app.state.cfg.paths.captures_dir = tmp_path

    with TestClient(app) as client:
        response = client.get("/captures/2026-05-16_ply_smoke/scene.ply")
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/octet-stream"


def test_capture_ply_route_returns_404_when_no_ply(app: FastAPI, tmp_path: Path) -> None:
    capture_dir = tmp_path / "2026-05-16_no_ply"
    capture_dir.mkdir()

    app.state.cfg.paths.captures_dir = tmp_path

    with TestClient(app) as client:
        response = client.get("/captures/2026-05-16_no_ply/scene.ply")
    assert response.status_code == 404


def test_capture_detail_route_returns_200(app: FastAPI, tmp_path: Path) -> None:
    capture_dir = tmp_path / "2026-05-16_smoke"
    capture_dir.mkdir()
    (capture_dir / "output").mkdir()
    (capture_dir / "output" / "scene.ply").write_bytes(b"ply\n")

    # Override captures_dir in app config for this test
    app.state.cfg.paths.captures_dir = tmp_path

    with TestClient(app) as client:
        response = client.get("/captures/2026-05-16_smoke")
    assert response.status_code == 200
    assert "2026-05-16_smoke" in response.text


def test_capture_new_form_returns_200(app: FastAPI) -> None:
    """GET /captures/new renders the form — not shadowed by /{capture_id}."""
    with TestClient(app) as client:
        response = client.get("/captures/new")
    assert response.status_code == 200
    assert "New capture" in response.text
    assert 'name="video_path"' in response.text


def test_capture_new_submit_starts_job_and_redirects(app: FastAPI, tmp_path: Path) -> None:
    """Posting a valid video path launches a job and 303-redirects to the capture."""
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"fake-video-bytes")

    with TestClient(app) as client, patch(
        "autosplat.webui.jobs_runner._run_pipeline_thread"
    ):
        response = client.post(
            "/captures/new",
            data={"video_path": str(video)},
            follow_redirects=False,
        )
    assert response.status_code == 303
    location = response.headers["location"]
    assert location.startswith("/captures/")
    assert location.endswith("_clip")


def test_capture_new_submit_missing_file_shows_error(app: FastAPI, tmp_path: Path) -> None:
    """A non-existent path re-renders the form with a 400 and an error message."""
    with TestClient(app) as client:
        response = client.post(
            "/captures/new",
            data={"video_path": str(tmp_path / "nope.mp4")},
            follow_redirects=False,
        )
    assert response.status_code == 400
    assert "No file found" in response.text


def test_capture_new_submit_wrong_extension_shows_error(
    app: FastAPI, tmp_path: Path
) -> None:
    """A non-video file is rejected with a 400 and an error message."""
    bad = tmp_path / "notes.txt"
    bad.write_text("not a video")
    with TestClient(app) as client:
        response = client.post(
            "/captures/new",
            data={"video_path": str(bad)},
            follow_redirects=False,
        )
    assert response.status_code == 400
    assert "Unsupported file type" in response.text


def test_capture_new_submit_empty_path_shows_error(app: FastAPI) -> None:
    """A blank path is rejected server-side even though the input is required."""
    with TestClient(app) as client:
        response = client.post(
            "/captures/new",
            data={"video_path": "   "},
            follow_redirects=False,
        )
    assert response.status_code == 400
    assert "Please enter" in response.text
