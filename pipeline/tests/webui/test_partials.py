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
