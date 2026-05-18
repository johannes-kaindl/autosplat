# PHASE-10-PLAN — WebUI Release (v1.0.0)

*Plan snapshot 2026-05-16 · Status: **HISTORICAL — DONE** · Author: CC-Executor*
*Basis: recon-v1.0.0-webui.md, session 2026-05-16-autosplat-v1.0.0-webui-release*
*Rollback tag: `autosplat-pre-v1.0.0-webui`*

---

## §1 Context + Scope

**What was built:** A full WebUI for the autosplat pipeline — admin control and public surface in one FastAPI + HTMX + Jinja2 app. No MVP cut; dashboard, capture list, detail view, job runner, SuperSplat embed and AGPL footer in a single commit burst.

**What was not:** No multi-user auth, no persistent DB (the WatcherState JSON remains the state backbone), no cloud-deploy infrastructure, no rebuild of the CLI `serve` command (kept in parallel), no Node build step.

**Stack:** FastAPI + uvicorn + Jinja2 + HTMX (CDN). New sub-package `src/autosplat/webui/`. SuperSplat dist/ mounted via FastAPI StaticFiles. AGPL §13 network clause: footer on every page + `/source` route.

---

## §2 Architecture sketch

### FastAPI app structure

```
src/autosplat/
  webui/
    __init__.py          re-exports create_app
    app.py               FastAPI factory (create_app(cfg)), CORSMiddleware,
                         StaticFiles mounts, lifespan hook
    state.py             WatcherState adapter (read-only):
                         list_captures(), get_capture(), read_log_tail()
    jobs_runner.py       async background executor:
                         JobRunner, Dict[id → JobState], cancel via Popen handle
    routes/
      __init__.py
      dashboard.py       GET / → dashboard.html
      captures.py        GET /captures/, /captures/{id}, /captures/{id}/view
                         GET /captures/{id}/ply (FileResponse + CORS)
                         POST /captures/{id}/process, /captures/{id}/cancel
      jobs.py            GET /jobs/
      health.py          GET /healthz → {"status":"ok","version":"..."}
      source.py          GET /source  → AGPL §13 compliance
      partials.py        GET /partials/* — HTMX fragments
    templates/           Jinja2: base.html (HTMX CDN + AGPL footer),
                         dashboard.html, capture/list.html, capture/detail.html,
                         capture/view.html, jobs.html, source.html,
                         partials/dashboard_inner.html, partials/jobs_inner.html,
                         partials/capture_status.html
    static/style.css     minimal dark-mode CSS (native CSS grid/flex, no framework)
```

### Module boundaries

- `webui/app.py`: FastAPI instance, middleware, mounts, lifespan (loads config + JobRunner)
- `webui/state.py`: reads the WatcherState JSON + filesystem for capture discovery. **Read-only** — never writes WatcherState directly
- `webui/jobs_runner.py`: wraps asyncio threading for `run_pipeline()`. Holds `Dict[capture_id → JobState]` in memory. Monkey-patches `subprocess.Popen` for cancel support
- `webui/routes/`: thin handlers — load state, render templates
- `cli.py`: gains the `autosplat webui` command (starts uvicorn with `create_app()`)

### Relationship to serve_directory

`viewer.py`/`serve_directory` stays unchanged — it serves the CLI `serve` command. The WebUI solves the same problem differently: SuperSplat dist/ and PLY are served via FastAPI StaticFiles + FileResponse. No code sharing, no merge, no refactor.

---

## §3 Routes inventory

| URL | Method | Template / Response | Purpose |
|---|---|---|---|
| `/` | GET | `dashboard.html` | Dashboard: queue, recent captures, active job |
| `/captures/` | GET | `capture/list.html` | All captures from captures_dir, sorted by date |
| `/captures/{id}` | GET | `capture/detail.html` | Detail: stage status, PLY size, trigger button, errors |
| `/captures/{id}/process` | POST | redirect → `/captures/{id}` | Enqueue capture into the job queue |
| `/captures/{id}/cancel` | POST | redirect → `/captures/{id}` | Cancel the running job |
| `/captures/{id}/view` | GET | `capture/view.html` | SuperSplat embed (iframe + ?load=) |
| `/captures/{id}/ply` | GET | `FileResponse` | PLY file for SuperSplat's ?load= parameter |
| `/captures/{id}/log` | GET | JSON | pipeline.log tail (last 50 lines) |
| `/jobs/` | GET | `jobs.html` | Active jobs, queue, recent runs |
| `/partials/dashboard` | GET | HTMX partial | Dashboard status update (5s poll) |
| `/partials/capture/{id}/status` | GET | HTMX partial | Stage badge + status (3s poll on detail view) |
| `/partials/jobs` | GET | HTMX partial | Job-queue partial (2s poll on jobs view) |
| `/source` | GET | `source.html` | AGPL §13 network clause: source-code link |
| `/healthz` | GET | JSON `{"status":"ok"}` | Liveness check |

**StaticFiles mounts (no route handler):**
- `/static/` → `src/autosplat/webui/static/`
- `/supersplat/` → `target/supersplat/dist/` (only when `dist/index.html` exists)

---

## §4 Sub-phases (✅ DONE — historical)

### P1 — FastAPI foundation + `autosplat webui` CLI

**Scope:** App skeleton, dependencies, CLI command, first test.

**Status:** ✅ done — commit `f8b8f5b`

**DoD met:**
- `pyproject.toml`: fastapi, uvicorn[standard], jinja2 as core dependencies; httpx in dev
- `src/autosplat/webui/__init__.py`, `app.py`, `routes/health.py`
- `GET /healthz` → `{"status":"ok","version":"0.9.0"}`
- `autosplat webui --port 8080` starts uvicorn with `create_app()`
- `tests/webui/test_app.py`: /healthz test + TestClient via Starlette
- AGPL header in all new Python files

**Gate-1:** Smoke `http://localhost:8080/healthz` → OK ✅

---

### P2 — Capture list + detail view

**Scope:** Filesystem walk for captures, /captures/, /captures/{id}, HTMX polling.

**Status:** ✅ done — commit `c4c1b2f`

**DoD met:**
- `webui/state.py`: `list_captures()` → `list[CaptureInfo]`, WatcherState overlay
- Templates: `capture/list.html` (status badge), `capture/detail.html` (stage timeline)
- `/partials/capture/{id}/status` — HTMX fragment (hx-trigger="every 3s")
- `/captures/{id}/log` — JSON-lines tail (last 50 lines)
- Template directory `capture/` (singular) — avoids the `.gitignore` conflict with `captures/`
- Tests: list empty, list with fixture, detail 200

---

### P3 — Job runner + trigger + cancel

**Scope:** POST /captures/{id}/process, asyncio job runner, cancel path.

**Status:** ✅ done — commit `1981178`

**DoD met:**
- `webui/jobs_runner.py`: `JobRunner`, `Dict[id → JobState]`, `start_job()`, `cancel_job()`
- Threading for the synchronous `run_pipeline()` — does not block the ASGI event loop
- `subprocess.Popen` monkey-patch for the cancel handle
- `GET /jobs/` + `/partials/jobs` (hx-trigger="every 2s")
- Tests: `find_source_video`, enqueue, cancel

---

### P4 — SuperSplat embed + PLY serving

**Scope:** /captures/{id}/view, StaticFiles for dist/, PLY FileResponse.

**Status:** ✅ done — commit `2d1f691`

**DoD met:**
- `/supersplat/` StaticFiles mount (only when `dist/index.html` exists)
- `GET /captures/{id}/ply` → `FileResponse` with `Accept-Ranges` + CORS headers
- `capture/view.html`: iframe `src="/supersplat/index.html?load=/captures/{id}/ply"` + fallback when no PLY
- Tests: PLY route 200 + MIME, 404 when no PLY

---

### P5 — AGPL §13 footer + /source

**Scope:** AGPL compliance: footer in base.html, /source route.

**Status:** ✅ done — commit `bb0d3a7`

**DoD met:**
- `base.html` footer on every page: Codeberg link + "AGPL-3.0-or-later"
- `GET /source` → `source.html` with the licence text + a direct Codeberg link
- Tests: GET /source returns 200

---

### P6 — CHANGELOG + version bump + release tag

**Scope:** CHANGELOG entry, version 1.0.0, annotated tag.

**Status:** ✅ done — commit `85dce52`, tag `v1.0.0`

**DoD met:**
- `CHANGELOG.md` v1.0.0 section incl. pre-1.0 polish commits
- `pyproject.toml`: `version = "1.0.0"`
- `src/autosplat/__init__.py`: `__version__ = "1.0.0"`
- All tests green (185 collected, 185 passed)
- `git tag -a v1.0.0` annotated + pushed to Codeberg
- Codeberg release page created manually by the architect

**Gate-2:** Full browser smoke (dashboard, detail, /source, /healthz) → OK ✅

---

## §5 Risks + mitigations (as resolved)

| Risk | Mitigation | Resolved? |
|---|---|---|
| Brush async: `run_pipeline()` blocks synchronously | Threading for `run_pipeline()`, job runner asyncio-safe | ✅ via `threading.Thread` in `jobs_runner.py` |
| PLY streaming performance (200+ MB) | `FileResponse` with `Accept-Ranges` | ✅ FastAPI streams automatically |
| `autosplat serve` + `autosplat webui` port conflict | Different default ports (8765 vs 8080), independent config | ✅ no conflict |
| WatcherState race (WebUI reads, daemon writes) | `state.py` catches `JSONDecodeError`, returns the last state | ✅ graceful degradation |
| SuperSplat dist/ missing (fresh clone) | StaticFiles mount only when `dist/index.html` exists | ✅ fallback hint on the view page |
| `.gitignore` `captures/` pattern | Template directory named `capture/` (singular) | ✅ all refs adjusted |
| `ASGITransport` is async-only | Starlette `TestClient` instead of `httpx.Client(transport=ASGITransport)` | ✅ TestClient for sync tests |

---

## §6 Test strategy

**Target directory:** `tests/webui/`

**Framework:** `pytest` + Starlette `TestClient` (ASGI-sync). No `pytest-anyio` needed for sync tests; `anyio.from_thread` for async job-runner tests.

**Files:**
- `tests/webui/__init__.py`
- `tests/webui/conftest.py` — `app` fixture (`load_config(include_xdg=False)` + `create_app(cfg)`), `tmp_captures_dir`
- `tests/webui/test_app.py` — /healthz, /source
- `tests/webui/test_captures.py` — filesystem walk, detail 200, PLY 200/404
- `tests/webui/test_jobs.py` — `find_source_video`, enqueue, cancel

**Marker:** `needs_supersplat_dist` for tests that need `target/supersplat/dist/`.

**Result:** 185 tests total (175 before + 10 new WebUI tests). All green.

**Key pattern:** Real ASGI requests (no response mock) — consistent with the `test_viewer.py` precedent. Pattern memory `feedback_integration_tests_http.md` confirms: HTTP integration tests catch bugs (CORS) that unit tests miss.

---

## §7 v1.1.0 Restyle — Kuro Signal Protocol

*Addendum 2026-05-17 · Session `2026-05-16-autosplat-v1.1.0-webui-restyle` · Rollback tag stack `autosplat-pre/post-v1.1.0-restyle-P{N}-*`*

The v1.0.0 WebUI used a minimal `static/style.css`. v1.1.0 replaces it with a full design system, with no change to pipeline behaviour.

### Token system

- `static/css/tokens.css` — primitives: colour scales, spacing (`--space-1…8`), radii, fonts (display/body/mono), signal accents (`--signal-phosphor`, `--signal-circuit`, …), stage colours.
- `static/css/autosplat.css` — component layer (~24 sections): frame grid, top bar, sidebar, cards, tables, stage timeline, badges, buttons, viewer HUD.
- Both are aspect-capable: `data-aspect` on `<html>` switches subthemes (gunshi/kantoku/sensei) — hard-pinned to `shugo` in v1.1.0, with the tokens present but latent.

### Theme toggle

- `data-theme` on `<html>` (`dark` default / `light`), persisted in `localStorage` as `autosplat-theme`.
- Anti-flash: an inline `<script>` in the `<head>` sets `data-theme` before the first paint.
- Top-bar pill with a pre-rendered sun/moon SVG and a CSS visibility toggle.

### HTMX polling architecture

| Surface | Poll interval | Swap target |
|---|---|---|
| Dashboard `/partials/dashboard` | 3 s | `outerHTML` |
| Captures list `/partials/captures` | 3 s | `outerHTML` |
| Jobs `/partials/jobs` | 2 s | `outerHTML` |
| Capture detail log `/partials/capture/{id}/log` | 2 s | `innerHTML` |
| Capture detail brush `/partials/capture/{id}/brush` | 3 s | `outerHTML` |

### Wrapper pattern lock (P2.7 lesson)

- **`as-poll-region`** — outer wrapper, carries the HTMX poll attributes, no padding. Target of an `outerHTML` swap.
- **`as-main-inner`** — inner wrapper, carries the layout padding. The partial additionally carries its own HTMX attributes for self-renewal.
- Nested `as-main-inner` was the P2.7 bug — separating outer-poll from inner-padding resolves it.

### Vendored HTMX

- `static/js/htmx.min.js` — htmx@1.9.12, BSD-2, served locally.
- Reason: the CDN `integrity` SRI hash was wrong → the browser blocked HTMX entirely (P4.5 root cause). Same-origin needs no SRI, works offline, and is AGPL-compliant.

### Latent features (no UI exposure)

- HTMX polling annotation overlay: `document.body.setAttribute('data-annot', 'on')` from the console.
- Aspect subthemes gunshi/kantoku/sensei — CSS tokens present, no picker (removed in P2.6 as out of scope).

### Tests

`tests/webui/test_ui_smoke.py` — 10 HTTP integration tests: all 7 surfaces, static assets (tokens.css / autosplat.css / htmx.min.js), partial routes. Full suite 185 → 195.

### Known v1.1.1 hotfix candidates

`SF-G2-9` (backend status-write race), `SF-PIPE-1` (SuperSplat PLY URL-loading), `SF-G3-3` (JobRunner single-run-per-capture). All three are WebUI-display-only — the pipeline itself runs correctly. Details in `CHANGELOG.md` [v1.1.0] § Known Issues.
