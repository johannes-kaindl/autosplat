"""Unit tests for the ffmpeg command-builder and fps-target logic."""

from __future__ import annotations

from pathlib import Path

import pytest

from autosplat.preprocess import (
    VideoMeta,
    _count_skipped_frames,
    build_ffmpeg_command,
    compute_fps_target,
)


def test_build_ffmpeg_command_has_required_flags(tmp_path: Path) -> None:
    video = tmp_path / "in.mp4"
    frames = tmp_path / "frames"
    cmd = build_ffmpeg_command(video, frames, fps_target=5.0)
    assert cmd[0] == "ffmpeg"
    assert "-i" in cmd
    assert str(video) in cmd
    assert any("fps=5.0000" in part for part in cmd)
    # Output template
    assert any(str(frames / "frame_%05d.jpg") == part for part in cmd)


def test_compute_fps_target_from_duration() -> None:
    meta = VideoMeta(duration_s=50.0, fps=30.0, width=1920, height=1080, nb_frames=1500)
    # 250 frames over 50s = 5 fps (well below 1/0.2 = 5 fps boundary)
    fps = compute_fps_target(meta, target_frames=250, min_distance_sec=0.2)
    assert fps == pytest.approx(5.0)


def test_compute_fps_target_clamped_by_min_distance() -> None:
    meta = VideoMeta(duration_s=10.0, fps=60.0, width=1920, height=1080, nb_frames=600)
    # 1000 frames / 10s = 100 fps; min_distance=0.1 caps at 10 fps
    fps = compute_fps_target(meta, target_frames=1000, min_distance_sec=0.1)
    assert fps == pytest.approx(10.0)


def test_compute_fps_target_clamped_by_source_fps() -> None:
    meta = VideoMeta(duration_s=10.0, fps=24.0, width=1920, height=1080, nb_frames=240)
    # 1000 / 10 = 100, min_distance=0 → ∞, but source fps caps at 24
    fps = compute_fps_target(meta, target_frames=1000, min_distance_sec=0.0)
    assert fps == pytest.approx(24.0)


def test_compute_fps_target_zero_duration_raises() -> None:
    meta = VideoMeta(duration_s=0.0, fps=30.0, width=100, height=100, nb_frames=0)
    with pytest.raises(ValueError):
        compute_fps_target(meta, target_frames=100, min_distance_sec=0.1)


# ─── _count_skipped_frames (Phase 6 / Spec §5) ──────────────────────────────


def test_count_skipped_frames_empty_stderr_returns_zero() -> None:
    assert _count_skipped_frames("") == 0
    assert _count_skipped_frames("nothing relevant\nhere") == 0


def test_count_skipped_frames_parses_skipped_n_frames() -> None:
    stderr = "frame= 100\n[ffmpeg] skipped 5 frames\n"
    assert _count_skipped_frames(stderr) == 5


def test_count_skipped_frames_parses_progress_line() -> None:
    stderr = "frame=  250 fps= 30 size= 1024kB time=00:00:08.33 skipped: 12\n"
    assert _count_skipped_frames(stderr) == 12


def test_count_skipped_frames_returns_max_across_lines() -> None:
    """ffmpeg may emit cumulative + final counts — take the largest."""
    stderr = "skipped: 3\nframe= 200\nskipped 17 frames\n"
    assert _count_skipped_frames(stderr) == 17
