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


def test_prune_removes_rescue_probes_and_brush_dataset(tmp_path: Path) -> None:
    # Regression: INTERMEDIATE_SUBDIRS listed only frames/colmap/training, so
    # 11,2 GB of bisection-rescue leftovers were never reclaimed. C1: the
    # rescue *probes* are where that mass sits — `rescue/clips/*.mp4` are the
    # bisected capture's recorded origin and are kept (see
    # test_prune_keeps_rescue_clips).
    capture = tmp_path / "2026-07-01_x"
    (capture / "output").mkdir(parents=True)
    (capture / "output" / "scene.ply").write_bytes(b"ply\n")
    for sub in ("frames", "colmap", "brush_dataset"):
        (capture / sub).mkdir()
        (capture / sub / "blob").write_bytes(b"x" * 10)
    (capture / "rescue" / "probes").mkdir(parents=True)
    (capture / "rescue" / "probes" / "blob").write_bytes(b"x" * 10)

    result = prune_intermediates(capture)

    assert {p.name for p in result.removed} == {"frames", "colmap", "probes", "brush_dataset"}
    assert result.bytes_reclaimed == 40
    assert not (capture / "rescue" / "probes").exists()
    assert not (capture / "brush_dataset").exists()
    assert (capture / "output" / "scene.ply").exists()


def test_prune_keeps_rescue_clips(tmp_path: Path) -> None:
    """C1: `rescue/clips/*.mp4` are the leaf-clip sources a bisected capture
    records in pipeline.log as its origin — `add-video`/`resume` re-extract
    from them. `cleanup-rescue` keeps them by default and CAPTURE-GUIDE says
    dropping them breaks both; the automatic paths must not override that."""
    capture = tmp_path / "2026-07-01_x"
    (capture / "output").mkdir(parents=True)
    (capture / "output" / "scene.ply").write_bytes(b"ply\n")
    (capture / "rescue" / "clips").mkdir(parents=True)
    (capture / "rescue" / "clips" / "0.mp4").write_bytes(b"m" * 10)
    (capture / "rescue" / "probes" / "0").mkdir(parents=True)
    (capture / "rescue" / "probes" / "0" / "blob").write_bytes(b"x" * 10)

    prune_intermediates(capture)

    assert (capture / "rescue" / "clips" / "0.mp4").exists()
    assert not (capture / "rescue" / "probes").exists()


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
        # Age the intermediates too, matching the PLY: a real capture this
        # old has no recently-touched files either, unlike a rebuild in
        # flight (see test_sweep_expired_skips_recently_active_capture).
        os.utime(capture / "output" / "scene.ply", (mtime, mtime))
        os.utime(capture / "colmap" / "blob", (mtime, mtime))

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


def test_sweep_expired_skips_recently_active_capture(tmp_path: Path) -> None:
    # Finding 1 (task 7 review): reclaim eligibility only looks at PLY mtime,
    # which stays old for the whole duration of an add-video/resume rebuild.
    # A capture otherwise fully past grace, but with a colmap/ file touched
    # seconds ago (an in-flight rebuild), must survive the sweep.
    import os
    from datetime import UTC, datetime, timedelta

    now = datetime(2026, 7, 28, 12, 0, tzinfo=UTC)
    capture = tmp_path / "2026-06-01_rebuilding"
    (capture / "output").mkdir(parents=True)
    ply = capture / "output" / "scene.ply"
    ply.write_bytes(b"ply\n")
    old = (now - timedelta(days=40)).timestamp()
    os.utime(ply, (old, old))
    (capture / "colmap").mkdir()
    blob = capture / "colmap" / "blob"
    blob.write_bytes(b"x" * 5)
    recent = (now - timedelta(seconds=5)).timestamp()
    os.utime(blob, (recent, recent))

    results = cleanup.sweep_expired(tmp_path, grace_days=30, now=now)

    assert results == []
    assert (capture / "colmap").exists()


def test_sweep_expired_reclaims_when_everything_aged(tmp_path: Path) -> None:
    # Same shape of capture as above, but with the colmap/ file also aged —
    # no rebuild in flight, so it must be reclaimed.
    import os
    from datetime import UTC, datetime, timedelta

    now = datetime(2026, 7, 28, 12, 0, tzinfo=UTC)
    capture = tmp_path / "2026-06-01_stale"
    (capture / "output").mkdir(parents=True)
    ply = capture / "output" / "scene.ply"
    ply.write_bytes(b"ply\n")
    old = (now - timedelta(days=40)).timestamp()
    os.utime(ply, (old, old))
    (capture / "colmap").mkdir()
    blob = capture / "colmap" / "blob"
    blob.write_bytes(b"x" * 5)
    os.utime(blob, (old, old))

    results = cleanup.sweep_expired(tmp_path, grace_days=30, now=now)

    assert len(results) == 1
    assert not (capture / "colmap").exists()


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


def test_prune_intermediates_rejects_target_outside_capture_dir(tmp_path: Path) -> None:
    """Round-2 review finding: `targets=` was accepted verbatim with no
    check it actually sits under `capture_dir` — an unvalidated deletion
    parameter on a function that calls `shutil.rmtree` on its contents. A
    caller mistake (or a future refactor) handing in an unrelated path
    would rmtree it without complaint."""
    capture_dir = _make_done_capture(tmp_path)
    outside = tmp_path / "not-part-of-this-capture"
    outside.mkdir()
    (outside / "precious.txt").write_bytes(b"do not delete me")

    with pytest.raises(ValueError, match="not inside capture_dir"):
        prune_intermediates(capture_dir, targets=[outside])

    assert outside.exists()
    assert (outside / "precious.txt").exists()


def test_prune_intermediates_accepts_target_nested_under_capture_dir(tmp_path: Path) -> None:
    """The containment check must not reject legitimate nested targets —
    only `capture_dir` itself and anything outside it."""
    capture_dir = _make_done_capture(tmp_path)
    nested = capture_dir / "colmap" / "sparse" / "0"

    result = prune_intermediates(capture_dir, targets=[nested])

    assert result.removed == [nested]
    assert not nested.exists()
