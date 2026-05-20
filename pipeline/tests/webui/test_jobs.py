# SPDX-License-Identifier: AGPL-3.0-or-later

"""Tests for the async job runner."""

from __future__ import annotations

import re
from pathlib import Path
from unittest.mock import patch

import pytest

from autosplat.webui.jobs_runner import JobRunner, JobState, _find_source_video
from autosplat.webui.state import list_captures

ISO_UTC_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")


def test_find_source_video_returns_none_for_empty(tmp_path: Path) -> None:
    assert _find_source_video(tmp_path) is None


def test_find_source_video_finds_mp4(tmp_path: Path) -> None:
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"fake")
    result = _find_source_video(tmp_path)
    assert result == video


@pytest.mark.anyio
async def test_enqueue_creates_job_state(tmp_path: Path) -> None:
    runner = JobRunner()

    video = tmp_path / "clip.mp4"
    video.write_bytes(b"fake")

    capture_path = tmp_path / "2026-05-16_test"
    capture_path.mkdir()
    (capture_path / "clip.mp4").write_bytes(b"fake")

    from autosplat.config import load_config

    cfg = load_config(include_xdg=False)
    cfg.paths.captures_dir = tmp_path

    with patch("autosplat.webui.jobs_runner._run_pipeline_thread"):
        job = await runner.start_job("2026-05-16_test", capture_path, cfg)

    assert job.capture_id == "2026-05-16_test"
    assert job.status in ("queued", "running")


@pytest.mark.anyio
async def test_cancel_job_sets_cancelled(tmp_path: Path) -> None:
    runner = JobRunner()
    capture_path = tmp_path / "2026-05-16_cancel"
    capture_path.mkdir()
    (capture_path / "clip.mp4").write_bytes(b"fake")

    from autosplat.config import load_config

    cfg = load_config(include_xdg=False)

    # Start job with a long-running mock thread so we can cancel it
    with patch("autosplat.webui.jobs_runner._run_pipeline_thread"):
        job = await runner.start_job("2026-05-16_cancel", capture_path, cfg)

    job.status = "running"  # force running so cancel is valid
    cancelled = await runner.cancel_job("2026-05-16_cancel")
    assert cancelled is True
    assert job.status == "cancelled"


@pytest.mark.anyio
async def test_all_jobs_keeps_history_per_capture(tmp_path: Path) -> None:
    """SF-G3-3: re-triggering a capture keeps both runs in all_jobs().

    `_jobs` still holds only the current job per capture (for get_job/cancel),
    but `all_jobs()` returns the full history so the jobs view shows every run.
    """
    from autosplat.config import load_config

    runner = JobRunner()
    capture_path = tmp_path / "2026-05-17_g3_3"
    capture_path.mkdir()
    (capture_path / "clip.mp4").write_bytes(b"fake")
    cfg = load_config(include_xdg=False)

    with patch("autosplat.webui.jobs_runner._run_pipeline_thread"):
        await runner.start_job("2026-05-17_g3_3", capture_path, cfg)
        await runner.start_job("2026-05-17_g3_3", capture_path, cfg)

    assert len(runner.all_jobs()) == 2
    assert runner.get_job("2026-05-17_g3_3") is runner.all_jobs()[-1]


def test_list_captures_overlays_running_jobrunner_state(tmp_path: Path) -> None:
    """SF-G2-9: a WebUI job running via JobRunner must show as running.

    WebUI jobs run `run_pipeline()` in a thread and never write
    WatcherState/state.json — without the JobRunner overlay the capture
    would resolve to 'idle'.
    """
    capture_dir = tmp_path / "2026-05-17_g2_9"
    capture_dir.mkdir()

    runner = JobRunner()
    runner._jobs["2026-05-17_g2_9"] = JobState(
        capture_id="2026-05-17_g2_9", status="running"
    )

    assert list_captures(tmp_path)[0].status == "idle"
    assert list_captures(tmp_path, runner)[0].status == "running"


def test_list_captures_overlays_failed_jobrunner_state(tmp_path: Path) -> None:
    """SF-G2-9: a failed WebUI job surfaces its status + error reason."""
    capture_dir = tmp_path / "2026-05-17_g2_9_fail"
    capture_dir.mkdir()

    runner = JobRunner()
    runner._jobs["2026-05-17_g2_9_fail"] = JobState(
        capture_id="2026-05-17_g2_9_fail", status="failed", error="boom"
    )

    capture = list_captures(tmp_path, runner)[0]
    assert capture.status == "failed"
    assert capture.reason == "boom"


# ---------------------------------------------------------------------------
# SF-G3-1 — JobState wall-clock timestamps (V112-1)
# ---------------------------------------------------------------------------


def test_jobstate_started_at_walltime_is_iso_utc() -> None:
    """SF-G3-1: JobState must record a wall-clock ISO timestamp at creation."""
    job = JobState(capture_id="2026-05-20_test", status="queued")
    assert isinstance(job.started_at_walltime, str)
    assert ISO_UTC_RE.match(job.started_at_walltime), (
        f"expected ISO-Z timestamp, got {job.started_at_walltime!r}"
    )


def test_jobstate_finished_at_walltime_starts_none() -> None:
    """SF-G3-1: finished_at_walltime is unset until the job terminates."""
    job = JobState(capture_id="2026-05-20_test", status="queued")
    assert job.finished_at_walltime is None


@pytest.mark.anyio
async def test_cancel_sets_finished_at_walltime(tmp_path: Path) -> None:
    """SF-G3-1: cancelling a job stamps a wall-clock finished_at."""
    runner = JobRunner()
    capture_path = tmp_path / "2026-05-20_cancel"
    capture_path.mkdir()
    (capture_path / "clip.mp4").write_bytes(b"fake")

    from autosplat.config import load_config

    cfg = load_config(include_xdg=False)
    with patch("autosplat.webui.jobs_runner._run_pipeline_thread"):
        job = await runner.start_job("2026-05-20_cancel", capture_path, cfg)

    job.status = "running"
    await runner.cancel_job("2026-05-20_cancel")
    assert job.finished_at_walltime is not None
    assert ISO_UTC_RE.match(job.finished_at_walltime)


def test_list_captures_done_jobrunner_propagates_finished_at(tmp_path: Path) -> None:
    """SF-G3-1: a done WebUI job must surface its wall-clock finished_at_walltime.

    Before the fix: done jobs fell through to the ply-not-None branch with
    finished_at=None, so Recent Captures rendered "—" for WebUI-completed runs.
    """
    capture_dir = tmp_path / "2026-05-20_done"
    capture_dir.mkdir()
    (capture_dir / "scene.ply").write_bytes(b"fake-ply")

    runner = JobRunner()
    job = JobState(capture_id="2026-05-20_done", status="done")
    job.finished_at_walltime = "2026-05-20T12:34:56Z"
    runner._jobs["2026-05-20_done"] = job

    capture = list_captures(tmp_path, runner)[0]
    assert capture.status == "done"
    assert capture.finished_at == "2026-05-20T12:34:56Z"


# ---------------------------------------------------------------------------
# SF-NEW-3 — Recent captures secondary sort by finished_at (V112-1)
# ---------------------------------------------------------------------------


def test_list_captures_sorts_same_day_by_finished_at_desc(tmp_path: Path) -> None:
    """SF-NEW-3: two captures from the same day must order by finished_at DESC.

    Filesystem iteration order is alphabetical by capture name; without an
    explicit secondary sort, the UI shows captures in name-order within a day,
    which feels arbitrary. We want the most recently finished one on top.
    """
    # Names chosen so the wall-clock order disagrees with alpha-DESC by name:
    # "aaa" finished LATER than "zzz" — only a true timestamp sort gets this right.
    later_by_time = tmp_path / "2026-05-20_aaa"
    later_by_time.mkdir()
    (later_by_time / "scene.ply").write_bytes(b"fake")
    earlier_by_time = tmp_path / "2026-05-20_zzz"
    earlier_by_time.mkdir()
    (earlier_by_time / "scene.ply").write_bytes(b"fake")

    runner = JobRunner()
    later_job = JobState(capture_id="2026-05-20_aaa", status="done")
    later_job.finished_at_walltime = "2026-05-20T20:00:00Z"
    earlier_job = JobState(capture_id="2026-05-20_zzz", status="done")
    earlier_job.finished_at_walltime = "2026-05-20T08:00:00Z"
    runner._jobs[later_job.capture_id] = later_job
    runner._jobs[earlier_job.capture_id] = earlier_job

    captures = list_captures(tmp_path, runner)
    ids = [c.id for c in captures]
    assert ids.index("2026-05-20_aaa") < ids.index("2026-05-20_zzz"), (
        f"expected later finished_at first, got order {ids}"
    )
