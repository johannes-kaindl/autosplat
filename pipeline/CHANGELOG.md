# Changelog

Versioning follows the spec's phase model. Releases tag the head commit when a phase's acceptance criteria are met.

Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

---

## [v1.3.0] — 2026-05-24 — Multi-Video Rescue

When a single drone pass can't be reconstructed (180° turn, 360° spin, rotation-heavy footage), v1.2.0 told you to re-shoot. v1.3.0 lets you combine multiple passes into one capture — and ships the shoot rules that say when this works.

### Added

- **Multi-video captures** (`e95ccfa`) — `autosplat process v1.mp4 v2.mp4 [...]` combines frames from N videos into one capture; COLMAP solves the combined set. Each video gets a per-source frame-naming prefix (`<stem>_frame_NNNNN.jpg`) so passes don't clobber each other. WebUI's new-capture form accepts a multi-line textarea instead of a single input.
- **`autosplat add-video <capture_dir> <video>`** (`e95ccfa`) — append another pass to an existing capture and rebuild frames + SfM + training with the larger set. `JobRunner.start_add_video_job` + an "Add video" form on the capture detail page mirror it in the WebUI.
- **`--target-frames N` CLI flag** (`b1cac8f`) — on both `process` and `resume`. Per-run override for `preprocess.target_frames`, useful for long videos where the default cap of 250 subsamples too aggressively (a 30-min walkthrough otherwise drops to 1 frame every 7s).
- **`docs/CAPTURE-GUIDE.md`** (`a20d4fc`) — empirical shoot rules from v1.2.0 smoke testing. Translation > rotation, smooth turns, ≥80% overlap, textured surfaces, even lighting. Includes case data from real failed captures (`max_strasse` 180° turn, `360max` 360° spin) so users can interpret their own quality-gate output.

### Fixed / improved

- **`QualityGateFailure` surfaces a CAPTURE-GUIDE pointer** (`b1cac8f`) when the matcher swap has already been tried (i.e. `retry_hint=None`). Lands in both the CLI (`Pipeline failure: …`) and the WebUI (`JobState.error`) without per-caller plumbing — overridden `__str__` keeps the structured `reason` field clean.
- **Resume adapts to multi-video captures** (`e95ccfa`) — `read_source_video_from_log` always returns a list now; transparently handles both the legacy `video: str` and the new `videos: [...]` schemas. `resume_capture` re-feeds the entire list to the pipeline.

### Design Notes

- **`Path | list[Path]` union type** throughout `run_pipeline`, `JobRunner.start_job_from_video`, and `run_pipeline_with_adaptive_retry`. Every existing single-video caller stays byte-identical; only the multi-video path normalises internally to a list.
- **No special-case for "add to single-video capture."** When `add_video_to_capture` runs, all frames re-extract with the consistent per-source naming. Trades one re-preprocess run (~1-2 min for typical drone footage) for zero migration logic across naming schemes.
- **`pipeline.log` schema is additively versioned** — the new `videos: [...]` field is only present when multiple videos were used; single-video runs still log `video: str` for backwards-compat with older capture-dir tooling.
- **WebUI form fields** — new-capture POST accepts both `video_paths` (multi-line, takes precedence) and `video_path` (legacy single). v1.2.0 bookmarks of the form keep working.

### Known Issues

- The smoke test for *combining* two halves of a rotation-broken video (split `max_strasse` at the 180° turn, then `autosplat process pre.mp4 post.mp4`) was deferred from this session due to compute time. The mechanism is unit-tested end-to-end; the empirical "can the user's typical rotation-heavy footage be rescued by splitting" answer is open.

### Tests

265 unit tests (263 passed, 2 opt-in E2E skipped) — +19 over v1.2.0. Coverage breakdown for the new work: 5 for multi-video extraction + run_pipeline routing (test_preprocess.py + test_pipeline.py), 3 for `add_video_to_capture`, 4 for the WebUI multi-video form + add-video route, 2 for `QualityGateFailure.__str__`, plus log-reader migration tests. `ruff check src/ tests/` → "All checks passed!".

### Internal Notes

- 3 atomic commits between v1.2.0 and v1.3.0 + 1 release commit. Multi-video work touched 30 files but the substantive changes are isolated to `pipeline.py`, `preprocess.py`, `cli.py`, `webui/jobs_runner.py`, `webui/routes/captures.py`, and the two capture templates — the rest was a ruff-format sweep across transitively imported files.

---

## [v1.2.0] — 2026-05-24 — Resume & Recovery

Pipeline failures used to be terminal: every botched run had to be re-started from scratch (re-extracting frames, re-running COLMAP) and the user had to remember to swap the matcher by hand. v1.2.0 makes the pipeline self-healing — a partial capture can pick up where it died, the WebUI exposes a Resume button, and a low-camera SfM result auto-retries with the exhaustive matcher even after a process crash. The release also lands four V12 quality-of-life slices that accumulated since v1.1.2.

### Added

- **Adaptive matcher retry in CLI + WebUI** (`32f329e`) — the watcher daemon's Phase-3 retry mechanism (`QualityGateFailure → retry_hint → swap matcher`) was only wired into the long-running `watch` daemon. `autosplat process` and the WebUI's `JobRunner` now share it via a new in-process `run_pipeline_with_adaptive_retry` wrapper. A 180° drone turn that breaks the sequential matcher with 3/244 cameras self-rescues with exhaustive, frames intact.
- **`autosplat resume <capture_dir>` CLI command** (`6b0b429`) — continues a previous capture from on-disk state. `detect_completed_stages` inspects `frames/`, `colmap/sparse/0/`, `training/*.ply`, `output/scene.ply` and computes the skip-set; `read_source_video_from_log` scrapes the original video path from `pipeline.log` (no new manifest file — works for every existing capture). New `capture_dir_override` parameter on `run_pipeline` so the resumed run keeps its original date-stamped directory instead of forking `<today>_<stem>`.
- **WebUI Resume button** (`70161fe`) — failed captures show a Resume button (replacing the broken-for-real-captures Retry that routed through `/process`). `POST /captures/{id}/resume` calls a new `JobRunner.start_resume_job` that spins up a worker thread running `resume_capture(...)`. Shares the existing cancellation/persistence/runs.jsonl path.
- **New-capture run-start flow** (`d9eb069`, V12-1) — the dashboard's "New capture" button now actually starts a pipeline run from a video path (it previously linked back to the captures list). `GET/POST /captures/new` with path validation (`.mp4`/`.mov`/`.m4v`, file-exists check).
- **Persistent job history via `runs.jsonl`** (`9d5c7f8`, V12-2) — the JobRunner appends one record per finalized job to `<captures_dir>/<id>/runs.jsonl` (status, start/finish timestamps, error). On startup, `load_history()` rehydrates the in-memory history so a WebUI restart no longer wipes the "Recent jobs" view. Append-only, crash-safe.
- **Responsive WebUI layout + mobile sidebar** (`c21be7b`, V12-3) — three breakpoints (Desktop ≥1024px / Tablet ≤1023px / Mobile ≤767px). Sidebar narrows then slides off-canvas; stat-tiles collapse 4→2 columns; hamburger button toggles `.mobile-sidebar-open` on body with tap-to-close backdrop; tables scroll horizontally on mobile.
- **URL-param developer mode** (`19f308c`, V12-4) — reactivates the latent aspect subthemes (`?aspect=shugo|gunshi|kantoku|sensei`) and the HTMX-annot debug overlay (`?dev=1`) without adding a settings UI. Both persist in localStorage; URL-params set/clear them.

### Fixed

- **Quality gate runs on resumed SfM** (`248b92c`) — resuming a capture whose previous SfM stage produced a bad sparse model (e.g. only 3/244 cameras) used to silently skip the quality gate and let Brush train on garbage — the gate lived inside the SfM `else` branch. `run_pipeline` now re-parses `sparse/0` via `_parse_mapper_stats` when `sfm` is in `skip_stages` and feeds the synthesized `SfmResult` into `check_sfm_quality`. The adaptive-retry wrapper also drops `"sfm"` from `skip_stages` on retry so the matcher swap actually re-runs SfM.
- **Stale-job liveness reconciliation** (`d9eb069`) — jobs whose worker thread died mid-run (e.g. host sleep) used to hang as phantom `running` entries forever. `JobRunner._reconcile` now flips them to `failed` with `interrupted — the run ended without producing a result` on the next read.
- **Version-source consistency** — `pyproject.toml` and `src/autosplat/__init__.py` now agree (both `1.2.0`). Pre-v1.2.0 drift had `__init__.py` stuck on `1.1.1` while pyproject moved to `1.1.2`.

### Design Notes

- **Adaptive retry vs. resume — orthogonal mechanisms.** Adaptive retry (in-process) catches `QualityGateFailure` during a live pipeline and retries the next stage with the hint set; frames stay in memory. Resume (cross-process) is the answer when the process is fully gone (sleep / crash / Ctrl-C): it reads disk artifacts and the original log to reconstruct the run. Both share the same stage-skip plumbing.
- **No manifest file for resume.** Source video is scraped from the `pipeline.start` JSON event in `pipeline.log`. Works for every existing capture without any migration; user can override with `--video` if the original file has moved.
- **Resume refuses on a complete capture.** If `output/scene.ply` exists, `resume_capture` raises immediately instead of silently redoing the whole pipeline. Delete the output to re-run, or use `autosplat process`.
- **WebUI Retry → Resume.** The old Retry button POSTed to `/process`, whose `JobRunner.start_job` finds the source video via `_find_source_video(capture_path)` — a glob inside the capture directory that's typically empty for real (non-fixture) captures. Resume scrapes from the log instead, so it works for every real failed capture.

### Known Issues

- Resume is **single-attempt aware**: the adaptive-retry wrapper restarts mid-pipeline up to `cfg.retry.max_retries` times, but cross-process resume always starts at the highest already-completed stage. A capture that died during Brush won't re-do SfM with a new matcher — by that point the SfM passed quality, so there'd be no signal to do so anyway.

### Tests

246 unit tests (244 passed, 2 opt-in E2E skipped) — +40 over v1.1.2. New coverage: 11 for adaptive-retry + resume helpers + `resume_capture` orchestrator (test_pipeline.py), 4 for `JobRunner.start_resume_job` + the WebUI resume route + the detail-template button (test_jobs.py / test_captures.py), 2 for quality-gate-on-resumed-SfM, plus the V12-2/3/4 + new-capture-flow regression tests landed in earlier commits. `ruff check src/ tests/` → "All checks passed!".

### Internal Notes

- 8 atomic commits between v1.1.2 and v1.2.0 (4 V12 slices + 4 resume/retry slices). Tags `v1.2.0` and the release-commit are signed by the in-repo identity.

---

## [v1.1.2] — 2026-05-20 — Hotfix Release

Closes the three v1.1.1 backlog items: wall-clock job timestamps + within-day sort, zero ruff findings, and a job-specific status badge. WebUI- and hygiene-only — no change to the capture/train/export algorithm.

### Fixed

- **[SF-G3-1] + [SF-NEW-3]** Wall-clock job timestamps + within-day sort (`cc84d2f`) — `JobState` now carries `started_at_walltime` and `finished_at_walltime` as ISO-Z strings (monotonic siblings stay for duration math). `state.py` grew an explicit `done`-branch so WebUI-completed jobs surface their `finished_at` instead of falling through to the ply-not-None path with `finished_at=None` — Recent Captures used to render `—` for every WebUI-completed run. `list_captures` now sorts by `finished_at DESC` with capture-name DESC as a tiebreaker; within a single day, captures order by the time they actually finished rather than alphabetically by capture name.
- **[SF-G3-2]** Job-status badge cancelled/queued rendering (`ba373cc`) — the jobs view rendered cancelled/queued `JobState`s as a grey "ready" badge because `capture_badge` had no branches for them and `JobState` has no `stage` attribute (so failed jobs even showed `failed · preflight` regardless of where they actually failed). New sibling `job_badge` macro purpose-built for `JobState`: explicit branches for queued, running, done, failed, cancelled. New CSS class `.s-cancelled` keeps cancelled runs visually distinct from idle/ready captures. `capture_badge` stays unchanged — it remains the right macro for `CaptureInfo`.

### Changed (Hygiene)

- **[SF-H1-1]** Zero ruff findings (`9e81b7e`) — `uv run ruff check src/ tests/` now passes cleanly (23 pre-existing findings resolved). Three categories: 11x F401 unused imports across test files (auto-fixed), 3x I001 unsorted import blocks (auto-fixed), 7x SIM117 nested `with`-statements collapsed via PEP 617 multi-context syntax, and 2x B904 `raise typer.Exit(...) from None` in `cli.py` (the inner RuntimeError is already user-facing-printed, so the chained traceback was noise).

### Design Notes

- **`job_badge` vs `capture_badge` separation** — the two macros now own different status enums. `capture_badge` knows the pipeline stages (preflight → export) and the CaptureInfo lifecycle (idle/running/done/failed). `job_badge` knows the JobRunner lifecycle (queued/running/done/failed/cancelled) and has no stage information. Code that pulls a `CaptureInfo` calls `capture_badge`; code that pulls a `JobState` calls `job_badge`.
- **Wall-clock timestamps coexist with monotonic** — `JobState` keeps both `started_at`/`finished_at` (monotonic `float`, for duration math) and `started_at_walltime`/`finished_at_walltime` (ISO-Z strings, for display + sorting). Replacing monotonic with wall-clock would have broken the `(finished_at - started_at) / 60` duration computation in `jobs_inner.html`.

### Known Issues

- All v1.1.1 known issues resolved. Remaining v1.2 candidates: multi-slot `WatcherState` (or a JobRunner extension) for parallel-run tracking; persistent JobRunner history via `runs.jsonl` append-log.

### Tests

206 unit tests (204 passed, 2 opt-in E2E skipped) — +6 over v1.1.1 (5 SF-G3-1 / SF-NEW-3 regression tests + 1 SF-G3-2 integration test). `ruff check src/ tests/` → "All checks passed!".

### Internal Notes

- 3 atomic fix-commits + 1 release commit. Tags `v1.1.2` and the release-commit are signed by the in-repo Identity (Johannes Kaindl `<code.jkaindl@mailbox.org>`).

---

## [v1.1.1] — 2026-05-18 — Hotfix Release

Resolves all three v1.1.0 known issues plus four polish findings from cowork smoke-testing. WebUI-and-pipeline fixes only — no change to the capture/train/export algorithm.

### Fixed

- **[SF-G2-9]** Backend status-write sync — the WebUI now tracks runs from every trigger path (CLI-direct `autosplat process`, watch-daemon, WebUI Process-button). Live monitoring shows correct running/stage/done/failed states.
  - Part 1 (`6420aec`) — `list_captures`/`get_capture` overlay the in-memory `JobRunner` status for WebUI-button-triggered jobs.
  - Part 2 (`a9e1976`) — `run_pipeline()` reports status into an optional `WatcherState` (begin / update_stage / mark_done), keyed by the capture directory, for the CLI-direct and watch-daemon paths. `InProgress` gained a `source_video` field so the Phase-3 retry/recovery machinery still re-enqueues by video path.
- **[SF-PIPE-1]** Embedded SuperSplat viewer URL-loading — the PLY route moved from `/captures/{id}/ply` to `/captures/{id}/scene.ply` (`9e82a2f`). SuperSplat detects the file type from the URL extension, so it now recognizes the `.ply` suffix. The `Unrecognized file type` error is resolved. Bonus: browser downloads are named `scene.ply`.
- **[SF-G3-3]** Recent-jobs single-run-per-capture — `JobRunner` now keeps an in-memory `_history` list (`3eacf4c`); `all_jobs()` exposes the full history so re-triggering a capture no longer hides earlier runs.
- **[SF-PIPE-2]** Log-box width — raw log lines render only a `.msg` cell, which was being placed into the 56px time column of `.as-log-row`'s 3-column grid; JSON wrapped at ~7 chars. A `.msg:only-child` now spans the full row (`0c7d5a4`).
- **[SF-PIPE-3]** REASON-card text overflow — `.as-kv .v` gets `min-width: 0; overflow-wrap: anywhere` (`0c7d5a4`); long whitespace-free error strings now wrap inside the card.
- **[SF-PIPE-4]** Vertical scroll — there was no `html, body { height: 100% }` rule, so `<body>` (`.as-frame`) collapsed to content height, its `overflow: hidden` propagated to the viewport, and the page could not scroll (`13ddad9`).
- **[SF-PIPE-5]** Viewer-iframe full-height — same root cause as SF-PIPE-4: without the height chain the viewer's `flex:1` / `height:100%` subtree had no parent height, so the SuperSplat iframe collapsed to a strip (`13ddad9`).

### Changed (Internal Improvement)

- The CLI `process` command broadened its exception handling from `except RuntimeError` to `except Exception` — domain errors (QualityGateFailure, BrushOOMError) now exit cleanly via `EXIT_PIPELINE_FAILURE` and record a failed entry instead of raising an untrapped traceback. (SF-G2-9-PART-3, a side-effect of the Part-2 work.)

### Design Notes

- **JobRunner history is in-memory** — a WebUI server restart resets it. Persistent per-capture history (e.g. a `runs.jsonl` append-log) is a v1.2 candidate.
- **`WatcherState.in_progress` is single-slot** — running `autosplat watch` and `autosplat process` in parallel, or starting a second `autosplat process` while a first is running, makes the UI flicker / show only the most recent job. autosplat is a single-user Mac tool; use one trigger path at a time. A multi-slot model is a v1.2 candidate.
- **PLY URL renamed** from `/captures/{id}/ply` to `/captures/{id}/scene.ply` — externally saved links to the old path will 404. Pre-v1.1.0 had no public users, so external impact is unlikely.

### Known Issues

- **Recent-captures ordering within a single day** uses filesystem order, not wall-clock time — related to SF-G3-1 (`JobState.finished_at` is a `time.monotonic()` value, not a wall-clock timestamp). Multiple captures on the same day may sort non-deterministically. A v1.1.2 candidate (needs a wall-clock timestamp field on the capture model + a secondary sort key).

### Tests

200 unit tests (198 passed, 2 opt-in E2E skipped) — +5 over v1.1.0 (3 SF-G2-9 regression tests, 2 SF-G2-9-PART-2 regression tests). The touched source files pass `ruff check`.

### Internal Notes

- 6 atomic fix-commits + 1 release commit across the v1.1.1-hotfix session; 7 pre/post tag-pairs for granular rollback.
- v1.1.2 backlog: SF-G3-1 / SF-NEW-3 (wall-clock timestamps + secondary sort key), SF-H1-1 (~23 pre-existing `ruff` findings — `ruff check src/ tests/` is not clean despite the README claim).
- v1.2 backlog: multi-slot `WatcherState` (or a JobRunner extension) for parallel-run tracking; persistent JobRunner history.

---

## [v1.1.0] — 2026-05-17 — Kuro Signal Protocol WebUI Restyle

Full visual restyle of the WebUI. All seven browser surfaces migrated to the **Kuro Signal Protocol** design system. No pipeline behaviour changes — the capture/train/export flow is byte-identical to v1.0.1.

### Added

- **Kuro Signal Protocol** WebUI restyle — all 7 surfaces migrated to KSP design tokens (`tokens.css` + `autosplat.css`). Local-first, no CDN dependencies.
- **Theme toggle** (dark/light) with anti-flash `localStorage` persistence on `<html>` via the `data-theme` attribute. Default dark.
- **Pre-rendered icon toggle** for the theme button (sun/moon SVG with label).
- **Captures-list HTMX polling** every 3 s (the list was static before).
- **Capture-detail two-column layout** with a `stage_timeline` macro using the `STAGE_MAP` backend→mockup-slot mapping (6-slot pipeline visualization).
- **Brush-metrics partial** — 8-tile card with 3 s HTMX polling.
- **Viewer page** with sidebar-collapse + CSS-only fullscreen toggle + Esc-key + GUI close-button. Three-state fallback (SuperSplat+PLY / PLY-only / no-PLY).
- **Jobs page** Active + Recent sections with 2 s HTMX polling.
- **Source page** KSP-styled AGPL §13 compliance card.
- **WebUI smoke-test suite** — 10 HTTP-integration tests covering all 7 surfaces, static assets, and partial routes.
- **Vendored HTMX** (`/static/js/htmx.min.js`, htmx@1.9.12, BSD-2) — eliminates the CDN SRI-mismatch class of failure.
- **Latent features** (no UI exposure, console-accessible): HTMX polling annotation overlay (`document.body.setAttribute('data-annot', 'on')`) and aspect-subthemes gunshi/kantoku/sensei (CSS tokens, default `shugo` hardcoded).

### Changed

- `static/style.css` removed in favour of `static/css/tokens.css` + `static/css/autosplat.css`.
- All page templates restructured with proper `as-poll-region` (HTMX outerHTML-swap target, no padding) vs `as-main-inner` (layout-padding wrapper) differentiation.
- Pipeline live-pip text "chamber quiet" → "idle" (less lore, more clarity).

### Known Issues

⚠ Three known issues affect v1.1.0 and are scheduled for the v1.1.1 hotfix. All three are **WebUI-display-only** — the underlying pipeline runs correctly in every case and the captured data is intact.

- **Backend status-write sync** (`SF-G2-9`) — pipeline state changes may not reflect in WebUI live-monitoring immediately. The active-jobs section can show empty while Brush training runs in the background; capture-detail pages may show stale status. *Workaround:* refresh the page manually, or check the CLI log directly. Root cause: a `state.json` write-sync race between the pipeline and `WatcherState`.
- **SuperSplat viewer URL-loading** (`SF-PIPE-1`) — the embedded SuperSplat viewer may fail to load a PLY via URL parameter (`Unrecognized file type while loading 'ply'`). *Workaround:* download the PLY via the ↓ PLY button and drag-drop it onto [playcanvas.com/supersplat/editor](https://playcanvas.com/supersplat/editor) — file-drop loading works correctly. Root cause under investigation (URL encoding, Content-Type header, or CORS between the FastAPI PLY route and the iframe-embedded SuperSplat). Pre-dates v1.1.0.
- **Recent-jobs single-run-per-capture** (`SF-G3-3`) — the `JobRunner` registry is keyed by `capture_id`, so re-triggering the same capture overwrites the previous job state. A capture that completed successfully but was later re-triggered with a failed preflight will show as `failed · preflight` in the WebUI jobs history. *Workaround:* check for the PLY at `<captures-dir>/<capture-id>/output/scene.ply` to confirm whether a successful run exists. Root cause: `JobRunner._jobs` is single-state, not job-history.

### Tests

195 unit tests (193 passed, 2 opt-in E2E skipped) — +10 over v1.0.1 from the new WebUI smoke-test suite. WebUI tests use `starlette.testclient.TestClient` against the real ASGI app.

### Internal Notes

- Built across 5 implementation bursts + 3 drift-resolution patches (P2.5 / P2.6 / P2.7 / P4.5).
- Granular Tag-pairs `autosplat-pre/post-v1.1.0-restyle-P{N}-{slug}` for per-sub-phase rollback.
- The `as-poll-region` vs `as-main-inner` wrapper pattern emerged in P2.7 and was applied through P4.5 and all subsequent templates.

---

## [v1.0.1] — 2026-05-16 — Docs Sync Patch

Documentation-only release. Brings README + docs/ in sync with the v1.0.0 WebUI release state. No code changes.

### Changed

- `README.md` — status badge updated to v1.0.1 CLI + WebUI; phase table extended with Phase 10 WebUI row; quick-start gained `autosplat webui` block; CLI section now covers WebUI with short subsection and workflow pointer; test count updated to 185; module count updated to 16.
- `docs/GETTING-STARTED.md` — added "Option B: Use the WebUI" alternative path in 15-minute walkthrough.
- `docs/WORKFLOWS.md` — new section "Web-UI control (v1.0.0+)" documenting browser flows (dashboard, trigger, cancel, SuperSplat embed, LAN access, parallel with CLI).
- `docs/ARCHITECTURE.md` — "future web UI" reference replaced with implemented Phase 10 module reference; WebUI module section added; stale Phase 6 "Open architectural decisions" item resolved.

### Added

- `docs/PHASE-10-WEBUI.md` — plan-style snapshot for Phase 10 WebUI, analogous to existing PHASE-N-*.md files. Includes routes inventory, sub-phase log with commit hashes, architecture, risks/mitigations, test strategy.

---

## [v1.0.0] — 2026-05-16 — WebUI Release

First production-ready release. Adds a full browser-based control interface (FastAPI + HTMX + Jinja2) for the autosplat pipeline.

### Added — WebUI (Phase 10)

- **`autosplat webui --port 8080`** — new CLI command that starts the WebUI via uvicorn. Shares the same config as the CLI pipeline.
- **Dashboard** (`/`) — live queue overview + recent captures, auto-refreshing via HTMX polling every 5 s.
- **Capture list** (`/captures/`) — filesystem-backed discovery of all capture directories, status overlay from WatcherState, PLY size display.
- **Capture detail** (`/captures/{id}`) — stage timeline (preprocess → sfm → train → export), PLY info, process/cancel/retry buttons, live log tail via HTMX polling.
- **SuperSplat embed** (`/captures/{id}/view`) — serves `target/supersplat/dist/` as StaticFiles, embeds SuperSplat in an iframe with `?load=` pointing at the local PLY route. Falls back gracefully when dist/ not built.
- **PLY streaming** (`/captures/{id}/ply`) — `FileResponse` with `Accept-Ranges` + CORS headers for direct browser access.
- **Job runner** (`webui/jobs_runner.py`) — async background executor for `run_pipeline()`, in-memory job registry, cancel via `proc.terminate()`, log ringbuffer (500 lines).
- **Jobs view** (`/jobs/`) — active + recent job list, HTMX polling every 2 s.
- **AGPL §13 compliance** — `/source` route + footer on every page, links to Codeberg source repository.
- **`GET /healthz`** — liveness check returning `{"status":"ok","version":"1.0.0"}`.

### Added — Infrastructure

- Dependencies: `fastapi>=0.111`, `uvicorn[standard]>=0.29`, `jinja2>=3.1` (runtime); `httpx>=0.27` (dev/test).
- Test suite extended: `tests/webui/` (11 tests) covering healthz, /source, capture discovery, PLY route (200 + 404), detail view, job runner enqueue + cancel.
- New pytest marker: `needs_supersplat_dist`.

### Fixed

- `src/autosplat/__init__.py` had `__version__ = "0.1.0"` (drift from initial scaffold) — corrected to `0.9.0` in P1, bumped to `1.0.0` in this release.

### Pre-1.0 Polish (committed between v0.9.0 and v1.0.0)

- `3a85a81` — AGPL-3.0 license headers added to all `src/autosplat/` Python sources
- `bcef4f6` — AGPL-3.0 license headers added to all `tests/` Python sources
- `61fea53` — `pyproject.toml`: Repository + Documentation URLs added to `[project.urls]`
- `2334170` — docs: example capture filenames clarified as illustrative (not real capture names)

### Tests

185 unit tests (183 passed, 2 opt-in E2E skipped). WebUI tests use `starlette.testclient.TestClient` against real ASGI app — no mock HTTP stack.

### Validated

Gate-1 (healthz browser smoke) + Gate-2 (full WebUI browser smoke: dashboard, captures, /source, footer) verified by Jay 2026-05-16.

---

## [v0.9.0] — 2026-05-15 — Initial Public Release

First public release of the video-to-3d-gaussian-splat pipeline. CLI-complete, locally validated on real-world drone footage.

### Added — Phases 0–9.7 (complete scope)

- **Phase 0** — Manual baseline: first end-to-end run establishing the full pipeline manually (ffmpeg → COLMAP → Brush → PLY). Calibration data for blur threshold, SfM parameters, and training steps.
- **Phase 1** — CLI MVP: `autosplat process <video>` runs the complete pipeline in one command. 15 Python modules under `src/autosplat/`.
- **Phase 2** — Watch-folder daemon: `autosplat watch <inbox>` with persistent `state.json`, atomic queue operations, crash-recovery on restart.
- **Phase 3** — Quality-gate + adaptive retry: gate before Brush training checks minimum camera count and point density. Automatic retry with `exhaustive` COLMAP matcher hint on first failure.
- **Phase 4** — Obsidian capture-note auto-generation: opt-in via `[obsidian].enabled = true`. Writes structured frontmatter note per capture. Preserves user-added content via marker-based tail split.
- **Phase 5** — Compress stage: `autosplat compress <ply>`, SOG + SPZ + ksplat output via `splat-transform` npx backend. Real-world compression ratios: 82–91% size reduction.
- **Phase 6** — Spec-mandate sweep: preflight checks for all binary deps, OOM retry logic, skipped-frames guard, PLY min-size gate. Closes §9.2 + §5 of spec.
- **Phase 7** — Pipeline visibility: Rich progress bar with wall-time-based ETA during Brush training. `autosplat status` table for queue + history.
- **Phase 8** — Obsidian polish: vault-agnostic config defaults, user frontmatter key preservation across pipeline re-runs.
- **Phase 9** — Local SuperSplat auto-open: starts local SuperSplat static server + PLY HTTP server in parallel, auto-opens browser after training. CORS fix (Phase 9.6) discovered via manual smoke run — browser blocked cross-origin PLY fetch.
- **Phase 9.7** — splat CLI real executable: `scripts/install_splat.sh` installs `~/.local/bin/splat` as a real Bash binary with subcommand-aware caffeinate wrap. Enables `nohup splat watch`, tmux usage, background process management.

### Tests

~175 unit tests across 15 test modules. 2 opt-in E2E tests (`AUTOSPLAT_E2E=1`, `AUTOSPLAT_COMPRESS_E2E=1`). All unit tests pass in ~3s on Apple Silicon.

### Validated

8/11 real-world captures trained successfully in overnight run 2026-05-15. Failure modes are deterministic and structured — COLMAP SfM failure, quality-gate rejection, and compress-backend unavailability all produce explicit events and are visible via `autosplat status`. No silent failures.

### Build Methodology

Pipeline built phase by phase using a Recon → Plan → Sub-Phase pattern. Each phase has a `docs/PHASE-N-RECON.md` (problem space mapping) and `docs/PHASE-N-PLAN.md` (acceptance criteria before code). Phases tagged in git on completion. Part of ongoing research into trace-based emergent coordination.

### License

Switched from MIT to AGPL-3.0-or-later (code) + CC BY-SA 4.0 (documentation). See [LICENSE](LICENSE) and [LICENSE-DOCS](LICENSE-DOCS).

### Release Polish (Burst C.1)

- PII strip: `/Users/johannes/` paths replaced with `~/` (docs) and `Path.home()` (Python)
- examples/ generalized: location-specific capture names replaced with generic identifiers
- `*.sog` added to `.gitignore`
- pyproject.toml: version bump 0.1.0 → 0.9.0, author identity updated, AGPL-3.0 license-id set
- Issue templates added (`.forgejo/issue_template/`)

---

## [autosplat-post-phase-9.7-splat-cli-refactor] — 2026-05-15

`splat` CLI promoted from zsh function to real executable, enabling `caffeinate -i splat watch …`, `nohup`, and `tmux` usage. Root cause of yesterday's over-night-run setup failure (F9-10-5).

### Added — Phase 9.7 (splat real executable)
- `scripts/install_splat.sh` — idempotent installer: creates `~/.local/bin/splat`, removes old function block from `~/.zshrc` (marker-free, sed-based), adds `~/.local/bin` to PATH if absent
- `~/.local/bin/splat` (generated at install time) — Bash executable with subcommand-aware caffeinate: `watch|process|compress` → `exec caffeinate -i uv run --project <repo> autosplat "$@"`; all other subcommands → direct `exec uv run` without caffeinate overhead

### Changed — Phase 9.7
- `scripts/install_splat_alias.sh` marked deprecated — function-based approach not compatible with execvp; kept for existing-user reference

---

## [phase-9-post] — 2026-05-14

Local SuperSplat auto-open: pipeline now starts a local SuperSplat editor instance, serves the freshly trained PLY over HTTP, and opens the browser automatically after training — no manual file-drag required. Acceptance verified by manual Gate-1 + Gate-2 smoke on 2026-05-14 (Jay, burgstall PLY).

### Added — Phase 9.1 (viewer.py local-SuperSplat-mode)
- `ViewerConfig.target = "supersplat-local"` as new enum value
- `ViewerConfig.supersplat_local_port` field (default 3000)
- `_build_viewer_url` extended for localhost target: `http://localhost:<port>?load=http://127.0.0.1:<ply-port>/<name>`
- Tests for config roundtrip + URL construction (commits `404e36e`, `3037c18`, `47fb3fa`, `3ad3b8b`)

### Added — Phase 9.2 (Setup-Script + Doctor)
- `scripts/setup_supersplat.sh` — clones `playcanvas/supersplat`, runs `npm ci && npm run build`
- Doctor row `supersplat`: WARN when target is `supersplat-local` but dist missing, OK when dist present; row skipped when target is anything else
- (commits `ac77939`, `69a662a`, `21b2a88`)

### Added — Phase 9.3 (`autosplat serve --with-supersplat`)
- `viewer.serve_supersplat_local` context manager starts SuperSplat static server + PLY server in parallel, SIGTERM-poll graceful shutdown
- CLI command `autosplat serve <capture_dir>` with `--with-supersplat`, `--ply-port`, `--supersplat-port`, `--no-open-browser` flags
- Auto browser-open after both servers are ready
- Tests for lifecycle + `_find_ply` (commits `91eefcd`, `d17ea49`, `c44311a`, `0bbf77f`)

### Added — Phase 9.4 (embed_url auto-fill)
- `obsidian.py` writes `embed_url: http://localhost:3000?load=http://localhost:8765/scene.ply` into capture note frontmatter, gated on `viewer.target = "supersplat-local"`
- Frontmatter schema documented
- Tests for enabled + disabled obsidian mode (commits `6f9daec`, `2f70a21`, `3aac6be`)

### Added — Phase 9.5 (macOS notification)
- `notification.py` — `notify_training_complete()` via `osascript`
- Opt-in via `[notification].notify_on_complete = true` (default false)
- Non-macOS no-op + graceful failure on osascript error
- `pipeline.py` fires notification after training stage (commits `d8c10b8`, `3c2ff25`, `dad15f5`, `9d370b5`)

### Fixed — Phase 9.6 (CORS hotfix)
- `serve_directory._Handler.end_headers` now sends `Access-Control-Allow-Origin: *` and `Access-Control-Allow-Methods: GET, OPTIONS`
- Bug: SuperSplat on `:3000` could not fetch PLY from `:8765` — browser blocked cross-origin request. Same-origin assumption from Phase 9.1 was falsified by Jay-burgstall smoke run 2026-05-14.
- CORS header verified by new integration test (`test_serve_directory_sends_cors_header`) (commits `e254d95`, `89c7433`)

### Tests
- 116 → ~175 (+59). New test coverage in `tests/test_viewer.py`, `tests/test_serve.py`, `tests/test_doctor.py`, `tests/test_notification.py`; extensions in `tests/test_pipeline.py`

### Acceptance
- Phase-9-DoD from `docs/PHASE-9-PLAN.md` §6 complete
- Gate-1 (doctor + setup build) — verified manually by Jay 2026-05-14
- Gate-2 (`autosplat serve <burgstall> --with-supersplat`, PLY auto-loads in browser) — verified manually by Jay 2026-05-14

### Architecture note
- Structural fragmentation reduced from 3 tools (CLI + hosted browser + vault embed) to 2 tools (CLI + local editor), per spec §5.2. Latent CORS bug in Phase-1-era `viewer.py` (`playcanvas.com/supersplat/editor` remote target) also resolved as side-effect.

---

## [phase-6-7-8-post] — 2026-05-14

Three coordinated phases shipped together because they share the existing
Phase-3 retry plumbing or touch the same hot files.

### Added — Phase 6 (Spec-Mandate-Sweep, §9.2 + §5)
- **A1 Brush OOM adaptive retry** (`feat(phase-6)`, `c620163`)
  - `train.BrushOOMError` raised when stderr matches 6 OOM patterns
    (`out of memory`, `wgpu memory`, `device lost`, …)
  - `quality.retry_hint_for_brush_oom(cap)` returns `{brush: {resolution_cap: cap//2}}`,
    clamped to Pydantic minimum (256)
  - `watcher` routes via `reconcile_failure` into the existing Phase-3 retry path
- **A2 Video-corruption + A3 plausibility** — new `preflight.py` module
  - ffprobe-validate + duration/resolution/fps checks before any extraction work
  - Defaults: 3 s ≤ duration ≤ 10 min, ≥720p, 23-120 fps
- **A4 Skipped-frames detection** — preprocess scans ffmpeg stderr for
  `skipped: N` / `skipped N frames`, threshold-logs at >5 % of target_frames
- **A5 PLY-min-size 100 KB → 1 MB** (matches spec §9.2)

### Added — Phase 7 (Pipeline-Visibility)
- **B4 Brush progress streaming + ETA** (`feat(phase-6)`, `c620163` — train.py)
  - `estimate_wall_time_s(cfg)` heuristic calibrated against Phase-0 + burgstall
    runs (~80 ms/step at resolution_cap=1600, scales quadratically with res)
  - Heartbeat thread in `run_brush` fires `progress_callback(elapsed, est_pct)` every 2 s
  - `pipeline.py` wraps the Brush stage in a Rich Progress bar when TTY is detected
    (`[bold blue]Brush training [bar] 87% 0:13:24 · 0:01:56`)

### Added — Phase 8 (Obsidian-Polish)
- **B1 Vault-agnostic defaults** (`feat(phase-8)`, `57671cb`)
  - `[obsidian].vault_path` default `""` (was `~/Documents/Vault`)
  - `[obsidian].captures_subdir` default `"Captures"` (was `"3D Memories"`)
  - New doctor row `obsidian` — WARN when enabled but vault_path empty/missing
- **B6 Frontmatter user-key-preservation**
  - `yaml.safe_load` parses existing frontmatter on re-write
  - `_merge_frontmatter` policy: Cowork-managed keys win (stats),
    `embed_url`-style keys preserve user-set values, anything else
    (user-added `location`, `weather`, …) is preserved untouched
  - `pyyaml` added as runtime dep

### Added — Dev-experience quick-wins
- `.pre-commit-config.yaml` (`chore(dev)`, `2f14c4d`) — ruff + standard hooks
- `Field(description=...)` sweep across every Pydantic config model (`docs(config)`, `4b2a6a3`)
- `ruff` added as dev-dep, codebase now passes `ruff check` cleanly

### Fixed
- `autosplat compress` CLI was missing imports of `CompressorNotAvailable` /
  `compress_ply` / `install_hint_for` — fixed alongside B904 raise-from-err
  sweep (`fix(cli)`, `aea2ef8`)
- `cli.py` excepts now chain via `from e` so tracebacks show actual cause

### Tests
- 116 → 142 (+26 across Phase 6/7/8 + frontmatter-merge coverage)
- ruff: All checks passed (config in pyproject.toml ignores Typer's
  idiomatic `B008`, math-comment Unicode `RUF002`/`RUF003`, test-only `B017`)

### Acceptance
- Spec §9.2 recovery-table — all rows now implemented (Brush OOM, corrupt
  video, low cameras already via Phase 3)
- Spec §5 Phase-3 implicit items — preflight + skipped-frames detection closed

---

## [phase-5-post-doc-audit] — 2026-05-14

Post-Phase-5 documentation audit + gap-filling. Pure docs commits, no code.

### Added
- `CHANGELOG.md` — retroactive Keep-A-Changelog for phase 0/1/2/3/4/5 (`docs`, `e91418e`)
- `CONTRIBUTING.md` — slim, personal-tool stance
- `docs/GETTING-STARTED.md` — 15-min onboarding tutorial
- `docs/CONCEPTS.md` — domain primer + failure diagnosis tree
- `examples/` — 5 ready-made `--config` overlays (`docs(examples)`, `5467451`)
- `tests/README.md` — run instructions + per-file map (`docs(tests)`, `0c15450`)
- README doc-index sweep linking the new files (`docs(readme)`, `12174e8`)

---

## [phase-5-post] — 2026-05-14

### Added
- Real `compress` stage via PlayCanvas `splat-transform` (`feat(compress)`, `f3a09eb`)
  - SOG + SPZ outputs, three quality profiles (`low` / `medium` / `high`)
  - Backend auto-resolves via `npx -y @playcanvas/splat-transform@^2.1.1` — no global install needed
  - Prefers globally-installed `splat-transform` if present (zero npx startup cost)
- Optional pipeline stage runs after Export when `[compress].enabled = true` (`feat(pipeline)`, `e1015f5`)
- `docs/PLY-OUTPUT-FORMAT.md`: measured compression ratios from bench_chill + format-selection guide (`docs(phase-5)`, `3b1bea7`)

### Measured
- bench_chill 19.4 MB PLY →
  - SOG medium: 3.58 MB (82 % reduction, 16.1 s)
  - SOG low (SH=1): 1.72 MB (91 % reduction, 5.1 s)
  - SPZ medium: 1.87 MB (90 % reduction, 1.3 s)

### Removed
- KSPLAT output is not supported by `splat-transform` (only as input). `install_hint_for("ksplat")` now redirects users to the mkkellogg/GaussianSplats3D toolchain.

### Fixed
- `autosplat compress` CLI command was missing imports of `CompressorNotAvailable`, `compress_ply`, and `install_hint_for`. Now functional.

### Tests
- 104 → 116 unit tests (+12 Phase-5: quality-profile mapping, command-builder, backend-detection priority, error paths). Plus 1 opt-in E2E gated by `AUTOSPLAT_COMPRESS_E2E=1`.

---

## [phase-4-post] — 2026-05-14

### Added
- Phase 4 — Obsidian capture-note auto-generation (`feat(obsidian)`, `c13769e`)
  - `CaptureNoteData` Pydantic schema (16 fields: gaussians, SH degree, cameras_registered, etc.)
  - PLY header parser pulls gaussian count + SH degree (from `comment SH degree:` or `f_rest_*` count inference)
  - Marker-pattern for user-edit preservation: `<!-- AUTO-GENERATED:START/END -->` brackets
  - `.bak` fallback when an existing note has no markers
- Phase 5 skeleton — compress dispatch + doctor probe (`feat(compress)`, `acea8f5`)
- `docs/PLY-OUTPUT-FORMAT.md` + `docs/WORKFLOWS.md` — new docs (`docs`, `69b615d`)
- README / ARCHITECTURE / CONFIGURATION / TROUBLESHOOTING all swept

### Tests
- 83 → 104 unit tests (+17 obsidian + 4 compress)

### Acceptance §11.4 — ✅
- Capture note created at configured vault path
- Frontmatter validates against Obsidian-Bases-compatible schema

---

## [phase-3-post] — 2026-05-14

### Added
- Quality-Gate stage between SfM and Brush (`feat(quality_gate)`, `3b37890`)
  - Configurable thresholds: `min_camera_ratio` (default 0.5), `min_points` (default 5000)
  - `QualityGateFailure(reason, stage, retry_hint, metrics)` carries structured retry info
- Adaptive retry + history pruning + override-aware worker (`feat(retry)`, `cd77afa`)
  - `RetryRecord(attempts, last_reason, next_override)` per path
  - `reconcile_failure()` is the single decision point: retry-with-override or final-fail
  - `recover_state()` respects retry policy on crash recovery
  - `mark_done` / `mark_failed` prune `completed` / `failed` FIFO at `cfg.status.max_history`
- New TOML sections: `[quality_gate]`, `[retry]`, `[status]` (`feat(config)`, `a3408c3`)
- `config.apply_override()` — deep-merge cfg overrides for adaptive retry
- CLI `watch` threads `config_override` through to `run_pipeline` (`feat(cli)`, `8a8ce01`)

### Tests
- 57 → 83 (+26: 9 quality + 12 watcher-Phase-3 + 5 config-Phase-3)

### Acceptance §11.3 — ✅
- Bad footage → graceful retry → skip
- Validation failures landed with reason in state file

---

## [phase-2-post] — 2026-05-14

### Added
- Phase 2 — Watch-folder daemon (`feat(watcher)`, `89ab9bd`)
  - `WatcherState`: queue / in_progress / completed / failed lists, all mutations under `threading.Lock`
  - Atomic state.json writes via tmp + `os.replace` + `fsync` — SIGKILL-safe
  - `WatchDaemon`: watchdog Observer thread + thread-safe `queue.Queue` + single worker thread
  - `recover_state()` moves orphan `in_progress` to `failed` with reason `"interrupted"`
  - Loader tolerates pre-Phase-2 schema (no `failed` list, `started` instead of `started_at`)
- CLI `watch` + `status` integrated with `WatchDaemon` + `recover_state` (`feat(cli)`, `a6c9260`)
- 17 watcher tests (`feat(test)`, `9f510bf`)
- `docs/PHASE-2-WATCHER.md` (`docs(phase-2)`, `0384772`)

### Tests
- 40 → 57 (+17 watcher)

### Acceptance §11.2 — ✅
- FIFO processing
- Survives capture failures without hard crash
- State file consistent across kill/restart
- Sequential serial processing

---

## [phase-0-post + phase-1-post] — 2026-05-14

### Added
- Initial Phase-1 skeleton per Cowork spec (`4ce1e53`) — 11 src/autosplat modules + 31 unit tests
- Phase-0 baseline run on `bench_chill.MP4` — 7:15 min, 107/107 cameras, 82 172 Gaussians, 19.4 MB PLY

### Fixed
- `fetch_brush.sh`: pipefail + `.tar.xz` asset handling (`fix(install)`, `f8e885f`)
- `doctor` probe for COLMAP via `help` instead of hanging `--version` (`fix(doctor)`, `c9f038a`)
- `train.py` aligned with Brush v0.3 CLI surface + dataset staging (`fix(train)`, `54f5060`)
- `sfm.py` aligned with COLMAP 4.0 flag namespace + binary `.bin` parser (`fix(sfm)`, `a0efe62`)

### Added — Tests
- `tiny_video.mp4` fixture + opt-in E2E test (`feat(test)`, `913d3b8`)
- `docs/PHASE-0-CALIBRATION.md` — first end-to-end run findings (`docs(phase-0)`, `129c2da`)
- `docs/PHASE-0-CALIBRATION.md` extended with ice_bird SfM-failure findings → Phase-3-trigger documentation (`docs(phase-0)`, `b1d432a`)

### Acceptance §11.1 — ✅
- `autosplat doctor` reports missing deps correctly
- `autosplat process <video>` produces valid `scene.ply`
- Pipeline log captures start/end events per stage with duration
- Config overrides via CLI work
- SuperSplat auto-open implemented (opt-in)
- Unit tests + opt-in E2E green
