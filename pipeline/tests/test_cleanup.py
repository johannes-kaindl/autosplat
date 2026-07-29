# SPDX-License-Identifier: AGPL-3.0-or-later

"""Shared prune-intermediates core — used by the CLI and the WebUI button."""

from __future__ import annotations

from pathlib import Path

import pytest

from autosplat import cleanup
from autosplat.cleanup import NotExported, prune_intermediates


def _make_done_capture(tmp_path: Path) -> Path:
    capture_dir = tmp_path / "2026-05-27_cap"
    (capture_dir / "output").mkdir(parents=True)
    (capture_dir / "output" / "scene.ply").write_bytes(b"PLY" * 1000)
    (capture_dir / "frames").mkdir()
    (capture_dir / "frames" / "frame_00001.jpg").write_bytes(b"\xff" * 2048)
    (capture_dir / "colmap" / "sparse" / "0").mkdir(parents=True)
    (capture_dir / "colmap" / "database.db").write_bytes(b"\x00" * 4096)
    (capture_dir / "training").mkdir()
    (capture_dir / "training" / "step_1000.ply").write_bytes(b"PLY" * 500)
    return capture_dir


def test_prune_intermediates_removes_dirs_and_reports_bytes(tmp_path: Path) -> None:
    capture_dir = _make_done_capture(tmp_path)

    result = prune_intermediates(capture_dir)

    assert not (capture_dir / "frames").exists()
    assert not (capture_dir / "colmap").exists()
    assert not (capture_dir / "training").exists()
    assert (capture_dir / "output" / "scene.ply").exists()
    assert result.bytes_reclaimed == 2048 + 4096 + 1500
    assert {p.name for p in result.removed} == {"frames", "colmap", "training"}


def test_prune_intermediates_dry_run_touches_nothing(tmp_path: Path) -> None:
    capture_dir = _make_done_capture(tmp_path)

    result = prune_intermediates(capture_dir, dry_run=True)

    assert (capture_dir / "frames").is_dir()
    assert (capture_dir / "colmap").is_dir()
    assert (capture_dir / "training").is_dir()
    assert result.bytes_reclaimed > 0


def test_prune_intermediates_raises_when_export_not_done(tmp_path: Path) -> None:
    capture_dir = tmp_path / "2026-05-27_unfinished"
    (capture_dir / "frames").mkdir(parents=True)

    with pytest.raises(NotExported):
        prune_intermediates(capture_dir)

    assert (capture_dir / "frames").exists()


def test_prune_intermediates_nothing_to_remove(tmp_path: Path) -> None:
    capture_dir = tmp_path / "2026-05-27_already_clean"
    (capture_dir / "output").mkdir(parents=True)
    (capture_dir / "output" / "scene.ply").write_bytes(b"PLY")

    result = prune_intermediates(capture_dir)

    assert result.removed == []
    assert result.bytes_reclaimed == 0


def test_prune_removes_rescue_and_brush_dataset(tmp_path: Path) -> None:
    # Regression: INTERMEDIATE_SUBDIRS listed only frames/colmap/training, so
    # 11,2 GB of bisection-rescue leftovers were never reclaimed.
    capture = tmp_path / "2026-07-01_x"
    (capture / "output").mkdir(parents=True)
    (capture / "output" / "scene.ply").write_bytes(b"ply\n")
    for sub in ("frames", "colmap", "rescue", "brush_dataset"):
        (capture / sub).mkdir()
        (capture / sub / "blob").write_bytes(b"x" * 10)

    result = prune_intermediates(capture)

    assert {p.name for p in result.removed} == {"frames", "colmap", "rescue", "brush_dataset"}
    assert result.bytes_reclaimed == 40
    assert not (capture / "rescue").exists()
    assert not (capture / "brush_dataset").exists()
    assert (capture / "output" / "scene.ply").exists()


def test_prune_removes_share_tmp_but_keeps_bundles(tmp_path: Path) -> None:
    capture = tmp_path / "2026-07-01_x"
    (capture / "output").mkdir(parents=True)
    (capture / "output" / "scene.ply").write_bytes(b"ply\n")
    (capture / "share" / "_tmp").mkdir(parents=True)
    (capture / "share" / "tok").mkdir()

    prune_intermediates(capture)

    assert not (capture / "share" / "_tmp").exists()
    assert (capture / "share" / "tok").exists()


def test_prune_is_idempotent(tmp_path: Path) -> None:
    capture = tmp_path / "2026-07-01_x"
    (capture / "output").mkdir(parents=True)
    (capture / "output" / "scene.ply").write_bytes(b"ply\n")
    (capture / "colmap").mkdir()

    prune_intermediates(capture)
    second = prune_intermediates(capture)

    assert second.removed == []
    assert second.bytes_reclaimed == 0


def test_sweep_expired_reclaims_only_past_grace(tmp_path: Path) -> None:
    import os
    from datetime import UTC, datetime, timedelta

    now = datetime(2026, 7, 28, 12, 0, tzinfo=UTC)
    for name, age in (("2026-07-01_fresh", 2), ("2026-06-01_old", 40)):
        capture = tmp_path / name
        (capture / "output").mkdir(parents=True)
        (capture / "output" / "scene.ply").write_bytes(b"ply\n")
        (capture / "colmap").mkdir()
        (capture / "colmap" / "blob").write_bytes(b"x" * 5)
        mtime = (now - timedelta(days=age)).timestamp()
        os.utime(capture / "output" / "scene.ply", (mtime, mtime))

    results = cleanup.sweep_expired(tmp_path, grace_days=30, now=now)

    assert len(results) == 1
    assert (tmp_path / "2026-07-01_fresh" / "colmap").exists()
    assert not (tmp_path / "2026-06-01_old" / "colmap").exists()


def test_prune_partial_failures_are_reported(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Finding 2: Partial failures have no test. Verify that when shutil.rmtree
    # fails on one target, it's reported in .failed, others are still removed,
    # and bytes_reclaimed counts only successful targets.
    capture = tmp_path / "2026-07-01_x"
    (capture / "output").mkdir(parents=True)
    (capture / "output" / "scene.ply").write_bytes(b"ply\n")
    (capture / "frames").mkdir()
    (capture / "frames" / "blob").write_bytes(b"x" * 20)
    (capture / "colmap").mkdir()
    (capture / "colmap" / "blob").write_bytes(b"x" * 30)
    (capture / "training").mkdir()
    (capture / "training" / "blob").write_bytes(b"x" * 40)

    import shutil

    original_rmtree = shutil.rmtree

    def rmtree_with_failure(path: str | Path) -> None:
        path_obj = Path(path)
        # Fail only on colmap
        if path_obj.name == "colmap":
            raise OSError("Permission denied")
        original_rmtree(path_obj)

    monkeypatch.setattr(shutil, "rmtree", rmtree_with_failure)

    result = prune_intermediates(capture)

    # colmap should be in failed, not in removed
    assert capture / "colmap" in result.failed
    assert capture / "colmap" not in result.removed

    # frames and training should be removed
    assert capture / "frames" not in result.failed
    assert capture / "frames" in result.removed
    assert capture / "training" not in result.failed
    assert capture / "training" in result.removed

    # colmap should still exist (removal failed)
    assert (capture / "colmap").exists()
    # frames and training should be gone
    assert not (capture / "frames").exists()
    assert not (capture / "training").exists()

    # bytes_reclaimed should only count frames (20) + training (40), NOT colmap (30)
    assert result.bytes_reclaimed == 60


def test_sweep_expired_handles_enumeration_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Finding 1: sweep_expired must never raise, even if find_capture_dirs fails.
    # Verify it returns [] and logs the error instead of propagating OSError.
    from datetime import UTC, datetime

    from autosplat import lifecycle

    now = datetime(2026, 7, 28, 12, 0, tzinfo=UTC)

    def find_capture_dirs_failing(_: Path) -> list[Path]:
        raise OSError("Permission denied during directory enumeration")

    monkeypatch.setattr(lifecycle, "find_capture_dirs", find_capture_dirs_failing)

    # Should not raise, should return empty list
    result = cleanup.sweep_expired(tmp_path, grace_days=30, now=now)

    assert result == []
