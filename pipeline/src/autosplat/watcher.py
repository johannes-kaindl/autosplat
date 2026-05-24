# SPDX-License-Identifier: AGPL-3.0-or-later

"""Watch-folder daemon (Phase 2).

Spec §11.2 acceptance:
  - `autosplat watch <folder>` runs as a long-lived daemon, sequential
  - Process survives single-capture failures (no hard crash)
  - State file consistent across kill/restart
  - Two files in inbox are processed FIFO

Architecture:
  - The watchdog Observer runs on its own thread and only enqueues path strings.
  - A single worker thread pulls from a queue.Queue and invokes the supplied
    `process` callable. One capture at a time — Brush already saturates the
    Mac GPU, parallel runs would only thrash.
  - All mutations of WatcherState go through `state_lock` and are persisted
    atomically (tmp + os.replace) so a SIGKILL mid-write can't corrupt JSON.
  - On startup, `recover_state()` moves any `in_progress` entry to `failed`
    with reason "interrupted" — Phase 3 will turn that into an adaptive retry.
"""

from __future__ import annotations

import json
import os
import queue
import tempfile
import threading
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer

from .config import RetryConfig, StatusConfig
from .logging import get_logger
from .quality import QualityGateFailure, retry_hint_for_brush_oom
from .train import BrushOOMError

logger = get_logger(__name__)

VIDEO_SUFFIXES = {".mp4", ".mov", ".m4v"}
DEFAULT_STATE_FILE = Path("~/.autosplat/state.json").expanduser()
STABILITY_CHECK_INTERVAL_S = 2.0
STABILITY_CHECK_COUNT = 3

EntryStatus = Literal["queued", "processing", "done", "failed"]


def _now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


@dataclass
class InProgress:
    """Snapshot of the currently-executing capture. Persisted so a crash leaves
    a trail. Stage is updated by run_pipeline as it advances.

    `path` is the capture *directory* once run_pipeline has called begin() —
    that is what the WebUI matches against. `source_video` keeps the original
    input path so the retry/recovery machinery can re-enqueue it.
    """

    path: str
    started_at: str
    stage: str = "starting"
    source_video: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> InProgress:
        return cls(
            path=d["path"],
            started_at=d.get("started_at") or d.get("started") or _now_iso(),
            stage=d.get("stage", "starting"),
            source_video=d.get("source_video"),
        )


@dataclass
class CompletedEntry:
    path: str
    output_ply: str
    duration_s: float
    finished_at: str

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> CompletedEntry:
        return cls(
            path=d["path"],
            output_ply=d.get("output_ply", ""),
            duration_s=float(d.get("duration_s", 0.0)),
            finished_at=d.get("finished_at") or _now_iso(),
        )


@dataclass
class FailedEntry:
    path: str
    failed_at: str
    reason: str
    stage: str | None = None
    retry_count: int = 0  # Phase 3: how many attempts before giving up

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> FailedEntry:
        return cls(
            path=d["path"],
            failed_at=d.get("failed_at") or _now_iso(),
            reason=d.get("reason", "unknown"),
            stage=d.get("stage"),
            retry_count=int(d.get("retry_count", 0)),
        )


@dataclass
class RetryRecord:
    """Phase-3 per-path retry state. Persisted in WatcherState.retry_state."""

    attempts: int = 0  # number of attempts already made (0 before first run)
    last_reason: str | None = None
    next_override: dict | None = None  # cfg override to apply on the next try

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> RetryRecord:
        return cls(
            attempts=int(d.get("attempts", 0)),
            last_reason=d.get("last_reason"),
            next_override=d.get("next_override"),
        )


@dataclass
class WatcherState:
    """Persistent state model for the watch-folder daemon.

    Mutation must hold `lock`. Persistence is atomic via tmp+os.replace.
    """

    queue: list[str] = field(default_factory=list)
    in_progress: InProgress | None = None
    completed: list[CompletedEntry] = field(default_factory=list)
    failed: list[FailedEntry] = field(default_factory=list)
    # Phase 3: per-path retry tracking (path → RetryRecord)
    retry_state: dict[str, RetryRecord] = field(default_factory=dict)

    state_file: Path = field(default=DEFAULT_STATE_FILE)
    lock: threading.Lock = field(default_factory=threading.Lock)

    def to_dict(self) -> dict:
        return {
            "queue": list(self.queue),
            "in_progress": self.in_progress.to_dict() if self.in_progress else None,
            "completed": [e.to_dict() for e in self.completed],
            "failed": [e.to_dict() for e in self.failed],
            "retry_state": {k: v.to_dict() for k, v in self.retry_state.items()},
        }

    @classmethod
    def load(cls, state_file: Path = DEFAULT_STATE_FILE) -> WatcherState:
        if not state_file.exists():
            return cls(state_file=state_file)
        try:
            data = json.loads(state_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            logger.error("watcher.state_unreadable", path=str(state_file), error=str(e))
            return cls(state_file=state_file)

        return cls(
            queue=list(data.get("queue", [])),
            in_progress=(
                InProgress.from_dict(data["in_progress"]) if data.get("in_progress") else None
            ),
            completed=[CompletedEntry.from_dict(d) for d in data.get("completed", [])],
            failed=[FailedEntry.from_dict(d) for d in data.get("failed", [])],
            retry_state={
                k: RetryRecord.from_dict(v) for k, v in (data.get("retry_state") or {}).items()
            },
            state_file=state_file,
        )

    def save(self) -> None:
        """Atomic save: write to a sibling temp file, then os.replace.

        Crash mid-write cannot leave an unparseable state.json on disk —
        os.replace is atomic on POSIX file systems.
        """
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(self.to_dict(), indent=2)
        # Sibling tmp file keeps the rename on the same FS for atomicity.
        fd, tmp_path = tempfile.mkstemp(
            prefix=".state.", suffix=".tmp", dir=str(self.state_file.parent)
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(payload)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, self.state_file)
        except Exception:
            # Best-effort cleanup of the temp file on failure.
            import contextlib

            with contextlib.suppress(OSError):
                os.unlink(tmp_path)
            raise

    # --- Mutation helpers — caller must NOT also acquire self.lock. ---

    def enqueue(self, path: Path) -> bool:
        """Add `path` to the back of the queue, unless already queued or in-flight.

        Returns True if newly added.
        """
        path_str = str(path)
        with self.lock:
            if path_str in self.queue:
                return False
            if self.in_progress and self.in_progress.path == path_str:
                return False
            self.queue.append(path_str)
            self.save()
        logger.info("watcher.enqueued", path=path_str, queue_size=len(self.queue))
        return True

    def pop_next(self) -> tuple[str, dict | None] | None:
        """Pop head of queue, set in_progress, return (path, pending_override).

        `pending_override` is the cfg-override dict the worker should apply for
        this attempt (set on a previous failure by Phase-3 adaptive retry).
        Returns None if the queue is empty.
        """
        with self.lock:
            if not self.queue:
                return None
            path = self.queue.pop(0)
            # Crash-safety net between pop and run_pipeline's begin(): keep the
            # video path in both fields. run_pipeline.begin() then re-keys
            # `path` to the capture directory, leaving source_video intact.
            self.in_progress = InProgress(path=path, started_at=_now_iso(), source_video=path)
            override = None
            record = self.retry_state.get(path)
            if record is not None and record.next_override:
                override = record.next_override
                # Bump attempt counter and clear the pending override now that
                # we're consuming it. attempts now reflects the run we're about
                # to start (1=first try, 2=second try, …).
                record.attempts += 1
                record.next_override = None
            elif record is not None:
                record.attempts += 1
            else:
                self.retry_state[path] = RetryRecord(attempts=1)
            self.save()
        return (path, override)

    def begin(self, capture_dir: Path, source_video: Path | None = None) -> None:
        """Mark `capture_dir` as the in-progress capture.

        Called by run_pipeline so every trigger path (CLI-direct, watch-daemon,
        WebUI) reports status keyed by the capture directory — the key the
        WebUI matches against. Overwrites any prior in_progress (single-slot).
        """
        with self.lock:
            self.in_progress = InProgress(
                path=str(capture_dir),
                started_at=_now_iso(),
                source_video=str(source_video) if source_video is not None else None,
            )
            self.save()

    def update_stage(self, stage: str) -> None:
        with self.lock:
            if self.in_progress is None:
                return
            self.in_progress.stage = stage
            self.save()

    def mark_done(
        self, output_ply: Path, duration_s: float, *, max_history: int | None = None
    ) -> None:
        with self.lock:
            if self.in_progress is None:
                return
            path = self.in_progress.path
            self.completed.append(
                CompletedEntry(
                    path=path,
                    output_ply=str(output_ply),
                    duration_s=duration_s,
                    finished_at=_now_iso(),
                )
            )
            self.in_progress = None
            # Successful completion → wipe retry state for this path
            self.retry_state.pop(path, None)
            if max_history is not None and len(self.completed) > max_history:
                self.completed = self.completed[-max_history:]
            self.save()

    def mark_failed(
        self,
        reason: str,
        stage: str | None = None,
        *,
        retry_count: int = 0,
        max_history: int | None = None,
    ) -> None:
        with self.lock:
            if self.in_progress is None:
                return
            self.failed.append(
                FailedEntry(
                    path=self.in_progress.path,
                    failed_at=_now_iso(),
                    reason=reason,
                    stage=stage or self.in_progress.stage,
                    retry_count=retry_count,
                )
            )
            self.in_progress = None
            if max_history is not None and len(self.failed) > max_history:
                self.failed = self.failed[-max_history:]
            self.save()

    def schedule_retry(self, override: dict | None) -> None:
        """Re-enqueue the in_progress path for another attempt.

        Stores `override` (if any) in retry_state so the next pop_next picks
        it up. Caller must have already validated that retries remain.
        """
        with self.lock:
            if self.in_progress is None:
                return
            # Queue + retry_state are keyed by the source video; in_progress.path
            # is the capture directory once run_pipeline has re-keyed it.
            path = self.in_progress.source_video or self.in_progress.path
            record = self.retry_state.setdefault(path, RetryRecord())
            record.next_override = override
            # in_progress.attempts was set by pop_next; we leave it as the
            # already-consumed count and let the next pop_next bump it again.
            self.in_progress = None
            self.queue.append(path)
            self.save()
        logger.info(
            "watcher.retry_scheduled",
            path=path,
            attempts_so_far=record.attempts,
            override=override,
        )


def recover_state(
    state: WatcherState,
    retry_cfg: RetryConfig | None = None,
) -> int:
    """Reconcile a state-file from a previous (possibly crashed) session.

    Anything we found in `in_progress` was mid-flight when the process died.
    Phase-3 behaviour:
      - If retries are enabled and `retry_state[path].attempts < max_retries`,
        re-enqueue the path so the daemon picks it up again on this start.
      - Otherwise, move it to `failed` with reason "interrupted_max_retries"
        (or just "interrupted" if retries disabled) so the user sees it.

    Returns 1 if there was an orphan to reconcile, else 0.
    """
    with state.lock:
        orphan = state.in_progress
        if orphan is None:
            return 0

        # Queue + retry_state are keyed by the source video; the failed-entry
        # is keyed by the capture directory so the WebUI can match it.
        video = orphan.source_video or orphan.path
        capture_path = orphan.path
        record = state.retry_state.get(video) or RetryRecord()
        retries_remaining = (
            retry_cfg is not None and retry_cfg.enabled and record.attempts < retry_cfg.max_retries
        )

        if retries_remaining:
            # Re-enqueue. Don't add to failed — the failure will land there only
            # if all retries are exhausted.
            record.last_reason = "interrupted"
            record.next_override = record.next_override  # preserve any pending hint
            state.retry_state[video] = record
            state.in_progress = None
            if video not in state.queue:
                state.queue.append(video)
            state.save()
            logger.warning(
                "watcher.recovered",
                path=video,
                stage=orphan.stage,
                action="re_enqueued",
                attempts_so_far=record.attempts,
                max_retries=retry_cfg.max_retries if retry_cfg else None,
            )
            return 1

        # No retries left (or retries disabled): final-fail.
        reason = "interrupted_max_retries" if retry_cfg and retry_cfg.enabled else "interrupted"
        state.failed.append(
            FailedEntry(
                path=capture_path,
                failed_at=_now_iso(),
                reason=reason,
                stage=orphan.stage,
                retry_count=record.attempts,
            )
        )
        state.in_progress = None
        state.save()
    logger.warning(
        "watcher.recovered",
        path=orphan.path,
        stage=orphan.stage,
        action="moved_to_failed",
        attempts=record.attempts,
    )
    return 1


def reconcile_failure(
    state: WatcherState,
    *,
    reason: str,
    stage: str | None,
    retry_hint: dict | None,
    retry_cfg: RetryConfig,
    max_history: int | None = None,
) -> str:
    """Decide whether the in_progress capture should be retried or final-failed.

    Returns "retry" if scheduled for re-run, "failed" if marked terminal.
    """
    if state.in_progress is None:
        return "noop"
    # Keyed by source video — see schedule_retry.
    path = state.in_progress.source_video or state.in_progress.path
    record = state.retry_state.get(path) or RetryRecord()
    record.last_reason = reason

    can_retry = retry_cfg.enabled and record.attempts < retry_cfg.max_retries

    if can_retry:
        state.retry_state[path] = record
        state.schedule_retry(override=retry_hint)
        return "retry"

    # Out of retries — write a final failure.
    state.mark_failed(
        reason=reason if record.attempts <= 1 else f"{reason} (after {record.attempts} attempts)",
        stage=stage,
        retry_count=record.attempts,
        max_history=max_history,
    )
    return "failed"


def _is_size_stable(path: Path) -> bool:
    """Poll `path`'s size to decide it's no longer being written to."""
    if not path.exists():
        return False
    sizes: list[int] = []
    for _ in range(STABILITY_CHECK_COUNT):
        sizes.append(path.stat().st_size)
        time.sleep(STABILITY_CHECK_INTERVAL_S)
    return len(set(sizes)) == 1 and sizes[0] > 0


class _VideoEventHandler(FileSystemEventHandler):
    """watchdog handler — fast path: just enqueue the path. Worker does the work."""

    def __init__(self, on_ready: Callable[[Path], None]):
        self._on_ready = on_ready

    def _maybe_handle(self, raw_path: str) -> None:
        path = Path(raw_path)
        if path.suffix.lower() not in VIDEO_SUFFIXES:
            return
        logger.info("watcher.detected", path=str(path))
        if _is_size_stable(path):
            self._on_ready(path)
        else:
            logger.warning("watcher.unstable", path=str(path))

    def on_created(self, event: FileSystemEvent) -> None:
        if event.is_directory:
            return
        self._maybe_handle(event.src_path)

    def on_moved(self, event: FileSystemEvent) -> None:
        if event.is_directory:
            return
        target = getattr(event, "dest_path", event.src_path)
        self._maybe_handle(target)


class WatchDaemon:
    """Long-lived watch-folder daemon — coordinates Observer, queue, and worker.

    Lifecycle:
        d = WatchDaemon(folder, state, process_fn, retry_cfg=…, status_cfg=…)
        d.start(process_existing=True)
        d.wait_until_idle()         # for tests, or
        d.wait_for_shutdown()       # for the CLI (blocks until Ctrl-C)
        d.stop()

    Sequential by construction — one worker thread, one item at a time.

    `process_fn(path, config_override=…)` is called per capture. It must accept
    the override kwarg even if it ignores it — Phase-3 adaptive retry uses it
    to swap the COLMAP matcher (or any other deep-merge override).
    """

    def __init__(
        self,
        folder: Path,
        state: WatcherState,
        process_fn: Callable[..., dict],
        *,
        retry_cfg: RetryConfig | None = None,
        status_cfg: StatusConfig | None = None,
    ):
        self._folder = folder
        self._state = state
        self._process_fn = process_fn
        self._retry_cfg = retry_cfg or RetryConfig()
        self._status_cfg = status_cfg or StatusConfig()
        self._work_queue: queue.Queue[str] = queue.Queue()
        self._observer: Observer | None = None
        self._worker: threading.Thread | None = None
        self._stop = threading.Event()
        self._idle = threading.Event()
        self._idle.set()

    def _enqueue_path(self, path: Path) -> None:
        if self._state.enqueue(path):
            self._work_queue.put(str(path))

    def _worker_loop(self) -> None:
        while not self._stop.is_set():
            try:
                self._work_queue.get(timeout=0.5)
            except queue.Empty:
                continue
            self._idle.clear()
            popped = self._state.pop_next()
            if popped is None:
                self._idle.set()
                self._work_queue.task_done()
                continue
            path, override = popped
            try:
                # run_pipeline reports status into self._state itself (begin /
                # update_stage / mark_done), so the worker no longer marks done.
                self._process_fn(Path(path), config_override=override)
                logger.info("watcher.done", path=path)
            except QualityGateFailure as e:
                outcome = reconcile_failure(
                    self._state,
                    reason=e.reason,
                    stage=e.stage,
                    retry_hint=e.retry_hint,
                    retry_cfg=self._retry_cfg,
                    max_history=self._status_cfg.max_history,
                )
                logger.warning(
                    "watcher.quality_gate_failure",
                    path=path,
                    reason=e.reason,
                    outcome=outcome,
                    metrics=e.metrics,
                )
                if outcome == "retry":
                    # Re-add to the in-process queue so the worker picks it up.
                    self._work_queue.put(path)
            except BrushOOMError as e:
                hint = retry_hint_for_brush_oom(e.resolution_cap_attempted)
                outcome = reconcile_failure(
                    self._state,
                    reason=f"brush_oom: resolution_cap={e.resolution_cap_attempted}",
                    stage="train",
                    retry_hint=hint,
                    retry_cfg=self._retry_cfg,
                    max_history=self._status_cfg.max_history,
                )
                logger.warning(
                    "watcher.brush_oom",
                    path=path,
                    resolution_cap_attempted=e.resolution_cap_attempted,
                    next_resolution_cap=hint["brush"]["resolution_cap"],
                    outcome=outcome,
                )
                if outcome == "retry":
                    self._work_queue.put(path)
            except Exception as e:
                outcome = reconcile_failure(
                    self._state,
                    reason=str(e),
                    stage=None,
                    retry_hint=None,
                    retry_cfg=self._retry_cfg,
                    max_history=self._status_cfg.max_history,
                )
                logger.error("watcher.process_failed", path=path, error=str(e), outcome=outcome)
                if outcome == "retry":
                    self._work_queue.put(path)
            finally:
                self._work_queue.task_done()
                if self._work_queue.empty():
                    self._idle.set()

    def start(self, *, process_existing: bool = True) -> None:
        if not self._folder.exists():
            raise FileNotFoundError(f"Watch folder does not exist: {self._folder}")

        # Resume queue from state.json (e.g., enqueued before previous crash).
        for queued_path in list(self._state.queue):
            self._work_queue.put(queued_path)

        if process_existing:
            for existing in sorted(self._folder.iterdir()):
                if (
                    existing.is_file()
                    and existing.suffix.lower() in VIDEO_SUFFIXES
                    and _is_size_stable(existing)
                ):
                    self._enqueue_path(existing)

        handler = _VideoEventHandler(self._enqueue_path)
        self._observer = Observer()
        self._observer.schedule(handler, str(self._folder), recursive=False)
        self._observer.start()

        self._worker = threading.Thread(
            target=self._worker_loop, name="autosplat-worker", daemon=True
        )
        self._worker.start()

        logger.info("watcher.started", folder=str(self._folder))

    def wait_until_idle(self, timeout: float | None = None) -> bool:
        """Block until the queue is drained. Used by tests and `--once`."""
        return self._idle.wait(timeout=timeout)

    def wait_for_shutdown(self) -> None:
        """Block until KeyboardInterrupt — used by the CLI long-running mode."""
        assert self._observer is not None
        try:
            while self._observer.is_alive():
                self._observer.join(timeout=1.0)
        except KeyboardInterrupt:
            pass

    def stop(self) -> None:
        self._stop.set()
        if self._observer is not None:
            self._observer.stop()
            self._observer.join(timeout=5)
        if self._worker is not None:
            self._worker.join(timeout=10)


# ─── Backwards-compat shim ──────────────────────────────────────────────────
# Some code (and tests) still imports STATE_FILE / watch_folder. Keep them.

STATE_FILE = DEFAULT_STATE_FILE


def watch_folder(
    folder: Path,
    on_ready: Callable[[Path], None],
    *,
    process_existing: bool = True,
) -> Observer:
    """Lightweight watcher used pre-Phase-2 — keeps existing CLI import working."""
    if not folder.exists():
        raise FileNotFoundError(f"Watch folder does not exist: {folder}")

    if process_existing:
        for existing in sorted(folder.iterdir()):
            if (
                existing.is_file()
                and existing.suffix.lower() in VIDEO_SUFFIXES
                and _is_size_stable(existing)
            ):
                on_ready(existing)

    handler = _VideoEventHandler(on_ready)
    observer = Observer()
    observer.schedule(handler, str(folder), recursive=False)
    observer.start()
    logger.info("watcher.started", folder=str(folder))
    return observer
