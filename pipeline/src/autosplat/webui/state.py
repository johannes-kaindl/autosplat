# SPDX-License-Identifier: AGPL-3.0-or-later

"""Read-only bridge between the filesystem + WatcherState and WebUI data models."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from autosplat.watcher import WatcherState

CaptureStatus = Literal["idle", "queued", "running", "done", "failed"]

# Matches pipeline capture dirs: YYYY-MM-DD_<stem>
_CAPTURE_DIR_RE = re.compile(r"^\d{4}-\d{2}-\d{2}_.+$")

STAGE_ORDER = ["preflight", "preprocess", "sfm", "train", "export"]


@dataclass
class CaptureInfo:
    id: str
    path: Path
    status: CaptureStatus
    stage: str | None
    has_ply: bool
    ply_path: Path | None
    ply_size_bytes: int | None
    has_log: bool
    started_at: str | None
    finished_at: str | None
    duration_s: float | None
    reason: str | None


def _find_ply(capture_dir: Path) -> Path | None:
    for candidate in [
        capture_dir / "output" / "scene.ply",
        capture_dir / "scene.ply",
    ]:
        if candidate.exists():
            return candidate
    plys = sorted(capture_dir.glob("*.ply"))
    return plys[0] if plys else None


def _load_watcher_state() -> WatcherState:
    return WatcherState.load()


def list_captures(captures_dir: Path) -> list[CaptureInfo]:
    """Discover all capture directories and overlay WatcherState for live status."""
    if not captures_dir.exists():
        return []

    state = _load_watcher_state()

    # Build fast lookups from WatcherState
    in_progress_path = state.in_progress.path if state.in_progress else None
    queued_paths = set(state.queue)
    completed_by_path = {e.path: e for e in state.completed}
    failed_by_path = {e.path: e for e in state.failed}

    captures: list[CaptureInfo] = []
    for entry in sorted(captures_dir.iterdir(), reverse=True):
        if not entry.is_dir():
            continue
        if not _CAPTURE_DIR_RE.match(entry.name):
            continue

        path_str = str(entry)
        ply = _find_ply(entry)
        log_path = entry / "pipeline.log"

        # Determine status + metadata via WatcherState overlay
        if in_progress_path == path_str:
            status: CaptureStatus = "running"
            stage = state.in_progress.stage if state.in_progress else None
            started_at = state.in_progress.started_at if state.in_progress else None
            finished_at = None
            duration_s = None
            reason = None
        elif path_str in queued_paths:
            status = "queued"
            stage = None
            started_at = None
            finished_at = None
            duration_s = None
            reason = None
        elif path_str in completed_by_path:
            completed = completed_by_path[path_str]
            status = "done"
            stage = "export"
            started_at = None
            finished_at = completed.finished_at
            duration_s = completed.duration_s
            reason = None
        elif path_str in failed_by_path:
            failed = failed_by_path[path_str]
            status = "failed"
            stage = failed.stage
            started_at = None
            finished_at = failed.failed_at
            duration_s = None
            reason = failed.reason
        elif ply is not None:
            status = "done"
            stage = "export"
            started_at = None
            finished_at = None
            duration_s = None
            reason = None
        else:
            status = "idle"
            stage = None
            started_at = None
            finished_at = None
            duration_s = None
            reason = None

        captures.append(
            CaptureInfo(
                id=entry.name,
                path=entry,
                status=status,
                stage=stage,
                has_ply=ply is not None,
                ply_path=ply,
                ply_size_bytes=ply.stat().st_size if ply is not None else None,
                has_log=log_path.exists(),
                started_at=started_at,
                finished_at=finished_at,
                duration_s=duration_s,
                reason=reason,
            )
        )

    return captures


def get_capture(captures_dir: Path, capture_id: str) -> CaptureInfo | None:
    """Return a single CaptureInfo by id, or None if not found."""
    capture_path = captures_dir / capture_id
    if not capture_path.is_dir() or not _CAPTURE_DIR_RE.match(capture_id):
        return None

    all_captures = list_captures(captures_dir)
    for c in all_captures:
        if c.id == capture_id:
            return c
    return None


def read_log_tail(capture_dir: Path, max_lines: int = 50) -> list[str]:
    """Return the last `max_lines` lines from pipeline.log."""
    log_path = capture_dir / "pipeline.log"
    if not log_path.exists():
        return []
    try:
        lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
        return lines[-max_lines:]
    except OSError:
        return []
