# SPDX-License-Identifier: AGPL-3.0-or-later

"""Classify a capture's failure reason into a human headline + remediation hint.

Display-only and derived from the already-stored `reason` string (plus a
pipeline.log fallback), so it works retroactively on captures that failed before
this module existed and never changes pipeline behaviour. All strings English.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class FailureInfo:
    category: str  # machine key: blur | sfm | oom | no_video | interrupted | unknown
    headline: str  # human one-liner
    hint: str  # actionable remediation — never empty


_FALLBACK = FailureInfo(
    "unknown",
    "The run failed",
    "Check the log below for detail, then resume or re-run.",
)


def classify_failure(reason: str | None, stage: str | None = None) -> FailureInfo:
    """Map a stored failure `reason` to a `FailureInfo` via an ordered rules
    table (first match wins). Returns the generic fallback for None/unknown."""
    if not reason:
        return _FALLBACK
    r = reason.lower()

    if "rejected as blurry" in r or "blur_threshold" in r:
        return FailureInfo(
            "blur",
            "All frames were too blurry",
            "Footage too soft — use sharper video (slower flight, check focus) "
            "or lower `blur_threshold`.",
        )
    if (
        "no images with matches" in r
        or "failed to create any sparse model" in r
        or ("mapper" in r and "non-zero" in r)
    ):
        return FailureInfo(
            "sfm",
            "COLMAP couldn't align the frames",
            "Rotation-heavy or low-overlap footage — try `autosplat rescue` "
            "(auto-bisection) or shoot with more overlap and slower motion.",
        )
    if "out of memory" in r or "oom" in r or "resolution_cap" in r:
        return FailureInfo(
            "oom",
            "Brush ran out of memory",
            "Lower `resolution_cap` in your config and re-run.",
        )
    if "no source video" in r:
        return FailureInfo(
            "no_video",
            "Source video not found",
            "The original video moved or was deleted — re-add it, then resume.",
        )
    if "interrupted" in r:
        return FailureInfo(
            "interrupted",
            "The run was interrupted",
            "Sleep, crash, or quit ended it early — click Resume to continue.",
        )
    return _FALLBACK


def failure_reason_from_log(capture_dir: Path) -> str | None:
    """Best-effort reason when `CaptureInfo.reason` is None: the message of the
    last `error`-level event in pipeline.log, else the last non-empty line."""
    log = capture_dir / "pipeline.log"
    try:
        lines = [ln for ln in log.read_text(encoding="utf-8", errors="replace").splitlines() if ln.strip()]
    except OSError:
        return None
    if not lines:
        return None
    for line in reversed(lines):
        try:
            obj = json.loads(line)
        except ValueError:
            continue
        if obj.get("level") == "error":
            msg = obj.get("error") or obj.get("event")
            if msg:
                return str(msg)
    return lines[-1]
