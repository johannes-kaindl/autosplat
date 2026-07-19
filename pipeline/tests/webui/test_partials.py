# SPDX-License-Identifier: AGPL-3.0-or-later

"""Tests for live-progress partials (v1.6.0 brush metrics)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastapi import FastAPI
from starlette.testclient import TestClient

from autosplat.progress import ProgressState, write_progress

# ─── pure view-model helper ────────────────────────────────────────────────


def _state(**kw: object) -> ProgressState:
    base: dict[str, object] = {
        "stage": "train",
        "elapsed_s": 1204.0,
        "est_pct": 0.50,
        "eta_s": 2400.0,
        "updated_at": "2026-05-29T09:29:52Z",
    }
    base.update(kw)
    return ProgressState(**base)  # type: ignore[arg-type]


def test_build_progress_view_formats_time_and_pct() -> None:
    from autosplat.webui.progress_view import build_progress_view

    state = _state()
    now = datetime.fromisoformat("2026-05-29T09:29:57+00:00")  # 5 s later
    view = build_progress_view(state, now)

    assert view.pct == 50
    assert view.elapsed_str == "20:04"  # 1204 s
    assert view.eta_remaining_str == "19:56"  # 2400 - 1204 = 1196 s
    assert view.updated_ago_s == 5
    assert view.stalled is False


def test_build_progress_view_flags_stall_when_update_is_old() -> None:
    from autosplat.webui.progress_view import build_progress_view

    state = _state()
    updated = datetime.fromisoformat("2026-05-29T09:29:52+00:00")
    now = updated + timedelta(seconds=120)  # > 90 s threshold
    view = build_progress_view(state, now)

    assert view.stalled is True
    assert view.updated_ago_s == 120


def test_build_progress_view_passes_through_eval_metrics() -> None:
    from autosplat.webui.progress_view import build_progress_view

    state = _state(step=12000, total_steps=30000, psnr=24.8)
    now = datetime.fromisoformat("2026-05-29T09:29:54+00:00")
    view = build_progress_view(state, now)

    assert view.step == 12000
    assert view.total_steps == 30000
    assert view.psnr == 24.8


def test_eta_remaining_never_negative_past_estimate() -> None:
    from autosplat.webui.progress_view import build_progress_view

    state = _state(elapsed_s=2500.0, est_pct=0.99)  # past the 2400 s estimate
    now = datetime.fromisoformat("2026-05-29T09:29:54+00:00")
    view = build_progress_view(state, now)

    assert view.eta_remaining_str == "0:00"


# ─── HTTP rendering ─────────────────────────────────────────────────────────


def _running_capture(app: FastAPI, tmp_path: Path, name: str) -> Path:
    capture_dir = tmp_path / name
    (capture_dir / "frames").mkdir(parents=True)
    (capture_dir / "pipeline.log").write_text('{"event": "train.brush.start"}\n')
    app.state.cfg.paths.captures_dir = tmp_path
    return capture_dir


def test_brush_partial_renders_live_bar_and_elapsed(app: FastAPI, tmp_path: Path) -> None:
    capture_dir = _running_capture(app, tmp_path, "2026-05-29_live")
    write_progress(
        capture_dir,
        ProgressState(
            stage="train",
            elapsed_s=1204.0,
            est_pct=0.50,
            eta_s=2400.0,
            updated_at=datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z"),
            total_steps=30000,
        ),
    )

    with TestClient(app) as client:
        response = client.get("/partials/capture/2026-05-29_live/brush")

    assert response.status_code == 200
    body = response.text
    assert "50" in body  # percent
    assert "20:04" in body  # elapsed mm:ss
    assert "updated" in body.lower()  # liveness label


def test_brush_partial_shows_stall_warning_for_old_update(app: FastAPI, tmp_path: Path) -> None:
    capture_dir = _running_capture(app, tmp_path, "2026-05-29_stalled")
    old = (datetime.now(UTC) - timedelta(seconds=300)).isoformat(timespec="seconds")
    write_progress(
        capture_dir,
        ProgressState(
            stage="train",
            elapsed_s=600.0,
            est_pct=0.25,
            eta_s=2400.0,
            updated_at=old.replace("+00:00", "Z"),
        ),
    )

    with TestClient(app) as client:
        response = client.get("/partials/capture/2026-05-29_stalled/brush")

    assert response.status_code == 200
    assert "stalled" in response.text.lower()


def test_brush_partial_shows_eval_tiles_when_present(app: FastAPI, tmp_path: Path) -> None:
    capture_dir = _running_capture(app, tmp_path, "2026-05-29_eval")
    write_progress(
        capture_dir,
        ProgressState(
            stage="train",
            elapsed_s=1204.0,
            est_pct=0.50,
            eta_s=2400.0,
            updated_at=datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z"),
            step=12000,
            total_steps=30000,
            psnr=24.8,
        ),
    )

    with TestClient(app) as client:
        response = client.get("/partials/capture/2026-05-29_eval/brush")

    body = response.text
    assert "psnr" in body.lower()
    assert "24.8" in body
    assert "12,000" in body  # step rendered with thousands separator


def test_brush_partial_hides_eval_tiles_when_absent(app: FastAPI, tmp_path: Path) -> None:
    """Plateau disabled (the default) → no step/psnr in the file → no fake tiles."""
    capture_dir = _running_capture(app, tmp_path, "2026-05-29_noeval")
    write_progress(
        capture_dir,
        ProgressState(
            stage="train",
            elapsed_s=1204.0,
            est_pct=0.50,
            eta_s=2400.0,
            updated_at=datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z"),
            total_steps=30000,
        ),
    )

    with TestClient(app) as client:
        response = client.get("/partials/capture/2026-05-29_noeval/brush")

    assert response.status_code == 200
    assert "psnr" not in response.text.lower()


def test_brush_partial_warming_up_without_progress_file(app: FastAPI, tmp_path: Path) -> None:
    """No progress.json yet (Brush just launched) → a 'warming up' placeholder,
    still polling, never a 5xx."""
    _running_capture(app, tmp_path, "2026-05-29_warm")

    with TestClient(app) as client:
        response = client.get("/partials/capture/2026-05-29_warm/brush")

    assert response.status_code == 200
    assert "warming up" in response.text.lower()
    assert "/partials/capture/2026-05-29_warm/brush" in response.text  # still polling


# ─── all-stages liveness (log mtime) ───────────────────────────────────────


def test_last_activity_age_s_from_log_mtime(tmp_path: Path) -> None:
    import os

    from autosplat.webui.state import last_activity_age_s

    log = tmp_path / "pipeline.log"
    log.write_text("x\n")
    os.utime(log, (1000.0, 1000.0))  # mtime = 1000

    assert last_activity_age_s(tmp_path, now=1042.0) == 42


def test_last_activity_age_s_none_without_log(tmp_path: Path) -> None:
    from autosplat.webui.state import last_activity_age_s

    assert last_activity_age_s(tmp_path, now=1042.0) is None


def test_last_activity_age_s_uses_colmap_database_mtime_when_newer(tmp_path: Path) -> None:
    """The mapper stage writes nothing to pipeline.log for long stretches, but
    COLMAP is still actively touching its own workspace — database.db mtime
    must count as activity even when the JSONL log has gone stale."""
    import os

    from autosplat.webui.state import last_activity_age_s

    log = tmp_path / "pipeline.log"
    log.write_text("x\n")
    os.utime(log, (1000.0, 1000.0))  # stale — no JSONL event during matching

    colmap_dir = tmp_path / "colmap"
    colmap_dir.mkdir()
    db = colmap_dir / "database.db"
    db.write_text("db")
    os.utime(db, (1030.0, 1030.0))  # COLMAP is actively writing here

    assert last_activity_age_s(tmp_path, now=1042.0) == 12


def test_last_activity_age_s_uses_colmap_sparse_mtime_when_newer(tmp_path: Path) -> None:
    """Same for the mapper's incremental sparse-model output."""
    import os

    from autosplat.webui.state import last_activity_age_s

    log = tmp_path / "pipeline.log"
    log.write_text("x\n")
    os.utime(log, (1000.0, 1000.0))

    sparse_dir = tmp_path / "colmap" / "sparse" / "0"
    sparse_dir.mkdir(parents=True)
    images_bin = sparse_dir / "images.bin"
    images_bin.write_bytes(b"x")
    os.utime(images_bin, (1035.0, 1035.0))  # mapper just wrote a reconstruction

    assert last_activity_age_s(tmp_path, now=1042.0) == 7


def test_liveness_partial_shows_activity_pulse(app: FastAPI, tmp_path: Path) -> None:
    """Any running capture (e.g. COLMAP, which has no brush card) gets a generic
    'last activity Xs ago' pulse so a silent-but-healthy stage isn't a dead screen."""
    from autosplat.webui.jobs_runner import JobState

    _running_capture(app, tmp_path, "2026-05-29_colmap")
    app.state.job_runner._jobs["2026-05-29_colmap"] = JobState(
        capture_id="2026-05-29_colmap", status="running"
    )

    with TestClient(app) as client:
        response = client.get("/partials/capture/2026-05-29_colmap/liveness")

    assert response.status_code == 200
    body = response.text
    assert "activity" in body.lower()
    assert "/partials/capture/2026-05-29_colmap/liveness" in body  # keeps polling


def test_liveness_partial_triggers_page_refresh_when_run_finished(
    app: FastAPI, tmp_path: Path
) -> None:
    """A run that finishes while the detail page is open must break the stale
    'running' render. The detail page only ever polls /liveness (the stepper,
    badge and action buttons are rendered once). So when the capture is no
    longer running, the liveness poll returns `HX-Refresh: true`, telling HTMX
    to reload the whole page into the real 'done' view (SF-LIVE-REFRESH)."""
    capture_dir = tmp_path / "2026-07-10_done"
    (capture_dir / "output").mkdir(parents=True)
    (capture_dir / "output" / "scene.ply").write_bytes(b"ply\n")
    (capture_dir / "pipeline.log").write_text('{"event": "pipeline.done"}\n')
    app.state.cfg.paths.captures_dir = tmp_path

    with TestClient(app) as client:
        response = client.get("/partials/capture/2026-07-10_done/liveness")

    assert response.status_code == 200
    assert response.headers.get("HX-Refresh") == "true"


def test_liveness_partial_no_refresh_while_running(app: FastAPI, tmp_path: Path) -> None:
    """The guard against a refresh loop: while a job is genuinely running, the
    liveness poll must keep swapping the pulse in place and NOT ask for a full
    page reload."""
    from autosplat.webui.jobs_runner import JobState

    capture_dir = tmp_path / "2026-05-29_run"
    (capture_dir / "frames").mkdir(parents=True)
    (capture_dir / "pipeline.log").write_text('{"event": "train.brush.start"}\n')
    app.state.cfg.paths.captures_dir = tmp_path
    app.state.job_runner._jobs["2026-05-29_run"] = JobState(
        capture_id="2026-05-29_run", status="running"
    )

    with TestClient(app) as client:
        response = client.get("/partials/capture/2026-05-29_run/liveness")

    assert response.status_code == 200
    assert response.headers.get("HX-Refresh") is None
    assert "activity" in response.text.lower()


def test_brush_card_gated_to_train_stage(app: FastAPI, tmp_path: Path) -> None:
    """During COLMAP (stage=sfm) the detail page must NOT show the brush card —
    that would read as 'brush warming up' while SfM is actually running."""
    capture_dir = tmp_path / "2026-05-29_sfm_stage"
    (capture_dir / "frames").mkdir(parents=True)
    (capture_dir / "colmap").mkdir()
    (capture_dir / "pipeline.log").write_text('{"event": "sfm.mapper.start"}\n')
    app.state.cfg.paths.captures_dir = tmp_path

    from unittest.mock import patch

    from autosplat.watcher import InProgress, WatcherState

    state = WatcherState()
    state.in_progress = InProgress(path=str(capture_dir), started_at="t", stage="sfm", detail=None)
    with (
        patch("autosplat.webui.state._load_watcher_state", return_value=state),
        TestClient(app) as client,
    ):
        response = client.get("/captures/2026-05-29_sfm_stage")

    assert response.status_code == 200
    assert "gaussian training" not in response.text.lower()
