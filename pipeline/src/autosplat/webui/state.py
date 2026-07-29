# SPDX-License-Identifier: AGPL-3.0-or-later

"""Read-only bridge between the filesystem + WatcherState and WebUI data models."""

from __future__ import annotations

import contextlib
import re
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from autosplat import lifecycle
from autosplat.lifecycle import ReviewStatus as ReviewStatus
from autosplat.lifecycle import resolve_publish_ply as resolve_publish_ply
from autosplat.lifecycle import review_marker_path as review_marker_path
from autosplat.watcher import WatcherState

_find_ply = lifecycle.find_ply
_review_status = lifecycle.review_status

if TYPE_CHECKING:
    from autosplat.webui.jobs_runner import JobRunner

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
    detail: str | None = None  # v1.4.1: stage-specific sub-info (e.g. bisect clip)
    review_status: ReviewStatus = "unreviewed"  # v1.15.0: publish quality gate
    reclaimable_bytes: int = 0  # v1.16.0: lifecycle retention
    grace_days_left: int | None = None


def _load_watcher_state() -> WatcherState:
    return WatcherState.load()


def list_captures(
    captures_dir: Path,
    job_runner: JobRunner | None = None,
    *,
    grace_days: int = 30,
    now: datetime | None = None,
) -> list[CaptureInfo]:
    """Discover all capture directories and overlay live status.

    Status is resolved from two sources, JobRunner first:
      1. The in-memory JobRunner (WebUI-triggered jobs) — authoritative for
         running/queued/failed WebUI jobs.
      2. WatcherState (`state.json`) — the CLI `watch` daemon's queue.

    The JobRunner overlay closes SF-G2-9: WebUI jobs run `run_pipeline()` in a
    thread and never touch WatcherState, so a running WebUI job would otherwise
    be misreported as idle/done.
    """
    if not captures_dir.exists():
        return []

    state = _load_watcher_state()

    # Build fast lookups from WatcherState
    in_progress_path = state.in_progress.path if state.in_progress else None
    queued_paths = set(state.queue)
    completed_by_path = {e.path: e for e in state.completed}
    failed_by_path = {e.path: e for e in state.failed}

    captures: list[CaptureInfo] = []
    for entry in captures_dir.iterdir():
        if not entry.is_dir():
            continue
        if not _CAPTURE_DIR_RE.match(entry.name):
            continue

        path_str = str(entry)
        life = lifecycle.inspect(entry, now=now or datetime.now(UTC), grace_days=grace_days)
        review_status = _review_status(entry)
        ply = resolve_publish_ply(entry, review_status)
        log_path = entry / "pipeline.log"

        # Determine status + metadata. JobRunner (in-memory, WebUI jobs) wins
        # over WatcherState — see SF-G2-9 in the docstring.
        job = job_runner.get_job(entry.name) if job_runner is not None else None
        last_run = job_runner.last_run(entry.name) if job_runner is not None else None
        detail: str | None = None  # only the WatcherState.in_progress branch sets this
        if job is not None and job.status == "running":
            status: CaptureStatus = "running"
            stage = None
            started_at = None
            finished_at = None
            duration_s = None
            reason = None
        elif job is not None and job.status == "queued":
            status = "queued"
            stage = None
            started_at = None
            finished_at = None
            duration_s = None
            reason = None
        elif job is not None and job.status == "failed":
            status = "failed"
            stage = None
            started_at = None
            finished_at = job.finished_at_walltime
            duration_s = None
            reason = job.error
        elif job is not None and job.status == "done":
            # SF-G3-1: WebUI-completed jobs must surface their wall-clock
            # finished_at — otherwise Recent Captures rendered "—" because
            # this branch used to fall through to the ply-not-None path.
            status = "done"
            stage = "export"
            started_at = job.started_at_walltime
            finished_at = job.finished_at_walltime
            duration_s = None
            reason = None
        elif in_progress_path == path_str:
            status = "running"
            stage = state.in_progress.stage if state.in_progress else None
            started_at = state.in_progress.started_at if state.in_progress else None
            finished_at = None
            duration_s = None
            reason = None
            detail = state.in_progress.detail if state.in_progress else None
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
        elif last_run is not None and last_run.status == "failed" and ply is None:
            # Durable failed status from runs.jsonl — a WebUI job that failed
            # before a restart (in-memory job gone) must not revert to 'idle'.
            status = "failed"
            stage = None
            started_at = last_run.started_at_walltime
            finished_at = last_run.finished_at_walltime
            duration_s = None
            reason = last_run.error
        elif last_run is not None and last_run.status == "done" and ply is not None:
            # Durable done status from runs.jsonl — a WebUI job that finished
            # before a restart (in-memory job gone) must still surface its
            # wall-clock finished_at instead of falling through to the bare
            # ply-not-None branch below, which has no timestamp to offer.
            status = "done"
            stage = "export"
            started_at = last_run.started_at_walltime
            finished_at = last_run.finished_at_walltime
            duration_s = None
            reason = None
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
                detail=detail,
                review_status=review_status,
                reclaimable_bytes=life.reclaimable_bytes,
                grace_days_left=life.grace_days_left,
            )
        )

    # SF-NEW-3: order by wall-clock finished_at DESC (most-recent first),
    # falling back to capture name DESC for captures without a timestamp
    # (idle/queued/running) so within-day order stays deterministic.
    captures.sort(key=lambda c: c.id, reverse=True)
    captures.sort(key=lambda c: c.finished_at or "", reverse=True)
    return captures


_SORT_KEYS = {
    "id": lambda c: c.id,
    "created": lambda c: c.id,  # capture id is prefixed YYYY-MM-DD, same ordering
    "status": lambda c: c.status,
    "stage": lambda c: c.stage or "",
    "ply": lambda c: c.ply_size_bytes or 0,
}


def sort_captures(
    captures: list[CaptureInfo], sort: str | None, direction: str = "desc"
) -> list[CaptureInfo]:
    """Re-order captures by a list-column key (click-to-sort UI).

    `sort=None` (or an unknown key) passes the input order through unchanged —
    callers rely on this to keep `list_captures`'s finished_at-desc default.
    """
    key = _SORT_KEYS.get(sort) if sort else None
    if key is None:
        return captures
    return sorted(captures, key=key, reverse=(direction != "asc"))


def get_capture(
    captures_dir: Path,
    capture_id: str,
    job_runner: JobRunner | None = None,
    *,
    grace_days: int = 30,
) -> CaptureInfo | None:
    """Return a single CaptureInfo by id, or None if not found."""
    capture_path = captures_dir / capture_id
    if not capture_path.is_dir() or not _CAPTURE_DIR_RE.match(capture_id):
        return None

    all_captures = list_captures(captures_dir, job_runner, grace_days=grace_days)
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


def _colmap_activity_mtime(capture_dir: Path) -> float | None:
    """Latest mtime among COLMAP's own workspace files (database.db, sparse/**).

    COLMAP's subprocesses (feature_extractor/matcher/mapper) are blocking
    external processes that never touch pipeline.log — during their silent
    stretches (especially the mapper) these files are the only on-disk sign
    that work is still happening.
    """
    colmap_dir = capture_dir / "colmap"
    mtimes: list[float] = []
    with contextlib.suppress(OSError):
        mtimes.append((colmap_dir / "database.db").stat().st_mtime)
    sparse_dir = colmap_dir / "sparse"
    if sparse_dir.is_dir():
        for f in sparse_dir.rglob("*"):
            if f.is_file():
                with contextlib.suppress(OSError):
                    mtimes.append(f.stat().st_mtime)
    return max(mtimes) if mtimes else None


def last_activity_age_s(capture_dir: Path, now: float | None = None) -> int | None:
    """Seconds since the most recent sign of activity, or None if there is none.

    A stage-agnostic liveness signal: pipeline.log is appended throughout every
    in-process stage, but COLMAP's own subprocesses (feature_extractor/matcher/
    mapper) write only to their own workspace — see `_colmap_activity_mtime`.
    The freshest of the two wins.
    """
    mtimes: list[float] = []
    with contextlib.suppress(OSError):
        mtimes.append((capture_dir / "pipeline.log").stat().st_mtime)
    colmap_mtime = _colmap_activity_mtime(capture_dir)
    if colmap_mtime is not None:
        mtimes.append(colmap_mtime)
    if not mtimes:
        return None
    return max(0, int((now if now is not None else time.time()) - max(mtimes)))
