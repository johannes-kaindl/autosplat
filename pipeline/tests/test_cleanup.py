# SPDX-License-Identifier: AGPL-3.0-or-later

"""Shared prune-intermediates core — used by the CLI and the WebUI button."""

from __future__ import annotations

from pathlib import Path

import pytest

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
