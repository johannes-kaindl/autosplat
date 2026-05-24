# SPDX-License-Identifier: AGPL-3.0-or-later

"""Phase-2 watcher tests — state roundtrip, crash-recovery, queue semantics.

Aims to validate spec §11.2 acceptance criteria:
  - `autosplat watch <folder>` processes drops in FIFO order
  - Process survives single-capture failures (no hard crash)
  - State file consistent across kill/restart
  - Two files in inbox are processed serially
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path

import pytest

from autosplat.config import RetryConfig
from autosplat.quality import QualityGateFailure
from autosplat.watcher import (
    CompletedEntry,
    FailedEntry,
    InProgress,
    RetryRecord,
    WatchDaemon,
    WatcherState,
    reconcile_failure,
    recover_state,
)

# ─── State load / save / roundtrip ──────────────────────────────────────────


def test_load_returns_empty_when_missing(tmp_path: Path) -> None:
    state = WatcherState.load(tmp_path / "no-such.json")
    assert state.queue == []
    assert state.in_progress is None
    assert state.completed == []
    assert state.failed == []


def test_save_creates_parent_dirs(tmp_path: Path) -> None:
    target = tmp_path / "nested" / "deeper" / "state.json"
    state = WatcherState(state_file=target)
    state.save()
    assert target.exists()


def test_roundtrip_preserves_all_lists(tmp_path: Path) -> None:
    target = tmp_path / "state.json"
    state = WatcherState(state_file=target)
    state.queue = ["a.mp4", "b.mp4"]
    state.in_progress = InProgress(path="c.mp4", started_at="2026-01-01T00:00:00Z", stage="sfm")
    state.completed = [
        CompletedEntry(path="d.mp4", output_ply="d.ply", duration_s=12.5, finished_at="t1"),
    ]
    state.failed = [
        FailedEntry(path="e.mp4", failed_at="t2", reason="OOM", stage="train"),
    ]
    state.save()

    reloaded = WatcherState.load(target)
    assert reloaded.queue == ["a.mp4", "b.mp4"]
    assert reloaded.in_progress is not None
    assert reloaded.in_progress.path == "c.mp4"
    assert reloaded.in_progress.stage == "sfm"
    assert len(reloaded.completed) == 1
    assert reloaded.completed[0].output_ply == "d.ply"
    assert len(reloaded.failed) == 1
    assert reloaded.failed[0].reason == "OOM"


def test_atomic_save_no_partial_file_after_crash_simulation(tmp_path: Path) -> None:
    """tmp+rename leaves either old or new content — never a half-written file."""
    target = tmp_path / "state.json"
    target.write_text(json.dumps({"queue": ["pre-existing.mp4"]}), encoding="utf-8")

    state = WatcherState.load(target)
    state.queue = ["new.mp4"]
    state.save()

    # File must always be valid JSON, no .tmp sibling left behind.
    json.loads(target.read_text(encoding="utf-8"))  # raises if corrupt
    leftover = [p for p in tmp_path.glob(".state.*.tmp")]
    assert leftover == []


def test_load_tolerates_corrupt_state_file(tmp_path: Path) -> None:
    """A garbage state.json shouldn't crash startup — just log + start fresh."""
    target = tmp_path / "state.json"
    target.write_text("{not valid json", encoding="utf-8")

    state = WatcherState.load(target)
    assert state.queue == []
    assert state.in_progress is None


# ─── Crash recovery ─────────────────────────────────────────────────────────


def test_recover_state_moves_in_progress_to_failed(tmp_path: Path) -> None:
    state = WatcherState(state_file=tmp_path / "state.json")
    state.in_progress = InProgress(
        path="/captures/v1.mp4",
        started_at="2026-01-01T00:00:00Z",
        stage="training",
    )
    state.save()

    n = recover_state(state)
    assert n == 1
    assert state.in_progress is None
    assert len(state.failed) == 1
    assert state.failed[0].path == "/captures/v1.mp4"
    assert state.failed[0].reason == "interrupted"
    assert state.failed[0].stage == "training"


def test_recover_state_is_noop_when_no_in_progress(tmp_path: Path) -> None:
    state = WatcherState(state_file=tmp_path / "state.json")
    state.queue = ["x.mp4"]
    n = recover_state(state)
    assert n == 0
    assert state.queue == ["x.mp4"]
    assert state.failed == []


def test_recover_state_persists_change(tmp_path: Path) -> None:
    target = tmp_path / "state.json"
    state = WatcherState(state_file=target)
    state.in_progress = InProgress(path="/captures/v1.mp4", started_at="x", stage="sfm")
    state.save()

    recover_state(state)

    fresh = WatcherState.load(target)
    assert fresh.in_progress is None
    assert len(fresh.failed) == 1


# ─── Enqueue dedup ──────────────────────────────────────────────────────────


def test_enqueue_dedups_against_existing_queue(tmp_path: Path) -> None:
    state = WatcherState(state_file=tmp_path / "state.json")
    assert state.enqueue(Path("a.mp4")) is True
    assert state.enqueue(Path("a.mp4")) is False
    assert state.queue == ["a.mp4"]


def test_enqueue_dedups_against_in_progress(tmp_path: Path) -> None:
    state = WatcherState(state_file=tmp_path / "state.json")
    state.in_progress = InProgress(path="busy.mp4", started_at="x")
    assert state.enqueue(Path("busy.mp4")) is False


def test_pop_next_promotes_to_in_progress(tmp_path: Path) -> None:
    state = WatcherState(state_file=tmp_path / "state.json")
    state.enqueue(Path("a.mp4"))
    state.enqueue(Path("b.mp4"))

    popped = state.pop_next()
    assert popped is not None
    path, override = popped
    assert path == "a.mp4"
    assert override is None  # no retry-hint configured for first try
    assert state.in_progress is not None and state.in_progress.path == "a.mp4"
    assert state.queue == ["b.mp4"]


def test_pop_next_returns_none_on_empty_queue(tmp_path: Path) -> None:
    state = WatcherState(state_file=tmp_path / "state.json")
    assert state.pop_next() is None


# ─── Daemon worker loop — sequencing + failure survival ─────────────────────


def _make_test_folder(tmp_path: Path) -> Path:
    d = tmp_path / "inbox"
    d.mkdir()
    return d


def _make_video(folder: Path, name: str, content: bytes = b"\x00" * 4096) -> Path:
    """Tiny `video` file — content is irrelevant for queue tests."""
    p = folder / name
    p.write_bytes(content)
    return p


def test_daemon_processes_existing_files_sequentially(tmp_path: Path, monkeypatch) -> None:
    """Files dropped before start are picked up; worker processes FIFO."""
    folder = _make_test_folder(tmp_path)
    _make_video(folder, "a.mp4")
    _make_video(folder, "b.mp4")

    # Speed up the size-stability poll for tests.
    monkeypatch.setattr("autosplat.watcher.STABILITY_CHECK_COUNT", 1)
    monkeypatch.setattr("autosplat.watcher.STABILITY_CHECK_INTERVAL_S", 0.01)

    processed: list[Path] = []
    process_lock = threading.Lock()

    def fake_process(p: Path, *, config_override=None) -> dict:
        # Stand in for run_pipeline: it now reports status into WatcherState.
        with process_lock:
            processed.append(p)
        state.begin(p, source_video=p)
        ply = p.with_suffix(".ply")
        state.mark_done(ply, duration_s=0.01)
        return {"output_ply": str(ply), "duration_s": 0.01}

    state = WatcherState(state_file=tmp_path / "state.json")
    daemon = WatchDaemon(folder, state, fake_process)
    daemon.start(process_existing=True)
    try:
        # Give the worker time to drain; idle event will set when queue empty.
        assert daemon.wait_until_idle(timeout=10.0), "Daemon never went idle"
        # Wait briefly for the worker to record completions.
        deadline = time.monotonic() + 2.0
        while len(state.completed) < 2 and time.monotonic() < deadline:
            time.sleep(0.05)
    finally:
        daemon.stop()

    assert len(processed) == 2
    assert processed[0].name == "a.mp4"
    assert processed[1].name == "b.mp4"
    assert len(state.completed) == 2


def test_daemon_survives_processing_failure(tmp_path: Path, monkeypatch) -> None:
    """If `process_fn` raises, the entry lands in `failed` and the worker keeps going."""
    folder = _make_test_folder(tmp_path)
    _make_video(folder, "bad.mp4")
    _make_video(folder, "good.mp4")

    monkeypatch.setattr("autosplat.watcher.STABILITY_CHECK_COUNT", 1)
    monkeypatch.setattr("autosplat.watcher.STABILITY_CHECK_INTERVAL_S", 0.01)

    def fake_process(p: Path, *, config_override=None) -> dict:
        # Stand in for run_pipeline: begin() sets in_progress; on failure it is
        # left intact for reconcile_failure; on success mark_done() records it.
        state.begin(p, source_video=p)
        if p.name == "bad.mp4":
            raise RuntimeError("simulated SfM failure")
        ply = p.with_suffix(".ply")
        state.mark_done(ply, duration_s=0.01)
        return {"output_ply": str(ply), "duration_s": 0.01}

    state = WatcherState(state_file=tmp_path / "state.json")
    daemon = WatchDaemon(folder, state, fake_process)
    daemon.start(process_existing=True)
    try:
        assert daemon.wait_until_idle(timeout=10.0)
        deadline = time.monotonic() + 2.0
        while (len(state.completed) < 1 or len(state.failed) < 1) and time.monotonic() < deadline:
            time.sleep(0.05)
    finally:
        daemon.stop()

    assert any(f.path.endswith("bad.mp4") for f in state.failed)
    assert any(c.path.endswith("good.mp4") for c in state.completed)
    assert state.in_progress is None


def test_daemon_raises_on_missing_folder(tmp_path: Path) -> None:
    state = WatcherState(state_file=tmp_path / "state.json")
    daemon = WatchDaemon(tmp_path / "nope", state, lambda p, **_: {})
    with pytest.raises(FileNotFoundError):
        daemon.start()


def test_daemon_resumes_queue_from_state(tmp_path: Path, monkeypatch) -> None:
    """If state.json has a queue from a previous session, the daemon picks it up.

    Uses a non-existent path so the watchdog Observer can't independently
    re-detect it from the filesystem — the only way the worker sees it is
    via the resumed queue.
    """
    folder = _make_test_folder(tmp_path)
    pre_queued = tmp_path / "queued-but-not-on-disk.mp4"

    state = WatcherState(state_file=tmp_path / "state.json")
    state.queue.append(str(pre_queued))
    state.save()

    monkeypatch.setattr("autosplat.watcher.STABILITY_CHECK_COUNT", 1)
    monkeypatch.setattr("autosplat.watcher.STABILITY_CHECK_INTERVAL_S", 0.01)

    processed: list[Path] = []

    def fake_process(p: Path, *, config_override=None) -> dict:
        processed.append(p)
        return {"output_ply": "x.ply", "duration_s": 0.0}

    daemon = WatchDaemon(folder, state, fake_process)
    daemon.start(process_existing=False)
    try:
        assert daemon.wait_until_idle(timeout=10.0)
        deadline = time.monotonic() + 2.0
        while not state.completed and time.monotonic() < deadline:
            time.sleep(0.05)
    finally:
        daemon.stop()

    assert len(processed) == 1
    assert processed[0].name == "queued-but-not-on-disk.mp4"


# ─── Schema-compat with the pre-Phase-2 state.json shape ────────────────────


# ─── Phase 3 — retry-on-interrupt, reconcile_failure, pruning ───────────────


def _retry_cfg(max_retries: int = 3, enabled: bool = True) -> RetryConfig:
    return RetryConfig(enabled=enabled, max_retries=max_retries)


def test_recover_state_reenqueues_when_retries_remain(tmp_path: Path) -> None:
    state = WatcherState(state_file=tmp_path / "state.json")
    state.in_progress = InProgress(path="/v.mp4", started_at="t", stage="training")
    state.retry_state["/v.mp4"] = RetryRecord(attempts=1)
    state.save()

    n = recover_state(state, retry_cfg=_retry_cfg(max_retries=3))
    assert n == 1
    assert state.in_progress is None
    assert state.queue == ["/v.mp4"]
    assert state.failed == []
    assert state.retry_state["/v.mp4"].attempts == 1  # still 1 — bumped by next pop_next


def test_recover_state_final_fails_when_retries_exhausted(tmp_path: Path) -> None:
    state = WatcherState(state_file=tmp_path / "state.json")
    state.in_progress = InProgress(path="/v.mp4", started_at="t", stage="training")
    state.retry_state["/v.mp4"] = RetryRecord(attempts=3)  # already used 3 attempts
    state.save()

    recover_state(state, retry_cfg=_retry_cfg(max_retries=3))

    assert state.in_progress is None
    assert state.queue == []
    assert len(state.failed) == 1
    assert state.failed[0].reason == "interrupted_max_retries"
    assert state.failed[0].retry_count == 3


def test_recover_state_disabled_retry_marks_failed(tmp_path: Path) -> None:
    state = WatcherState(state_file=tmp_path / "state.json")
    state.in_progress = InProgress(path="/v.mp4", started_at="t", stage="training")
    state.save()

    recover_state(state, retry_cfg=_retry_cfg(enabled=False))
    assert state.in_progress is None
    assert len(state.failed) == 1
    assert state.failed[0].reason == "interrupted"


def test_reconcile_failure_schedules_retry_with_override(tmp_path: Path) -> None:
    state = WatcherState(state_file=tmp_path / "state.json")
    state.in_progress = InProgress(path="/v.mp4", started_at="t", stage="sfm_validation")
    state.save()

    outcome = reconcile_failure(
        state,
        reason="low_camera_ratio: 0.04 < 0.5",
        stage="sfm_validation",
        retry_hint={"colmap": {"matcher": "exhaustive"}},
        retry_cfg=_retry_cfg(max_retries=3),
    )

    assert outcome == "retry"
    assert state.in_progress is None
    assert state.queue == ["/v.mp4"]
    assert state.retry_state["/v.mp4"].next_override == {"colmap": {"matcher": "exhaustive"}}
    assert state.failed == []


def test_reconcile_failure_final_fails_at_max_attempts(tmp_path: Path) -> None:
    state = WatcherState(state_file=tmp_path / "state.json")
    state.in_progress = InProgress(path="/v.mp4", started_at="t", stage="sfm_validation")
    state.retry_state["/v.mp4"] = RetryRecord(attempts=3)
    state.save()

    outcome = reconcile_failure(
        state,
        reason="low_camera_ratio",
        stage="sfm_validation",
        retry_hint={"colmap": {"matcher": "exhaustive"}},
        retry_cfg=_retry_cfg(max_retries=3),
    )

    assert outcome == "failed"
    assert state.queue == []
    assert len(state.failed) == 1
    assert state.failed[0].retry_count == 3
    assert "after 3 attempts" in state.failed[0].reason


def test_pop_next_consumes_pending_override(tmp_path: Path) -> None:
    state = WatcherState(state_file=tmp_path / "state.json")
    state.queue.append("/v.mp4")
    state.retry_state["/v.mp4"] = RetryRecord(
        attempts=1, next_override={"colmap": {"matcher": "exhaustive"}}
    )

    popped = state.pop_next()
    assert popped is not None
    path, override = popped
    assert path == "/v.mp4"
    assert override == {"colmap": {"matcher": "exhaustive"}}
    # Override consumed → retry_state.next_override cleared, attempts bumped
    assert state.retry_state["/v.mp4"].next_override is None
    assert state.retry_state["/v.mp4"].attempts == 2


def test_mark_done_clears_retry_state(tmp_path: Path) -> None:
    state = WatcherState(state_file=tmp_path / "state.json")
    state.queue.append("/v.mp4")
    state.retry_state["/v.mp4"] = RetryRecord(attempts=2)
    state.pop_next()

    state.mark_done(Path("/v.ply"), duration_s=1.0)

    assert "/v.mp4" not in state.retry_state
    assert len(state.completed) == 1


def test_mark_done_prunes_completed_history(tmp_path: Path) -> None:
    state = WatcherState(state_file=tmp_path / "state.json")
    # Seed 50 completed entries
    for i in range(50):
        state.completed.append(
            CompletedEntry(
                path=f"v{i}.mp4", output_ply=f"v{i}.ply", duration_s=1.0, finished_at="t"
            )
        )
    state.queue.append("/v51.mp4")
    state.pop_next()
    state.mark_done(Path("/v51.ply"), duration_s=1.0, max_history=50)

    assert len(state.completed) == 50
    assert state.completed[0].path == "v1.mp4"  # oldest (v0) dropped
    assert state.completed[-1].path == "/v51.mp4"


def test_mark_failed_prunes_failed_history(tmp_path: Path) -> None:
    state = WatcherState(state_file=tmp_path / "state.json")
    for i in range(50):
        state.failed.append(FailedEntry(path=f"v{i}.mp4", failed_at="t", reason="x"))
    state.queue.append("/v51.mp4")
    state.pop_next()
    state.mark_failed("simulated", max_history=50)

    assert len(state.failed) == 50
    assert state.failed[0].path == "v1.mp4"
    assert state.failed[-1].path == "/v51.mp4"


def test_state_roundtrip_includes_retry_state(tmp_path: Path) -> None:
    target = tmp_path / "state.json"
    state = WatcherState(state_file=target)
    state.retry_state["/v.mp4"] = RetryRecord(
        attempts=2,
        last_reason="low_camera_ratio",
        next_override={"colmap": {"matcher": "exhaustive"}},
    )
    state.save()

    reloaded = WatcherState.load(target)
    assert "/v.mp4" in reloaded.retry_state
    assert reloaded.retry_state["/v.mp4"].attempts == 2
    assert reloaded.retry_state["/v.mp4"].next_override == {"colmap": {"matcher": "exhaustive"}}


# ─── Daemon-level retry behaviour ───────────────────────────────────────────


def test_daemon_retries_quality_gate_failure(tmp_path: Path, monkeypatch) -> None:
    """First call raises QualityGateFailure with retry_hint → second call succeeds.

    Verifies end-to-end: quality_gate → reconcile_failure → schedule_retry →
    pop_next emits override → worker passes override → second attempt OK.
    """
    folder = _make_test_folder(tmp_path)
    _make_video(folder, "flaky.mp4")

    monkeypatch.setattr("autosplat.watcher.STABILITY_CHECK_COUNT", 1)
    monkeypatch.setattr("autosplat.watcher.STABILITY_CHECK_INTERVAL_S", 0.01)

    calls: list[dict] = []

    def fake_process(p: Path, *, config_override=None) -> dict:
        # Stand in for run_pipeline: reports status into WatcherState.
        calls.append({"path": str(p), "override": config_override})
        state.begin(p, source_video=p)
        if config_override is None:
            raise QualityGateFailure(
                reason="low_camera_ratio: 0.04 < 0.5",
                stage="sfm_validation",
                retry_hint={"colmap": {"matcher": "exhaustive"}},
                metrics={"cameras_registered": 4, "frames_kept": 106, "matcher": "sequential"},
            )
        ply = p.with_suffix(".ply")
        state.mark_done(ply, duration_s=0.01)
        return {"output_ply": str(ply), "duration_s": 0.01}

    state = WatcherState(state_file=tmp_path / "state.json")
    daemon = WatchDaemon(folder, state, fake_process, retry_cfg=_retry_cfg(max_retries=3))
    daemon.start(process_existing=True)
    try:
        assert daemon.wait_until_idle(timeout=10.0)
        deadline = time.monotonic() + 2.0
        while not state.completed and time.monotonic() < deadline:
            time.sleep(0.05)
    finally:
        daemon.stop()

    assert len(calls) == 2
    assert calls[0]["override"] is None
    assert calls[1]["override"] == {"colmap": {"matcher": "exhaustive"}}
    assert len(state.completed) == 1
    assert state.failed == []  # retried successfully, no permanent failure


def test_daemon_final_fails_after_max_retries(tmp_path: Path, monkeypatch) -> None:
    folder = _make_test_folder(tmp_path)
    _make_video(folder, "hopeless.mp4")

    monkeypatch.setattr("autosplat.watcher.STABILITY_CHECK_COUNT", 1)
    monkeypatch.setattr("autosplat.watcher.STABILITY_CHECK_INTERVAL_S", 0.01)

    def fake_process(p: Path, *, config_override=None) -> dict:
        raise QualityGateFailure(
            reason="low_camera_ratio",
            stage="sfm_validation",
            retry_hint={"colmap": {"matcher": "exhaustive"}},
        )

    state = WatcherState(state_file=tmp_path / "state.json")
    daemon = WatchDaemon(folder, state, fake_process, retry_cfg=_retry_cfg(max_retries=2))
    daemon.start(process_existing=True)
    try:
        assert daemon.wait_until_idle(timeout=10.0)
        deadline = time.monotonic() + 2.0
        while not state.failed and time.monotonic() < deadline:
            time.sleep(0.05)
    finally:
        daemon.stop()

    assert state.completed == []
    assert len(state.failed) == 1
    assert state.failed[0].retry_count == 2  # max_retries == 2


def test_load_pre_phase2_state(tmp_path: Path) -> None:
    """Older state files used 'started' rather than 'started_at' and had no
    'failed' list. The loader should still cope."""
    target = tmp_path / "state.json"
    target.write_text(
        json.dumps(
            {
                "queue": ["q1.mp4"],
                "in_progress": {"path": "ip.mp4", "stage": "training", "started": 1700000000.0},
                "completed": [{"path": "old.mp4", "output_ply": "old.ply", "duration_s": 50.0}],
            }
        ),
        encoding="utf-8",
    )

    state = WatcherState.load(target)
    assert state.queue == ["q1.mp4"]
    assert state.in_progress is not None and state.in_progress.path == "ip.mp4"
    assert state.completed[0].path == "old.mp4"
    assert state.failed == []
