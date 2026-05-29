# SPDX-License-Identifier: AGPL-3.0-or-later

"""Tests for the progress.json single-source-of-truth helpers."""

from __future__ import annotations

from pathlib import Path

from autosplat.progress import ProgressState, read_progress, write_progress


def test_write_then_read_round_trips(tmp_path: Path) -> None:
    state = ProgressState(
        stage="train",
        elapsed_s=1204.0,
        est_pct=0.5017,
        eta_s=2400.0,
        updated_at="2026-05-29T09:29:52Z",
        step=12000,
        total_steps=30000,
        psnr=24.8,
    )
    write_progress(tmp_path, state)

    loaded = read_progress(tmp_path)
    assert loaded == state


def test_write_creates_progress_json_at_capture_root(tmp_path: Path) -> None:
    state = ProgressState(
        stage="train",
        elapsed_s=2.0,
        est_pct=0.0,
        eta_s=2400.0,
        updated_at="2026-05-29T09:09:50Z",
    )
    write_progress(tmp_path, state)
    assert (tmp_path / "progress.json").is_file()


def test_optional_metric_fields_default_to_none(tmp_path: Path) -> None:
    """A time-only heartbeat (plateau disabled) carries no step/psnr."""
    state = ProgressState(
        stage="train",
        elapsed_s=10.0,
        est_pct=0.004,
        eta_s=2400.0,
        updated_at="2026-05-29T09:10:00Z",
    )
    write_progress(tmp_path, state)
    loaded = read_progress(tmp_path)
    assert loaded is not None
    assert loaded.step is None
    assert loaded.total_steps is None
    assert loaded.psnr is None


def test_read_missing_file_returns_none(tmp_path: Path) -> None:
    assert read_progress(tmp_path) is None


def test_read_corrupt_json_returns_none(tmp_path: Path) -> None:
    (tmp_path / "progress.json").write_text("{not valid json")
    assert read_progress(tmp_path) is None


def test_write_is_atomic_no_leftover_tmp(tmp_path: Path) -> None:
    """Atomic write leaves only progress.json behind — no .tmp dross that a
    concurrent reader could trip over."""
    state = ProgressState(
        stage="train",
        elapsed_s=1.0,
        est_pct=0.0,
        eta_s=100.0,
        updated_at="2026-05-29T09:00:00Z",
    )
    write_progress(tmp_path, state)
    leftovers = [p.name for p in tmp_path.iterdir() if p.name != "progress.json"]
    assert leftovers == []


def test_write_overwrites_previous_state(tmp_path: Path) -> None:
    first = ProgressState("train", 1.0, 0.0, 100.0, "2026-05-29T09:00:00Z")
    second = ProgressState("train", 50.0, 0.5, 100.0, "2026-05-29T09:00:50Z")
    write_progress(tmp_path, first)
    write_progress(tmp_path, second)
    assert read_progress(tmp_path) == second
