# SPDX-License-Identifier: AGPL-3.0-or-later

"""Tests for the async job runner."""

from __future__ import annotations

import subprocess
import threading
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from autosplat.webui.jobs_runner import JobRunner, JobState, _find_source_video
from autosplat.webui.state import list_captures


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
