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
    """GET /captures/new renders the multi-video form — not shadowed by /{capture_id}."""
    with TestClient(app) as client:
        response = client.get("/captures/new")
    assert response.status_code == 200
    assert "New capture" in response.text
    assert 'name="video_paths"' in response.text


def test_capture_new_submit_starts_job_and_redirects(app: FastAPI, tmp_path: Path) -> None:
    """Posting a valid video path launches a job and 303-redirects to the capture."""
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"fake-video-bytes")

    with TestClient(app) as client, patch("autosplat.webui.jobs_runner._run_pipeline_thread"):
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


def test_capture_new_submit_wrong_extension_shows_error(app: FastAPI, tmp_path: Path) -> None:
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


# ─── V12-6 — resume route ────────────────────────────────────────────────────


def test_capture_resume_route_launches_job_and_redirects(app: FastAPI, tmp_path: Path) -> None:
    """POST /captures/{id}/resume launches a resume job and 303-redirects
    back to the capture's detail page."""
    capture_dir = tmp_path / "2026-05-22_max_strasse"
    (capture_dir / "frames").mkdir(parents=True)
    (capture_dir / "frames" / "frame_00001.jpg").write_bytes(b"\xff\xd8")
    app.state.cfg.paths.captures_dir = tmp_path

    with (
        TestClient(app) as client,
        patch("autosplat.webui.jobs_runner._run_resume_thread") as mocked,
    ):
        response = client.post("/captures/2026-05-22_max_strasse/resume", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == "/captures/2026-05-22_max_strasse"
    mocked.assert_called_once()


def test_capture_resume_route_404_for_unknown_capture(app: FastAPI, tmp_path: Path) -> None:
    """Resuming a capture that doesn't exist on disk returns 404."""
    app.state.cfg.paths.captures_dir = tmp_path
    with TestClient(app) as client:
        response = client.post("/captures/2099-01-01_nope/resume", follow_redirects=False)
    assert response.status_code == 404


def test_capture_detail_failed_shows_resume_button(app: FastAPI, tmp_path: Path) -> None:
    """A failed capture's detail page surfaces a Resume button that POSTs
    to the resume route (replacing the broken-for-real-captures Retry)."""
    capture_dir = tmp_path / "2026-05-22_failed_one"
    (capture_dir / "frames").mkdir(parents=True)
    (capture_dir / "pipeline.log").write_text(
        '{"event": "pipeline.start", "video": "/tmp/v.mp4"}\n', encoding="utf-8"
    )
    app.state.cfg.paths.captures_dir = tmp_path

    from autosplat.webui.jobs_runner import JobState

    runner = app.state.job_runner
    runner._jobs["2026-05-22_failed_one"] = JobState(
        capture_id="2026-05-22_failed_one", status="failed", error="boom"
    )

    with TestClient(app) as client:
        response = client.get("/captures/2026-05-22_failed_one")

    assert response.status_code == 200
    assert 'action="/captures/2026-05-22_failed_one/resume"' in response.text
    assert "Resume" in response.text


def test_capture_new_submit_accepts_multiple_videos(app: FastAPI, tmp_path: Path) -> None:
    """The form accepts a newline-separated list of paths in video_paths
    and launches a single multi-video capture (NOT one job per video)."""
    v1 = tmp_path / "pass_a.mp4"
    v2 = tmp_path / "pass_b.mp4"
    v1.write_bytes(b"\0")
    v2.write_bytes(b"\0")

    with (
        TestClient(app) as client,
        patch("autosplat.webui.jobs_runner._run_pipeline_thread") as mocked,
    ):
        response = client.post(
            "/captures/new",
            data={"video_paths": f"{v1}\n{v2}"},
            follow_redirects=False,
        )

    assert response.status_code == 303
    assert response.headers["location"].endswith("_pass_a")
    args = mocked.call_args.args
    # Thread receives the videos list (3rd positional arg = videos; signature
    # may have changed but the list-of-paths should be present somewhere).
    assert any(arg == [v1, v2] for arg in args)


def test_capture_new_submit_single_video_textbox_still_works(app: FastAPI, tmp_path: Path) -> None:
    """Backwards-compat: the legacy single-line `video_path` field still
    launches a single-video capture if no multi-line `video_paths` is given."""
    video = tmp_path / "only.mp4"
    video.write_bytes(b"\0")

    with TestClient(app) as client, patch("autosplat.webui.jobs_runner._run_pipeline_thread"):
        response = client.post(
            "/captures/new",
            data={"video_path": str(video)},
            follow_redirects=False,
        )

    assert response.status_code == 303
    assert response.headers["location"].endswith("_only")


def test_capture_add_video_route_launches_job(app: FastAPI, tmp_path: Path) -> None:
    """POST /captures/{id}/add-video kicks off an add-video job thread and
    redirects to the capture detail page."""
    capture_dir = tmp_path / "2026-05-22_first_pass"
    capture_dir.mkdir()
    new_video = tmp_path / "pass_b.mp4"
    new_video.write_bytes(b"\0")
    app.state.cfg.paths.captures_dir = tmp_path

    with (
        TestClient(app) as client,
        patch("autosplat.webui.jobs_runner._run_add_video_thread") as mocked,
    ):
        response = client.post(
            "/captures/2026-05-22_first_pass/add-video",
            data={"video_path": str(new_video)},
            follow_redirects=False,
        )

    assert response.status_code == 303
    assert response.headers["location"] == "/captures/2026-05-22_first_pass"
    mocked.assert_called_once()


def test_capture_add_video_route_400_for_missing_video(app: FastAPI, tmp_path: Path) -> None:
    """Pointing at a file that doesn't exist returns 400 with the form re-
    rendered + an error message — not a 5xx from the worker."""
    capture_dir = tmp_path / "2026-05-22_existing"
    capture_dir.mkdir()
    app.state.cfg.paths.captures_dir = tmp_path

    with TestClient(app) as client:
        response = client.post(
            "/captures/2026-05-22_existing/add-video",
            data={"video_path": str(tmp_path / "nope.mp4")},
            follow_redirects=False,
        )
    assert response.status_code == 400


def test_capture_detail_done_hides_resume_button(app: FastAPI, tmp_path: Path) -> None:
    """A completed capture must not show a Resume button — resume_capture
    would refuse it anyway, so hide the dead control."""
    capture_dir = tmp_path / "2026-05-22_done_one"
    (capture_dir / "output").mkdir(parents=True)
    (capture_dir / "output" / "scene.ply").write_bytes(b"ply\n")
    app.state.cfg.paths.captures_dir = tmp_path

    with TestClient(app) as client:
        response = client.get("/captures/2026-05-22_done_one")

    assert response.status_code == 200
    assert "/resume" not in response.text
