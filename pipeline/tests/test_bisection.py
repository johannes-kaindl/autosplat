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
    cut_video,
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


# ─── Slice 2: cut_video (mocked subprocess) ─────────────────────────────────


def test_cut_video_calls_ffmpeg(monkeypatch, tmp_path: Path) -> None:
    """cut_video runs the built command via subprocess.run and returns the output path."""
    import subprocess as sp

    calls: list[list[str]] = []

    def fake_run(cmd, capture_output=False, text=False, check=False):
        calls.append(list(cmd))
        # Touch the output file so any downstream existence check passes.
        Path(cmd[-1]).write_bytes(b"\x00")
        return sp.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

    monkeypatch.setattr(sp, "run", fake_run)

    video = tmp_path / "source.mp4"
    video.write_bytes(b"\x00")
    output = tmp_path / "out.mp4"

    result = cut_video(video, start_s=10.0, duration_s=20.0, output=output)

    assert result == output
    assert output.exists()
    assert len(calls) == 1
    assert calls[0][0] == "ffmpeg"
    assert calls[0][cmd_index(calls[0], "-ss") + 1] == "10.000"
    assert calls[0][cmd_index(calls[0], "-t") + 1] == "20.000"


def test_cut_video_propagates_subprocess_error(monkeypatch, tmp_path: Path) -> None:
    import subprocess as sp

    def fake_run(cmd, capture_output=False, text=False, check=False):
        raise sp.CalledProcessError(returncode=1, cmd=cmd, stderr="broken")

    monkeypatch.setattr(sp, "run", fake_run)

    video = tmp_path / "v.mp4"
    video.write_bytes(b"\x00")
    import pytest

    with pytest.raises(sp.CalledProcessError):
        cut_video(video, 0.0, 10.0, tmp_path / "o.mp4")


def cmd_index(cmd: list[str], flag: str) -> int:
    return cmd.index(flag)
