# SPDX-License-Identifier: AGPL-3.0-or-later

"""v1.4 Auto-Bisection-Rescue — unit tests.

Most tests stay pure-Python by monkeypatching subprocess calls and pipeline
helpers. Real-binary tests live behind needs_ffmpeg / needs_colmap markers.
"""

from __future__ import annotations

from pathlib import Path

from autosplat.bisection import (
    BisectionClip,
    build_ffmpeg_cut_command,
)

# ─── Slice 1: build_ffmpeg_cut_command (pure string assertion) ──────────────


def test_build_ffmpeg_cut_command_basic() -> None:
    cmd = build_ffmpeg_cut_command(
        Path("/tmp/in.mp4"),
        start_s=30.0,
        duration_s=60.0,
        output=Path("/tmp/out.mp4"),
    )
    assert cmd[0] == "ffmpeg"
    assert "/tmp/in.mp4" in cmd
    assert "/tmp/out.mp4" in cmd
    # -ss before -i for fast seek
    assert cmd.index("-ss") < cmd.index("-i")
    assert "30.0" in cmd or "30.000" in cmd
    assert "60.0" in cmd or "60.000" in cmd


def test_build_ffmpeg_cut_command_uses_stream_copy() -> None:
    cmd = build_ffmpeg_cut_command(Path("/tmp/in.mp4"), 0.0, 10.0, Path("/tmp/out.mp4"))
    # Stream copy — no re-encode (fast + bit-exact in the kept range)
    assert "-c" in cmd
    assert cmd[cmd.index("-c") + 1] == "copy"
    # No video filter
    assert "-vf" not in cmd


def test_build_ffmpeg_cut_command_clamps_negative_start() -> None:
    cmd = build_ffmpeg_cut_command(Path("/tmp/in.mp4"), -5.0, 30.0, Path("/tmp/out.mp4"))
    # -ss value follows the -ss flag
    ss_value = cmd[cmd.index("-ss") + 1]
    assert float(ss_value) == 0.0


# ─── BisectionClip dataclass sanity ─────────────────────────────────────────


def test_bisection_clip_is_frozen() -> None:
    clip = BisectionClip(
        source_video=Path("/tmp/in.mp4"),
        clip_id="0_1",
        start_s=30.0,
        duration_s=60.0,
        path=Path("/tmp/rescue/clips/in_part_0_1.mp4"),
    )
    import dataclasses

    assert dataclasses.is_dataclass(clip)
    # Frozen dataclasses raise on attribute assignment
    import pytest

    with pytest.raises(dataclasses.FrozenInstanceError):
        clip.clip_id = "9"  # type: ignore[misc]
