# SPDX-License-Identifier: AGPL-3.0-or-later

"""Unit tests for the ffmpeg command-builder and fps-target logic."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from autosplat.config import PreprocessConfig
from autosplat.preprocess import (
    VideoMeta,
    _count_skipped_frames,
    build_ffmpeg_command,
    compute_fps_target,
    extract_frames_from_many,
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


# ─── build_ffmpeg_command — prefix support for multi-video captures ────────


def test_build_ffmpeg_command_with_prefix_in_output_template(tmp_path: Path) -> None:
    """Multi-video extraction needs unique per-video frame names. A `prefix`
    parameter slots into the ffmpeg output template — e.g. `pass_a` →
    frames/pass_a_frame_%05d.jpg — so frames from different sources don't
    clobber each other."""
    video = tmp_path / "pass_a.mp4"
    frames = tmp_path / "frames"
    cmd = build_ffmpeg_command(video, frames, fps_target=5.0, prefix="pass_a")
    assert any(str(frames / "pass_a_frame_%05d.jpg") == part for part in cmd)


def test_build_ffmpeg_command_default_prefix_is_empty(tmp_path: Path) -> None:
    """The old (single-video) call shape must keep producing `frame_%05d.jpg`
    so existing captures stay intact."""
    video = tmp_path / "in.mp4"
    frames = tmp_path / "frames"
    cmd = build_ffmpeg_command(video, frames, fps_target=5.0)
    assert any(str(frames / "frame_%05d.jpg") == part for part in cmd)


# ─── extract_frames_from_many — multi-video orchestrator ───────────────────


def _preprocess_cfg() -> PreprocessConfig:
    return PreprocessConfig(target_frames=250, blur_threshold=100.0, min_frame_distance_sec=0.2)


def test_extract_frames_from_many_uses_per_video_prefix(tmp_path: Path) -> None:
    """Each video gets its stem as the prefix so frame names stay unique
    across sources; the blur filter then runs once over the combined set."""
    v1 = tmp_path / "pass_a.mp4"
    v2 = tmp_path / "pass_b.mp4"
    v1.write_bytes(b"\0")
    v2.write_bytes(b"\0")
    frames_dir = tmp_path / "frames"

    def fake_run(cmd, **_):
        # Simulate ffmpeg dropping one file per video into frames_dir.
        prefix = "pass_a" if "pass_a" in " ".join(cmd) else "pass_b"
        (frames_dir / f"{prefix}_frame_00001.jpg").write_bytes(b"\xff\xd8")
        return MagicMock(stderr="", returncode=0)

    fake_meta = VideoMeta(duration_s=50.0, fps=30.0, width=1920, height=1080, nb_frames=1500)
    with (
        patch("autosplat.preprocess.probe_video", return_value=fake_meta),
        patch("autosplat.preprocess.subprocess.run", side_effect=fake_run),
        patch("autosplat.preprocess.laplacian_blur_score", return_value=999.0),
    ):
        result = extract_frames_from_many([v1, v2], frames_dir, _preprocess_cfg())

    names = sorted(p.name for p in frames_dir.glob("*.jpg"))
    assert names == ["pass_a_frame_00001.jpg", "pass_b_frame_00001.jpg"]
    assert result.extracted_count == 2
    assert result.kept_count == 2


def test_extract_frames_from_many_aggregates_blur_rejections(tmp_path: Path) -> None:
    """Aggregated PreprocessResult sums extracted + rejected across videos."""
    v1 = tmp_path / "v1.mp4"
    v2 = tmp_path / "v2.mp4"
    v1.write_bytes(b"\0")
    v2.write_bytes(b"\0")
    frames_dir = tmp_path / "frames"

    blur_scores: list[float] = []  # sharp, blur, sharp, blur

    def fake_run(cmd, **_):
        prefix = "v1" if "v1.mp4" in " ".join(cmd) else "v2"
        (frames_dir / f"{prefix}_frame_00001.jpg").write_bytes(b"\xff\xd8")
        (frames_dir / f"{prefix}_frame_00002.jpg").write_bytes(b"\xff\xd8")
        return MagicMock(stderr="", returncode=0)

    def fake_blur(_path):
        # Two videos × two frames; one blurry per video.
        blur_scores.append(1.0)
        return [999.0, 1.0, 999.0, 1.0][len(blur_scores) - 1]

    fake_meta = VideoMeta(duration_s=10.0, fps=30.0, width=1920, height=1080, nb_frames=300)
    with (
        patch("autosplat.preprocess.probe_video", return_value=fake_meta),
        patch("autosplat.preprocess.subprocess.run", side_effect=fake_run),
        patch("autosplat.preprocess.laplacian_blur_score", side_effect=fake_blur),
    ):
        result = extract_frames_from_many([v1, v2], frames_dir, _preprocess_cfg())

    assert result.extracted_count == 4
    assert result.rejected_blur == 2
    assert result.kept_count == 2


def test_extract_frames_from_many_single_video_matches_legacy_layout(tmp_path: Path) -> None:
    """Calling the multi-video extractor with one video must still produce
    the bare `frame_NNNNN.jpg` naming the rest of the pipeline (capture-dir
    scanning, resume) already keys on."""
    video = tmp_path / "only.mp4"
    video.write_bytes(b"\0")
    frames_dir = tmp_path / "frames"

    def fake_run(cmd, **_):
        (frames_dir / "frame_00001.jpg").write_bytes(b"\xff\xd8")
        return MagicMock(stderr="", returncode=0)

    fake_meta = VideoMeta(duration_s=50.0, fps=30.0, width=1920, height=1080, nb_frames=1500)
    with (
        patch("autosplat.preprocess.probe_video", return_value=fake_meta),
        patch("autosplat.preprocess.subprocess.run", side_effect=fake_run),
        patch("autosplat.preprocess.laplacian_blur_score", return_value=999.0),
    ):
        extract_frames_from_many([video], frames_dir, _preprocess_cfg())

    assert (frames_dir / "frame_00001.jpg").exists()
    assert not (frames_dir / "only_frame_00001.jpg").exists()
