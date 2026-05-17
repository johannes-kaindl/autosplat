# Changelog

Versioning follows the spec's phase model. Releases tag the head commit when a phase's acceptance criteria are met.

Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

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
