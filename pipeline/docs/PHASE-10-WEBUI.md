# PHASE-10-PLAN — WebUI Release (v1.0.0)

*Plan-Snapshot 2026-05-16 · Status: **HISTORICAL — DONE** · Autor: CC-Executor*
*Basis: recon-v1.0.0-webui.md, session 2026-05-16-autosplat-v1.0.0-webui-release*
*Rollback-Tag: `autosplat-pre-v1.0.0-webui`*

---

## §1 Kontext + Scope

**Was gebaut wurde:** Vollständige WebUI für die autosplat-Pipeline — Admin-Steuerung und Public-Surface in einer FastAPI + HTMX + Jinja2 App. Kein MVP-Cut; Dashboard, Capture-Liste, Detail-View, Job-Runner, SuperSplat-Embed und AGPL-Footer in einem Commit-Burst.

**Was nicht:** Kein Multi-User-Auth, keine persistente DB (WatcherState-JSON bleibt State-Backbone), keine Cloud-Deploy-Infrastruktur, kein Neubau des CLI-`serve`-Kommandos (bleibt parallel), kein Node-Build-Step.

**Stack:** FastAPI + uvicorn + Jinja2 + HTMX (CDN). Neues Sub-Package `src/autosplat/webui/`. SuperSplat-dist/ via FastAPI StaticFiles gemountet. AGPL §13 Network-Clause: Footer auf jeder Seite + `/source`-Route.

---

## §2 Architektur-Skizze

### FastAPI-App-Struktur

```
src/autosplat/
  webui/
    __init__.py          re-exports create_app
    app.py               FastAPI factory (create_app(cfg)), CORSMiddleware,
                         StaticFiles-Mounts, Lifespan-Hook
    state.py             WatcherState-Adapter (read-only):
                         list_captures(), get_capture(), read_log_tail()
    jobs_runner.py       Async Background-Executor:
                         JobRunner, Dict[id → JobState], cancel via Popen-handle
    routes/
      __init__.py
      dashboard.py       GET / → dashboard.html
      captures.py        GET /captures/, /captures/{id}, /captures/{id}/view
                         GET /captures/{id}/ply (FileResponse + CORS)
                         POST /captures/{id}/process, /captures/{id}/cancel
      jobs.py            GET /jobs/
      health.py          GET /healthz → {"status":"ok","version":"..."}
      source.py          GET /source  → AGPL §13 Compliance
      partials.py        GET /partials/* — HTMX-Fragmente
    templates/           Jinja2: base.html (HTMX-CDN + AGPL-Footer),
                         dashboard.html, capture/list.html, capture/detail.html,
                         capture/view.html, jobs.html, source.html,
                         partials/dashboard_inner.html, partials/jobs_inner.html,
                         partials/capture_status.html
    static/style.css     Minimal dark-mode CSS (native CSS Grid/Flex, kein Framework)
```

### Module-Boundaries

- `webui/app.py`: FastAPI-Instanz, Middleware, Mounts, Lifespan (lädt Config + JobRunner)
- `webui/state.py`: liest WatcherState-JSON + Filesystem für Capture-Discovery. **Read-only** — kein direktes Schreiben in WatcherState
- `webui/jobs_runner.py`: kapselt asyncio-Threading für `run_pipeline()`. Hält `Dict[capture_id → JobState]` im Speicher. Monkey-patcht `subprocess.Popen` für Cancel-Support
- `webui/routes/`: Thin Handler — laden State, rendern Templates
- `cli.py`: bekommt `autosplat webui` Kommando (startet uvicorn mit `create_app()`)

### Verhältnis zu serve_directory

`viewer.py`/`serve_directory` bleibt unverändert — dient dem CLI-`serve`-Command. Die WebUI löst dasselbe Problem anders: SuperSplat dist/ und PLY werden über FastAPI StaticFiles + FileResponse ausgeliefert. Kein Code-Sharing, kein Merge, kein Refactor.

---

## §3 Routes-Inventar

| URL | Method | Template / Response | Purpose |
|---|---|---|---|
| `/` | GET | `dashboard.html` | Dashboard: Queue, letzte Captures, aktiver Job |
| `/captures/` | GET | `capture/list.html` | Alle Captures aus captures_dir, sortiert nach Datum |
| `/captures/{id}` | GET | `capture/detail.html` | Detail: Stage-Status, PLY-Größe, Trigger-Button, Fehler |
| `/captures/{id}/process` | POST | redirect → `/captures/{id}` | Capture in Job-Queue einreihen |
| `/captures/{id}/cancel` | POST | redirect → `/captures/{id}` | Laufenden Job abbrechen |
| `/captures/{id}/view` | GET | `capture/view.html` | SuperSplat-Embed (iframe + ?load=) |
| `/captures/{id}/ply` | GET | `FileResponse` | PLY-Datei für SuperSplat ?load= Parameter |
| `/captures/{id}/log` | GET | JSON | pipeline.log-Tail (letzte 50 Zeilen) |
| `/jobs/` | GET | `jobs.html` | Aktive Jobs, Queue, letzte Läufe |
| `/partials/dashboard` | GET | HTMX-Partial | Dashboard-Status-Update (5s-Poll) |
| `/partials/capture/{id}/status` | GET | HTMX-Partial | Stage-Badge + Status (3s-Poll auf Detail-View) |
| `/partials/jobs` | GET | HTMX-Partial | Job-Queue-Partial (2s-Poll auf Jobs-View) |
| `/source` | GET | `source.html` | AGPL §13 Network-Clause: Quellcode-Link |
| `/healthz` | GET | JSON `{"status":"ok"}` | Liveness-Check |

**StaticFiles-Mounts (kein Route-Handler):**
- `/static/` → `src/autosplat/webui/static/`
- `/supersplat/` → `target/supersplat/dist/` (nur wenn `dist/index.html` vorhanden)

---

## §4 Sub-Phasen (✅ DONE — historisch)

### P1 — FastAPI Foundation + `autosplat webui` CLI

**Scope:** App-Skeleton, Dependencies, CLI-Kommando, erster Test.

**Status:** ✅ done — Commit `f8b8f5b`

**DoD erreicht:**
- `pyproject.toml`: fastapi, uvicorn[standard], jinja2 als core dependencies; httpx in dev
- `src/autosplat/webui/__init__.py`, `app.py`, `routes/health.py`
- `GET /healthz` → `{"status":"ok","version":"0.9.0"}`
- `autosplat webui --port 8080` startet uvicorn mit `create_app()`
- `tests/webui/test_app.py`: /healthz Test + TestClient via Starlette
- AGPL-Header in allen neuen Python-Dateien

**Gate-1:** Smoke `http://localhost:8080/healthz` → OK ✅

---

### P2 — Capture-Liste + Detail-View

**Scope:** Filesystem-Walk für Captures, /captures/, /captures/{id}, HTMX-Polling.

**Status:** ✅ done — Commit `c4c1b2f`

**DoD erreicht:**
- `webui/state.py`: `list_captures()` → `list[CaptureInfo]`, WatcherState-Overlay
- Templates: `capture/list.html` (Status-Badge), `capture/detail.html` (Stage-Timeline)
- `/partials/capture/{id}/status` — HTMX-Fragment (hx-trigger="every 3s")
- `/captures/{id}/log` — JSON-Lines-Tail (letzte 50 Zeilen)
- Template-Verzeichnis `capture/` (singular) — `.gitignore`-Konflikt mit `captures/` vermieden
- Tests: list empty, list with fixture, detail 200

---

### P3 — Job-Runner + Trigger + Cancel

**Scope:** POST /captures/{id}/process, asyncio Job-Runner, Cancel-Path.

**Status:** ✅ done — Commit `1981178`

**DoD erreicht:**
- `webui/jobs_runner.py`: `JobRunner`, `Dict[id → JobState]`, `start_job()`, `cancel_job()`
- Threading für synchronen `run_pipeline()` — blockiert nicht den ASGI Event-Loop
- `subprocess.Popen` Monkey-Patch für Cancel-Handle
- `GET /jobs/` + `/partials/jobs` (hx-trigger="every 2s")
- Tests: `find_source_video`, enqueue, cancel

---

### P4 — SuperSplat-Embed + PLY-Serve

**Scope:** /captures/{id}/view, StaticFiles für dist/, PLY-FileResponse.

**Status:** ✅ done — Commit `2d1f691`

**DoD erreicht:**
- `/supersplat/` StaticFiles-Mount (nur wenn `dist/index.html` vorhanden)
- `GET /captures/{id}/ply` → `FileResponse` mit `Accept-Ranges` + CORS-Header
- `capture/view.html`: iframe `src="/supersplat/index.html?load=/captures/{id}/ply"` + Fallback wenn kein PLY
- Tests: PLY-Route 200 + MIME, 404 wenn kein PLY

---

### P5 — AGPL §13 Footer + /source

**Scope:** AGPL-Compliance: Footer in base.html, /source-Route.

**Status:** ✅ done — Commit `bb0d3a7`

**DoD erreicht:**
- `base.html` Footer auf jeder Seite: Codeberg-Link + "AGPL-3.0-or-later"
- `GET /source` → `source.html` mit License-Text + direktem Codeberg-Link
- Tests: GET /source returns 200

---

### P6 — CHANGELOG + Version-Bump + Release-Tag

**Scope:** CHANGELOG-Entry, Version 1.0.0, annotierter Tag.

**Status:** ✅ done — Commit `85dce52`, Tag `v1.0.0`

**DoD erreicht:**
- `CHANGELOG.md` v1.0.0-Section inkl. Pre-1.0-Polish-Commits
- `pyproject.toml`: `version = "1.0.0"`
- `src/autosplat/__init__.py`: `__version__ = "1.0.0"`
- Alle Tests grün (185 collected, 185 passed)
- `git tag -a v1.0.0` annotiert + nach Codeberg gepusht
- Codeberg-Release-Page durch Architekten manuell angelegt

**Gate-2:** Vollständiger Browser-Smoke (Dashboard, Detail, /source, /healthz) → OK ✅

---

## §5 Risiken + Mitigations (wie aufgelöst)

| Risiko | Mitigation | Aufgelöst? |
|---|---|---|
| Brush-Async: `run_pipeline()` synchron blockierend | Threading für `run_pipeline()`, Job-Runner asyncio-safe | ✅ via `threading.Thread` in `jobs_runner.py` |
| PLY-Streaming-Performance (200+ MB) | `FileResponse` mit `Accept-Ranges` | ✅ FastAPI streamt automatisch |
| `autosplat serve` + `autosplat webui` Port-Konflikt | Verschiedene Default-Ports (8765 vs 8080), unabhängige Config | ✅ kein Konflikt |
| WatcherState-Race (WebUI liest, Daemon schreibt) | `state.py` fängt `JSONDecodeError` ab, gibt letzten State zurück | ✅ graceful degradation |
| SuperSplat dist/ fehlt (frischer Clone) | StaticFiles-Mount nur wenn `dist/index.html` existiert | ✅ Fallback-Hinweis auf View-Seite |
| `.gitignore` `captures/` Muster | Template-Verzeichnis als `capture/` (singular) angelegt | ✅ alle Refs angepasst |
| `ASGITransport` ist async-only | Starlette `TestClient` statt `httpx.Client(transport=ASGITransport)` | ✅ TestClient für Sync-Tests |

---

## §6 Test-Strategie

**Zielordner:** `tests/webui/`

**Framework:** `pytest` + Starlette `TestClient` (ASGI-Sync). Kein `pytest-anyio` benötigt für Sync-Tests; `anyio.from_thread` für async Job-Runner-Tests.

**Dateien:**
- `tests/webui/__init__.py`
- `tests/webui/conftest.py` — `app` Fixture (`load_config(include_xdg=False)` + `create_app(cfg)`), `tmp_captures_dir`
- `tests/webui/test_app.py` — /healthz, /source
- `tests/webui/test_captures.py` — Filesystem-Walk, Detail 200, PLY 200/404
- `tests/webui/test_jobs.py` — `find_source_video`, enqueue, cancel

**Marker:** `needs_supersplat_dist` für Tests die `target/supersplat/dist/` brauchen.

**Ergebnis:** 185 Tests gesamt (vorher 175 + 10 neue WebUI-Tests). Alle grün.

**Schlüssel-Pattern:** Echte ASGI-Requests (kein Response-Mock) — konsistent mit `test_viewer.py`-Vorbild. Pattern-Memory `feedback_integration_tests_http.md` bestätigt: HTTP-Integration-Tests finden Bugs (CORS), die Unit-Tests übersehen.

---

## §7 v1.1.0 Restyle — Kuro Signal Protocol

*Addendum 2026-05-17 · Session `2026-05-16-autosplat-v1.1.0-webui-restyle` · Rollback-Tag-Stack `autosplat-pre/post-v1.1.0-restyle-P{N}-*`*

Die v1.0.0-WebUI nutzte ein minimales `static/style.css`. v1.1.0 ersetzt es durch ein vollständiges Design-System ohne Verhaltensänderung der Pipeline.

### Token-System

- `static/css/tokens.css` — Primitive: Farb-Skalen, Spacing (`--space-1…8`), Radii, Fonts (display/body/mono), Signal-Akzente (`--signal-phosphor`, `--signal-circuit`, …), Stage-Farben.
- `static/css/autosplat.css` — Komponenten-Layer (~24 Sektionen): Frame-Grid, TopBar, Sidebar, Cards, Tabellen, Stage-Timeline, Badges, Buttons, Viewer-HUD.
- Beide aspekt-fähig: `data-aspect` auf `<html>` schaltet Subthemes (gunshi/kantoku/sensei) — in v1.1.0 hart auf `shugo` gepinnt, Tokens latent vorhanden.

### Theme-Toggle

- `data-theme` auf `<html>` (`dark` Default / `light`), in `localStorage` als `autosplat-theme` persistiert.
- Anti-Flash: ein Inline-`<script>` im `<head>` setzt `data-theme` vor dem ersten Paint.
- TopBar-Pill mit vorgerendertem sun/moon-SVG, CSS-Visibility-Toggle.

### HTMX-Polling-Architektur

| Surface | Poll-Intervall | Swap-Ziel |
|---|---|---|
| Dashboard `/partials/dashboard` | 3 s | `outerHTML` |
| Captures-List `/partials/captures` | 3 s | `outerHTML` |
| Jobs `/partials/jobs` | 2 s | `outerHTML` |
| Capture-Detail Log `/partials/capture/{id}/log` | 2 s | `innerHTML` |
| Capture-Detail Brush `/partials/capture/{id}/brush` | 3 s | `outerHTML` |

### Wrapper-Pattern-Lock (P2.7-Lesson)

- **`as-poll-region`** — äußerer Wrapper, trägt die HTMX-Poll-Attribute, kein Padding. Ziel eines `outerHTML`-Swaps.
- **`as-main-inner`** — innerer Wrapper, trägt das Layout-Padding. Das Partial trägt zusätzlich eigene HTMX-Attribute für Self-Renewal.
- Verschachtelte `as-main-inner` waren der P2.7-Bug — die Trennung outer-Poll / inner-Padding löst ihn.

### Vendored HTMX

- `static/js/htmx.min.js` — htmx@1.9.12, BSD-2, lokal ausgeliefert.
- Grund: der CDN-`integrity`-SRI-Hash war fehlerhaft → Browser blockierte HTMX komplett (P4.5-Root-Cause). Same-origin braucht kein SRI, ist offline-fähig und AGPL-konform.

### Latent Features (kein UI-Exposure)

- HTMX-Polling-Annotation-Overlay: `document.body.setAttribute('data-annot', 'on')` in der Konsole.
- Aspect-Subthemes gunshi/kantoku/sensei — CSS-Tokens vorhanden, kein Picker (in P2.6 als scope-frei entfernt).

### Tests

`tests/webui/test_ui_smoke.py` — 10 HTTP-Integration-Tests: alle 7 Surfaces, Static-Assets (tokens.css / autosplat.css / htmx.min.js), Partial-Routes. Gesamt-Suite 185 → 195.

### Bekannte v1.1.1-Hotfix-Kandidaten

`SF-G2-9` (Backend-Status-Write-Race), `SF-PIPE-1` (SuperSplat-PLY-URL-Loading), `SF-G3-3` (JobRunner single-run-per-capture). Alle drei sind WebUI-Display-only — die Pipeline selbst läuft korrekt. Details in `CHANGELOG.md` [v1.1.0] § Known Issues.
