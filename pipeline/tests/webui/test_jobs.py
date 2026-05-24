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


def _read_jsonl(path: Path) -> list[dict]:
    import json
    return [json.loads(line) for line in path.read_text().splitlines() if line]


# ---------------------------------------------------------------------------
# V12-2 — runs.jsonl persistence
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_cancel_appends_runs_jsonl_when_captures_dir_set(tmp_path: Path) -> None:
    """V12-2: cancelling a job persists a JSON line to <capture>/runs.jsonl."""
    capture_dir = tmp_path / "2026-05-20_persist"
    capture_dir.mkdir()
    (capture_dir / "clip.mp4").write_bytes(b"fake")

    runner = JobRunner(captures_dir=tmp_path)

    from autosplat.config import load_config

    cfg = load_config(include_xdg=False)
    with patch("autosplat.webui.jobs_runner._run_pipeline_thread"):
        job = await runner.start_job("2026-05-20_persist", capture_dir, cfg)

    job.status = "running"
    await runner.cancel_job("2026-05-20_persist")

    runs_path = capture_dir / "runs.jsonl"
    assert runs_path.exists(), "runs.jsonl should be created on cancel"
    records = _read_jsonl(runs_path)
    assert len(records) == 1
    assert records[0]["capture_id"] == "2026-05-20_persist"
    assert records[0]["status"] == "cancelled"
    assert ISO_UTC_RE.match(records[0]["started_at"])
    assert ISO_UTC_RE.match(records[0]["finished_at"])


def test_jobrunner_no_persist_when_captures_dir_none(tmp_path: Path) -> None:
    """V12-2: without captures_dir, no runs.jsonl is written — backward compat."""
    capture_dir = tmp_path / "2026-05-20_nopersist"
    capture_dir.mkdir()

    runner = JobRunner()  # no captures_dir
    job = JobState(capture_id="2026-05-20_nopersist", status="cancelled")
    job.finished_at_walltime = "2026-05-20T12:00:00Z"
    runner._persist_job(job)  # should no-op

    assert not (capture_dir / "runs.jsonl").exists()


def test_load_history_populates_from_runs_jsonl(tmp_path: Path) -> None:
    """V12-2: JobRunner.load_history reads runs.jsonl across all captures."""
    import json

    capture_a = tmp_path / "2026-05-20_cap_a"
    capture_a.mkdir()
    (capture_a / "runs.jsonl").write_text(json.dumps({
        "capture_id": "2026-05-20_cap_a",
        "status": "done",
        "started_at": "2026-05-20T08:00:00Z",
        "finished_at": "2026-05-20T08:30:00Z",
        "error": None,
    }) + "\n")
    capture_b = tmp_path / "2026-05-20_cap_b"
    capture_b.mkdir()
    (capture_b / "runs.jsonl").write_text(json.dumps({
        "capture_id": "2026-05-20_cap_b",
        "status": "failed",
        "started_at": "2026-05-20T09:00:00Z",
        "finished_at": "2026-05-20T09:05:00Z",
        "error": "boom",
    }) + "\n")

    runner = JobRunner(captures_dir=tmp_path)
    runner.load_history()

    history = runner.all_jobs()
    assert len(history) == 2
    by_id = {j.capture_id: j for j in history}
    assert by_id["2026-05-20_cap_a"].status == "done"
    assert by_id["2026-05-20_cap_a"].finished_at_walltime == "2026-05-20T08:30:00Z"
    assert by_id["2026-05-20_cap_b"].status == "failed"
    assert by_id["2026-05-20_cap_b"].error == "boom"


def test_load_history_skips_malformed_lines(tmp_path: Path) -> None:
    """V12-2: malformed JSON lines are skipped without breaking the load."""
    capture_dir = tmp_path / "2026-05-20_partial_corrupt"
    capture_dir.mkdir()
    # one bad line, one good line
    (capture_dir / "runs.jsonl").write_text(
        "{not valid json\n"
        '{"capture_id": "2026-05-20_partial_corrupt", "status": "done", '
        '"started_at": "2026-05-20T10:00:00Z", "finished_at": "2026-05-20T10:30:00Z"}\n'
    )

    runner = JobRunner(captures_dir=tmp_path)
    runner.load_history()

    history = runner.all_jobs()
    assert len(history) == 1
    assert history[0].capture_id == "2026-05-20_partial_corrupt"


def test_load_history_no_op_when_captures_dir_missing(tmp_path: Path) -> None:
    """V12-2: load_history on a non-existent captures_dir is a clean no-op."""
    runner = JobRunner(captures_dir=tmp_path / "does-not-exist")
    runner.load_history()
    assert runner.all_jobs() == []


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


# ---------------------------------------------------------------------------
# Liveness reconcile — stale "running" jobs whose worker thread has died
# ---------------------------------------------------------------------------


def test_get_job_reconciles_dead_thread_to_failed() -> None:
    """A job that claims 'running' but whose worker thread has died is
    reconciled to 'failed' — covers hard aborts (suspend/kill mid-run)."""
    import threading

    runner = JobRunner()
    job = JobState(capture_id="2026-05-22_stale", status="running")
    dead = threading.Thread(target=lambda: None)
    dead.start()
    dead.join()  # thread has finished → not alive
    job._thread = dead
    runner._jobs[job.capture_id] = job
    runner._history.append(job)

    reconciled = runner.get_job("2026-05-22_stale")
    assert reconciled is not None
    assert reconciled.status == "failed"
    assert "interrupted" in (reconciled.error or "")


def test_get_job_keeps_running_when_thread_alive() -> None:
    """A job whose worker thread is still alive must stay 'running'."""
    import threading

    runner = JobRunner()
    job = JobState(capture_id="2026-05-22_live", status="running")
    stop = threading.Event()
    alive = threading.Thread(target=stop.wait)
    alive.start()
    job._thread = alive
    runner._jobs[job.capture_id] = job
    try:
        assert runner.get_job("2026-05-22_live").status == "running"
    finally:
        stop.set()
        alive.join()


def test_all_jobs_reconciles_dead_thread() -> None:
    """all_jobs() also reconciles — the jobs view must not show stale 'running'."""
    import threading

    runner = JobRunner()
    job = JobState(capture_id="2026-05-22_stale2", status="running")
    dead = threading.Thread(target=lambda: None)
    dead.start()
    dead.join()
    job._thread = dead
    runner._history.append(job)

    assert runner.all_jobs()[0].status == "failed"


# ---------------------------------------------------------------------------
# start_job_from_video — launch a run for a video that has no capture dir yet
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_start_job_from_video_derives_capture_id(tmp_path: Path) -> None:
    """start_job_from_video derives the capture id (date_stem) from the video."""
    from datetime import date

    from autosplat.config import load_config

    runner = JobRunner()
    video = tmp_path / "herkules.mp4"
    video.write_bytes(b"fake")
    cfg = load_config(include_xdg=False)

    with patch("autosplat.webui.jobs_runner._run_pipeline_thread"):
        job = await runner.start_job_from_video(video, cfg)

    expected_id = f"{date.today().isoformat()}_herkules"
    assert job.capture_id == expected_id
    assert runner._jobs[expected_id] is job
    assert job in runner._history
