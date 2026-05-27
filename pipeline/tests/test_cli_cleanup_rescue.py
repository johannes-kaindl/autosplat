# SPDX-License-Identifier: AGPL-3.0-or-later

"""CLI `autosplat cleanup-rescue` — v1.4.5 disk-reclaim helper."""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from autosplat.cli import app

runner = CliRunner()


def _make_rescue_layout(tmp_path: Path) -> Path:
    """Build a capture-dir with rescue/clips/*.mp4 and rescue/probes/<id>/
    artefacts — same layout autosplat rescue produces on success."""
    capture_dir = tmp_path / "2026-05-27_cap"
    (capture_dir / "rescue" / "clips").mkdir(parents=True)
    (capture_dir / "rescue" / "probes" / "0" / "frames").mkdir(parents=True)
    (capture_dir / "rescue" / "probes" / "0" / "colmap" / "sparse").mkdir(parents=True)
    (capture_dir / "rescue" / "probes" / "1" / "frames").mkdir(parents=True)
    (capture_dir / "rescue" / "clips" / "v_part_0.mp4").write_bytes(b"\x00" * 1024)
    (capture_dir / "rescue" / "clips" / "v_part_1.mp4").write_bytes(b"\x00" * 1024)
    (capture_dir / "rescue" / "probes" / "0" / "frames" / "frame_00001.jpg").write_bytes(
        b"\xff" * 2048
    )
    (capture_dir / "rescue" / "probes" / "1" / "frames" / "frame_00001.jpg").write_bytes(
        b"\xff" * 2048
    )
    return capture_dir


def test_cleanup_rescue_removes_probes_keeps_clips_by_default(tmp_path: Path) -> None:
    capture_dir = _make_rescue_layout(tmp_path)

    result = runner.invoke(app, ["cleanup-rescue", str(capture_dir)])

    assert result.exit_code == 0, result.output
    # probes/ gone
    assert not (capture_dir / "rescue" / "probes").exists()
    # clips/ kept (default --keep-clips)
    assert (capture_dir / "rescue" / "clips" / "v_part_0.mp4").exists()


def test_cleanup_rescue_remove_clips_also_drops_clips(tmp_path: Path) -> None:
    capture_dir = _make_rescue_layout(tmp_path)

    result = runner.invoke(
        app, ["cleanup-rescue", str(capture_dir), "--remove-clips"]
    )

    assert result.exit_code == 0, result.output
    assert not (capture_dir / "rescue" / "probes").exists()
    assert not (capture_dir / "rescue" / "clips").exists()


def test_cleanup_rescue_dry_run_touches_nothing(tmp_path: Path) -> None:
    capture_dir = _make_rescue_layout(tmp_path)

    result = runner.invoke(
        app, ["cleanup-rescue", str(capture_dir), "--dry-run"]
    )

    assert result.exit_code == 0, result.output
    assert "Would remove" in result.output
    # Everything still there
    assert (capture_dir / "rescue" / "probes" / "0" / "frames").is_dir()
    assert (capture_dir / "rescue" / "clips" / "v_part_0.mp4").exists()


def test_cleanup_rescue_no_rescue_dir_is_noop(tmp_path: Path) -> None:
    capture_dir = tmp_path / "fresh_cap"
    capture_dir.mkdir()

    result = runner.invoke(app, ["cleanup-rescue", str(capture_dir)])

    assert result.exit_code == 0, result.output
    assert "nothing to clean" in result.output.lower()
