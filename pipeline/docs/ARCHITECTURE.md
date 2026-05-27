---
title: ARCHITECTURE
aliases:
  - Architecture
created: 2026-05-14 14:32:12
updated: 2026-05-14 18:22:44
linter-yaml-title-alias: Architecture
---

# Architecture

> Authoritative spec: [`AUTO-SPLAT PIPELINE — Spec & Implementation Plan.md`](./AUTO-SPLAT%20PIPELINE%20%E2%80%94%20Spec%20%26%20Implementation%20Plan.md)
>
> This document is a developer's-eye view of the runtime — how the modules in `src/autosplat/` fit together as of Phases 0–8 done.

## Module map

```
cli.py            Typer entry point. Parses args, loads config, dispatches.
├── pipeline.py   Orchestrator. Glues stages, owns capture-dir layout, runs gate.
│   ├── preflight.py     Phase-6 ffprobe-validate + duration/resolution/fps plausibility
│   ├── preprocess.py    FFmpeg + Laplacian-blur filter + skipped-frames detection
│   ├── sfm.py           COLMAP feature_extractor → matcher → mapper (binary stats)
│   ├── quality.py       Phase-3 gate + Phase-6 Brush-OOM retry-hint policy
│   ├── train.py         Brush wrapper + dataset staging + OOM detection +
│   │                    Phase-7 wall-time-based progress heartbeat
│   ├── export.py        PLY validation (≥1 MB) + metadata.json + outputs copy
│   ├── compress.py      Phase-5 SOG/SPZ via splat-transform (via npx)
│   ├── viewer.py        Local HTTP server + browser open (SuperSplat / PlayCanvas)
│   └── obsidian.py      Phase-4 capture-note + Phase-8 frontmatter user-key-merge
├── watcher.py    Phase-2/3 daemon: queue, threaded worker, atomic state, retry,
│                 BrushOOMError → resolution_cap halving, pruning
├── doctor.py     Preflight: platform, python, ffmpeg, colmap, brush, compress,
│                 obsidian-config (Phase-8 vault-path validation)
├── config.py     Pydantic models with Field(description) + TOML layering +
│                 apply_override deep-merge (used by Phase-3 retry)
└── logging.py    structlog + Rich console + per-capture JSON pipeline.log
```

## End-to-end pipeline flow (Phase 8-complete)

```
                    ┌──────────────┐
                    │ Watch-Folder │  watchdog Observer thread (or `process` CLI)
                    │  *.mp4/mov   │  enqueues into thread-safe queue.Queue
                    └──────┬───────┘
                           │
                           ▼
                    ┌──────────────┐
                    │  Worker pop  │  pop_next() → (path, retry_override)
                    │  retry merge │  apply_override(cfg, override) if any
                    └──────┬───────┘
                           │
                           ▼
                  ┌──────────────────┐
                  │ run_pipeline()   │
                  │                  │
                  │  0. Preflight    │  ffprobe-validate + duration/resolution/fps    [Phase 6]
                  │  1. Preprocess   │  ffmpeg → frame_*.jpg + Laplacian + skipped-frames-detect
                  │  2. SfM          │  colmap feature_extractor / matcher / mapper
                  │  3. Quality-Gate │  ratio + min-points → raise if below            [Phase 3]
                  │  4. Train        │  brush <staged> → scene.ply
                  │                  │  + heartbeat → Rich progress-bar (TTY only)    [Phase 7]
                  │                  │  + OOM detection → BrushOOMError                [Phase 6]
                  │  5. Export       │  validate (≥1 MB) + metadata.json + outputs copy
                  │  6. Compress     │  splat-transform → SOG / SPZ (opt-in)           [Phase 5]
                  │  7. Viewer       │  open SuperSplat (opt-in)
                  │  8. Obsidian     │  capture-note with user-key-merge (opt-in)      [Phase 4 + 8]
                  └──────┬───────────┘
                         │
              ┌──────────┴──────────┐
              │                     │
         success                 QualityGateFailure / BrushOOMError / Exception
              │                     │
              ▼                     ▼
      ┌────────────┐       ┌──────────────────────────────────────┐
      │ mark_done  │       │ reconcile_failure(reason, retry_hint)│
      │ + prune    │       │  - QualityGate.low_camera_ratio →    │
      │ + clear    │       │      {colmap: {matcher: exhaustive}} │
      │ retry_state│       │  - BrushOOMError →                   │
      └────────────┘       │      {brush: {resolution_cap: //2}}  │
                           │  - if retries remain → schedule_retry │
                           │  - else → mark_failed(retry_count)    │
                           └──────────────────────────────────────┘
```

## Capture directory layout

Every `process` run creates a self-contained capture directory:

```
captures/2026-05-14_neo2_garden/
├── source/                 # original input (sometimes a symlink)
├── frames/                 # extracted keyframes (frame_00001.jpg…)
├── colmap/
│   ├── database.db         # SQLite — features + matches
│   └── sparse/0/           # cameras.bin, images.bin, points3D.bin (COLMAP 4.0+)
├── brush_dataset/          # symlinks: images→frames, sparse→colmap/sparse
├── training/               # Brush output (scene.ply + intermediate exports)
├── output/
│   ├── scene.ply           # the trained splat
│   └── metadata.json       # frame counts, COLMAP stats, durations
└── pipeline.log            # structured JSON event log
```

## Stage I/O

| Stage         | Input                                | Output                                       | Idempotent? |
| ------------- | ------------------------------------ | -------------------------------------------- | ----------- |
| Preflight     | `source/<video>`                     | ffprobe metadata or `PreflightFailure`       | n/a — pure function (Phase 6) |
| Preprocess    | `source/<video>`                     | `frames/frame_*.jpg` + skipped-frames count  | yes (wipes + redoes) |
| SfM           | `frames/`                            | `colmap/database.db`, `colmap/sparse/0/*.bin`| yes (overwrites)     |
| Quality-Gate  | `colmap/sparse/0/*.bin`, `frames/`   | (raises QualityGateFailure or no-op)         | n/a — pure function (Phase 3) |
| Train         | `colmap/sparse/0/`                   | `training/scene.ply` or `BrushOOMError`      | yes (Brush handles); progress heartbeat (Phase 7) |
| Export        | `training/scene.ply`                 | `output/scene.ply` (≥1 MB), `output/metadata.json` | yes (overwrites) |
| Compress      | `output/scene.ply`                   | `output/scene.sog` / `.spz`                  | yes (Phase 5, `-w` flag — opt-in) |
| Viewer        | `output/scene.ply`                   | Browser window (HTTP server on :8765)        | n/a                  |
| Obsidian      | `output/scene.ply`, capture metadata | `<vault>/<subdir>/<filename>.md` with merged frontmatter | yes (preserves user-tail + user frontmatter keys via Phase-4 markers + Phase-8 YAML merge) |

## State persistence (`~/.autosplat/state.json`)

Phase-3 schema. Atomic writes via tmp + `os.replace`.

```json
{
  "queue": ["..."],
  "in_progress": {"path": "...", "started_at": "...", "stage": "..."},
  "completed": [{"path", "output_ply", "duration_s", "finished_at"}],
  "failed":    [{"path", "failed_at", "reason", "stage", "retry_count"}],
  "retry_state": {
    "/inbox/v.mp4": {"attempts": 1, "last_reason": "...", "next_override": {"colmap": {"matcher": "exhaustive"}}}
  }
}
```

`mark_done`/`mark_failed` prune `completed`/`failed` FIFO at `cfg.status.max_history`. Successful completion clears `retry_state[path]`.

## Quality-Gate decision flow (Phase 3)

```
sfm.done(cameras_registered, points)
        │
        ▼
   evaluate_sfm(stats, frames_kept, cfg)
        │
   ┌────┴─────┐
   │ ok       │ fail
   ▼          ▼
   continue   QualityGateFailure(reason, stage, retry_hint, metrics)
              │
              ▼
   reconcile_failure(state, …, retry_cfg):
        - if retry_state[path].attempts < max_retries:
            schedule_retry(override=retry_hint)  → re-enqueue
        - else:
            mark_failed(reason="…(after N attempts)", retry_count=N)
```

Retry-hint matrix (in `quality._retry_hint_for` + `quality.retry_hint_for_brush_oom`):

| Failure              | Condition                | Retry hint                                          |
| -------------------- | ------------------------ | --------------------------------------------------- |
| `low_camera_ratio`   | matcher was `sequential` | `{"colmap": {"matcher": "exhaustive"}}`             |
| `low_camera_ratio`   | matcher was `exhaustive` | `None` (no further matcher swap)                    |
| `low_points`         | any                      | `None` (footage-suitability issue)                  |
| `brush_oom`          | any resolution_cap > 256 | `{"brush": {"resolution_cap": cap // 2}}` (Phase 6) |
| `brush_oom`          | resolution_cap ≤ 256     | clamps to 256 (Pydantic minimum)                    |
| anything else        | retries remain           | `None` — retry without override                     |

## Why this module split

- **One stage = one module = one subprocess wrapper.** Easy to test in isolation, easy to swap (e.g. Brush → msplat in Phase 6+).
- **No module imports `cli.py`.** The CLI is a thin shell; everything else is pure library code that can be driven from tests, the watcher, or the WebUI (src/autosplat/webui/, Phase 10).
- **Config is centralised + override-friendly.** `apply_override()` lets the watcher rewrite any TOML key before a per-attempt run — that's how Phase-3 swaps the matcher without mutating the user's config.
- **Watcher knows about pipeline failures, not pipeline details.** It catches `QualityGateFailure` and generic `Exception`; the gate's own knowledge of "what should I retry with?" lives in `quality._retry_hint_for`. New retry policies are one function-edit away.

## Logging contract

Every stage emits structured JSON events through `structlog`. The minimum schema:

```json
{"ts": "...Z", "level": "info", "logger": "...", "event": "<stage>.<event>", ...}
```

Convention: `event` names follow `<module>.<thing_happened>` (e.g. `preprocess.done`, `quality_gate.failed`, `watcher.retry_scheduled`). Grep-friendly.

Per-capture file at `<capture-dir>/pipeline.log` mirrors the JSON stream so a finished run is forensically inspectable later.

## WebUI module (Phase 10)

```
src/autosplat/webui/
  __init__.py          re-exports create_app
  app.py               FastAPI factory — CORSMiddleware, StaticFiles mounts, lifespan
  state.py             WatcherState adapter (read-only): list_captures(), get_capture(), read_log_tail()
  jobs_runner.py       Async background executor: JobRunner, cancel via subprocess handle
  routes/
    health.py          GET /healthz → {"status":"ok","version":"..."}
    dashboard.py       GET / → dashboard.html (HTMX 3s poll)
    captures.py        GET+POST /captures/ and /captures/{id}; GET /captures/{id}/ply (FileResponse)
    jobs.py            GET /jobs/ (HTMX 2s poll)
    partials.py        GET /partials/* — HTMX fragments
    source.py          GET /source — AGPL §13 Network Clause
  templates/           Jinja2 templates
    base.html          KSP shell — TopBar, sidebar, footer, theme anti-flash, vendored HTMX
    dashboard.html · jobs.html · source.html
    capture/           list.html · detail.html · view.html
    partials/          dashboard_inner · jobs_inner · captures_list_inner · capture_status · brush_metrics
    _macros.html       capture_badge, stage_timeline, stat_tile, STAGE_MAP (backend→visual-slot)
    _icons.html        inline SVG icon macro
  static/css/tokens.css       KSP design primitives — colors, spacing, fonts, signal accents
  static/css/autosplat.css    KSP component layer — frame grid, cards, tables, timeline, badges
  static/js/htmx.min.js       vendored htmx@1.9.12 (BSD-2) — same-origin, no CDN/SRI
```

SuperSplat `dist/` is served via a `/supersplat/` StaticFiles mount (only mounted when `dist/index.html` exists). PLY files stream via `FileResponse` with `Accept-Ranges` + CORS headers so the SuperSplat iframe can load them cross-origin.

**Design system (v1.1.0 — Kuro Signal Protocol).** All 7 surfaces are styled via two CSS layers: `tokens.css` (primitives) + `autosplat.css` (components). Theme is `data-theme` on `<html>` (dark/light, `localStorage`-persisted, anti-flash inline script). The `STAGE_MAP` dict in `_macros.html` maps backend pipeline-stage names (`starting`, `train`, `export`, …) onto the 6-slot visual timeline — the pipeline code is never changed for display purposes. HTMX templates follow a wrapper pattern-lock: `as-poll-region` (outer, carries poll attributes, `outerHTML`-swap target) vs `as-main-inner` (inner, layout padding).

## Open architectural decisions

1. **Compress backend choice** — Phase 5 implemented SOG + SPZ via `splat-transform`. KSPLAT output is not supported by `splat-transform`; use `mkkellogg/GaussianSplats3D` directly for KSPLAT.
2. **Brush versioning** — currently `latest` with override via `BRUSH_VERSION=v0.x.y`. Pin once we hit a regression.

## Documentation convention

Phases 0-10 each had a `docs/PHASE-N-*.md` report — the build was sequential and each phase had a discrete acceptance criterion. **Starting with v1.4, the project moved to spec-driven release notes** under `docs/superpowers/specs/YYYY-MM-DD-<topic>-design.md`: a spec is brainstormed, agreed, and committed before code lands. The CHANGELOG entry for the release links the spec for reference. Reasons for the switch:

- v1.4+ work is feature-shaped, not phase-shaped — fixes, features, and refactors interleave across releases rather than building toward a single phase deliverable.
- Specs capture design *intent* before implementation, which the post-hoc PHASE reports tended to lose.
- Releases (v1.4.0 through v1.4.5 in 24 h) need lightweight per-release documentation, not a full PHASE write-up each.

`docs/PHASE-*.md` remain as historical record. New design docs go under `docs/superpowers/specs/`.
