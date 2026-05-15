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
from dataclasses import dataclass
from pathlib import Path

import cv2

from .config import PreprocessConfig
from .logging import get_logger

logger = get_logger(__name__)


@dataclass
class VideoMeta:
    duration_s: float
    fps: float
    width: int
    height: int
    nb_frames: int | None  # may be unknown for some containers


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
        "stream=width,height,r_frame_rate,nb_frames:format=duration",
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
    )


def build_ffmpeg_command(
    video: Path,
    frames_dir: Path,
    *,
    fps_target: float,
) -> list[str]:
    """Construct the ffmpeg invocation for keyframe extraction.

    Extracted as a separate function so unit tests can assert on the command
    without actually running ffmpeg.
    """
    return [
        "ffmpeg",
        "-y",
        "-i",
        str(video),
        "-vf",
        f"fps={fps_target:.4f}",
        "-q:v",
        "2",
        str(frames_dir / "frame_%05d.jpg"),
    ]


def compute_fps_target(meta: VideoMeta, target_frames: int, min_distance_sec: float) -> float:
    """Compute the extraction fps that hits target_frames, respecting min distance."""
    if meta.duration_s <= 0:
        raise ValueError("Video has zero duration")

    fps_from_target = target_frames / meta.duration_s
    fps_max_by_distance = 1.0 / min_distance_sec if min_distance_sec > 0 else float("inf")

    return min(fps_from_target, fps_max_by_distance, meta.fps if meta.fps > 0 else fps_from_target)


_SKIPPED_FRAMES_RE = re.compile(r"frame=\s*\d+.*skipped:?\s*(\d+)|skipped\s+(\d+)\s+frames?", re.IGNORECASE)


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
    )

    fps_target = compute_fps_target(meta, cfg.target_frames, cfg.min_frame_distance_sec)
    cmd = build_ffmpeg_command(video, frames_dir, fps_target=fps_target)
    logger.info("preprocess.ffmpeg_start", fps_target=fps_target, cmd=cmd)

    proc = subprocess.run(cmd, check=True, capture_output=True, text=True)
    skipped_frames = _count_skipped_frames(proc.stderr)
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
    rejected = 0
    for frame in extracted:
        if laplacian_blur_score(frame) < cfg.blur_threshold:
            frame.unlink()
            rejected += 1

    kept = len(list(frames_dir.glob("frame_*.jpg")))

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
