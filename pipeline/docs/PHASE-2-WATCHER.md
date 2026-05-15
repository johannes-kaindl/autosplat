# Phase 2 — Watch-Folder Daemon

Implements spec §11.2: a long-running daemon that processes drone videos as they arrive in an inbox folder, with persistent state and crash-recovery.

## Lifecycle

```
        drop *.mp4 / *.mov in inbox
                    │
                    ▼
       ┌──────────────────────────┐
       │ watchdog Observer thread │ — detects create / move events
       └──────────────────────────┘
                    │
                    │  (size-stability poll, then state.enqueue)
                    ▼
       ┌──────────────────────────┐
       │  queue.Queue (in-mem)    │
       │  WatcherState.queue (FS) │  — persisted on every mutation
       └──────────────────────────┘
                    │
                    │  worker thread: pop_next() → in_progress
                    ▼
       ┌──────────────────────────┐
       │   run_pipeline(video)    │
       └──────────────────────────┘
                    │
                    ├── ok    → state.mark_done()   → completed[]
                    └── error → state.mark_failed() → failed[]
```

One worker thread, one capture at a time — Brush already saturates the Mac GPU, parallel runs would only thrash.

## state.json schema

Lives at `~/.autosplat/state.json` by default. Written atomically (tmp + `os.replace`) so a SIGKILL mid-write cannot corrupt the file.

```json
{
  "queue": [
    "/AutoSplat/inbox/video3.mp4"
  ],
  "in_progress": {
    "path": "/AutoSplat/inbox/video2.mp4",
    "started_at": "2026-05-14T13:42:00Z",
    "stage": "training"
  },
  "completed": [
    {
      "path": "/AutoSplat/inbox/video1.mp4",
      "output_ply": "/AutoSplat/outputs/2026-05-14_video1/scene.ply",
      "duration_s": 435.6,
      "finished_at": "2026-05-14T13:35:00Z"
    }
  ],
  "failed": [
    {
      "path": "/AutoSplat/inbox/bad.mov",
      "failed_at": "2026-05-14T13:30:00Z",
      "reason": "interrupted",
      "stage": "sfm"
    }
  ]
}
```

### Field-by-field

| Field         | Type            | When                                              |
| ------------- | --------------- | ------------------------------------------------- |
| `queue`       | `list[str]`     | absolute paths, FIFO                              |
| `in_progress` | object or null  | exactly one capture at a time, null when idle     |
| `completed`   | `list[object]`  | grows unboundedly — manual prune if needed        |
| `failed`      | `list[object]`  | failures inc. crashed-mid-run (`reason: "interrupted"`) |

The loader is tolerant of pre-Phase-2 schemas — it accepts both `started` and `started_at`, and synthesizes any missing `failed` list as empty.

## CLI

```bash
# Start daemon (runs until Ctrl-C)
autosplat watch ~/AutoSplat/inbox

# Process whatever's in the folder and exit
autosplat watch --once ~/AutoSplat/inbox

# Inspect current state — queue, in-progress, completed, failures
autosplat status
```

On start, `autosplat watch` does the following in order:

1. Load `state.json` (tolerates missing file, garbage JSON, old schema)
2. `recover_state()` — any orphan `in_progress` entry from a previous crash is moved to `failed` with reason `"interrupted"`. Phase 3 will turn that into an adaptive retry.
3. Resume queue from `state.json` (paths queued before the previous shutdown)
4. Optionally scan the inbox for pre-existing files (controlled by `process_existing`)
5. Start the watchdog Observer + worker thread

## Crash-recovery example

```bash
# Imagine autosplat was SIGKILLed while training:
$ cat ~/.autosplat/state.json
{
  "queue": [],
  "in_progress": {"path": "/inbox/foo.mp4", "stage": "training", "started_at": "..."},
  "completed": [],
  "failed": []
}

$ autosplat watch ~/inbox
Recovered 1 in-progress entry from previous run (moved to failed: 'interrupted').
Watching: /inbox (Ctrl-C to stop)

$ autosplat status
No active run.
                    Recent failures
┏━━━━━━━━━━━━━━━━┳━━━━━━━━━━┳━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━┓
┃ Video          ┃ Stage    ┃ Reason      ┃ Failed at            ┃
┡━━━━━━━━━━━━━━━━╇━━━━━━━━━━╇━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━┩
│ /inbox/foo.mp4 │ training │ interrupted │ 2026-05-14T13:30:00Z │
└────────────────┴──────────┴─────────────┴──────────────────────┘
```

## Threading & state safety

- `WatcherState.lock` (a `threading.Lock`) guards every mutation. Mutation helpers (`enqueue`, `pop_next`, `mark_done`, `mark_failed`) acquire the lock internally — callers must NOT also hold it.
- Writes are atomic: temp file in the same directory → `os.fsync` → `os.replace`. The state file is either fully old or fully new on disk.
- The watchdog event thread is intentionally light — it only enqueues. All heavy work happens on the single worker thread.

## Acceptance against spec §11.2

| Criterion                                                | Status                                       |
| -------------------------------------------------------- | -------------------------------------------- |
| `autosplat watch ~/inbox` processes files FIFO           | ✅ `test_daemon_processes_existing_files_sequentially` |
| Process survives single-capture failures (no hard crash) | ✅ `test_daemon_survives_processing_failure` |
| State file consistent across kill/restart                | ✅ `test_atomic_save_*` + `test_load_tolerates_corrupt_state_file` |
| Two files in inbox processed serially                    | ✅ — single worker thread, FIFO `queue.Queue` |

## Out of scope (Phase 3)

- **Automatic re-queue on `interrupted` entries.** Today they go to `failed`; the user re-triggers manually. Phase 3 adaptive-retry would re-enqueue with backoff.
- **Quality-gating before Brush.** As proposed in `PHASE-0-CALIBRATION.md`, the cameras-registered ratio should gate Brush from running on hopelessly-bad SfM output.
- **Concurrent processing across multiple inboxes.** Current design is single-folder, single-worker. Multi-tenant capture-stations are a future concern.
