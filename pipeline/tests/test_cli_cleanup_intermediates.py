# SPDX-License-Identifier: AGPL-3.0-or-later

"""CLI `autosplat cleanup-intermediates` — reclaim disk space held by
frames/colmap/training once a capture has finished exporting."""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from autosplat.cli import app

runner = CliRunner()


def _make_done_capture(tmp_path: Path) -> Path:
    """A finished capture: output/scene.ply plus the stage working dirs
    that are safe to reclaim once export has succeeded."""
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


def test_cleanup_intermediates_removes_frames_colmap_training_when_done(
    tmp_path: Path,
) -> None:
    capture_dir = _make_done_capture(tmp_path)

    result = runner.invoke(app, ["cleanup-intermediates", str(capture_dir)])

    assert result.exit_code == 0, result.output
    assert not (capture_dir / "frames").exists()
    assert not (capture_dir / "colmap").exists()
    assert not (capture_dir / "training").exists()
    # The deliverable stays.
    assert (capture_dir / "output" / "scene.ply").exists()


def test_cleanup_intermediates_dry_run_touches_nothing(tmp_path: Path) -> None:
    capture_dir = _make_done_capture(tmp_path)

    result = runner.invoke(app, ["cleanup-intermediates", str(capture_dir), "--dry-run"])

    assert result.exit_code == 0, result.output
    assert "Would remove" in result.output
    assert (capture_dir / "frames").is_dir()
    assert (capture_dir / "colmap").is_dir()
    assert (capture_dir / "training").is_dir()


def test_cleanup_intermediates_refuses_when_export_not_done(tmp_path: Path) -> None:
    """No output/scene.ply → the capture hasn't finished; `autosplat resume`
    still needs these dirs, so refuse rather than delete."""
    capture_dir = tmp_path / "2026-05-27_unfinished"
    (capture_dir / "frames").mkdir(parents=True)
    (capture_dir / "frames" / "frame_00001.jpg").write_bytes(b"\xff" * 2048)

    result = runner.invoke(app, ["cleanup-intermediates", str(capture_dir)])

    assert result.exit_code != 0
    assert (capture_dir / "frames").exists()


def test_cleanup_intermediates_nothing_to_remove_is_noop(tmp_path: Path) -> None:
    capture_dir = tmp_path / "2026-05-27_already_clean"
    (capture_dir / "output").mkdir(parents=True)
    (capture_dir / "output" / "scene.ply").write_bytes(b"PLY")

    result = runner.invoke(app, ["cleanup-intermediates", str(capture_dir)])

    assert result.exit_code == 0, result.output
    assert "nothing to" in result.output.lower()
