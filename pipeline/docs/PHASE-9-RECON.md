# PHASE-9-RECON — SuperSplat Local + WebUI Options

*Recon-Burst 2026-05-14 · Status: **Decision-Gate** · Author: CC-Executor*

---

## 1 · SuperSplat-Source-Recon

**License:** MIT — fully open source, unrestricted self-hosting and modification allowed.

**Repo:** [github.com/playcanvas/supersplat](https://github.com/playcanvas/supersplat)

**Build-Stack:**
- Rollup 4.60.3 (bundler), TypeScript 6.0.3, SCSS/PostCSS
- Node.js ≥ 20.19.0 required
- PlayCanvas Engine 2.18.1 (WebGL/WebGPU renderer)

**Dev-Server:**
- `npm run develop` → concurrent Rollup build + dev server on **port 3000** (`http://localhost:3000`)
- `npm run serve` → server-only (no live rebuild), also port 3000
- `npm run build` → production bundle to `dist/`

**Bundle size:** Not officially documented. Typical for Rollup+TS SPAs with a WebGPU engine: 2–8 MB minified+gzip. Must be verified after a local build.

**Headless mode:** **None.** No CLI mode, no programmatic PLY import API. The application is purely browser-interactive (drag-and-drop or file-open dialog). Machine-driven batch processing is not provided for.

**URL parameters:** SuperSplat supports a `?load=<URL>` parameter (confirmed from `main.ts`: `url.searchParams.getAll('load')`). The app fetches the URL via `fetch()` on startup. Implication for the pipeline: a locally running SuperSplat can thus automatically load a locally served PLY file — without manual drag-and-drop.

---

## 2 · Local-Server-Integration-Options

Three approaches to running SuperSplat locally:

| Criterion | **(a) Static build in repo** | **(b) `file://`-iframe** | **(c) Electron wrapper** |
|---|---|---|---|
| Description | Clone the SuperSplat repo, `npm run build`, serve `dist/` statically via uvicorn/http.server | Build SuperSplat `dist/` locally, `file://`-URL in Obsidian | Wrap SuperSplat in an Electron app |
| Dev effort | Medium (Node setup + build step in install script) | Low (build only) | High (Electron packaging) |
| CORS/Mixed-Content | ✅ **OK** — `http://localhost:3000 → http://localhost:8765` = same-scheme, no mixed-content | ⚠️ Browser-dependent — `file://` pages may not fetch `http://` in newer Chrome/Safari versions | ✅ OK (Electron-native) |
| Obsidian embed (`iframe src`) | ✅ `http://localhost:PORT?load=...` works in reading mode | ❌ `file://`-URLs blocked in Obsidian iframes | ❌ no iframe compatibility |
| User prerequisites | Node.js + npm (one-time via install script) | Node.js + npm (only for build) | No Node after build |
| Update maintenance | SuperSplat updates: `git pull && npm run build` | Identical | High (Electron releases) |
| Sharing/Mobile | ❌ `localhost`-URL not shareable | ❌ | ❌ |
| **Verdict** | **Recommended for Phase 9** | Feasible for a pure viewer, no Obsidian embed | Overengineering for this scope |

**Important CORS clarification:** The current `viewer.py` code opens `https://playcanvas.com/supersplat/editor?load=http://127.0.0.1:8765/scene.ply`. This is **demonstrably broken**: for security reasons an HTTPS document (playcanvas.com) may not fetch an HTTP resource (127.0.0.1) (mixed-content blocking). The `?load=` function exists in SuperSplat but was de facto never usable with the current remote-viewer configuration.

---

## 3 · Web-UI scope axes

What would a local web UI offer beyond the CLI? Evaluated by Phase-9 relevance:

| Feature | Description | Phase-9 mandatory? | Rationale |
|---|---|---|---|
| **(a) Drop-Zone** | Drag a video into the browser window → starts the pipeline | No | CLI `autosplat watch` covers this. Duplication with no additional benefit. |
| **(b) Live pipeline status** | Progress of the running stage, ETA, logs | No | `autosplat status` + Rich terminal are sufficient. WebUI polling increases complexity with no real advantage over a terminal tab. |
| **(c) Capture browser** | List of all captures with FM stats (Gaussians, date, PLY size) | **Yes (Phase 9)** | Directly addresses the "Where is my capture?" pain (see §11). Obsidian Bases is an alternative, but an autosplat-native view would be more valuable for the viewer-launch flow. |
| **(d) Inline SuperSplat editor** | SuperSplat as an iframe in the web UI | Optional | Works, but opening `localhost:3000` directly is just as good. The iframe adds nothing. |
| **(e) "Save to Obsidian" button** | Fills `embed_url:` + `embed_view_url:` in the capture note after cleanup | **Yes (Phase 9)** | Addresses the #1 pain point: empty `embed_url` after a pipeline run. |
| **(f) Doctor status pane** | Deps status in the browser | No | `autosplat doctor` is fully sufficient. |

**Minimal Phase-9 web UI scope** (if a WebUI is built): capture-browser list + "Open in SuperSplat" button + "Write embed_url into Obsidian note" button. Everything else is Phase 10+.

---

## 4 · iframe target strategy

Three approaches for the `embed_url` value in Obsidian capture notes:

| Strategy | Example URL | Pros | Cons |
|---|---|---|---|
| **localhost:PORT** (local) | `http://localhost:3000?load=http://localhost:8765/burgstall/scene.ply` | Works offline, no cloud upload needed, automatable | Usable only on the same machine; Obsidian Mobile sees an empty iframe; not shareable |
| **superspl.at share URL** (cloud) | `https://superspl.at/s?id=09cbbcd9` | Shareable, mobile-compatible, no local server needed | Requires a manual cloud upload via browser; no known API; PlayCanvas-cloud dependency |
| **Standalone HTML export** | `file:///Users/.../burgstall-viewer.html` | Fully offline + local | `file://`-URLs blocked in Obsidian iframes; file size unclear; SuperSplat does not support standalone HTML export |

**Recommendation:** Two-tier strategy:
1. **`embed_url` = localhost URL** — automatically populated after a pipeline run, immediately usable on the work machine.
2. **`embed_view_url` = superspl.at URL** — entered manually after a cloud upload, optional.

The Obsidian note template should provide for both fields with a fallback link: show the iframe when `embed_url` is set, show an "Open in SuperSplat" link as fallback.

---

## 5 · Obsidian-Reader-UX

**When a local SuperSplat server is running:** `iframe src="http://localhost:3000?load=..."` renders fully interactive in Obsidian reading mode.

**When the server is not running:** the iframe shows an empty/broken page with no error message — poor UX. Mitigation: the note template should include an HTML fallback with a visible hint:

```html
<iframe src="http://localhost:3000?load=..." ...></iframe>

> **Viewer offline?** Start autosplat with `autosplat serve` or use the [cloud link](https://superspl.at/s?id=XXXX).
```

**Screenshot-preview fallback:** Phase 4 does not generate preview screenshots. A static `preview.jpg` (e.g. via the Brush `--with-viewer` screenshot API or FFmpeg thumbnailing) would be low effort and would make the note usable mobile/offline as well. Candidate for Phase 10.

**Mobile (Obsidian iOS/Android):** localhost URLs never work. Here `embed_view_url` with a superspl.at link is the only way. Without it the note remains purely textual on mobile.

---

## 6 · Auth + Sharing

**Out of scope for Phase 9.** Context note for the roadmap:

The PlayCanvas Cloud Publish service (`superspl.at`) is the only existing sharing solution. It is tied to the PlayCanvas account and — as far as is publicly known — has **no official API** for programmatic uploading (no REST endpoint, no CLI tool documented). An automatic "publish + copy URL" would therefore be a reverse-engineering project.

Alternatives for Phase 10+:
- **Self-hosted splat server** (e.g. nginx + static HTML with Three.js/gaussian-splats-3d.js) → own share URLs on your own server/NAS
- **Obsidian Publish** — iframe rendering of external domains is restricted by CSP; superspl.at works (as burgstall proves), localhost URLs do not
- **Airdrop/Export** — share the `.ply` directly; the recipient opens it themselves in supersplat.com

---

## 7 · Tech-stack implications

| Approach | New runtime deps | Footprint | Setup complexity | Test story |
|---|---|---|---|---|
| **SuperSplat local only** (Option A) | `node` + `npm` (system) | ~200 MB after `npm install` | Medium — `scripts/setup_supersplat.sh` | Smoke: `curl localhost:3000` + PLY load check |
| **FastAPI WebUI** (Option B) | `fastapi`, `uvicorn`, `jinja2` | ~15 MB pip | Medium — new `pyproject.toml` deps | Playwright- or `httpx`-based tests |
| **`python -m http.server`** | None | Minimal | Trivial | N/A |
| **PyWebView** | `pywebview` | ~50 MB | Low | Hard to automate |

**Observation:** `python -m http.server` is already implemented via `socketserver.ThreadingTCPServer` in `viewer.py` — the HTTP-server layer is solved. What is missing is merely (a) a locally running SuperSplat and (b) CORS-compliant URL construction.

FastAPI would mainly make sense if the WebUI needs interactive endpoints (pipeline trigger, note update). For purely static capture-browsing pages, `http.server` + generated HTML is also sufficient.

---

## 8 · CLI-vs-WebUI-Hybrid

**Proposal for spec §4 repo-structure extension** (hybrid approach):

```
auto-splat-pipeline/
├── src/autosplat/
│   ├── viewer.py          # existing — fix CORS logic, add local-supersplat-path
│   ├── ui/
│   │   ├── server.py      # FastAPI/uvicorn app (optional, opt-in)
│   │   ├── templates/
│   │   │   └── captures.html   # Jinja2 capture browser
│   │   └── static/
│   └── supersplat/        # OR: target/supersplat/ (gitignored build-artifact)
└── scripts/
    └── setup_supersplat.sh  # clone + npm install + npm run build
```

**CLI extension:**
```
autosplat serve [--port 8765] [--with-supersplat] [--open-browser]
```
- Without `--with-supersplat`: PLY-server only (as today, but without the remote-viewer bug)
- With `--with-supersplat`: starts a local SuperSplat on :3000 + PLY server on :8765
- `autosplat watch` runs unchanged in parallel

**Separation of concerns:** `autosplat watch` and `autosplat serve` are independent processes. Watch runs continuously in the background, serve is interactive for review sessions. No coupling.

---

## 9 · Test strategy

| Level | Approach | Coverage | Time effort |
|---|---|---|---|
| **Unit** | Mocks for SuperSplat process start, URL-builder tests | URL construction, server start/stop logic | Low |
| **Integration** | `curl localhost:3000` after `setup_supersplat.sh` + server start | SuperSplat runs + reachable | Medium (requires npm in CI — problematic) |
| **Playwright E2E** | Headless Chrome, load PLY via localhost:3000, check canvas element | Real PLY render | High + slow + CI-infra effort |
| **Smoke (realistic)** | `autosplat serve --with-supersplat --no-open`, curl check, then manual | Reachability | Low |

**Recommendation:** For Phase 9, **smoke-only** is realistic: unit tests for the URL builder + process management + a `curl`-based smoke test. Playwright would be the gold standard but disproportionate for this scope. CI with npm/Node is solvable but increases setup complexity.

---

## 10 · Phase-plan consequences

### Option A — SuperSplat Local Auto-Open (~1–2 days)

Scope: fix `viewer.py` (CORS bug), `scripts/setup_supersplat.sh` (clone + build), `autosplat serve --with-supersplat`, `embed_url` auto-fill with a localhost URL after a pipeline run.

Directly addresses:
- CORS/mixed-content bug in `viewer.py` (PLY was never really loaded automatically)
- `embed_url: ""` problem — becomes `http://localhost:3000?load=...`
- Manual drag-and-drop requirement is eliminated

Not addressed:
- Cloud share URL for mobile/sharing
- Capture-browser overview
- No new UI besides the terminal

### Option B — Full Local WebUI (several days, 4–8 days realistic)

Scope: FastAPI app with capture browser, pipeline status, embedded SuperSplat iframe, "Obsidian note update" button, doctor status pane.

Additionally addresses:
- All §3 features (a)–(f)
- Better onboarding UX

Risks:
- Scope creep — "just one more feature" can swallow weeks
- FastAPI as a new runtime dep (not critical, but `uv add`)
- Playwright tests or manual tests
- Time-to-benefit ratio: most gains come from Option A, not from the UI layer

### Option C — Hybrid: Local SuperSplat + Minimal Capture Browser (~2–3 days)

Option A + a simple HTML page (statically generated, no framework) with a capture list and "Open in SuperSplat" / "Update embed_url" buttons. No pipeline control in the browser.

**Decision-gate criteria:**
1. How often is the pipeline used daily? (fewer than 3× → A is sufficient)
2. Is mobile sharing / Obsidian Mobile a hard requirement for Phase 9? (yes → the cloud-URL question remains open regardless of A/B/C)
3. How important is capture browsing outside of Obsidian? (Obsidian Bases already covers that)

---

## 11 · Real-World-Use-Case-Friction

### Sources: bench_chill handover + burgstall capture note

**Pain points from the bench_chill handover (manual round-trip):**

1. **PLY load is manual** — step 1 explicitly requires drag-and-drop into the browser. The `viewer.py` `?load=` mechanism does not work because of mixed-content blocking (HTTPS→HTTP blocked). For bench_chill (19.4 MB) still reasonably fast; for burgstall (214 MB) potentially slow.

2. **`embed_url` stays empty** — the Obsidian note is auto-generated with `embed_url: ""` and `embed_view_url: ""`. After the cloud publish, Jay has to enter the URL into the frontmatter manually. This is the only step that requires JSON/YAML editing in Obsidian — error-prone and easy to forget.

3. **Cloud publish is mandatory for the Obsidian embed** — without a superspl.at share URL the note has no working viewer. The entire "Obsidian 3D memory" workflow hangs on this single manual cloud-upload step.

4. **SuperSplat cleanup is genuinely hand work** — floater removal and crop are inherently manual and cannot be automated. Phase 9 should explicitly frame this step as "remains manual" — that is not a bug, that is intentional.

**Pain points from the burgstall note:**

5. **214 MB PLY — upload time** — loading a 214 MB PLY into SuperSplat.com takes considerably longer in the browser than 19.4 MB (bench_chill). A local SuperSplat (`http://localhost:3000?load=http://localhost:8765/scene.ply`) loads from localhost — no network transfer, immediate availability.

6. **`embed_view_url: ""`** — a second embed-URL field already exists in the note (alongside `embed_url`). Its semantics are unclear (editor vs. viewer?). The Obsidian schema should be defined explicitly for Phase 9: `embed_url` = local (localhost), `embed_view_url` = cloud share.

7. **`total_duration_s: 3780` (~63 min)** — for long training runs Jay is not at the machine when the PLY finishes. The watch-folder daemon model (Phase 2) is built for that — but a SuperSplat auto-open at pipeline end would be disruptive (an unwanted window popup after 63 min). A **"done" notification** (macOS Notification Center) would be more valuable than auto-open. Candidate for Phase 9 in addition to Option A.

**What Phase 9 should directly address (prioritized):**
1. PLY-load automation (local SuperSplat + `?load=` works)
2. `embed_url` auto-fill after a pipeline run (localhost URL, no cloud upload needed)
3. Possibly a macOS notification after training ends

---

## § Options matrix

| Dimension | **Option A** — SuperSplat Local Auto-Open | **Option B** — Full Local WebUI | **Option C** — Hybrid (A + capture browser) |
|---|---|---|---|
| **Scope** | Fix viewer.py CORS + setup script + embed_url auto-fill | Complete web app (capture browser, status, inline SuperSplat, Obsidian button) | Option A + static capture-browser page |
| **Time estimate** | 1–2 days | 4–8 days | 2–3 days |
| **Tech stack** | Node.js (SuperSplat build), Python HTTP server (already present) | FastAPI + uvicorn + Jinja2 + Node.js | Node.js + simple generated HTML |
| **Test coverage** | Unit (URL builder) + smoke | Unit + integration + possibly Playwright | Unit + smoke |
| **Reader UX (Obsidian)** | localhost URL in embed_url — works on the work machine | Identical + cloud-URL button | Identical to A |
| **Mobile UX** | ❌ (localhost not reachable) | ❌ (identical — cloud URL remains manual) | ❌ identical |
| **Risks** | npm/Node prerequisite; SuperSplat dev server must be running | Scope creep; new framework; longer implementation time | Moderate — HTML generation easy to keep simple |
| **Concept-paper friction reduction** | High — fixes the CORS bug + eliminates drag-and-drop + fills embed_url | Medium-high — additional value low vs. effort | High + marginal capture-browser improvement |
| **Addresses core pain points (§11)** | #1, #2, #5, #7 | #1–#7 | #1, #2, #5, #6, #7 |

---

## § Architect hypothesis (explicitly marked as a hypothesis — not a recommendation)

**Architect hypothesis (Jay/Cowork):** "Unite everything locally in a web UI" — Option B Full WebUI is the right direction.

**CC counter-position after recon:**

The hypothesis is conceptually coherent, but the time effort is disproportionate to the additional gains beyond Option A. The three biggest pain points (PLY-load friction, empty `embed_url`, 214 MB local transfer) are all solved by Option A — the web-UI layer adds no solution for these core problems, it only adds an alternative presentation (browser instead of terminal).

**Critical finding:** The `embed_view_url: ""` problem (manual cloud share URL) remains open for **all** options (A, B, C) as long as no superspl.at API exists. A full WebUI does not solve this problem. That is the limit Phase 9 must communicate honestly.

**Mobile UX** is the only dimension where B/C would have real added value over A — but B/C do not solve it either, because localhost URLs never work on mobile.

**CC hypothesis:** Option A + a macOS notification is the most efficient move for Phase 9. Option C (+ a minimal capture-browser page) would be a sensible bonus if the goal definition includes "something visual for the workflow overview". Option B should be framed as a Phase-10 candidate once concrete usage-feedback signals (more than 1 person uses the pipeline, more than 10 captures per week) are present.

**If the architect hypothesis favors B:** then plan B should be split into increments — B₁ = Option A (1-2 days, immediately usable), B₂ = capture browser (1-2 days), B₃ = pipeline control in the browser (2-3 days). No big-bang B.
