# Live Progress / Mission-Control — Design

**Date:** 2026-05-29
**Status:** Approved (autonomous implementation delegated)
**Target release:** v1.6.0

## Problem

During the long, opaque pipeline stages — COLMAP sparse reconstruction and the
~40 min Brush training — the WebUI looks frozen. `brush_metrics.html` renders
every tile as a hard-coded `—`, and the only liveness signal (a `train.heartbeat`
log line) is throttled to one entry every ~300 s. A user watching the page has
no moving element, no elapsed/ETA, no percent, and no way to tell a healthy run
from a hung one. For a neurodivergent maintainer this static screen reliably
triggers "is it dead?" anxiety.

## What data actually exists (verified against code + a live run)

| Datum | Source | Availability |
|---|---|---|
| `elapsed_s`, `est_pct` (time-based), `eta_s` | `run_brush` heartbeat, fires every 2 s | always |
| liveness ("updated Xs ago") | heartbeat wall-clock timestamp | always |
| real `step` + real eval-`psnr` | `PlateauMonitor` polling `eval_<step>/` dirs | only when `plateau_enabled = true` |
| loss, iter/s, GPU %, VRAM | — | **never** — Brush emits no per-step stdout, no GPU telemetry hook |

`est_pct` is a *time* estimate (`elapsed / estimated_wall_time`), not a true step
counter. loss/iter-s/gpu/vram tiles are dropped entirely rather than shown as
empty `—` placeholders (empty tiles are exactly what fuels the "static" feeling).

## Architecture — single source of truth: `progress.json`

A small `progress.json` written into the **capture root** (next to `state.json`
and `pipeline.log`) is the one channel between the running pipeline and any
reader (WebUI partial, CLI, future tooling). It decouples the display from log
throttling and works identically for the watch-daemon, the WebUI JobRunner, and
interactive CLI runs.

```jsonc
{
  "stage": "train",
  "elapsed_s": 1204.0,
  "est_pct": 0.5017,        // time-based 0..1
  "eta_s": 2400.0,          // total estimated wall time
  "updated_at": "2026-05-29T09:29:52Z",
  "step": 12000,            // null unless plateau eval ran
  "total_steps": 30000,     // null unless known
  "psnr": 24.8              // null unless plateau eval ran
}
```

`train.py` stays pure — it only invokes callbacks. `pipeline.py` owns
persistence (it already composes the heartbeat callback), so the
progress-file concern lives in one place.

## Components & slices

**Slice 1 — `src/autosplat/progress.py`**
`@dataclass ProgressState` + `write_progress(capture_dir, state)` (atomic
tmp-write + `os.replace`) + `read_progress(capture_dir) -> ProgressState | None`
(returns `None` on missing/corrupt JSON). Pure, fully unit-tested.

**Slice 2 — heartbeat → `progress.json`**
`pipeline.py`: on every heartbeat (every 2 s) write `progress.json` with the
time-based fields; lower `TRAIN_HEARTBEAT_INTERVAL_S` 300 → 30 for the *log*
emitter (the file write is unthrottled). The persister is a new callback
composed alongside `_emit_heartbeat`.

**Slice 3 — PlateauMonitor step/psnr**
`run_brush` gains an optional `eval_callback(step, psnr)` invoked from
`_plateau_loop` after each successful `poll_once`. `pipeline.py` wires it to
merge `step`/`total_steps`/`psnr` into `progress.json`. No-op when
`plateau_enabled` is false (current default).

**Slice 4 — `brush_metrics.html` renders `progress.json`**
Partial route reads `read_progress(capture.path)` and passes it in. Template:
moving progress bar + `%`, `elapsed` (mm:ss), `eta` remaining, a pulsing health
dot with "updated Xs ago", and a **stall warning** ("⚠ stalled?") when
`now - updated_at` exceeds a threshold (e.g. 90 s). Real `step` + `psnr` tiles
appear only when present in the file. Wrapped in a `<details>` for
collapse/expand, open by default, state persisted in `localStorage`.

**Slice 5 — all-stages liveness**
`last_activity_age_s(capture_dir, now)` derived from `pipeline.log` mtime gives a
stage-agnostic heartbeat. Running captures show an "active · Xs ago" pulse on the
detail page (and dashboard active-job line). COLMAP gets the pulse but no
percent bar (it reports no progress).

**Slice 6 — comprehensive logging**
`train.py` tees Brush stdout into a dedicated `brush.stdout.log` in the training
dir (so anything Brush flushes — even only at exit — is preserved for
diagnosis), and logs each eval-PSNR point when the plateau monitor produces one.

## Error handling

- `read_progress` never raises: missing/corrupt/partial JSON → `None`; the
  partial falls back to "warming up…" rather than erroring.
- Atomic writes (`os.replace`) guarantee the WebUI never reads a half-written
  file even though writes happen every 2 s while the page polls every 3 s.
- Stall detection is purely client-comparable (`updated_at` vs now), so a frozen
  pipeline surfaces as "⚠ stalled?" instead of a silently static screen.

## Testing

- Slice 1: round-trip, missing→None, corrupt→None, atomic-replace path.
- Slice 2/3: callbacks write/merge the expected fields; log throttle unchanged in
  behaviour (just a smaller interval).
- Slice 4: HTTP (TestClient) — bar shows pct, elapsed rendered, stall warning
  when `updated_at` stale, step/psnr hidden when absent and shown when present.
- Slice 5: age helper math; running capture renders the pulse.
- Slice 6: brush stdout lines land in `brush.stdout.log`.

## Out of scope

loss/iter-s/GPU/VRAM tiles (no data source); parsing Brush stdout for metrics
(Brush is silent mid-run); changing the plateau default.
