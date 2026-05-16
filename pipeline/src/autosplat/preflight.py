# SPDX-License-Identifier: AGPL-3.0-or-later

"""Pre-flight checks per video (Phase 6 / Spec §5 + §9.2).

Runs *before* preprocess so a corrupt or implausible video doesn't waste
extraction or COLMAP time. Two checks:

  1. **ffprobe-validate** — does ffprobe accept the file at all? Spec §9.2
     says "korruptes Video, kein Audio-Track ignorierbar" → skip + warn.
  2. **plausibility** — duration / resolution / fps within configurable
     thresholds. Catches "I uploaded a 4-minute timelapse" or "I uploaded
     a 240×135 thumbnail" before the pipeline burns minutes on it.

Raises `PreflightFailure(reason, detail)` on any check failure. The
watcher catches this like any other pipeline exception — no retry hint
because re-running with the same input is pointless.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .logging import get_logger

logger = get_logger(__name__)


class PreflightFailure(RuntimeError):
    """Raised when a video fails a pre-flight check.

    `reason` is a short slug for log/state.json; `detail` is human-readable.
    """

    def __init__(self, reason: str, detail: str):
        self.reason = reason
        self.detail = detail
        super().__init__(f"{reason}: {detail}")


@dataclass
class VideoProbe:
    duration_s: float
    width: int
    height: int
    fps: float
    codec: str


# Plausibility thresholds — chosen wide enough that any "normal drone clip"
# passes. Tighten only if a workflow produces consistent garbage at edges.
MIN_DURATION_S = 3.0
MAX_DURATION_S = 600.0   # 10 min
MIN_RESOLUTION = 720      # min(width, height) — drops 480p, keeps 720p+
MIN_FPS = 23.0            # cinema 24, NTSC 23.976
MAX_FPS = 120.0           # high-speed phones cap here


def probe_video(video: Path) -> VideoProbe:
    """ffprobe the video. Raises PreflightFailure on parse failure."""
    if shutil.which("ffprobe") is None:
        raise PreflightFailure(
            "ffprobe_missing",
            "ffprobe not in PATH — install via `brew install ffmpeg`",
        )

    cmd = [
        "ffprobe", "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "stream=codec_name,width,height,r_frame_rate:format=duration",
        "-of", "json",
        str(video),
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    except subprocess.TimeoutExpired as e:
        raise PreflightFailure(
            "ffprobe_timeout", f"ffprobe took >30 s on {video}"
        ) from e

    if result.returncode != 0:
        raise PreflightFailure(
            "video_corrupt",
            f"ffprobe rejected the file. stderr: {result.stderr[-500:].strip()}",
        )

    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError as e:
        raise PreflightFailure(
            "video_corrupt",
            f"ffprobe output not valid JSON: {e}",
        ) from e

    streams = data.get("streams") or []
    if not streams:
        raise PreflightFailure(
            "video_corrupt",
            "ffprobe found no video stream in the file",
        )
    stream = streams[0]

    try:
        num, denom = stream["r_frame_rate"].split("/")
        fps = float(num) / float(denom) if float(denom) > 0 else 0.0
        return VideoProbe(
            duration_s=float(data["format"]["duration"]),
            width=int(stream["width"]),
            height=int(stream["height"]),
            fps=fps,
            codec=stream.get("codec_name", "unknown"),
        )
    except (KeyError, ValueError, ZeroDivisionError) as e:
        raise PreflightFailure(
            "video_corrupt",
            f"ffprobe output missing expected fields: {e}",
        ) from e


def check_plausibility(probe: VideoProbe) -> None:
    """Raise PreflightFailure if duration / resolution / fps out of plausible range."""
    if not (MIN_DURATION_S <= probe.duration_s <= MAX_DURATION_S):
        raise PreflightFailure(
            "implausible_duration",
            f"duration {probe.duration_s:.1f}s outside [{MIN_DURATION_S}, {MAX_DURATION_S}]",
        )

    short_side = min(probe.width, probe.height)
    if short_side < MIN_RESOLUTION:
        raise PreflightFailure(
            "implausible_resolution",
            f"shortest side {short_side}px below {MIN_RESOLUTION}px floor",
        )

    if not (MIN_FPS <= probe.fps <= MAX_FPS):
        raise PreflightFailure(
            "implausible_fps",
            f"fps {probe.fps:.2f} outside [{MIN_FPS}, {MAX_FPS}]",
        )


def run_preflight(video: Path) -> VideoProbe:
    """Run all pre-flight checks. Returns the probe data on success.

    Composes probe_video + check_plausibility. The two are split so each
    can be tested in isolation.
    """
    if not video.exists():
        raise PreflightFailure(
            "video_missing", f"file not found: {video}"
        )

    probe = probe_video(video)
    check_plausibility(probe)
    logger.info(
        "preflight.passed",
        duration_s=probe.duration_s,
        width=probe.width,
        height=probe.height,
        fps=probe.fps,
        codec=probe.codec,
    )
    return probe
