# SPDX-License-Identifier: AGPL-3.0-or-later

"""Unit tests for the ffmpeg command-builder and fps-target logic."""

from __future__ import annotations

import json
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

# ─── HDR detection (v1.x — DJI Osmo HLG/Dolby-Vision footage) ───────────────


def _fake_ffprobe_json(**stream_extra: object) -> str:
    """Minimal ffprobe JSON with overridable stream fields."""
    stream: dict[str, object] = {
        "width": 3840,
        "height": 2160,
        "r_frame_rate": "50/1",
        "nb_frames": "3801",
    }
    stream.update(stream_extra)
    return json.dumps({"streams": [stream], "format": {"duration": "76.02"}})


def test_probe_video_parses_color_metadata(tmp_path: Path) -> None:
    from autosplat.preprocess import probe_video

    video = tmp_path / "dji.mov"
    video.write_bytes(b"\0")
    out = _fake_ffprobe_json(
        color_transfer="arib-std-b67", color_primaries="bt2020", pix_fmt="yuv420p10le"
    )
    with (
        patch("autosplat.preprocess.shutil.which", return_value="/usr/bin/ffprobe"),
        patch("autosplat.preprocess.subprocess.run", return_value=MagicMock(stdout=out)),
    ):
        meta = probe_video(video)
    assert meta.color_transfer == "arib-std-b67"
    assert meta.color_primaries == "bt2020"
    assert meta.pix_fmt == "yuv420p10le"


def test_probe_video_hlg_is_hdr(tmp_path: Path) -> None:
    from autosplat.preprocess import probe_video

    video = tmp_path / "dji.mov"
    video.write_bytes(b"\0")
    out = _fake_ffprobe_json(color_transfer="arib-std-b67")
    with (
        patch("autosplat.preprocess.shutil.which", return_value="/usr/bin/ffprobe"),
        patch("autosplat.preprocess.subprocess.run", return_value=MagicMock(stdout=out)),
    ):
        meta = probe_video(video)
    assert meta.is_hdr is True


def test_probe_video_sdr_rec709_not_hdr(tmp_path: Path) -> None:
    from autosplat.preprocess import probe_video

    video = tmp_path / "sdr.mp4"
    video.write_bytes(b"\0")
    out = _fake_ffprobe_json(color_transfer="bt709", color_primaries="bt709", pix_fmt="yuv420p")
    with (
        patch("autosplat.preprocess.shutil.which", return_value="/usr/bin/ffprobe"),
        patch("autosplat.preprocess.subprocess.run", return_value=MagicMock(stdout=out)),
    ):
        meta = probe_video(video)
    assert meta.is_hdr is False


def test_probe_video_missing_color_fields_defaults_none(tmp_path: Path) -> None:
    """Old captures / containers without color tags must not crash and are SDR."""
    from autosplat.preprocess import probe_video

    video = tmp_path / "old.mp4"
    video.write_bytes(b"\0")
    out = _fake_ffprobe_json()  # no color fields
    with (
        patch("autosplat.preprocess.shutil.which", return_value="/usr/bin/ffprobe"),
        patch("autosplat.preprocess.subprocess.run", return_value=MagicMock(stdout=out)),
    ):
        meta = probe_video(video)
    assert meta.color_transfer is None
    assert meta.is_hdr is False


def test_video_meta_is_hdr_pq() -> None:
    """PQ (smpte2084 / HDR10) is HDR too, not just HLG."""
    meta = VideoMeta(
        duration_s=10.0,
        fps=30.0,
        width=3840,
        height=2160,
        nb_frames=300,
        color_transfer="smpte2084",
    )
    assert meta.is_hdr is True


# ─── HLG → SDR tone-mapping ─────────────────────────────────────────────────


def test_hlg_inverse_oetf_reference_points() -> None:
    """BT.2100 HLG inverse OETF: 0→0, 0.5→1/12, 1→1 (continuous at 0.5)."""
    import numpy as np

    from autosplat.preprocess import _hlg_inverse_oetf

    out = _hlg_inverse_oetf(np.array([0.0, 0.5, 1.0]))
    assert out[0] == pytest.approx(0.0, abs=1e-6)
    assert out[1] == pytest.approx(1.0 / 12.0, abs=1e-3)
    assert out[2] == pytest.approx(1.0, abs=1e-3)


def test_hlg_to_sdr_shape_and_dtype() -> None:
    import numpy as np

    from autosplat.preprocess import hlg_to_sdr

    inp = np.random.default_rng(0).random((6, 5, 3)).astype(np.float32)
    out = hlg_to_sdr(inp)
    assert out.shape == (6, 5, 3)
    assert out.dtype == np.uint8


def test_hlg_to_sdr_is_deterministic() -> None:
    """No per-frame adaptation — same pixels in → identical pixels out, so the
    transform is consistent across all frames of a clip (matters for matching)."""
    import numpy as np

    from autosplat.preprocess import hlg_to_sdr

    inp = np.random.default_rng(1).random((8, 8, 3)).astype(np.float32)
    a = hlg_to_sdr(inp)
    b = hlg_to_sdr(inp.copy())
    assert np.array_equal(a, b)


def test_hlg_to_sdr_black_and_white_map_to_extremes() -> None:
    import numpy as np

    from autosplat.preprocess import hlg_to_sdr

    black = hlg_to_sdr(np.zeros((1, 1, 3), dtype=np.float32))
    white = hlg_to_sdr(np.ones((1, 1, 3), dtype=np.float32))
    assert int(black[0, 0, 0]) <= 2
    assert int(white[0, 0, 0]) >= 230


def test_hlg_to_sdr_is_monotonic_on_grey_ramp() -> None:
    """A monotonically increasing HLG grey ramp must stay monotonic after
    tone-mapping (no contrast inversion)."""
    import numpy as np

    from autosplat.preprocess import hlg_to_sdr

    ramp = np.linspace(0.0, 1.0, 32, dtype=np.float32)
    grey = np.repeat(ramp[:, None, None], 3, axis=2).reshape(32, 1, 3)
    out = hlg_to_sdr(grey)[:, 0, 0].astype(int)
    assert all(out[i] <= out[i + 1] for i in range(len(out) - 1))


def test_hlg_to_sdr_lifts_diffuse_white() -> None:
    """HLG diffuse white (signal 0.75) must land in the bright midtones, not be
    crushed dark — the whole point of tone-mapping flat HLG to usable SDR."""
    import numpy as np

    from autosplat.preprocess import hlg_to_sdr

    diffuse = hlg_to_sdr(np.full((1, 1, 3), 0.75, dtype=np.float32))
    assert int(diffuse[0, 0, 0]) >= 170


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
        # Simulate ffmpeg dropping two files per video into frames_dir
        # (≥ MIN_USABLE_FRAMES total once combined).
        prefix = "pass_a" if "pass_a" in " ".join(cmd) else "pass_b"
        for i in (1, 2):
            (frames_dir / f"{prefix}_frame_{i:05d}.jpg").write_bytes(b"\xff\xd8")
        return MagicMock(stderr="", returncode=0)

    fake_meta = VideoMeta(duration_s=50.0, fps=30.0, width=1920, height=1080, nb_frames=1500)
    with (
        patch("autosplat.preprocess.probe_video", return_value=fake_meta),
        patch("autosplat.preprocess.subprocess.run", side_effect=fake_run),
        patch("autosplat.preprocess.laplacian_blur_score", return_value=999.0),
    ):
        result = extract_frames_from_many([v1, v2], frames_dir, _preprocess_cfg())

    names = sorted(p.name for p in frames_dir.glob("*.jpg"))
    assert names == [
        "pass_a_frame_00001.jpg",
        "pass_a_frame_00002.jpg",
        "pass_b_frame_00001.jpg",
        "pass_b_frame_00002.jpg",
    ]
    assert result.extracted_count == 4
    assert result.kept_count == 4


def test_extract_frames_from_many_aggregates_blur_rejections(tmp_path: Path) -> None:
    """Aggregated PreprocessResult sums extracted + rejected across videos."""
    v1 = tmp_path / "v1.mp4"
    v2 = tmp_path / "v2.mp4"
    v1.write_bytes(b"\0")
    v2.write_bytes(b"\0")
    frames_dir = tmp_path / "frames"

    blur_scores: list[float] = []

    def fake_run(cmd, **_):
        prefix = "v1" if "v1.mp4" in " ".join(cmd) else "v2"
        (frames_dir / f"{prefix}_frame_00001.jpg").write_bytes(b"\xff\xd8")
        (frames_dir / f"{prefix}_frame_00002.jpg").write_bytes(b"\xff\xd8")
        return MagicMock(stderr="", returncode=0)

    def fake_blur(_path):
        # Four frames total; one blurry → 3 kept (≥ MIN_USABLE_FRAMES), 1 rejected.
        blur_scores.append(1.0)
        return [999.0, 999.0, 999.0, 1.0][len(blur_scores) - 1]

    fake_meta = VideoMeta(duration_s=10.0, fps=30.0, width=1920, height=1080, nb_frames=300)
    with (
        patch("autosplat.preprocess.probe_video", return_value=fake_meta),
        patch("autosplat.preprocess.subprocess.run", side_effect=fake_run),
        patch("autosplat.preprocess.laplacian_blur_score", side_effect=fake_blur),
    ):
        result = extract_frames_from_many([v1, v2], frames_dir, _preprocess_cfg())

    assert result.extracted_count == 4
    assert result.rejected_blur == 1
    assert result.kept_count == 3


# ─── HDR routing + pipe tone-mapping (Slice D) ─────────────────────────────


def test_extract_frames_routes_hdr_to_tonemap(tmp_path: Path) -> None:
    """When the probe reports HDR, extract_frames must use the tone-map pipe
    path (extract_hdr_frames), not the plain JPEG ffmpeg command."""
    from autosplat import preprocess

    video = tmp_path / "dji.mov"
    video.write_bytes(b"\0")
    frames_dir = tmp_path / "frames"
    hdr_meta = VideoMeta(
        duration_s=50.0,
        fps=50.0,
        width=3840,
        height=2160,
        nb_frames=2500,
        color_transfer="arib-std-b67",
    )

    def fake_hdr(video, frames_dir, *, fps_target, width, height, prefix=""):
        for i in (1, 2, 3):
            (frames_dir / f"frame_{i:05d}.jpg").write_bytes(b"\xff\xd8")
        return 3

    with (
        patch("autosplat.preprocess.probe_video", return_value=hdr_meta),
        patch("autosplat.preprocess.extract_hdr_frames", side_effect=fake_hdr) as hdr,
        patch("autosplat.preprocess.build_ffmpeg_command") as build,
        patch("autosplat.preprocess.laplacian_blur_score", return_value=999.0),
    ):
        result = preprocess.extract_frames(video, frames_dir, _preprocess_cfg())

    hdr.assert_called_once()
    build.assert_not_called()
    assert result.extracted_count == 3
    assert result.kept_count == 3


def test_extract_frames_sdr_uses_plain_ffmpeg(tmp_path: Path) -> None:
    """SDR footage must NOT go through the tone-map path."""
    from autosplat import preprocess

    video = tmp_path / "sdr.mp4"
    video.write_bytes(b"\0")
    frames_dir = tmp_path / "frames"
    sdr_meta = VideoMeta(
        duration_s=50.0, fps=30.0, width=1920, height=1080, nb_frames=1500, color_transfer="bt709"
    )

    def fake_run(cmd, **_):
        for i in (1, 2, 3):
            (frames_dir / f"frame_{i:05d}.jpg").write_bytes(b"\xff\xd8")
        return MagicMock(stderr="", returncode=0)

    with (
        patch("autosplat.preprocess.probe_video", return_value=sdr_meta),
        patch("autosplat.preprocess.extract_hdr_frames") as hdr,
        patch("autosplat.preprocess.subprocess.run", side_effect=fake_run),
        patch("autosplat.preprocess.laplacian_blur_score", return_value=999.0),
    ):
        preprocess.extract_frames(video, frames_dir, _preprocess_cfg())

    hdr.assert_not_called()


def test_extract_hdr_frames_tonemaps_pipe_to_jpeg(tmp_path: Path) -> None:
    """extract_hdr_frames reads raw 16-bit RGB from the ffmpeg pipe and writes
    one valid 8-bit JPEG per frame."""
    import io

    import cv2

    from autosplat import preprocess

    frames_dir = tmp_path / "frames"
    frames_dir.mkdir()
    w, h, n = 2, 2, 3
    # n frames of w*h*3 uint16 samples, distinct mid-tone values per frame.
    import numpy as np

    payload = b""
    for k in range(n):
        frame = np.full((h, w, 3), 20000 + 5000 * k, dtype="<u2")
        payload += frame.tobytes()

    class FakePopen:
        def __init__(self, *_a, **_kw):
            self.stdout = io.BytesIO(payload)

        def wait(self) -> int:
            return 0

    with patch("autosplat.preprocess.subprocess.Popen", FakePopen):
        count = preprocess.extract_hdr_frames(
            tmp_path / "v.mov", frames_dir, fps_target=2.0, width=w, height=h
        )

    assert count == n
    jpgs = sorted(frames_dir.glob("frame_*.jpg"))
    assert len(jpgs) == n
    img = cv2.imread(str(jpgs[0]))
    assert img is not None
    assert img.shape == (h, w, 3)
    assert img.dtype == np.uint8


def test_extract_frames_from_many_single_video_matches_legacy_layout(tmp_path: Path) -> None:
    """Calling the multi-video extractor with one video must still produce
    the bare `frame_NNNNN.jpg` naming the rest of the pipeline (capture-dir
    scanning, resume) already keys on."""
    video = tmp_path / "only.mp4"
    video.write_bytes(b"\0")
    frames_dir = tmp_path / "frames"

    def fake_run(cmd, **_):
        for i in (1, 2, 3):  # ≥ MIN_USABLE_FRAMES
            (frames_dir / f"frame_{i:05d}.jpg").write_bytes(b"\xff\xd8")
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


# ─── v1.7.2: blur filter fast-fail ─────────────────────────────────────────


def _make_frames(frames_dir: Path, n: int) -> list[Path]:
    frames_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    for i in range(1, n + 1):
        p = frames_dir / f"frame_{i:05d}.jpg"
        p.write_bytes(b"\xff\xd8")
        paths.append(p)
    return paths


def test_filter_blurry_frames_keeps_sharp_deletes_blurry(tmp_path: Path) -> None:
    from autosplat.preprocess import filter_blurry_frames

    frames = _make_frames(tmp_path, 5)
    # scores vs threshold 100 → keep #2, #4, #5 (3 sharp ≥ MIN_USABLE_FRAMES)
    scores = iter([50.0, 150.0, 30.0, 200.0, 250.0])
    kept, rejected = filter_blurry_frames(
        frames, blur_threshold=100.0, scorer=lambda _: next(scores)
    )

    assert (kept, rejected) == (3, 2)
    assert not frames[0].exists() and frames[1].exists()
    assert not frames[2].exists() and frames[3].exists() and frames[4].exists()


def test_filter_blurry_frames_raises_when_all_rejected(tmp_path: Path) -> None:
    """With rescue disabled: every frame below threshold → fail fast with an
    actionable error instead of letting COLMAP die on an empty set."""
    from autosplat.preprocess import AllFramesRejectedError, filter_blurry_frames

    frames = _make_frames(tmp_path, 5)
    with pytest.raises(AllFramesRejectedError) as exc:
        filter_blurry_frames(frames, blur_threshold=100.0, scorer=lambda _: 10.0, rescue=False)

    msg = str(exc.value)
    assert "5" in msg  # extracted count
    assert "blur_threshold" in msg
    assert exc.value.extracted == 5


def test_filter_blurry_frames_empty_list_no_raise(tmp_path: Path) -> None:
    """No extracted frames is a different failure (bad video), not 'all blurry'."""
    from autosplat.preprocess import filter_blurry_frames

    kept, rejected = filter_blurry_frames([], blur_threshold=100.0, scorer=lambda _: 0.0)
    assert (kept, rejected) == (0, 0)


def test_filter_blurry_frames_raises_when_too_few_kept(tmp_path: Path) -> None:
    """0 < kept < MIN_USABLE_FRAMES → fail fast: too few sharp frames for SfM,
    rather than a cryptic COLMAP failure downstream."""
    from autosplat.preprocess import MIN_USABLE_FRAMES, TooFewFramesError, filter_blurry_frames

    n = MIN_USABLE_FRAMES + 2
    frames = _make_frames(tmp_path, n)
    # Keep exactly MIN_USABLE_FRAMES - 1 sharp; reject the rest → too few.
    keep = MIN_USABLE_FRAMES - 1
    scores = iter([200.0] * keep + [10.0] * (n - keep))
    with pytest.raises(TooFewFramesError) as exc:
        filter_blurry_frames(
            frames, blur_threshold=100.0, scorer=lambda _: next(scores), rescue=False
        )

    assert exc.value.kept == keep
    assert str(MIN_USABLE_FRAMES) in str(exc.value)
    assert "blur_threshold" in str(exc.value)


def test_filter_blurry_frames_ok_at_minimum(tmp_path: Path) -> None:
    """Exactly MIN_USABLE_FRAMES kept is allowed — no raise."""
    from autosplat.preprocess import MIN_USABLE_FRAMES, filter_blurry_frames

    n = MIN_USABLE_FRAMES + 2
    frames = _make_frames(tmp_path, n)
    scores = iter([200.0] * MIN_USABLE_FRAMES + [10.0] * (n - MIN_USABLE_FRAMES))
    kept, _ = filter_blurry_frames(frames, blur_threshold=100.0, scorer=lambda _: next(scores))
    assert kept == MIN_USABLE_FRAMES


# ─── adaptive blur rescue (HDR / genuinely-soft footage) ───────────────────


def test_filter_blurry_frames_rescue_keeps_sharpest_when_all_below(tmp_path: Path) -> None:
    """The DJI-HLG failure: every frame is below the absolute threshold (flat,
    soft footage), but rather than fail the run, rescue keeps the frames that
    are sharp *relative to the batch* (≥ rel_factor × median)."""
    from autosplat.preprocess import filter_blurry_frames

    frames = _make_frames(tmp_path, 10)
    score_by_name = {
        f.name: s for f, s in zip(frames, [10, 20, 30, 40, 50, 15, 25, 35, 45, 55], strict=True)
    }
    kept, rejected = filter_blurry_frames(
        frames,
        blur_threshold=100.0,  # nothing clears this
        scorer=lambda f: float(score_by_name[f.name]),
        rescue=True,
        rescue_rel_factor=0.6,
    )
    # median = 32.5 → rel = 19.5 → keep scores ≥ 19.5 → {20,25,30,35,40,45,50,55} = 8
    assert (kept, rejected) == (8, 2)
    # the two softest (10, 15) are gone
    assert not frames[0].exists() and not frames[5].exists()


def test_filter_blurry_frames_rescue_does_not_trigger_when_threshold_ok(tmp_path: Path) -> None:
    """When enough frames clear the absolute threshold, rescue stays out of the
    way — normal SDR footage behaves exactly as before."""
    from autosplat.preprocess import filter_blurry_frames

    frames = _make_frames(tmp_path, 5)
    scores = iter([50.0, 150.0, 30.0, 200.0, 250.0])
    kept, rejected = filter_blurry_frames(
        frames, blur_threshold=100.0, scorer=lambda _: next(scores), rescue=True
    )
    assert (kept, rejected) == (3, 2)


def test_filter_blurry_frames_rescue_guarantees_minimum(tmp_path: Path) -> None:
    """If even the relative threshold would keep < MIN_USABLE_FRAMES, rescue
    falls back to the top-MIN sharpest rather than raising."""
    from autosplat.preprocess import MIN_USABLE_FRAMES, filter_blurry_frames

    n = MIN_USABLE_FRAMES + 2
    frames = _make_frames(tmp_path, n)
    scores = [float(10 * (i + 1)) for i in range(n)]  # 10,20,30,40,50
    score_by_name = {f.name: s for f, s in zip(frames, scores, strict=True)}
    # rel_factor 2.0 → threshold = 2 × median, which nothing clears → floor kicks in.
    kept, rejected = filter_blurry_frames(
        frames,
        blur_threshold=100.0,
        scorer=lambda f: score_by_name[f.name],
        rescue=True,
        rescue_rel_factor=2.0,
    )
    assert kept == MIN_USABLE_FRAMES
    assert rejected == n - MIN_USABLE_FRAMES
