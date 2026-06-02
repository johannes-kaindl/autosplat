# SPDX-License-Identifier: AGPL-3.0-or-later

"""Frame extraction: FFmpeg + Laplacian-variance blur filter.

Strategy:
  1. Probe video for duration/fps via `ffprobe`.
  2. Extract candidate frames at a target rate that aims for ~target_frames.
  3. Filter blurry frames using OpenCV Laplacian variance.
  4. Drop near-duplicates that are closer than `min_frame_distance_sec`.

This module is structured so that `build_ffmpeg_command` can be unit-tested
without invoking ffmpeg (string assertions only).
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from numpy.typing import NDArray

from .config import PreprocessConfig
from .logging import get_logger

logger = get_logger(__name__)


# Below this many sharp frames, COLMAP can't build a meaningful model — fail
# fast rather than waste an SfM run that dies with 'No images with matches'.
MIN_USABLE_FRAMES = 3


class AllFramesRejectedError(RuntimeError):
    """Every extracted frame scored below `blur_threshold`, leaving nothing for
    COLMAP. Raised to fail fast with an actionable message instead of letting
    SfM die later with a cryptic 'No images with matches'."""

    def __init__(self, extracted: int, blur_threshold: float) -> None:
        self.extracted = extracted
        self.blur_threshold = blur_threshold
        super().__init__(
            f"All {extracted} extracted frames were rejected as blurry "
            f"(Laplacian variance below blur_threshold={blur_threshold}). "
            f"The footage is too soft for SfM — use sharper video (slower "
            f"flight, check focus) or lower blur_threshold in your config."
        )


class TooFewFramesError(RuntimeError):
    """Some frames passed the blur filter, but fewer than `MIN_USABLE_FRAMES` —
    not enough for SfM. Fails fast with an actionable message."""

    def __init__(self, kept: int, extracted: int, blur_threshold: float) -> None:
        self.kept = kept
        self.extracted = extracted
        self.blur_threshold = blur_threshold
        super().__init__(
            f"Only {kept} of {extracted} frames passed the blur filter — fewer "
            f"than the {MIN_USABLE_FRAMES} needed for SfM. The footage is mostly "
            f"too soft — use sharper video or lower blur_threshold to keep more."
        )


# color_transfer values that signal High Dynamic Range footage. HLG
# (arib-std-b67) is what DJI Osmo Pocket / Action cameras emit; smpte2084
# is PQ / HDR10. Either decodes flat-and-grey to an 8-bit JPEG unless
# tone-mapped, which trips the blur gate (every frame scores near-zero).
HDR_TRANSFERS = frozenset({"arib-std-b67", "smpte2084"})


@dataclass
class VideoMeta:
    duration_s: float
    fps: float
    width: int
    height: int
    nb_frames: int | None  # may be unknown for some containers
    color_transfer: str | None = None  # e.g. "arib-std-b67" (HLG), "bt709", "smpte2084" (PQ)
    color_primaries: str | None = None  # e.g. "bt2020", "bt709"
    pix_fmt: str | None = None  # e.g. "yuv420p10le" (10-bit), "yuv420p" (8-bit)

    @property
    def is_hdr(self) -> bool:
        """True when the footage uses an HDR transfer curve (HLG or PQ).

        We key on the transfer characteristic, not the primaries: BT.2020
        primaries alone (wide gamut) don't require tone-mapping, but an HDR
        transfer curve does — naive 8-bit extraction produces flat frames.
        """
        return self.color_transfer in HDR_TRANSFERS


# ─── HLG → SDR tone-mapping ────────────────────────────────────────────────
#
# DJI Osmo Pocket / Action cameras record HLG (color_transfer=arib-std-b67),
# often inside a Dolby-Vision profile-8 wrapper. Decoded straight to 8-bit JPEG
# the frames come out flat and grey, so the Laplacian blur metric scores every
# frame near-zero and the gate rejects the whole clip. The functions below
# reconstruct normal SDR Rec.709 contrast in pure NumPy — no zscale/libplacebo
# needed, so they work with any stock ffmpeg.

# BT.2100 HLG inverse-OETF constants.
_HLG_A = 0.17883277
_HLG_B = 0.28466892
_HLG_C = 0.55991073

# BT.2020 → BT.709 primaries conversion in linear light. Rows sum to ~1, so a
# neutral grey maps to itself.
_BT2020_TO_709 = np.array(
    [
        [1.6605, -0.5876, -0.0728],
        [-0.1246, 1.1329, -0.0083],
        [-0.0182, -0.1006, 1.1187],
    ],
    dtype=np.float64,
)

# Tone-map tuning. HLG diffuse white is at scene-linear ≈0.265; the exposure
# gain lifts it into the SDR highlights, then an extended-Reinhard curve rolls
# off the rest so nothing hard-clips. Stateless on purpose (see hlg_to_sdr).
_TONEMAP_EXPOSURE = 3.0
_TONEMAP_WHITE = 4.0
_DISPLAY_GAMMA = 2.2


def _hlg_inverse_oetf(signal: NDArray[Any]) -> NDArray[np.float64]:
    """BT.2100 HLG inverse OETF: signal E' (0..1) → scene-linear E (0..1)."""
    e = np.asarray(signal, dtype=np.float64)
    lin: NDArray[np.float64] = np.where(
        e <= 0.5,
        (e * e) / 3.0,
        (np.exp((e - _HLG_C) / _HLG_A) + _HLG_B) / 12.0,
    )
    return lin


def hlg_to_sdr(rgb_signal: NDArray[Any]) -> NDArray[np.uint8]:
    """Tone-map HLG-encoded RGB (float, [0,1], RGB channel order) to 8-bit SDR.

    Pipeline: inverse HLG OETF → BT.2020→709 primaries → exposure gain →
    extended-Reinhard highlight roll-off → gamma encode. The transform is
    stateless — identical pixels always map to identical output — so every
    frame of a clip gets the same curve and SIFT descriptors stay matchable
    (per-frame auto-levels would shift descriptors and hurt COLMAP matching).
    """
    lin = _hlg_inverse_oetf(rgb_signal)  # scene-linear BT.2020, [0,1]
    lin709 = np.clip(lin @ _BT2020_TO_709.T, 0.0, None)
    exposed = lin709 * _TONEMAP_EXPOSURE
    rolled = exposed * (1.0 + exposed / (_TONEMAP_WHITE**2)) / (1.0 + exposed)
    disp = np.clip(rolled, 0.0, 1.0) ** (1.0 / _DISPLAY_GAMMA)
    out: NDArray[np.uint8] = (disp * 255.0 + 0.5).astype(np.uint8)
    return out


@dataclass
class PreprocessResult:
    frames_dir: Path
    extracted_count: int
    kept_count: int
    rejected_blur: int
    duration_s: float
    skipped_frames_warning: int = 0  # Phase 6 / Spec §5: ffmpeg "skipped N frames" total


def probe_video(video: Path) -> VideoMeta:
    """Probe video via ffprobe and return structured metadata."""
    if shutil.which("ffprobe") is None:
        raise RuntimeError("ffprobe not in PATH — install via `brew install ffmpeg`")

    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-select_streams",
        "v:0",
        "-show_entries",
        "stream=width,height,r_frame_rate,nb_frames,color_transfer,"
        "color_primaries,pix_fmt:format=duration",
        "-of",
        "json",
        str(video),
    ]
    raw = subprocess.run(cmd, capture_output=True, text=True, check=True)
    data = json.loads(raw.stdout)
    stream = data["streams"][0]
    fmt = data["format"]

    num, denom = stream["r_frame_rate"].split("/")
    fps = float(num) / float(denom) if float(denom) > 0 else 0.0

    nb_frames_raw = stream.get("nb_frames")
    nb_frames = int(nb_frames_raw) if nb_frames_raw and nb_frames_raw.isdigit() else None

    return VideoMeta(
        duration_s=float(fmt["duration"]),
        fps=fps,
        width=int(stream["width"]),
        height=int(stream["height"]),
        nb_frames=nb_frames,
        color_transfer=stream.get("color_transfer"),
        color_primaries=stream.get("color_primaries"),
        pix_fmt=stream.get("pix_fmt"),
    )


def build_ffmpeg_command(
    video: Path,
    frames_dir: Path,
    *,
    fps_target: float,
    prefix: str = "",
) -> list[str]:
    """Construct the ffmpeg invocation for keyframe extraction.

    `prefix`, when non-empty, slots into the output template as
    `<prefix>_frame_%05d.jpg` so multi-video captures don't have frames
    from one source clobbering frames from another. Empty prefix (default)
    keeps the legacy `frame_%05d.jpg` layout — both `autosplat resume`
    and the capture-dir scanners key on that name.

    Extracted as a separate function so unit tests can assert on the command
    without actually running ffmpeg.
    """
    template = f"{prefix}_frame_%05d.jpg" if prefix else "frame_%05d.jpg"
    return [
        "ffmpeg",
        "-y",
        "-i",
        str(video),
        "-vf",
        f"fps={fps_target:.4f}",
        "-q:v",
        "2",
        str(frames_dir / template),
    ]


def compute_fps_target(meta: VideoMeta, target_frames: int, min_distance_sec: float) -> float:
    """Compute the extraction fps that hits target_frames, respecting min distance."""
    if meta.duration_s <= 0:
        raise ValueError("Video has zero duration")

    fps_from_target = target_frames / meta.duration_s
    fps_max_by_distance = 1.0 / min_distance_sec if min_distance_sec > 0 else float("inf")

    return min(fps_from_target, fps_max_by_distance, meta.fps if meta.fps > 0 else fps_from_target)


_SKIPPED_FRAMES_RE = re.compile(
    r"frame=\s*\d+.*skipped:?\s*(\d+)|skipped\s+(\d+)\s+frames?", re.IGNORECASE
)


def _count_skipped_frames(stderr: str) -> int:
    """Spec §5 hook: count ffmpeg 'skipped N frames' warnings in stderr.

    ffmpeg occasionally emits 'skipped: N' in progress lines or 'X frames
    skipped' as a final warning. We match both and return the maximum,
    because the same skip-event may be reported multiple times.
    """
    if not stderr:
        return 0
    max_count = 0
    for match in _SKIPPED_FRAMES_RE.finditer(stderr):
        n = next((int(g) for g in match.groups() if g), 0)
        max_count = max(max_count, n)
    return max_count


def laplacian_blur_score(image_path: Path) -> float:
    """Variance of the Laplacian — higher = sharper."""
    img = cv2.imread(str(image_path), cv2.IMREAD_GRAYSCALE)
    if img is None:
        return 0.0
    return float(cv2.Laplacian(img, cv2.CV_64F).var())


def filter_blurry_frames(
    frames: list[Path],
    blur_threshold: float,
    scorer: Callable[[Path], float] | None = None,
    *,
    rescue: bool = True,
    rescue_rel_factor: float = 0.6,
) -> tuple[int, int]:
    """Delete blurry frames; return (kept, rejected).

    Two modes:

    * **Absolute** (the normal path): drop frames scoring below `blur_threshold`.
      Calibrated for sharp SDR footage (successful captures score 150–500).

    * **Rescue** (`rescue=True`, the default): if the absolute threshold would
      leave fewer than `MIN_USABLE_FRAMES`, the threshold is clearly mis-matched
      to this footage — HLG/HDR clips and genuinely-soft sources score an order
      of magnitude lower across the board. Rather than fail the whole run, fall
      back to a *relative* threshold (`rescue_rel_factor × median`) so we keep
      the frames that are sharp relative to the batch and only drop the soft
      tail. Guarantees at least `MIN_USABLE_FRAMES` (top-N sharpest) survive.

    With `rescue=False` the old fail-fast behaviour is preserved: an all-blurry
    clip raises `AllFramesRejectedError`, a near-empty one `TooFewFramesError`.

    `scorer` defaults to `laplacian_blur_score`, resolved at call time so tests
    (and callers) can monkeypatch the module function.
    """
    score = scorer if scorer is not None else laplacian_blur_score
    if not frames:
        return 0, 0

    scored = [(frame, score(frame)) for frame in frames]
    above = [f for f, s in scored if s >= blur_threshold]

    if rescue and len(above) < MIN_USABLE_FRAMES:
        keep_set = _rescue_keep_set(scored, rescue_rel_factor)
        median = float(np.median([s for _, s in scored]))
        logger.warning(
            "preprocess.blur_rescue",
            extracted=len(frames),
            kept=len(keep_set),
            blur_threshold=blur_threshold,
            median_score=round(median, 1),
            rel_threshold=round(rescue_rel_factor * median, 1),
            hint="footage scores far below blur_threshold (HDR/soft source) — "
            "kept the sharpest frames relative to the batch instead of failing",
        )
        rejected = _delete_unless_kept(scored, keep_set)
        return len(frames) - rejected, rejected

    rejected = 0
    for frame, s in scored:
        if s < blur_threshold:
            frame.unlink()
            rejected += 1
    kept = len(frames) - rejected
    if kept == 0:
        logger.error(
            "preprocess.all_frames_rejected",
            extracted=len(frames),
            blur_threshold=blur_threshold,
        )
        raise AllFramesRejectedError(len(frames), blur_threshold)
    if 0 < kept < MIN_USABLE_FRAMES:
        logger.error(
            "preprocess.too_few_frames",
            kept=kept,
            extracted=len(frames),
            blur_threshold=blur_threshold,
        )
        raise TooFewFramesError(kept, len(frames), blur_threshold)
    return kept, rejected


def _rescue_keep_set(scored: list[tuple[Path, float]], rel_factor: float) -> set[Path]:
    """Pick frames to keep when rescuing: those ≥ rel_factor × median, but never
    fewer than MIN_USABLE_FRAMES (top-N sharpest as the floor)."""
    median = float(np.median([s for _, s in scored]))
    rel = rel_factor * median
    keep = {f for f, s in scored if s >= rel}
    if len(keep) < MIN_USABLE_FRAMES:
        top = sorted(scored, key=lambda pair: pair[1], reverse=True)[:MIN_USABLE_FRAMES]
        keep = {f for f, _ in top}
    return keep


def _delete_unless_kept(scored: list[tuple[Path, float]], keep_set: set[Path]) -> int:
    """Unlink every scored frame not in `keep_set`; return the count removed."""
    rejected = 0
    for frame, _ in scored:
        if frame not in keep_set:
            frame.unlink()
            rejected += 1
    return rejected


def _read_exact(stream: Any, n: int) -> bytes:
    """Read exactly `n` bytes from a pipe (which may return short reads), or
    fewer only at clean EOF."""
    chunks: list[bytes] = []
    remaining = n
    while remaining > 0:
        chunk = stream.read(remaining)
        if not chunk:
            break
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def extract_hdr_frames(
    video: Path,
    frames_dir: Path,
    *,
    fps_target: float,
    width: int,
    height: int,
    prefix: str = "",
) -> int:
    """Extract + tone-map HLG/HDR frames into `frames_dir`; return the count.

    ffmpeg streams raw 16-bit RGB (`rgb48le`) over a pipe — no temp files, one
    frame in memory at a time — and each frame is tone-mapped to SDR Rec.709 via
    `hlg_to_sdr` before being written as JPEG. Works with any stock ffmpeg
    because it needs no zscale/libplacebo (the colour science is done in NumPy).
    """
    template = f"{prefix}_frame_" if prefix else "frame_"
    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        str(video),
        "-vf",
        f"fps={fps_target:.4f}",
        "-pix_fmt",
        "rgb48le",
        "-f",
        "rawvideo",
        "-",
    ]
    frame_bytes = width * height * 3 * 2  # 3 channels, 2 bytes/sample
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    assert proc.stdout is not None
    idx = 0
    try:
        while True:
            buf = _read_exact(proc.stdout, frame_bytes)
            if len(buf) < frame_bytes:
                break
            arr = np.frombuffer(buf, dtype=np.uint16).reshape(height, width, 3)  # RGB
            rgb01 = arr.astype(np.float32) / 65535.0
            sdr_rgb = hlg_to_sdr(rgb01)
            bgr = sdr_rgb[..., ::-1]  # cv2 writes BGR
            idx += 1
            cv2.imwrite(
                str(frames_dir / f"{template}{idx:05d}.jpg"),
                bgr,
                [cv2.IMWRITE_JPEG_QUALITY, 95],
            )
    finally:
        proc.stdout.close()
        proc.wait()
    return idx


def _extract_video_frames(
    video: Path,
    frames_dir: Path,
    *,
    meta: VideoMeta,
    fps_target: float,
    cfg: PreprocessConfig,
    prefix: str = "",
) -> int:
    """Extract one video's frames into `frames_dir` (HDR-aware). Returns the
    ffmpeg 'skipped N frames' count (always 0 on the HDR pipe path)."""
    if meta.is_hdr and cfg.hdr_tonemap:
        logger.info(
            "preprocess.hdr_tonemap",
            video=str(video),
            color_transfer=meta.color_transfer,
            color_primaries=meta.color_primaries,
            pix_fmt=meta.pix_fmt,
            fps_target=fps_target,
            hint="HDR (HLG/PQ) source — tone-mapping to SDR Rec.709 so the blur "
            "gate sees real contrast",
        )
        extract_hdr_frames(
            video,
            frames_dir,
            fps_target=fps_target,
            width=meta.width,
            height=meta.height,
            prefix=prefix,
        )
        return 0

    cmd = build_ffmpeg_command(video, frames_dir, fps_target=fps_target, prefix=prefix)
    logger.info("preprocess.ffmpeg_start", video=str(video), fps_target=fps_target, cmd=cmd)
    proc = subprocess.run(cmd, check=True, capture_output=True, text=True)
    return _count_skipped_frames(proc.stderr or "")


def extract_frames(
    video: Path,
    frames_dir: Path,
    cfg: PreprocessConfig,
) -> PreprocessResult:
    """Run the full preprocess stage: probe → ffmpeg → blur-filter."""
    t0 = time.monotonic()

    if not video.exists():
        raise FileNotFoundError(f"Video not found: {video}")

    frames_dir.mkdir(parents=True, exist_ok=True)
    for old in frames_dir.glob("frame_*.jpg"):
        old.unlink()

    meta = probe_video(video)
    logger.info(
        "preprocess.probe",
        duration_s=meta.duration_s,
        fps=meta.fps,
        width=meta.width,
        height=meta.height,
        is_hdr=meta.is_hdr,
        color_transfer=meta.color_transfer,
    )

    fps_target = compute_fps_target(meta, cfg.target_frames, cfg.min_frame_distance_sec)
    skipped_frames = _extract_video_frames(
        video, frames_dir, meta=meta, fps_target=fps_target, cfg=cfg
    )
    if skipped_frames > 0:
        # Spec §5 implicit: surface ffmpeg's "skipped N frames" warnings.
        # Threshold-only-log at >5 % of target — below that it's normal jitter.
        threshold = max(1, int(cfg.target_frames * 0.05))
        if skipped_frames > threshold:
            logger.warning(
                "preprocess.skipped_frames",
                skipped=skipped_frames,
                threshold=threshold,
                hint="ffmpeg dropped duplicate frames — usually harmless, but consider "
                "lowering target_frames if persistent",
            )
        else:
            logger.info("preprocess.skipped_frames_minor", skipped=skipped_frames)

    extracted = sorted(frames_dir.glob("frame_*.jpg"))
    kept, rejected = filter_blurry_frames(
        extracted,
        cfg.blur_threshold,
        rescue=cfg.blur_rescue,
        rescue_rel_factor=cfg.blur_rescue_rel_factor,
    )

    result = PreprocessResult(
        frames_dir=frames_dir,
        extracted_count=len(extracted),
        kept_count=kept,
        rejected_blur=rejected,
        duration_s=time.monotonic() - t0,
        skipped_frames_warning=skipped_frames,
    )
    logger.info(
        "preprocess.done",
        extracted=result.extracted_count,
        kept=result.kept_count,
        rejected_blur=result.rejected_blur,
        duration_s=result.duration_s,
    )
    return result


def extract_frames_from_many(
    videos: list[Path],
    frames_dir: Path,
    cfg: PreprocessConfig,
) -> PreprocessResult:
    """Extract frames from N source videos into a single frames_dir.

    Per-video:
      - ffmpeg target rate is computed against that video's own duration
        (each video gets `cfg.target_frames` worth of keyframes — short
        passes don't get starved by longer ones in the same capture).
      - frame names are prefixed with the video's stem (`pass_a_frame_*`)
        so two videos can't write to the same path.

    The blur filter then runs once over the combined frame set; the
    aggregated PreprocessResult sums extracted + rejected across videos
    so the existing pipeline downstream (sfm / quality_gate / log events)
    sees one consistent count.

    Single-video call (len==1) deliberately writes bare `frame_NNNNN.jpg`
    (no prefix) — keeps the on-disk layout identical to extract_frames so
    `autosplat resume` and capture-dir scanners still match.
    """
    t0 = time.monotonic()

    for video in videos:
        if not video.exists():
            raise FileNotFoundError(f"Video not found: {video}")

    frames_dir.mkdir(parents=True, exist_ok=True)
    for old in frames_dir.glob("*frame_*.jpg"):
        old.unlink()

    total_extracted = 0
    total_skipped_frames = 0
    for video in videos:
        prefix = video.stem if len(videos) > 1 else ""
        meta = probe_video(video)
        logger.info(
            "preprocess.probe",
            video=str(video),
            duration_s=meta.duration_s,
            fps=meta.fps,
            width=meta.width,
            height=meta.height,
            is_hdr=meta.is_hdr,
            color_transfer=meta.color_transfer,
        )
        fps_target = compute_fps_target(meta, cfg.target_frames, cfg.min_frame_distance_sec)
        total_skipped_frames += _extract_video_frames(
            video, frames_dir, meta=meta, fps_target=fps_target, cfg=cfg, prefix=prefix
        )

    extracted = sorted(frames_dir.glob("*frame_*.jpg"))
    total_extracted = len(extracted)

    kept, rejected = filter_blurry_frames(
        extracted,
        cfg.blur_threshold,
        rescue=cfg.blur_rescue,
        rescue_rel_factor=cfg.blur_rescue_rel_factor,
    )

    result = PreprocessResult(
        frames_dir=frames_dir,
        extracted_count=total_extracted,
        kept_count=kept,
        rejected_blur=rejected,
        duration_s=time.monotonic() - t0,
        skipped_frames_warning=total_skipped_frames,
    )
    logger.info(
        "preprocess.done",
        videos=len(videos),
        extracted=result.extracted_count,
        kept=result.kept_count,
        rejected_blur=result.rejected_blur,
        duration_s=result.duration_s,
    )
    return result
