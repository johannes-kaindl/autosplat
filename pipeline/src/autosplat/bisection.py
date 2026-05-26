# SPDX-License-Identifier: AGPL-3.0-or-later

"""v1.4 — Auto-Bisection-Rescue.

When the standard adaptive-retry path (sequential → exhaustive matcher swap)
exhausts itself with retry_hint=None, the pipeline can binary-subdivide the
source video, probe each leaf clip with a cheap preprocess+SfM-only run, and
combine the surviving leaves through the existing multi-video pipeline path.

See docs/superpowers/specs/2026-05-26-v14-bisection-rescue-design.md for the
full design and docs/CAPTURE-GUIDE.md for the user-facing explanation.

This module is built up across multiple slices:
  Slice 1 — build_ffmpeg_cut_command + BisectionClip   (this commit)
  Slice 2 — cut_video subprocess wrapper
  Slice 3 — probe_clip (preprocess + SfM-only)
  Slice 4 — bisect_recursively (DFS halt-on-success)
  Slice 5 — rescue_via_bisection (orchestrator)
  Slice 6 — pipeline.py integration
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class BisectionClip:
    """A single sub-clip in the bisection tree.

    `clip_id` is a depth-encoded path: '0', '0_1', '0_1_0'. Used as the
    filename suffix and as the probe-workspace directory name so a partial
    run is debuggable (which clips were tried, which passed).
    """

    source_video: Path
    clip_id: str
    start_s: float
    duration_s: float
    path: Path


def build_ffmpeg_cut_command(
    video: Path,
    start_s: float,
    duration_s: float,
    output: Path,
) -> list[str]:
    """Stream-copy ffmpeg command — no re-encode, fast cuts.

    `-ss` is placed before `-i` for fast seek; stream-copy (`-c copy`) skips
    re-encoding so the cut is near-instant and bit-exact in the kept range.

    Negative `start_s` is clamped to 0 (no-op on a normal video).
    """
    start = max(0.0, float(start_s))
    duration = max(0.0, float(duration_s))
    return [
        "ffmpeg",
        "-y",
        "-ss",
        f"{start:.3f}",
        "-i",
        str(video),
        "-t",
        f"{duration:.3f}",
        "-c",
        "copy",
        str(output),
    ]
