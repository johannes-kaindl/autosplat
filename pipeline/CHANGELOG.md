# Changelog

Versioning follows the spec's phase model. Releases tag the head commit when a phase's acceptance criteria are met.

Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
This project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [Unreleased]

- **fix(failure):** corrected the SfM failure hint — auto-rescue
  (sequential → exhaustive → bisection) already runs in the pipeline, so the
  hint no longer implies a manual `autosplat rescue` step; it points at the real
  fix (footage overlap). Ships with the next release.

---

## [v1.9.2] — 2026-05-29 — Fix: app launch hang (Homebrew PATH)

### Fixed

- **`AutoSplat.app` hung on launch** (Dock bounced, no window, force-quit needed)
  on a clean machine. A Finder/Dock launch inherits launchd's minimal PATH
  (`/usr/bin:/bin:/usr/sbin:/sbin`), not the shell PATH, so `ffmpeg`/`colmap`
  installed via Homebrew were invisible — `needs_first_run_setup` stayed True and
  `main()` looped forever waiting for tools that detection could never see.
  Startup now prepends `/opt/homebrew/bin` + `/usr/local/bin` to PATH
  (`ensure_homebrew_path`), fixing both detection and the pipeline subprocesses'
  tool lookup.
- `scripts/build_app.sh` retries `create-dmg` (its temp-volume eject loses an
  intermittent Spotlight race).

---

## [v1.9.1] — 2026-05-29 — Brand: marks, favicon, social card, app icon

### Added

- **Brand kit** (`docs/brand`) — generative point-cloud mark system (tokens,
  marks.js, brand kit page) plus a reproducible asset pipeline:
  `docs/brand/render_marks.mjs` ports the orb generator to emit static SVGs and
  `scripts/build_brand_assets.sh` rasterizes them (rsvg-convert / iconutil).
- **WebUI branding** — SVG + PNG favicon, apple-touch-icon, `theme-color`, and an
  Open Graph / Twitter social card (`/static/brand/og.png`) in the page `<head>`.
- **App icon** — `AutoSplat.app` now ships the orb icon (`packaging/AutoSplat.icns`),
  so the Dock/Finder show the brand mark instead of the generic placeholder.

### Changed

- **mypy strict added to the pre-push hooks** (`.pre-commit-config.yaml`) so the
  type-gate can't silently drift again; AGENTS.md updated to match.

---

## [v1.9.0] — 2026-05-29 — Quality pass: actionable blur control + green type-check

### Added

- **`blur_threshold` override on the New-capture form** — an optional numeric
  field applies a per-run `preprocess.blur_threshold` override (via
  `apply_override`), so when a capture fails with "all frames too blurry" you can
  retry with a lower threshold right there, without editing the config file.
- **Fast-fail on too-few frames** — `filter_blurry_frames` now raises
  `TooFewFramesError` when `0 < kept < MIN_USABLE_FRAMES` (3), extending the
  existing kept-0 guard so 1–2 surviving frames also fail clearly instead of via
  a cryptic COLMAP error.

### Changed

- **mypy strict is runnable and green again.** It was documented in AGENTS.md but
  missing from the uv dev group and not in pre-commit, so it had drifted to 66
  errors. Added `mypy` to `[dependency-groups].dev` and fixed every error with
  type annotations / casts only — no behaviour change (`_load_or_die -> Config`,
  typed WebUI route helpers, scoped `ignore_missing_imports` for webview + yaml).

---

## [v1.8.0] — 2026-05-29 — Failure diagnostics

Failed captures now say — prominently — **when** they failed, **why** in plain
language, and **what to do** so it doesn't recur, instead of leaving you to read
a raw COLMAP stderr tail.

### Added

- **`failure.py`** — `classify_failure(reason, stage)` maps a stored failure
  reason to a `FailureInfo{category, headline, hint}` via an ordered rules table
  (blur / SfM-no-overlap / OOM / missing-video / interrupted / generic fallback),
  with an English headline + actionable remediation hint.
  `failure_reason_from_log` recovers a reason from `pipeline.log` for records
  predating this feature.
- **Prominent failure panel** on the capture detail page: ⚠ headline, when
  (stage + failed-at), the verbatim reason, 💡 what-to-do, and Resume / jump-to-log.
- **Failure headline on the captures list** so the cause is visible at a glance
  on every failed row.

### Fixed

- **Durable failed status.** A WebUI job that failed before a restart reverted to
  "idle" because `get_job` only returns live in-memory jobs. `JobRunner.last_run`
  now surfaces the most recent persisted run from `runs.jsonl`, so `list_captures`
  keeps the failed status + reason across restarts — which is what makes the new
  panel appear for real past failures.

### Notes

All UI strings are English; German / i18n is intentionally out of scope (a
separate project — the WebUI has no localization framework).

---

## [v1.7.2] — 2026-05-29 — Blur fast-fail + install fix

### Added

- **Fail fast on all-blurry footage.** `extract_frames` / `extract_frames_from_many`
  now route through `filter_blurry_frames`, which raises a typed
  `AllFramesRejectedError` with an actionable message when frames were extracted
  but every one scored below `blur_threshold`. Previously the run proceeded into
  COLMAP and died with a cryptic "No images with matches". (Surfaced by a real
  4K capture whose Laplacian-variance scores were ~10 against the 100 threshold —
  high bitrate, but genuinely soft footage.)

### Docs

- Install instructions now tell recipients to clear the quarantine flag
  (`xattr -dr com.apple.quarantine /Applications/AutoSplat.app`) rather than the
  unreliable right-click → Open: for an ad-hoc-signed (un-notarized) app, App
  Translocation still blocks the launch with a `-1712` error otherwise.

---

## [v1.7.1] — 2026-05-29 — Classic app window

v1.7.0 shipped the app as a menubar agent (`LSUIElement`) — no Dock icon, no
window, so a double-click looked like nothing happened. v1.7.1 makes it a
classic app: a real **AutoSplat** window (WKWebView via pywebview) shows the
WebUI, with a Dock icon and Cmd-Q to quit. No browser, no menubar.

### Changed

- `desktop.main` now opens a native pywebview window pointed at the local WebUI
  instead of a rumps menubar + external browser. `wait_until_serving` (new,
  tested — condition-based, replaces a fixed sleep) ensures uvicorn is bound
  before the window loads. Falls back to the default browser if pywebview is
  unavailable.
- `Info.plist` drops `LSUIElement` (Dock icon + foreground app). Bundle hidden
  imports + the `app`/`build` dependency groups swap `rumps` → `pywebview`.
- `scripts/build_app.sh` detaches a stale mounted `/Volumes/AutoSplat` before
  cleaning `dist/` (it otherwise held the directory busy).

### Verification

The frozen `.app` launches as a foreground app with a window titled
"AutoSplat" serving the WebUI (confirmed via System Events + healthz). Headless
smoke (`AUTOSPLAT_APP_HEADLESS`) still serves end-to-end.

---

## [v1.7.0] — 2026-05-29 — AutoSplat.app (DMG)

autosplat now ships as a double-clickable macOS app in a `.dmg`. The Python
CLI + WebUI (cv2/uvicorn/FastAPI) are frozen into `AutoSplat.app` with
PyInstaller; the heavy external tools (ffmpeg, COLMAP, Brush) are installed at
first run via the existing Homebrew scripts rather than bundled. Signing and
notarization are optional, env-gated build steps — the app runs unsigned via
right-click → Open, and notarization can be added later once a Developer ID
exists.

### Added

- **`src/autosplat/desktop.py`** — the app launcher. Pure, tested helpers:
  `missing_required_tools` / `needs_first_run_setup` (filter `run_doctor` for
  installable gaps), `build_setup_terminal_command` (osascript that runs
  `install_deps.sh` in Terminal), `pick_free_port`, `serve_url`, `make_server`,
  `open_browser`, `run_first_run_setup`. `main()` serves the WebUI in a thread,
  opens the browser, and shows a `rumps` menubar item (optional import; falls
  back to headless serve). `AUTOSPLAT_APP_HEADLESS` enables curl-able smoke runs.
- **`autosplat app`** CLI command — same launcher from a dev checkout.
- **`packaging/AutoSplat.spec` + `autosplat_app.py`** — PyInstaller bundle
  (templates/static/config/scripts as data; uvicorn/route hidden imports;
  `LSUIElement` menubar agent).
- **`scripts/build_app.sh`** — freeze → `create-dmg` → `dist/AutoSplat.dmg`.
  Signing (`CODESIGN_IDENTITY`) + notarization (`AC_NOTARY_PROFILE`) are
  env-gated; ad-hoc signature otherwise.
- Build deps `pyinstaller` + `rumps` in `[dependency-groups].build` and an
  `[app]` extra.

### Changed

- `config.py` and `webui/app.py` resolve packaged data (default.toml,
  templates, static) via `sys._MEIPASS` when frozen, repo-relative otherwise.

### Verification

Frozen binary serves the WebUI end-to-end (healthz / dashboard / static /
templates all 200). The menubar rendering, Gatekeeper right-click→Open, and the
fresh-Mac first-run setup are human-verified (not automatable).

---

## [v1.6.0] — 2026-05-29 — Live Progress / Mission-Control

The WebUI no longer sits frozen during the long, silent stages. A capture's
progress is now published to a `progress.json` single-source-of-truth and
surfaced live: a moving percent bar, elapsed + ETA-remaining, a pulsing
"updated Xs ago" health dot with a stall warning, and a stage-agnostic
liveness pulse that also covers the silent COLMAP mapper. Real step/PSNR
tiles appear when the plateau monitor is enabled.

Honest about the data: `%`/ETA are wall-time estimates; loss/iter-s/GPU/VRAM
are *not* shown because Brush emits no per-step stdout and exposes no GPU
telemetry — the old all-`—` placeholder card is gone.

### Added

- **`progress.py`** — `ProgressState` dataclass + atomic `write_progress` /
  `read_progress` (`os.replace`, returns `None` on missing/corrupt JSON), the
  single channel between the running pipeline and any reader.
- **`_ProgressWriter`** (`pipeline.py`) — merges the 2 s time heartbeat
  (`tick`) and the slower plateau eval points (`record_eval`) into one
  `progress.json`, so the fast heartbeat never clobbers real step/PSNR.
- **`run_brush(eval_callback=…)`** + `_drain_eval_history` — forward each new
  `(step, psnr)` from the plateau monitor exactly once to the progress writer.
- **`progress_view.build_progress_view`** — pure, clock-injected view model
  (percent, mm:ss elapsed/remaining, `updated_ago_s`, `stalled`).
- **Live `brush_metrics.html`** — moving bar, elapsed/ETA tiles, health dot +
  stall warning, real step/PSNR tiles when present, wrapped in a collapsible
  `<details>` (state persisted in `localStorage`) whose static wrapper lives in
  `detail.html` so collapse survives the 3 s polls.
- **`last_activity_age_s`** + `/partials/capture/{id}/liveness` — stage-agnostic
  "last activity Xs ago" pulse from `pipeline.log` mtime, with a "quiet for Xs"
  warning past 120 s.
- **`brush.stdout.log`** — `_consume_brush_stream` tees every Brush stdout line
  into a dedicated, live-readable log beside the training output.
- **Native Finder file-picker** for the New-capture form — `POST
  /captures/pick-file` runs `osascript choose file` (a browser `<input
  type=file>` can't hand the server an absolute path) and fills the textarea.

### Changed

- Train heartbeat log throttle tightened 300 s → 30 s (the live view reads the
  unthrottled `progress.json`, so the log just needs a fresher trail).
- The brush card is gated to `stage == train`; SfM no longer renders a
  misleading "brush warming up" card.

---

## [v1.5.0] — 2026-05-27 — Train-till-Plateau

Brush trains for `--total-steps` (default 30 000) regardless of whether the splat already converged. v1.5.0 adds an **opt-in patience-stop**: hold out ~10 % of frames, monitor PSNR while training, and SIGTERM Brush when the curve flattens. On a typical converging capture this can save 30-50 % of the Brush stage.

### Added

- **`PlateauMonitor`** in `train.py` — pure-logic class that polls `<output_dir>/eval_<step>/` directories, computes mean PSNR via `compute_eval_psnr`, maintains the `(step, psnr)` history, and decides `should_stop` once the last `patience` consecutive Δ-PSNR values are all below `min_delta_psnr` and the last step is ≥ `min_steps`. Idempotent; missing/in-progress eval dirs are handled gracefully.
- **`compute_eval_psnr(eval_dir, frames_dir)`** — cv2-based mean PSNR across rendered eval images vs originals. Pairs by filename stem so Brush's `<orig>.png` lines up with our `frames/<orig>.jpg`. Originals get downscaled (`cv2.INTER_AREA`) to the render resolution before MSE.
- **Six new `[brush]` config fields**: `plateau_enabled` (bool, default `false`), `plateau_eval_split_every` (2-50, default 10), `plateau_eval_every` (100-10000, default 1000), `plateau_min_steps` (default 5000), `plateau_patience` (1-20, default 3), `plateau_min_delta_psnr` (0 < x ≤ 5, default 0.05). Cross-field validator rejects `plateau_min_steps > max_steps` *only when* the feature is enabled (so a CI-config lowering `max_steps` doesn't have to touch plateau fields).
- **`build_brush_command` extension**: when `plateau_enabled`, appends `--eval-split-every`, `--eval-every`, `--eval-save-to-disk`, and ties `--export-every` to `plateau_eval_every` so every eval checkpoint has a fresh PLY for the SIGTERM-safe stop mechanism.
- **`run_brush` orchestration**: spawns a daemon `PlateauMonitor` thread, polls every 5 s, sends `proc.terminate()` on `should_stop`. The non-zero returncode from our own SIGTERM is recognised and not re-raised as `CalledProcessError`. Edge case: SIGTERM before any export → `RuntimeError` with an actionable hint.

### Discovery (in spec doc)

A 250-step Brush probe against `max_strasse/brush_dataset` confirmed three load-bearing assumptions, all documented in `docs/superpowers/specs/2026-05-27-v15-train-till-plateau-design.md`:

1. **Brush emits no stdout/stderr in subprocess mode** (TUI suppressed) — stdout-PSNR parsing is not viable, hence the filesystem-watch approach.
2. **`--eval-save-to-disk` is reliable** and writes `eval_<step>/<orig_filename>.png`.
3. **`--eval-split-every N` is deterministic** — every Nth frame, sorted by filename.

### Tests

- 13 new unit tests (5 in `test_config.py`, 6 in `test_train.py` for PSNR helper, 6 in `test_train.py` for `PlateauMonitor`, 2 in `test_train.py` for `build_brush_command` branches). All purely synthetic — no Brush invocation, no real-world frames.
- 347 tests passing (up from 328 at v1.4.6), ruff clean, mypy clean on `train.py`.

### UX

In the default config (`plateau_enabled = false`), v1.5.0 changes nothing. Enable via your user config:

```toml
[brush]
plateau_enabled = true
# defaults are fine; tune patience / min_delta_psnr if you want aggressive stops
```

When triggered, `pipeline.log` will contain a `train.plateau_detected` event with the full history of `train.eval` events leading up to the stop. The final scene.ply is whichever export was written most recently before SIGTERM (one per `plateau_eval_every` steps).

### Default-on candidacy

v1.5.0 ships opt-in. After real-world validation on 2-3 captures, a follow-up release will likely flip the default to `true`.

---

## [v1.4.6] — 2026-05-27 — Final Polish

Closes the v1.4 line: small coverage gaps + early-warning UX + repo hygiene, so v1.5 starts from a clean baseline.

### Added

- **Pre-flight viewer-config check** (`cli._warn_if_viewer_misconfigured`). When `[viewer] auto_open=true` + `target="supersplat-local"` but the dist isn't built, the warning fires at the *start* of `process` / `resume` / `add-video` / `rescue` — not after the ~5 h run finishes and the auto-open silently falls back. Doctor still catches the same case independently. 4 unit tests.
- **Test coverage for the v1.4.5 deprecation warning** at `target="supersplat"` (remote). Verifies the `viewer.remote_supersplat_deprecated` logger.warning fires for the remote path and stays silent for the local one. 2 new tests in `test_viewer.py`.

### Removed

- **Orphaned v1.3 hero assets** — `docs/assets/max_strasse_hero.{gif,mp4,webm,jpg}` (≈9 MB). The README has pointed at `max_strasse_autobisect_hero.*` since v1.4.4; the v1.3 originals are still reachable via the `v1.3.0` git tag for historical purposes.

### Fixed

- **v1.4.0 Codeberg release-page body** PATCH'd to remove the stale "no real-world smoke against a non-trivial structurally-failing capture" line — refuted by the v1.4.4 max_strasse end-to-end success (490/493 cams, 5 h 36 min).

### Tests

- 328 tests passing (up from 322 at v1.4.5), ruff clean, mypy clean on the four core modules.

---

## [v1.4.5] — 2026-05-27 — Quality Sweep

Follow-up to the v1.4.0–v1.4.4 burst — non-feature improvements that accumulated during the v1.4 work: code hygiene, observability, disk reclaim, and a docs refresh that catches up with the local-viewer default.

### Added

- **`autosplat cleanup-rescue <capture_dir>`** — reclaim the per-probe `rescue/probes/<clip_id>/` workspaces (typically ~1-3 GB per successful rescue). `--keep-clips/--remove-clips` (default keep, so resume/add-video keep working), `--dry-run` to preview. 4 CliRunner tests.
- **`train.heartbeat` events** in `pipeline.log` every 5 min during Brush training. The ~1-2 h Brush stage previously emitted nothing between `train.brush.start` and `train.done`; non-TTY runs (watch daemon, WebUI, ssh) now have a visible pulse. Pure helper `_make_train_heartbeat_emitter()` so the throttling is unit-tested without a real Brush run (3 tests).
- **Deprecation warning** when `[viewer] target = "supersplat"` (remote). The remote editor is blocked by browsers' Mixed-Content policy (HTTPS page can't fetch HTTP localhost PLY) — the warning points users at the v1.4.4 `supersplat-local` default.

### Changed

- **`cli.serve --with-supersplat` shares `_serve_local_and_block`** with the auto-open path. The helper grew an `open_browser=False` kwarg so `--no-open-browser` still works.

### Fixed

- **All remaining mypy strict noise in `watcher.py` and `viewer.py`** — 18 errors in watcher (untyped `dict`, `bytes|str` event paths, `Observer` not-a-type) + 2 in viewer (`_Handler.__init__/log_message` annotations). The `Observer` issue fixed by typing as `watchdog.observers.api.BaseObserver`; the bytes/str by a tiny `_as_str()` helper. `mypy src/autosplat/viewer.py src/autosplat/watcher.py` is now clean.

### Docs

- **`GETTING-STARTED.md`** Section "Look at the result" rewritten to reflect the v1.4.4 local-viewer default (auto-open at `127.0.0.1:3000`, blocking server with Ctrl-C, `setup_supersplat.sh` as required first-time step).
- **`CONFIGURATION.md` `[viewer]` section** expanded — all five keys listed, the auto-open lifecycle described step-by-step, daemon/WebUI exception noted.
- **`CAPTURE-GUIDE.md`** gains a "Reclaiming disk after a successful rescue" subsection pointing at the new `cleanup-rescue` command.
- **`ARCHITECTURE.md`** gains a "Documentation convention" subsection: v1.4+ uses `docs/superpowers/specs/YYYY-MM-DD-<topic>-design.md` instead of post-hoc `PHASE-N-*.md` reports. Reasons recorded.

### Tests

- 322 tests passing (up from 315 at v1.4.4), ruff clean, mypy clean on the two modules touched.

---

## [v1.4.4] — 2026-05-27 — Local-Viewer Default

After the v1.4.2/v1.4.3 viewer hotfixes, the default `target="supersplat"` (remote editor at playcanvas.com) still produced an empty editor for users on modern browsers: HTTPS pages cannot fetch HTTP localhost resources (Mixed-Content blocking). The user could work around it with `--with-supersplat`; v1.4.4 just makes that the default.

### Changed

- **`[viewer] target` default flipped to `"supersplat-local"`.** When the dist is built (`bash scripts/setup_supersplat.sh` — already part of repo setup), `autosplat process` / `rescue` finish by starting *both* a local SuperSplat HTTP server and a local PLY server, opening `http://127.0.0.1:3000?load=http://127.0.0.1:8765/scene.ply` in the browser, and blocking until Ctrl-C. Everything is HTTP-on-localhost — no mixed-content blocking, no `.ply` download dialog, no manual drag-and-drop.
- **Graceful fallback when the dist is missing.** If `target="supersplat-local"` but `target/supersplat/dist/index.html` doesn't exist, the viewer prints a clear console hint to run the setup script and falls back to a no-op (the existing `autosplat doctor` warning already covers this).

### Added

- `viewer._serve_local_and_block()` — shared helper that wraps `serve_supersplat_local()` + browser-open + signal-handled block. Re-used by the auto-open path; `cli.serve --with-supersplat` keeps its inline equivalent for now.

### Tests

- `test_open_in_viewer_supersplat_local_no_browser` rewritten to assert the **dist-missing fallback** (no browser, hint message).
- New `test_open_in_viewer_supersplat_local_opens_local_servers_when_dist_present` verifies the dist-present path: fake dist with `index.html`, both servers start, browser receives a `http://127.0.0.1:*?load=http://127.0.0.1:*/scene.ply` URL, `stop_event` keeps the test from blocking.
- `test_load_default_config_parses_cleanly` updated to expect the new default target.
- 315 tests passing.

### Real-world validation

First end-to-end smoke against `max_strasse.MP4` — the same 5:35 drone pass that v1.2.0 left at 5/244 cameras and that v1.3.0 only rescued after a manual 4-clip cut. **`autosplat rescue max_strasse.MP4` produced a 2.0 GB scene.ply with 490/493 cameras registered (99.4 %) in 5 h 36 min on M5**, fully automatic. Pipeline trail in the logs:

```
bisection.start            duration_s=335.6
bisection.probe  clip=0    cameras_registered=120  passed=true
bisection.probe  clip=1    cameras_registered=115  passed=true
bisection.combine_start    leaves=[0, 1]
pipeline.adaptive_retry    reason="low_camera_ratio: 0.03 < 0.5"  matcher=sequential
sfm.done                   cams=490  points=368582
quality_gate.passed        ratio=0.9939  matcher=exhaustive
train.done                 duration_s=8398
pipeline.done              duration_s=20168
```

Fly-through: [YouTube](https://www.youtube.com/watch?v=1U-onh-9QNY). Updated hero asset in `docs/assets/max_strasse_autobisect_hero.*`.

---

## [v1.4.3] — 2026-05-27 — `autosplat serve` Browser-Download Hotfix

Follow-up to v1.4.2 — the auto-open path was fixed for `process` / `rescue`, but `autosplat serve` (without `--with-supersplat`) still opened the raw `http://127.0.0.1:8765/scene.ply` URL in the browser. Browsers have no MIME handler for `.ply`, so the result was a download prompt instead of a rendered splat.

### Fixed

- **`autosplat serve` (no `--with-supersplat`) opens the remote SuperSplat editor**, not the raw PLY URL. New `_remote_supersplat_url_for(ply_url)` helper wraps the local PLY URL in `https://playcanvas.com/supersplat/editor?load=<encoded-ply-url>` — the same pattern `viewer.open_in_viewer` uses for `target="supersplat"`. The local PLY server keeps running so the remote editor can fetch the file. `--no-open-browser` still suppresses the browser launch for headless / CI use.

### Tests

- 2 new tests in `test_cli_serve.py` cover URL construction (default port, high port). End-to-end CliRunner tests of the serve loop are intentionally avoided because they involve threading + signals + sockets and add fragility for no extra coverage — the helper is pure.
- 314 tests passing.

---

## [v1.4.2] — 2026-05-27 — Viewer Auto-Open Hotfix

Pre-v1.4.2, `autosplat process` opened SuperSplat in the browser with `?load=http://127.0.0.1:8765/scene.ply` but never actually started a server on port 8765 — SuperSplat tried to fetch, silently failed, and the editor opened blank. Drag-and-drop the file manually was the only workaround. The pattern existed since the earliest CLI but was first surfaced by the real-world v1.4.0 max_strasse rescue run (5 h 36 min total, 490/493 cams = 99.4 %, then SuperSplat opened empty).

### Fixed

- **`viewer.open_in_viewer` now actually serves the PLY.** For remote targets (`supersplat` / `playcanvas`) the function wraps `serve_directory()` around the browser-open and blocks on a `threading.Event` that a SIGINT/SIGTERM handler sets — so the local HTTP server stays up as long as the user wants to look at the splat, then shuts down cleanly when they press Ctrl-C. Console prints the viewer URL + PLY URL upfront so the user knows what's running.

### Changed

- **`pipeline.run_pipeline` no longer calls the viewer.** Blocking inside the pipeline orchestrator would stall the watch-folder daemon between captures and prevent the WebUI's JobRunner from marking jobs done. CLI commands (`process`, `resume`, `add-video`, `rescue`) now invoke a new `_open_viewer_if_configured()` helper *after* their Done summary, so the user sees the result first and then learns the server URL. Daemon and WebUI already had the same broken viewer path — removing it there is a no-op for users (it was never opening anything anyway).

### Tests

- 2 new end-to-end viewer tests: one verifies `serve_directory` is actually called inside `open_in_viewer`; the other fetches the PLY over HTTP from the running server to prove the bytes are reachable.
- `test_cli_rescue` gets `test_rescue_invokes_viewer_after_done` verifying the wiring at the CLI layer.
- Removed three obsolete `patch("autosplat.pipeline.viewer_mod.open_in_viewer")` in `test_pipeline` (the attribute no longer exists).
- 311 tests passing, ruff clean, mypy clean on viewer.py + pipeline.py.

### UX note

`autosplat process video.mp4` now blocks at the very end with a console message:

```
Viewer: https://playcanvas.com/supersplat/editor?load=…
Serving PLY at http://127.0.0.1:8765/scene.ply. Press Ctrl-C when finished to stop the local server.
```

To opt out — e.g. for CI runs or when SuperSplat is started manually — set `[viewer] auto_open = false` or `[viewer] target = "none"` in the config.

---

## [v1.4.1] — 2026-05-26 — Bisection Polish

Follow-up to v1.4.0 — a probe-performance cap, a manual `rescue` CLI command, per-clip progress visibility in the WebUI, and an optional smart-split at the motion peak. Plus the pre-existing `dict | None` mypy noise in `pipeline.py` is finally cleared.

### Added

- **`autosplat rescue <video | capture_dir>`** — manual trigger for the bisection path. Bypasses sequential/exhaustive matching when you already know a video is structurally hostile. Two modes (fresh-video / existing-capture); multi-video captures need an explicit `--video` because bisection is single-video only. 5 CliRunner tests cover both modes plus the rejection branches.
- **Probe-stage `target_frames` cap** — new `[retry] bisect_probe_target_frames` config (default 120, range 30-1000). Exhaustive matcher cost scales as n²/2, so the override cuts probe-stage compute by ~4× compared to the pipeline-wide default of 250. Applied automatically inside `probe_clip` alongside the existing matcher=exhaustive override.
- **WebUI per-clip bisection progress** — `WatcherState.InProgress.detail` (optional, backwards-compat), `update_stage(stage, detail)` API, end-to-end propagation through `webui.state.list_captures` and the dashboard's active-job line: *"Active job · bisect · probing clip 0_1 (depth 2/3)"*. Stage transitions reset the detail; legacy state.json without the field still loads cleanly.
- **Smart-split at motion peak** — opt-in `[retry] bisect_smart_split` (default `false`). When enabled, `find_motion_peak` samples 30 frames per cut range, runs dense Farneback optical flow (downsampled to 320 px wide for speed), and places the cut at the strongest motion event instead of at the midpoint. Output is clamped to `[min_clip_s, duration - min_clip_s]` so a peak near an edge can't produce a sub-min sub-clip. Falls back to midpoint cleanly when OpenCV can't open the file or the motion signal is too flat (<10 % peak-to-trough ratio).

### Fixed

- **`bisect_recursively` per-branch ffmpeg resilience** *(from the late-v1.4 fix sweep)* — `cut_video` raising `subprocess.CalledProcessError` on a corrupt sub-range is now caught, logged as `bisection.cut_aborted_branch`, and treated as a failed probe; the sibling branch still runs.
- **`read_source_video_from_log` now returns the most recent `pipeline.start`** *(from the late-v1.4 fix sweep)* — after bisection appends a fresh `pipeline.start` with the leaf-clip list, `autosplat resume` and `autosplat add-video` on a bisected capture see the current state instead of silently re-feeding the original failed input.
- **`run_pipeline` / `run_pipeline_with_adaptive_retry` dict type-args** — pre-existing mypy strict findings (lines 143 and 493, both `dict | None`) finally typed as `dict[str, Any] | None`. `mypy src/autosplat/{pipeline,bisection}.py` is now clean.

### Tests

- 22 new tests across `test_bisection.py` (smart-split + probe-perf + per-clip-state), `test_pipeline.py` (multi-`pipeline.start` reader), `test_watcher.py` (InProgress.detail), `test_cli_rescue.py` (the new command), and `tests/webui/test_captures.py` (detail propagation). Total **310 unit tests passing** (`uv run pytest -q`), up from 291 in v1.4.0.

### Docs

- README status line, mermaid, and release table updated to reflect v1.4.1.
- CAPTURE-GUIDE, CONFIGURATION, TROUBLESHOOTING already covered the bisection path; nothing new needed there for this point release.

---

## [v1.4.0] — 2026-05-26 — Auto-Bisection-Rescue

When `sequential → exhaustive` adaptive-retry exhausts itself (`retry_hint=None`), the pipeline now automatically binary-subdivides the source video, probes each leaf clip with a cheap preprocess+SfM-only run, and combines the surviving leaves through the existing multi-video path. Automates the manual 4-clip workflow that rescued `max_strasse` in v1.3.0 — no new command, no new flag, just a longer run when the matcher swap isn't enough.

### Added

- **Auto-bisection-rescue** — third escalation in `run_pipeline_with_adaptive_retry`, gated on `retry_hint=None`, single-video input, and `cfg.retry.bisect_enabled` (default `true`).
- **New module `src/autosplat/bisection.py`** — `BisectionClip` frozen dataclass, `build_ffmpeg_cut_command` + `cut_video` (stream-copy, no re-encode), `probe_clip` (forces `colmap.matcher=exhaustive` because sequential is unreliable on shorts), `bisect_recursively` (DFS halt-on-success-per-branch), and `rescue_via_bisection` orchestrator.
- **Three new `[retry]` config fields** with conservative defaults: `bisect_enabled=true`, `bisect_min_clip_s=60.0` (range 10–600), `bisect_max_depth=3` (range 1–6 — depth 3 = ≤ 8 leaves). Disable `bisect_enabled` for fast-fail in CI.
- **Bisection artefacts persist** under `<capture_dir>/rescue/clips/<stem>_part_<clip_id>.mp4` (physical sub-clips) and `<capture_dir>/rescue/probes/<clip_id>/{frames,colmap}` (per-clip SfM workspace) so a partial run is debuggable. `clip_id` is depth-encoded (`0`, `0_1`, `0_1_0`) — leading digit is the first/second half, deeper underscores trace each recursion step.
- **20 new tests** in `tests/test_bisection.py` + 4 in `tests/test_pipeline.py`. Two opt-in real-binary integration tests sit behind `AUTOSPLAT_BISECTION_E2E=1` plus the existing `needs_ffmpeg` / `needs_colmap` markers. Total 293 unit tests passing (`uv run pytest -q`, up from 265 in v1.3.0).
- **Docs:** `CAPTURE-GUIDE.md` gains an "Auto-bisection internals (v1.4+)" section with the rescue/ layout and `clip_id` semantics; `CONFIGURATION.md` `[retry]` table grows three rows; `TROUBLESHOOTING.md` replaces the old "if exhaustive also fails, you're stuck" branch with the actual escalation path and structured log events to watch for.

### Fixed

- **`bisect_recursively` per-branch ffmpeg resilience** — `cut_video` raising `subprocess.CalledProcessError` on a corrupt sub-range (broken keyframe, container quirk) is now caught, logged as `bisection.cut_aborted_branch`, and treated as a failed probe; the sibling branch still runs. Previously the whole rescue would abort with a raw `CalledProcessError`.
- **`read_source_video_from_log` now returns the most recent `pipeline.start`** — after bisection appends a fresh `pipeline.start` with the leaf-clip list, `autosplat resume` and `autosplat add-video` on a bisected capture see the current state (the leaves) instead of silently re-feeding the original failed input. Pre-v1.4 captures with only one start event behave identically.

### Design Notes

- **Why a separate module?** `pipeline.py` was already 600 LOC; bisection's ~330 LOC of recursion + ffmpeg-cut + probe logic gets isolated in `bisection.py` and exposes only the orchestrator to `pipeline.py`. Each unit is testable without the others (the recursion is monkeypatch-friendly via the `_probe_fn` injection point).
- **Why no WebUI per-clip progress in v1.4?** Bisection runs inside the existing `sfm` stage from the state-machine's perspective; events surface via structured logs only. A WebUI `bisect_probe` stage with per-clip progress is a v1.4.1 candidate.
- **Why no standalone `autosplat rescue` command?** The user-chosen trigger is the auto-escalation path — a normal `autosplat process …` just keeps running. A standalone command can be added in v1.4.1 if the auto-path proves clumsy.
- **Why no smart-split?** Midpoint binary cuts are the v1.4 strategy. Smart-split at motion-change (OpenCV optical flow) is a v1.4.1 candidate and would only help when the rotation event is concentrated rather than smeared across the clip.

### Known Issues

- **Probe-stage compute cost.** Each probe runs with `cfg.preprocess.target_frames` (default 250) and exhaustive matcher — roughly `n²/2 ≈ 31k` pair-matches per probe. At depth 3 with 8 leaves, worst-case probe cost is ~30 min to a few hours before the final combined Brush run. A `probe_target_frames` cap is a v1.4.1 candidate. Set `bisect_enabled=false` in CI budgets that can't absorb this.
- **No real-world smoke against a non-trivial structurally-failing capture has shipped with this release.** The integration tests use the tiny `tests/fixtures/tiny_video.mp4` fixture (passes a quality-gate sanity check but isn't a real failing case). v1.4.1 is expected to absorb the first real-world run feedback.

---

## [Earlier — pre-v1.4.0 work, previously under [Unreleased]]

### Added
- Repository documentation refresh: README brought up to v1.3.0 (badges, release table, CLI/WebUI sections, mermaid, test counts), CONTRIBUTING expanded with pre-commit/ruff/mypy setup, `SECURITY.md`, `CITATION.cff`, `.editorconfig`.

### Fixed
- Codeberg release pages: missing release notes published for `v1.1.0` and `v1.2.0`; the previously misfiled `v1.1.1` release (which pointed at tag `1.1.0`) was reattached to the correct `v1.1.1` tag.

### Removed
- Legacy non-prefixed tags `1.1.0` and `1.1.2` deleted from the Codeberg remote (duplicates of `v1.1.0` and `v1.1.2`); all release tags now follow the `vX.Y.Z` convention.

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
