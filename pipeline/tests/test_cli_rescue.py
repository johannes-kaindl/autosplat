# SPDX-License-Identifier: AGPL-3.0-or-later

"""CLI `autosplat rescue` — v1.4.1 manual bisection trigger."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from autosplat.cli import app

runner = CliRunner()


def _success(capture_dir: Path) -> MagicMock:
    res = MagicMock()
    res.capture_dir = capture_dir
    res.output_ply = capture_dir / "output" / "scene.ply"
    res.duration_s = 1.0
    return res


def test_rescue_video_target_creates_fresh_capture(tmp_path: Path) -> None:
    """TARGET is a video file → derive capture_name from stem, then bisect."""
    video = tmp_path / "v.mp4"
    video.write_bytes(b"\0")
    captures_root = tmp_path / "captures"

    with patch(
        "autosplat.cli.rescue_via_bisection",
        return_value=_success(captures_root / "x"),
    ) as rescue:
        result = runner.invoke(
            app,
            ["rescue", str(video), "--output-dir", str(captures_root)],
        )

    assert result.exit_code == 0, result.output
    rescue.assert_called_once()
    # First positional arg is the source video
    assert rescue.call_args.args[0] == video
    # Second positional is the capture_dir, which lives under captures_root
    assert rescue.call_args.args[1].parent == captures_root


def test_rescue_capture_dir_target_scrapes_pipeline_log(tmp_path: Path) -> None:
    """TARGET is an existing capture dir → recover source video from log."""
    capture_dir = tmp_path / "cap"
    capture_dir.mkdir()
    video = tmp_path / "src.mp4"
    video.write_bytes(b"\0")
    (capture_dir / "pipeline.log").write_text(
        '{"event": "pipeline.start", "video": "' + str(video) + '"}\n',
        encoding="utf-8",
    )

    with patch(
        "autosplat.cli.rescue_via_bisection",
        return_value=_success(capture_dir),
    ) as rescue:
        result = runner.invoke(app, ["rescue", str(capture_dir)])

    assert result.exit_code == 0, result.output
    rescue.assert_called_once()
    assert rescue.call_args.args[0] == video
    assert rescue.call_args.args[1] == capture_dir


def test_rescue_capture_dir_without_log_rejects(tmp_path: Path) -> None:
    """capture-dir without pipeline.log and without --video → user error."""
    capture_dir = tmp_path / "cap"
    capture_dir.mkdir()

    with patch("autosplat.cli.rescue_via_bisection") as rescue:
        result = runner.invoke(app, ["rescue", str(capture_dir)])

    assert result.exit_code == 1, result.output
    rescue.assert_not_called()
    assert "no source video recorded" in result.output


def test_rescue_capture_dir_video_override(tmp_path: Path) -> None:
    """--video wins over pipeline.log even when both are present."""
    capture_dir = tmp_path / "cap"
    capture_dir.mkdir()
    log_video = tmp_path / "from_log.mp4"
    log_video.write_bytes(b"\0")
    override = tmp_path / "from_flag.mp4"
    override.write_bytes(b"\0")
    (capture_dir / "pipeline.log").write_text(
        '{"event": "pipeline.start", "video": "' + str(log_video) + '"}\n',
        encoding="utf-8",
    )

    with patch(
        "autosplat.cli.rescue_via_bisection",
        return_value=_success(capture_dir),
    ) as rescue:
        result = runner.invoke(app, ["rescue", str(capture_dir), "--video", str(override)])

    assert result.exit_code == 0, result.output
    assert rescue.call_args.args[0] == override


def test_rescue_invokes_viewer_after_done(tmp_path: Path) -> None:
    """v1.4.2 — after the Done summary, rescue must call viewer.open_in_viewer
    so the user-facing local PLY server actually starts (the blocking happens
    inside open_in_viewer; here we patch it to keep the test fast)."""
    video = tmp_path / "v.mp4"
    video.write_bytes(b"\0")
    captures_root = tmp_path / "captures"
    capture_dir = captures_root / "2026-05-27_v"
    capture_dir.mkdir(parents=True)
    output_ply = capture_dir / "output" / "scene.ply"
    output_ply.parent.mkdir()
    output_ply.write_bytes(b"ply real bytes")

    success = MagicMock()
    success.capture_dir = capture_dir
    success.output_ply = output_ply
    success.duration_s = 1.0

    with (
        patch("autosplat.cli.rescue_via_bisection", return_value=success),
        patch("autosplat.cli.viewer_mod.open_in_viewer") as viewer,
    ):
        result = runner.invoke(
            app, ["rescue", str(video), "--output-dir", str(captures_root)]
        )

    assert result.exit_code == 0, result.output
    viewer.assert_called_once()
    assert viewer.call_args.args[0] == output_ply


def test_rescue_capture_dir_multi_video_requires_explicit_choice(
    tmp_path: Path,
) -> None:
    """A multi-video capture-dir → bisection is single-video only; ask user."""
    capture_dir = tmp_path / "cap"
    capture_dir.mkdir()
    v1 = tmp_path / "a.mp4"
    v2 = tmp_path / "b.mp4"
    v1.write_bytes(b"\0")
    v2.write_bytes(b"\0")
    (capture_dir / "pipeline.log").write_text(
        '{"event": "pipeline.start", "videos": ["' + str(v1) + '", "' + str(v2) + '"]}\n',
        encoding="utf-8",
    )

    with patch("autosplat.cli.rescue_via_bisection") as rescue:
        result = runner.invoke(app, ["rescue", str(capture_dir)])

    assert result.exit_code == 1, result.output
    rescue.assert_not_called()
    assert "single-video only" in result.output
