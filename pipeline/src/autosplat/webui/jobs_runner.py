# SPDX-License-Identifier: AGPL-3.0-or-later

"""Async background job runner for the autosplat WebUI.

Wraps run_pipeline() in an asyncio thread so it doesn't block the ASGI event loop.
Tracks JobState per capture_id and supports cancel via process termination.
"""

from __future__ import annotations

import asyncio
import json
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from autosplat.config import Config
from autosplat.logging import get_logger
from autosplat.watcher import _now_iso

logger = get_logger(__name__)

RUNS_FILENAME = "runs.jsonl"

JobStatus = Literal["queued", "running", "done", "failed", "cancelled"]


@dataclass
class JobState:
    capture_id: str
    status: JobStatus
    started_at: float = field(default_factory=time.monotonic)
    finished_at: float | None = None
    # Wall-clock ISO-UTC timestamps; monotonic siblings stay for duration math.
    started_at_walltime: str = field(default_factory=_now_iso)
    finished_at_walltime: str | None = None
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
    cancels any existing one first. `_jobs` holds the *current* job per
    capture; `_history` keeps every job ever started so the jobs view can
    show all runs of a re-triggered capture (SF-G3-3).
    """

    def __init__(self, captures_dir: Path | None = None) -> None:
        self._jobs: dict[str, JobState] = {}
        self._history: list[JobState] = []
        self._lock = asyncio.Lock()
        # When set, finalized jobs are appended to <captures_dir>/<id>/runs.jsonl
        # so the WebUI's recent-jobs view survives a server restart (V12-2).
        self.captures_dir = captures_dir

    def _persist_job(self, job: JobState) -> None:
        """Append a finalized job to <captures_dir>/<capture_id>/runs.jsonl."""
        if self.captures_dir is None:
            return
        capture_dir = self.captures_dir / job.capture_id
        if not capture_dir.exists():
            # Capture directory was removed mid-run; skip persist silently.
            return
        record = {
            "capture_id": job.capture_id,
            "status": job.status,
            "started_at": job.started_at_walltime,
            "finished_at": job.finished_at_walltime,
            "error": job.error,
        }
        runs_path = capture_dir / RUNS_FILENAME
        try:
            with runs_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(record) + "\n")
        except OSError as e:
            logger.warning(
                "job_runner.persist_failed",
                capture_id=job.capture_id,
                error=str(e),
            )

    def load_history(self) -> None:
        """Populate _history from every <capture>/runs.jsonl on startup.

        Malformed lines are skipped — a corrupted single entry must not block
        the entire load. Captures without runs.jsonl produce no entries.
        """
        if self.captures_dir is None or not self.captures_dir.exists():
            return
        for capture_dir in self.captures_dir.iterdir():
            if not capture_dir.is_dir():
                continue
            runs_path = capture_dir / RUNS_FILENAME
            if not runs_path.exists():
                continue
            try:
                lines = runs_path.read_text(encoding="utf-8").splitlines()
            except OSError as e:
                logger.warning(
                    "job_runner.read_failed",
                    path=str(runs_path),
                    error=str(e),
                )
                continue
            for line in lines:
                if not line.strip():
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    logger.warning(
                        "job_runner.skip_malformed",
                        path=str(runs_path),
                    )
                    continue
                job = JobState(
                    capture_id=record["capture_id"],
                    status=record["status"],
                )
                if record.get("started_at"):
                    job.started_at_walltime = record["started_at"]
                job.finished_at_walltime = record.get("finished_at")
                job.error = record.get("error")
                self._history.append(job)

    def _reconcile(self, job: JobState) -> None:
        """Liveness check: a job that still claims to be 'running' but whose
        worker thread has died (process suspended/killed mid-run) is marked
        'failed' — otherwise it hangs as a phantom job forever.
        """
        if (
            job.status == "running"
            and job._thread is not None
            and not job._thread.is_alive()
        ):
            job.status = "failed"
            job.error = "interrupted — the run ended without producing a result"
            job.finished_at = time.monotonic()
            job.finished_at_walltime = _now_iso()
            self._persist_job(job)
            logger.warning("job_runner.reconciled_stale", capture_id=job.capture_id)

    def get_job(self, capture_id: str) -> JobState | None:
        job = self._jobs.get(capture_id)
        if job is not None:
            self._reconcile(job)
        return job

    def all_jobs(self) -> list[JobState]:
        """Every job ever started, in start order — multiple runs per capture."""
        for job in self._history:
            self._reconcile(job)
        return list(self._history)

    async def start_job(self, capture_id: str, capture_path: Path, cfg: Config) -> JobState:
        async with self._lock:
            existing = self._jobs.get(capture_id)
            if existing and existing.status in ("queued", "running"):
                await self.cancel_job(capture_id)

            job = JobState(capture_id=capture_id, status="queued")
            self._jobs[capture_id] = job
            self._history.append(job)

        # Find the source video — look for any video file in capture_path
        video = _find_source_video(capture_path)
        if video is None:
            job.status = "failed"
            job.error = f"No source video found in {capture_path}"
            return job

        job.status = "running"
        thread = threading.Thread(
            target=_run_pipeline_thread,
            args=(job, video, cfg, self),
            daemon=True,
            name=f"autosplat-job-{capture_id}",
        )
        job._thread = thread
        thread.start()
        logger.info("job_runner.start", capture_id=capture_id, video=str(video))
        return job

    async def start_job_from_video(self, video: Path, cfg: Config) -> JobState:
        """Start a pipeline run for a video that has no capture dir yet.

        The capture id is derived exactly as run_pipeline derives it
        (`<date>_<video-stem>`), so the JobState keys onto the capture
        directory the pipeline will create.
        """
        from autosplat.pipeline import _make_capture_name

        capture_id = _make_capture_name(video)
        async with self._lock:
            existing = self._jobs.get(capture_id)
            if existing and existing.status in ("queued", "running"):
                await self.cancel_job(capture_id)

            job = JobState(capture_id=capture_id, status="queued")
            self._jobs[capture_id] = job
            self._history.append(job)

        job.status = "running"
        thread = threading.Thread(
            target=_run_pipeline_thread,
            args=(job, video, cfg, self),
            daemon=True,
            name=f"autosplat-job-{capture_id}",
        )
        job._thread = thread
        thread.start()
        logger.info("job_runner.start_from_video", capture_id=capture_id, video=str(video))
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
        job.finished_at_walltime = _now_iso()
        self._persist_job(job)
        logger.info("job_runner.cancelled", capture_id=capture_id)
        return True


def _find_source_video(capture_path: Path) -> Path | None:
    video_exts = {".mp4", ".mov", ".m4v"}
    for ext in video_exts:
        candidates = list(capture_path.glob(f"**/*{ext}"))
        if candidates:
            return candidates[0]
    return None


def _run_pipeline_thread(
    job: JobState, video: Path, cfg: Config, runner: JobRunner
) -> None:
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
        job.finished_at_walltime = _now_iso()
        runner._persist_job(job)
        job.append_log(f"Pipeline complete: {result.output_ply}")
        logger.info("job_runner.done", capture_id=job.capture_id, ply=str(result.output_ply))

    except Exception as e:
        if job.status == "cancelled":
            return
        job.status = "failed"
        job.finished_at = time.monotonic()
        job.finished_at_walltime = _now_iso()
        job.error = str(e)
        runner._persist_job(job)
        job.append_log(f"Pipeline failed: {e}")
        logger.error("job_runner.failed", capture_id=job.capture_id, error=str(e))
