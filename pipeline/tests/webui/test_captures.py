# SPDX-License-Identifier: AGPL-3.0-or-later

"""Tests for capture discovery and detail routes."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
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


def test_list_captures_propagates_in_progress_detail(tmp_path: Path) -> None:
    """v1.4.1: when WatcherState.in_progress carries a detail string (set by
    bisect_recursively per-clip), list_captures surfaces it on CaptureInfo
    so the dashboard's active-job line can show 'bisect · probing clip 0_1'."""
    from autosplat.watcher import InProgress, WatcherState

    capture_dir = tmp_path / "2026-05-26_bisecting"
    capture_dir.mkdir()

    state = WatcherState()
    state.in_progress = InProgress(
        path=str(capture_dir),
        started_at="t",
        stage="bisect",
        detail="probing clip 0_1 (depth 2/3)",
    )

    with patch("autosplat.webui.state._load_watcher_state", return_value=state):
        captures = list_captures(tmp_path)

    assert len(captures) == 1
    assert captures[0].status == "running"
    assert captures[0].stage == "bisect"
    assert captures[0].detail == "probing clip 0_1 (depth 2/3)"


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


def test_capture_new_submit_applies_blur_threshold_override(app: FastAPI, tmp_path: Path) -> None:
    """An optional blur_threshold on the form overrides cfg.preprocess for the run."""
    from autosplat.webui.jobs_runner import JobState

    video = tmp_path / "soft.mp4"
    video.write_bytes(b"x")
    captured: dict[str, object] = {}

    async def fake_start(self: object, payload: object, cfg: object) -> JobState:
        captured["cfg"] = cfg
        return JobState(capture_id="2026-05-29_soft", status="queued")

    with (
        patch("autosplat.webui.jobs_runner.JobRunner.start_job_from_video", fake_start),
        TestClient(app) as client,
    ):
        response = client.post(
            "/captures/new",
            data={"video_path": str(video), "blur_threshold": "8"},
            follow_redirects=False,
        )

    assert response.status_code == 303
    assert captured["cfg"].preprocess.blur_threshold == 8.0  # type: ignore[attr-defined]


def test_capture_new_submit_default_blur_threshold_unchanged(app: FastAPI, tmp_path: Path) -> None:
    from autosplat.webui.jobs_runner import JobState

    video = tmp_path / "ok.mp4"
    video.write_bytes(b"x")
    captured: dict[str, object] = {}

    async def fake_start(self: object, payload: object, cfg: object) -> JobState:
        captured["cfg"] = cfg
        return JobState(capture_id="2026-05-29_ok", status="queued")

    with (
        patch("autosplat.webui.jobs_runner.JobRunner.start_job_from_video", fake_start),
        TestClient(app) as client,
    ):
        response = client.post(
            "/captures/new", data={"video_path": str(video)}, follow_redirects=False
        )

    assert response.status_code == 303
    # Untouched → packaged default (100.0).
    assert captured["cfg"].preprocess.blur_threshold == 100.0  # type: ignore[attr-defined]


def test_capture_new_submit_invalid_blur_threshold_400(app: FastAPI, tmp_path: Path) -> None:
    video = tmp_path / "x.mp4"
    video.write_bytes(b"x")
    with TestClient(app) as client:
        response = client.post(
            "/captures/new",
            data={"video_path": str(video), "blur_threshold": "-5"},
            follow_redirects=False,
        )
    assert response.status_code == 400
    assert "blur" in response.text.lower()


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


# ── v1.8.0 — prominent failure panel ─────────────────────────────────────────


def test_capture_detail_shows_failure_panel(app: FastAPI, tmp_path: Path) -> None:
    """A failed capture's detail page surfaces a prominent panel with when it
    failed, a human headline, and an actionable remediation hint."""
    from autosplat.watcher import FailedEntry, WatcherState

    capture_dir = tmp_path / "2026-05-29_failed_blur"
    (capture_dir / "frames").mkdir(parents=True)
    (capture_dir / "pipeline.log").write_text('{"event": "x", "level": "info"}\n')
    app.state.cfg.paths.captures_dir = tmp_path

    state = WatcherState()
    state.failed = [
        FailedEntry(
            path=str(capture_dir),
            failed_at="2026-05-29T14:17:48Z",
            reason="All 250 extracted frames were rejected as blurry (blur_threshold=100.0).",
            stage="preprocess",
        )
    ]
    with (
        patch("autosplat.webui.state._load_watcher_state", return_value=state),
        TestClient(app) as client,
    ):
        response = client.get("/captures/2026-05-29_failed_blur")

    assert response.status_code == 200
    body = response.text
    assert "too blurry" in body.lower()  # headline
    assert "blur_threshold" in body  # hint
    assert "What to do" in body
    assert "2026-05-29T14:17:48Z" in body  # when


def test_capture_detail_done_has_no_failure_panel(app: FastAPI, tmp_path: Path) -> None:
    capture_dir = tmp_path / "2026-05-29_ok"
    (capture_dir / "output").mkdir(parents=True)
    (capture_dir / "output" / "scene.ply").write_bytes(b"ply\n")
    app.state.cfg.paths.captures_dir = tmp_path

    with TestClient(app) as client:
        response = client.get("/captures/2026-05-29_ok")

    assert response.status_code == 200
    assert "What to do" not in response.text


def test_captures_list_shows_failure_headline(app: FastAPI, tmp_path: Path) -> None:
    """The captures list shows a one-line failure headline on failed rows so the
    cause is visible at a glance, not only on the detail page."""
    from autosplat.watcher import FailedEntry, WatcherState

    capture_dir = tmp_path / "2026-05-29_failed_sfm"
    capture_dir.mkdir(parents=True)
    app.state.cfg.paths.captures_dir = tmp_path

    state = WatcherState()
    state.failed = [
        FailedEntry(
            path=str(capture_dir),
            failed_at="2026-05-29T14:00:00Z",
            reason="No images with matches",
            stage="sfm",
        )
    ]
    with (
        patch("autosplat.webui.state._load_watcher_state", return_value=state),
        TestClient(app) as client,
    ):
        response = client.get("/captures/")

    assert response.status_code == 200
    assert "align the frames" in response.text  # sfm headline


# ── v1.8.0 — durable failed status from runs.jsonl (survives restart) ─────────


def test_jobrunner_last_run_returns_latest_for_capture(tmp_path: Path) -> None:
    from autosplat.webui.jobs_runner import JobRunner

    cap = tmp_path / "2026-05-29_hist"
    cap.mkdir()
    (cap / "runs.jsonl").write_text(
        '{"capture_id":"2026-05-29_hist","status":"failed","error":"first"}\n'
        '{"capture_id":"2026-05-29_hist","status":"failed","error":"second"}\n'
    )
    jr = JobRunner(captures_dir=tmp_path)
    jr.load_history()

    last = jr.last_run("2026-05-29_hist")
    assert last is not None
    assert last.error == "second"  # most recent wins
    assert jr.last_run("2026-05-29_nope") is None


def test_list_captures_failed_from_runs_jsonl_after_restart(tmp_path: Path) -> None:
    """After a restart the in-memory job is gone; a capture whose last persisted
    run failed must still show as failed + reason — not revert to 'idle'."""
    from autosplat.webui.jobs_runner import JobRunner
    from autosplat.webui.state import list_captures

    cap = tmp_path / "2026-05-29_oldfail"
    cap.mkdir()
    (cap / "runs.jsonl").write_text(
        '{"capture_id":"2026-05-29_oldfail","status":"failed",'
        '"started_at":"2026-05-29T11:00:00Z","finished_at":"2026-05-29T11:01:00Z",'
        '"error":"No images with matches"}\n'
    )
    jr = JobRunner(captures_dir=tmp_path)
    jr.load_history()

    caps = list_captures(tmp_path, jr)
    c = next(x for x in caps if x.id == "2026-05-29_oldfail")
    assert c.status == "failed"
    assert c.reason == "No images with matches"
    assert c.finished_at == "2026-05-29T11:01:00Z"


# ── Native Finder file-picker (osascript) ────────────────────────────────────


def test_pick_files_via_finder_parses_osascript_paths() -> None:
    """The helper shells out to `osascript` and turns its newline-separated
    POSIX-path output into a list of Path objects (one per chosen file)."""
    from autosplat.webui.routes.captures import _pick_files_via_finder

    fake = SimpleNamespace(
        returncode=0,
        stdout="/Users/me/a.mov\n/Users/me/b.mp4\n",
        stderr="",
    )
    with patch("autosplat.webui.routes.captures.subprocess.run", return_value=fake):
        paths = _pick_files_via_finder()

    assert paths == [Path("/Users/me/a.mov"), Path("/Users/me/b.mp4")]


def test_pick_files_via_finder_returns_empty_on_cancel() -> None:
    """When the user cancels the dialog, osascript exits non-zero; the helper
    swallows that and returns an empty list rather than raising."""
    from autosplat.webui.routes.captures import _pick_files_via_finder

    fake = SimpleNamespace(returncode=1, stdout="", stderr="User canceled.")
    with patch("autosplat.webui.routes.captures.subprocess.run", return_value=fake):
        paths = _pick_files_via_finder()

    assert paths == []


def test_pick_file_route_returns_json_paths(app: FastAPI) -> None:
    """POST /captures/pick-file opens the native picker (mocked) and returns
    the chosen absolute paths as JSON for the New-capture form to consume."""
    with (
        patch(
            "autosplat.webui.routes.captures._pick_files_via_finder",
            return_value=[Path("/Users/me/clip.mov")],
        ),
        TestClient(app) as client,
    ):
        response = client.post("/captures/pick-file")

    assert response.status_code == 200
    assert response.json() == {"paths": ["/Users/me/clip.mov"]}


def test_pick_file_route_empty_when_cancelled(app: FastAPI) -> None:
    """A cancelled picker yields an empty paths list, not an error."""
    with (
        patch(
            "autosplat.webui.routes.captures._pick_files_via_finder",
            return_value=[],
        ),
        TestClient(app) as client,
    ):
        response = client.post("/captures/pick-file")

    assert response.status_code == 200
    assert response.json() == {"paths": []}


def test_new_form_has_browse_button(app: FastAPI) -> None:
    """The New-capture form exposes a Browse control wired to the pick-file
    endpoint so users aren't forced to hand-type absolute paths."""
    with TestClient(app) as client:
        response = client.get("/captures/new")

    assert response.status_code == 200
    assert "/captures/pick-file" in response.text
