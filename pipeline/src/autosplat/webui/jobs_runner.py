# SPDX-License-Identifier: AGPL-3.0-or-later

"""Async background job runner for the autosplat WebUI.

Wraps run_pipeline() in an asyncio thread so it doesn't block the ASGI event loop.
Tracks JobState per capture_id and supports cancel via process termination.
"""

from __future__ import annotations

import asyncio
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from autosplat.config import Config
from autosplat.logging import get_logger

logger = get_logger(__name__)

JobStatus = Literal["queued", "running", "done", "failed", "cancelled"]


@dataclass
class JobState:
    capture_id: str
    status: JobStatus
    started_at: float = field(default_factory=time.monotonic)
    finished_at: float | None = None
    log_lines: deque[str] = field(default_factory=lambda: deque(maxlen=500))
    error: str | None = None
    _proc: object = field(default=None, repr=False)  # subprocess.Popen handle
    _thread: threading.Thread | None = field(default=None, repr=False)

    @property
    def eta_s(self) -> float | None:
        return None  # P3-stub; full ETA requires BrushConfig access per job

    def append_log(self, line: str) -> None:
        self.log_lines.append(line)

    def get_log_tail(self) -> list[str]:
        return list(self.log_lines)


class JobRunner:
    """In-memory job registry for the WebUI.

    One job runs per capture_id; starting a new job for the same id
    cancels any existing one first.
    """

    def __init__(self) -> None:
        self._jobs: dict[str, JobState] = {}
        self._lock = asyncio.Lock()

    def get_job(self, capture_id: str) -> JobState | None:
        return self._jobs.get(capture_id)

    def all_jobs(self) -> list[JobState]:
        return list(self._jobs.values())

    async def start_job(self, capture_id: str, capture_path: Path, cfg: Config) -> JobState:
        async with self._lock:
            existing = self._jobs.get(capture_id)
            if existing and existing.status in ("queued", "running"):
                await self.cancel_job(capture_id)

            job = JobState(capture_id=capture_id, status="queued")
            self._jobs[capture_id] = job

        # Find the source video — look for any video file in capture_path
        video = _find_source_video(capture_path)
        if video is None:
            job.status = "failed"
            job.error = f"No source video found in {capture_path}"
            return job

        job.status = "running"
        thread = threading.Thread(
            target=_run_pipeline_thread,
            args=(job, video, cfg),
            daemon=True,
            name=f"autosplat-job-{capture_id}",
        )
        job._thread = thread
        thread.start()
        logger.info("job_runner.start", capture_id=capture_id, video=str(video))
        return job

    async def cancel_job(self, capture_id: str) -> bool:
        job = self._jobs.get(capture_id)
        if job is None or job.status not in ("queued", "running"):
            return False

        proc = job._proc
        if proc is not None:
            try:
                import subprocess
                if isinstance(proc, subprocess.Popen) and proc.poll() is None:
                    proc.terminate()
                    try:
                        proc.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        proc.kill()
            except Exception as e:
                logger.warning("job_runner.cancel_error", capture_id=capture_id, error=str(e))

        job.status = "cancelled"
        job.finished_at = time.monotonic()
        logger.info("job_runner.cancelled", capture_id=capture_id)
        return True


def _find_source_video(capture_path: Path) -> Path | None:
    video_exts = {".mp4", ".mov", ".m4v"}
    for ext in video_exts:
        candidates = list(capture_path.glob(f"**/*{ext}"))
        if candidates:
            return candidates[0]
    return None


def _run_pipeline_thread(job: JobState, video: Path, cfg: Config) -> None:
    """Execute run_pipeline in a background thread, updating job.status."""
    import subprocess

    from autosplat.pipeline import run_pipeline

    try:
        # Monkey-patch subprocess.Popen so we can capture the Brush process handle
        # for cancel support. We wrap only during this job's execution.
        original_popen = subprocess.Popen

        class _TrackingPopen(original_popen):  # type: ignore[valid-type,misc]
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                job._proc = self

        subprocess.Popen = _TrackingPopen  # type: ignore[misc]
        try:
            result = run_pipeline(video, cfg)
        finally:
            subprocess.Popen = original_popen  # type: ignore[misc]

        if job.status == "cancelled":
            return
        job.status = "done"
        job.finished_at = time.monotonic()
        job.append_log(f"Pipeline complete: {result.output_ply}")
        logger.info("job_runner.done", capture_id=job.capture_id, ply=str(result.output_ply))

    except Exception as e:
        if job.status == "cancelled":
            return
        job.status = "failed"
        job.finished_at = time.monotonic()
        job.error = str(e)
        job.append_log(f"Pipeline failed: {e}")
        logger.error("job_runner.failed", capture_id=job.capture_id, error=str(e))
