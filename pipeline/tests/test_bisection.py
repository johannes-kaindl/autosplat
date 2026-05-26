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
    probe_clip,
)
from autosplat.config import load_config
from autosplat.preprocess import PreprocessResult
from autosplat.sfm import SfmResult

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


# ─── Slice 3: probe_clip (monkeypatched preprocess + SfM) ───────────────────


def _clip_at(tmp_path: Path, clip_id: str = "0") -> BisectionClip:
    p = tmp_path / "rescue" / "clips" / f"v_part_{clip_id}.mp4"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"\x00")
    return BisectionClip(
        source_video=tmp_path / "v.mp4",
        clip_id=clip_id,
        start_s=0.0,
        duration_s=120.0,
        path=p,
    )


def _stub_preprocess(frames_kept: int):
    """Returns a stub for preprocess.extract_frames that fakes N kept frames."""

    def _stub(video, frames_dir, cfg):
        frames_dir.mkdir(parents=True, exist_ok=True)
        return PreprocessResult(
            frames_dir=frames_dir,
            extracted_count=frames_kept,
            kept_count=frames_kept,
            rejected_blur=0,
            duration_s=0.1,
        )

    return _stub


def _stub_sfm(cams: int, points: int):
    def _stub(frames_dir, workspace, cfg):
        workspace.mkdir(parents=True, exist_ok=True)
        sparse = workspace / "sparse"
        sparse.mkdir(parents=True, exist_ok=True)
        return SfmResult(
            workspace=workspace,
            database_path=workspace / "database.db",
            sparse_dir=sparse,
            cameras_registered=cams,
            points=points,
            duration_s=0.1,
        )

    return _stub


def test_probe_clip_passes_on_good_sfm(monkeypatch, tmp_path: Path) -> None:
    cfg = load_config(include_xdg=False)
    clip = _clip_at(tmp_path)
    workspace = tmp_path / "rescue" / "probes" / clip.clip_id

    import autosplat.bisection as bm

    monkeypatch.setattr(bm, "_run_preprocess", _stub_preprocess(frames_kept=100))
    monkeypatch.setattr(bm, "_run_sfm", _stub_sfm(cams=80, points=10000))

    assert probe_clip(clip, workspace, cfg) is True
    assert (workspace / "frames").exists()
    assert (workspace / "colmap" / "sparse").exists()


def test_probe_clip_fails_below_ratio(monkeypatch, tmp_path: Path) -> None:
    cfg = load_config(include_xdg=False)
    clip = _clip_at(tmp_path, "1")
    workspace = tmp_path / "rescue" / "probes" / clip.clip_id

    import autosplat.bisection as bm

    monkeypatch.setattr(bm, "_run_preprocess", _stub_preprocess(frames_kept=100))
    # ratio 0.1 < default 0.5 → fail
    monkeypatch.setattr(bm, "_run_sfm", _stub_sfm(cams=10, points=20000))

    assert probe_clip(clip, workspace, cfg) is False


def test_probe_clip_uses_exhaustive_matcher(monkeypatch, tmp_path: Path) -> None:
    """Probes always run with exhaustive — sequential is unreliable on shorts."""
    cfg = load_config(include_xdg=False)
    assert cfg.colmap.matcher == "sequential"

    clip = _clip_at(tmp_path, "2")
    workspace = tmp_path / "rescue" / "probes" / clip.clip_id

    seen_matchers: list[str] = []

    def capture_sfm(frames_dir, ws, colmap_cfg):
        seen_matchers.append(colmap_cfg.matcher)
        ws.mkdir(parents=True, exist_ok=True)
        (ws / "sparse").mkdir(parents=True, exist_ok=True)
        return SfmResult(
            workspace=ws,
            database_path=ws / "db.db",
            sparse_dir=ws / "sparse",
            cameras_registered=80,
            points=10000,
            duration_s=0.0,
        )

    import autosplat.bisection as bm

    monkeypatch.setattr(bm, "_run_preprocess", _stub_preprocess(frames_kept=100))
    monkeypatch.setattr(bm, "_run_sfm", capture_sfm)

    probe_clip(clip, workspace, cfg)
    assert seen_matchers == ["exhaustive"]


def test_probe_clip_returns_false_on_preprocess_error(monkeypatch, tmp_path: Path) -> None:
    """A subprocess error during probe is logged + treated as a failed probe."""
    cfg = load_config(include_xdg=False)
    clip = _clip_at(tmp_path, "3")
    workspace = tmp_path / "rescue" / "probes" / clip.clip_id

    def raise_preprocess(video, frames_dir, cfg):
        raise RuntimeError("ffmpeg blew up")

    import autosplat.bisection as bm

    monkeypatch.setattr(bm, "_run_preprocess", raise_preprocess)

    assert probe_clip(clip, workspace, cfg) is False
