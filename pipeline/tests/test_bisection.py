# SPDX-License-Identifier: AGPL-3.0-or-later

"""v1.4 Auto-Bisection-Rescue — unit tests.

Most tests stay pure-Python by monkeypatching subprocess calls and pipeline
helpers. Real-binary tests live behind needs_ffmpeg / needs_colmap markers.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest

from autosplat.bisection import (
    BisectionClip,
    bisect_recursively,
    build_ffmpeg_cut_command,
    cut_video,
    probe_clip,
    rescue_via_bisection,
)
from autosplat.config import load_config
from autosplat.preprocess import PreprocessResult
from autosplat.quality import QualityGateFailure
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


def test_probe_clip_caps_preprocess_target_frames(monkeypatch, tmp_path: Path) -> None:
    """v1.4.1: probes apply cfg.retry.bisect_probe_target_frames as the
    preprocess.target_frames override (cuts exhaustive matcher cost ~4× vs
    the pipeline default of 250)."""
    cfg = load_config(include_xdg=False)
    assert cfg.preprocess.target_frames == 250
    assert cfg.retry.bisect_probe_target_frames == 120

    clip = _clip_at(tmp_path, "pf")
    workspace = tmp_path / "rescue" / "probes" / clip.clip_id

    seen_target_frames: list[int] = []

    def capture_preprocess(video, frames_dir, pp_cfg):
        seen_target_frames.append(pp_cfg.target_frames)
        frames_dir.mkdir(parents=True, exist_ok=True)
        return PreprocessResult(
            frames_dir=frames_dir,
            extracted_count=100,
            kept_count=100,
            rejected_blur=0,
            duration_s=0.0,
        )

    import autosplat.bisection as bm

    monkeypatch.setattr(bm, "_run_preprocess", capture_preprocess)
    monkeypatch.setattr(bm, "_run_sfm", _stub_sfm(cams=80, points=10000))

    probe_clip(clip, workspace, cfg)
    assert seen_target_frames == [120]


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


# ─── Slice 4: bisect_recursively (pure tree walk, monkeypatched cut + probe) ──


def _stub_cut(tmp_path: Path):
    """Returns a stub for cut_video that touches the output file."""

    def _stub(video, start_s, duration_s, output):
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b"\x00")
        return output

    return _stub


def _scripted_probe(decisions: dict[str, bool]):
    """Return a fake probe_fn that consults a clip_id → bool decision table."""

    def _fake(clip: BisectionClip, workspace: Path, cfg) -> bool:
        return decisions.get(clip.clip_id, False)

    return _fake


def test_bisect_recursively_keeps_passing_first_level(monkeypatch, tmp_path: Path) -> None:
    """Both halves pass at depth 1 — return both, no recursion."""
    cfg = load_config(include_xdg=False)
    capture_dir = tmp_path / "capture"
    capture_dir.mkdir()
    video = tmp_path / "v.mp4"
    video.write_bytes(b"\x00")

    import autosplat.bisection as bm

    monkeypatch.setattr(bm, "cut_video", _stub_cut(tmp_path))

    leaves = bisect_recursively(
        video,
        duration_s=240.0,
        capture_dir=capture_dir,
        cfg=cfg,
        _probe_fn=_scripted_probe({"0": True, "1": True}),
    )
    assert {leaf.clip_id for leaf in leaves} == {"0", "1"}
    assert all(leaf.path.exists() for leaf in leaves)


def test_bisect_recursively_recurses_on_failed_branch(monkeypatch, tmp_path: Path) -> None:
    """Half '0' fails → split into '0_0' (passes) + '0_1' (passes). Half '1' passes."""
    cfg = load_config(include_xdg=False)
    capture_dir = tmp_path / "capture"
    capture_dir.mkdir()
    video = tmp_path / "v.mp4"
    video.write_bytes(b"\x00")

    import autosplat.bisection as bm

    monkeypatch.setattr(bm, "cut_video", _stub_cut(tmp_path))

    leaves = bisect_recursively(
        video,
        duration_s=480.0,
        capture_dir=capture_dir,
        cfg=cfg,
        _probe_fn=_scripted_probe({"0": False, "0_0": True, "0_1": True, "1": True}),
    )
    assert {leaf.clip_id for leaf in leaves} == {"0_0", "0_1", "1"}


def test_bisect_recursively_halts_at_max_depth(monkeypatch, tmp_path: Path) -> None:
    """All probes fail; max_depth=2 caps recursion, returns empty list."""
    cfg_obj = load_config(include_xdg=False)
    from autosplat.config import apply_override

    cfg = apply_override(cfg_obj, {"retry": {"bisect_max_depth": 2}})

    capture_dir = tmp_path / "capture"
    capture_dir.mkdir()
    video = tmp_path / "v.mp4"
    video.write_bytes(b"\x00")

    import autosplat.bisection as bm

    monkeypatch.setattr(bm, "cut_video", _stub_cut(tmp_path))

    leaves = bisect_recursively(
        video,
        duration_s=480.0,
        capture_dir=capture_dir,
        cfg=cfg,
        _probe_fn=_scripted_probe({}),  # everything False
    )
    assert leaves == []


def test_bisect_recursively_skips_below_min_clip(monkeypatch, tmp_path: Path) -> None:
    """Source is 90s, min_clip_s=60 → after first split each half is 45s,
    too short to probe — recursion bails before any cut."""
    cfg_obj = load_config(include_xdg=False)
    from autosplat.config import apply_override

    cfg = apply_override(cfg_obj, {"retry": {"bisect_min_clip_s": 60.0}})

    capture_dir = tmp_path / "capture"
    capture_dir.mkdir()
    video = tmp_path / "v.mp4"
    video.write_bytes(b"\x00")

    cut_called: list[tuple[float, float]] = []

    def tracking_cut(video, start_s, duration_s, output):
        cut_called.append((start_s, duration_s))
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b"\x00")
        return output

    import autosplat.bisection as bm

    monkeypatch.setattr(bm, "cut_video", tracking_cut)

    leaves = bisect_recursively(
        video,
        duration_s=90.0,
        capture_dir=capture_dir,
        cfg=cfg,
        _probe_fn=_scripted_probe({}),
    )
    assert leaves == []
    assert cut_called == []  # no cuts ever attempted


def test_bisect_recursively_reports_per_clip_progress_to_state(monkeypatch, tmp_path: Path) -> None:
    """v1.4.1: when a WatcherState is passed in, each per-clip cut/probe
    updates state.in_progress.stage='bisect' and .detail with the clip_id."""
    from autosplat.watcher import InProgress, WatcherState

    cfg = load_config(include_xdg=False)
    capture_dir = tmp_path / "capture"
    capture_dir.mkdir()
    video = tmp_path / "v.mp4"
    video.write_bytes(b"\x00")

    state = WatcherState(state_file=tmp_path / "state.json")
    state.in_progress = InProgress(path=str(capture_dir), started_at="t")

    seen_details: list[tuple[str, str | None]] = []
    orig_update = state.update_stage

    def tracking_update(stage, detail=None):
        seen_details.append((stage, detail))
        orig_update(stage, detail)

    state.update_stage = tracking_update  # type: ignore[method-assign]

    import autosplat.bisection as bm

    monkeypatch.setattr(bm, "cut_video", _stub_cut(tmp_path))

    bisect_recursively(
        video,
        duration_s=240.0,
        capture_dir=capture_dir,
        cfg=cfg,
        _probe_fn=_scripted_probe({"0": True, "1": True}),
        state=state,
    )

    # Both top-level halves are reported before cut+probe
    assert ("bisect", "probing clip 0 (depth 1/3)") in seen_details
    assert ("bisect", "probing clip 1 (depth 1/3)") in seen_details


def test_bisect_recursively_treats_ffmpeg_failure_as_failed_branch(
    monkeypatch, tmp_path: Path
) -> None:
    """If cut_video raises (e.g. ffmpeg blew up on a sub-range), bisection
    must treat that branch as a failed probe and continue with the sibling
    — not crash the whole rescue."""
    import subprocess as sp

    cfg = load_config(include_xdg=False)
    capture_dir = tmp_path / "capture"
    capture_dir.mkdir()
    video = tmp_path / "v.mp4"
    video.write_bytes(b"\x00")

    def failing_cut(video, start_s, duration_s, output):
        # First half (start_s=0) blows up, second half (start_s=120) works
        if start_s == 0.0:
            raise sp.CalledProcessError(returncode=1, cmd=["ffmpeg"], stderr="broken")
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b"\x00")
        return output

    import autosplat.bisection as bm

    monkeypatch.setattr(bm, "cut_video", failing_cut)

    leaves = bisect_recursively(
        video,
        duration_s=240.0,
        capture_dir=capture_dir,
        cfg=cfg,
        _probe_fn=_scripted_probe({"1": True}),  # only the right half can be probed
    )
    assert {leaf.clip_id for leaf in leaves} == {"1"}


# ─── v1.4.1: Smart-split ───────────────────────────────────────────────────


def test_bisect_recursively_uses_midpoint_by_default(monkeypatch, tmp_path: Path) -> None:
    """bisect_smart_split=False (default) → children are exactly equal halves."""
    cfg = load_config(include_xdg=False)
    assert cfg.retry.bisect_smart_split is False

    capture_dir = tmp_path / "capture"
    capture_dir.mkdir()
    video = tmp_path / "v.mp4"
    video.write_bytes(b"\x00")

    cut_calls: list[tuple[float, float]] = []

    def tracking_cut(video, start_s, duration_s, output):
        cut_calls.append((start_s, duration_s))
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b"\x00")
        return output

    import autosplat.bisection as bm

    monkeypatch.setattr(bm, "cut_video", tracking_cut)

    bisect_recursively(
        video,
        duration_s=240.0,
        capture_dir=capture_dir,
        cfg=cfg,
        _probe_fn=_scripted_probe({"0": True, "1": True}),
    )
    assert cut_calls == [(0.0, 120.0), (120.0, 120.0)]


def test_bisect_recursively_smart_split_uses_motion_peak(monkeypatch, tmp_path: Path) -> None:
    """When bisect_smart_split=True and the peak detector returns 90s in a
    240s clip, the cut lands at 90s — children are (90s, 150s) not (120s, 120s)."""
    cfg_obj = load_config(include_xdg=False)
    from autosplat.config import apply_override

    cfg = apply_override(cfg_obj, {"retry": {"bisect_smart_split": True}})

    capture_dir = tmp_path / "capture"
    capture_dir.mkdir()
    video = tmp_path / "v.mp4"
    video.write_bytes(b"\x00")

    cut_calls: list[tuple[float, float]] = []

    def tracking_cut(video, start_s, duration_s, output):
        cut_calls.append((start_s, duration_s))
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b"\x00")
        return output

    import autosplat.bisection as bm

    monkeypatch.setattr(bm, "cut_video", tracking_cut)
    monkeypatch.setattr(bm, "_smart_split_offset", lambda *a, **kw: 90.0)

    bisect_recursively(
        video,
        duration_s=240.0,
        capture_dir=capture_dir,
        cfg=cfg,
        _probe_fn=_scripted_probe({"0": True, "1": True}),
    )
    assert cut_calls == [(0.0, 90.0), (90.0, 150.0)]


def test_bisect_recursively_smart_split_clamps_to_min_clip(monkeypatch, tmp_path: Path) -> None:
    """Smart-split peak too close to start → clamp so both children ≥ min_clip_s."""
    cfg_obj = load_config(include_xdg=False)
    from autosplat.config import apply_override

    cfg = apply_override(
        cfg_obj,
        {"retry": {"bisect_smart_split": True, "bisect_min_clip_s": 60.0}},
    )

    capture_dir = tmp_path / "capture"
    capture_dir.mkdir()
    video = tmp_path / "v.mp4"
    video.write_bytes(b"\x00")

    cut_calls: list[tuple[float, float]] = []

    def tracking_cut(video, start_s, duration_s, output):
        cut_calls.append((start_s, duration_s))
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b"\x00")
        return output

    import autosplat.bisection as bm

    monkeypatch.setattr(bm, "cut_video", tracking_cut)
    # Peak at 10s in a 240s clip — far below min_clip_s=60. Clamp to 60.
    monkeypatch.setattr(bm, "_smart_split_offset", lambda *a, **kw: 10.0)

    bisect_recursively(
        video,
        duration_s=240.0,
        capture_dir=capture_dir,
        cfg=cfg,
        _probe_fn=_scripted_probe({"0": True, "1": True}),
    )
    # First child clamped up to min_clip_s=60; second child gets the rest.
    assert cut_calls == [(0.0, 60.0), (60.0, 180.0)]


def test_bisect_recursively_smart_split_falls_back_when_detector_returns_none(
    monkeypatch, tmp_path: Path
) -> None:
    """When find_motion_peak returns None (flat signal, broken video), bisect
    falls back to midpoint without complaining."""
    cfg_obj = load_config(include_xdg=False)
    from autosplat.config import apply_override

    cfg = apply_override(cfg_obj, {"retry": {"bisect_smart_split": True}})

    capture_dir = tmp_path / "capture"
    capture_dir.mkdir()
    video = tmp_path / "v.mp4"
    video.write_bytes(b"\x00")

    cut_calls: list[tuple[float, float]] = []

    def tracking_cut(video, start_s, duration_s, output):
        cut_calls.append((start_s, duration_s))
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b"\x00")
        return output

    import autosplat.bisection as bm

    monkeypatch.setattr(bm, "cut_video", tracking_cut)
    monkeypatch.setattr(bm, "_smart_split_offset", lambda *a, **kw: None)

    bisect_recursively(
        video,
        duration_s=240.0,
        capture_dir=capture_dir,
        cfg=cfg,
        _probe_fn=_scripted_probe({"0": True, "1": True}),
    )
    assert cut_calls == [(0.0, 120.0), (120.0, 120.0)]


def test_find_motion_peak_returns_none_when_video_unreadable(tmp_path: Path) -> None:
    """find_motion_peak gracefully returns None instead of raising when cv2
    can't open the file (e.g. a 1-byte dummy file used in unit tests)."""
    from autosplat.bisection import find_motion_peak

    bogus = tmp_path / "not_a_video.mp4"
    bogus.write_bytes(b"\x00")
    assert find_motion_peak(bogus, 0.0, 60.0) is None


# ─── Slice 5: rescue_via_bisection (orchestrator) ───────────────────────────


def test_rescue_via_bisection_calls_run_pipeline_with_leaves(monkeypatch, tmp_path: Path) -> None:
    """Successful bisection → run_pipeline_with_adaptive_retry invoked with leaf list."""
    cfg = load_config(include_xdg=False)

    video = tmp_path / "v.mp4"
    video.write_bytes(b"\x00")
    capture_dir = tmp_path / "captures" / "2026-05-26_v"
    capture_dir.mkdir(parents=True)

    import autosplat.bisection as bm

    monkeypatch.setattr(bm, "_probe_duration_s", lambda v: 240.0)
    monkeypatch.setattr(bm, "cut_video", _stub_cut(tmp_path))

    leaves_to_return = [
        BisectionClip(
            source_video=video,
            clip_id="0",
            start_s=0.0,
            duration_s=120.0,
            path=tmp_path / "leaf_0.mp4",
        ),
        BisectionClip(
            source_video=video,
            clip_id="1",
            start_s=120.0,
            duration_s=120.0,
            path=tmp_path / "leaf_1.mp4",
        ),
    ]
    for leaf in leaves_to_return:
        leaf.path.write_bytes(b"\x00")
    monkeypatch.setattr(
        bm,
        "bisect_recursively",
        lambda *a, **kw: leaves_to_return,
    )

    called_with: dict[str, object] = {}

    def fake_run_pipeline(videos, config, **kwargs):
        called_with["videos"] = list(videos)
        called_with["kwargs"] = kwargs
        from autosplat.pipeline import PipelineResult

        return PipelineResult(
            capture_name=capture_dir.name,
            capture_dir=capture_dir,
            output_ply=capture_dir / "output" / "scene.ply",
            metadata_path=capture_dir / "output" / "metadata.json",
            duration_s=1.0,
        )

    monkeypatch.setattr(bm, "_run_pipeline_with_adaptive_retry", fake_run_pipeline)

    result = rescue_via_bisection(video, capture_dir, cfg)

    assert called_with["videos"] == [leaf.path for leaf in leaves_to_return]
    assert called_with["kwargs"]["_bisection_already_attempted"] is True
    assert result.capture_dir == capture_dir


def test_rescue_via_bisection_raises_when_no_leaves(monkeypatch, tmp_path: Path) -> None:
    """Bisection returns no leaves → QualityGateFailure(reason='bisection_exhausted')."""
    cfg = load_config(include_xdg=False)

    video = tmp_path / "v.mp4"
    video.write_bytes(b"\x00")
    capture_dir = tmp_path / "captures" / "v"
    capture_dir.mkdir(parents=True)

    import pytest

    import autosplat.bisection as bm

    monkeypatch.setattr(bm, "_probe_duration_s", lambda v: 240.0)
    monkeypatch.setattr(bm, "bisect_recursively", lambda *a, **kw: [])

    with pytest.raises(QualityGateFailure) as excinfo:
        rescue_via_bisection(video, capture_dir, cfg)
    assert "bisection_exhausted" in str(excinfo.value) or "bisection" in excinfo.value.reason
    assert excinfo.value.retry_hint is None


def test_rescue_via_bisection_skips_when_video_too_short(monkeypatch, tmp_path: Path) -> None:
    """A source video shorter than 2 * min_clip_s is not worth bisecting → raise."""
    cfg = load_config(include_xdg=False)  # default min_clip_s=60.0

    video = tmp_path / "v.mp4"
    video.write_bytes(b"\x00")
    capture_dir = tmp_path / "captures" / "v"
    capture_dir.mkdir(parents=True)

    import pytest

    import autosplat.bisection as bm

    monkeypatch.setattr(bm, "_probe_duration_s", lambda v: 90.0)  # < 2 * 60s

    with pytest.raises(QualityGateFailure) as excinfo:
        rescue_via_bisection(video, capture_dir, cfg)
    assert excinfo.value.retry_hint is None
    assert "short" in excinfo.value.reason or "bisection" in excinfo.value.reason


def test_rescue_via_bisection_wipes_stale_stage_dirs(monkeypatch, tmp_path: Path) -> None:
    """frames/, colmap/, training/ from prior failed attempts are wiped before
    the multi-video re-run (so the combined preprocess starts clean)."""
    cfg = load_config(include_xdg=False)

    video = tmp_path / "v.mp4"
    video.write_bytes(b"\x00")
    capture_dir = tmp_path / "captures" / "v"
    capture_dir.mkdir(parents=True)
    for sub in ("frames", "colmap", "training"):
        d = capture_dir / sub
        d.mkdir()
        (d / "stale.txt").write_text("from_previous_attempt", encoding="utf-8")

    import autosplat.bisection as bm

    monkeypatch.setattr(bm, "_probe_duration_s", lambda v: 240.0)

    leaf = BisectionClip(
        source_video=video,
        clip_id="0",
        start_s=0.0,
        duration_s=120.0,
        path=tmp_path / "leaf.mp4",
    )
    leaf.path.write_bytes(b"\x00")
    monkeypatch.setattr(bm, "bisect_recursively", lambda *a, **kw: [leaf])

    def fake_run_pipeline(videos, config, **kwargs):
        # By the time run_pipeline runs, the stale dirs must already be gone.
        assert not (capture_dir / "frames").exists()
        assert not (capture_dir / "colmap").exists()
        assert not (capture_dir / "training").exists()
        from autosplat.pipeline import PipelineResult

        return PipelineResult(
            capture_name=capture_dir.name,
            capture_dir=capture_dir,
            output_ply=capture_dir / "output" / "scene.ply",
            metadata_path=capture_dir / "output" / "metadata.json",
            duration_s=1.0,
        )

    monkeypatch.setattr(bm, "_run_pipeline_with_adaptive_retry", fake_run_pipeline)

    rescue_via_bisection(video, capture_dir, cfg)


# ─── Slice 7: opt-in real-binary tests ──────────────────────────────────────


def _bisection_e2e_enabled() -> bool:
    return os.environ.get("AUTOSPLAT_BISECTION_E2E", "").lower() in ("1", "true", "yes")


@pytest.mark.skipif(
    not _bisection_e2e_enabled(),
    reason="set AUTOSPLAT_BISECTION_E2E=1 to run",
)
@pytest.mark.needs_ffmpeg
def test_cut_video_actually_runs_ffmpeg(tmp_path: Path) -> None:
    """Real ffmpeg cut against the bundled tiny_video.mp4 fixture."""
    if shutil.which("ffmpeg") is None:
        pytest.skip("ffmpeg not in PATH")
    fixture = Path(__file__).parent / "fixtures" / "tiny_video.mp4"
    if not fixture.exists():
        pytest.skip(f"fixture missing: {fixture}")

    output = tmp_path / "cut.mp4"
    result = cut_video(fixture, start_s=0.0, duration_s=1.0, output=output)
    assert result == output
    assert output.exists()
    assert output.stat().st_size > 0


@pytest.mark.skipif(
    not _bisection_e2e_enabled(),
    reason="set AUTOSPLAT_BISECTION_E2E=1 to run",
)
@pytest.mark.needs_ffmpeg
@pytest.mark.needs_colmap
def test_probe_clip_end_to_end(tmp_path: Path) -> None:
    """Real preprocess + SfM against the tiny_video fixture.

    The fixture is intentionally minimal and may not pass the quality-gate
    on its own; we only assert that probe_clip runs to completion and
    returns a bool — not which value.
    """
    if shutil.which("ffmpeg") is None:
        pytest.skip("ffmpeg not in PATH")
    if shutil.which("colmap") is None:
        pytest.skip("colmap not in PATH")
    fixture = Path(__file__).parent / "fixtures" / "tiny_video.mp4"
    if not fixture.exists():
        pytest.skip(f"fixture missing: {fixture}")

    clip = BisectionClip(
        source_video=fixture,
        clip_id="e2e",
        start_s=0.0,
        duration_s=2.0,
        path=fixture,
    )
    cfg = load_config(include_xdg=False)
    workspace = tmp_path / "probe"

    result = probe_clip(clip, workspace, cfg)
    assert isinstance(result, bool)
    assert (workspace / "frames").exists()
    assert (workspace / "colmap").exists()
