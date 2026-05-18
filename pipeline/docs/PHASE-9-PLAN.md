# PHASE-9-PLAN — Local SuperSplat Auto-Open (Option A)

*Plan-build burst 2026-05-14 · Status: **Decision-Gate** · Author: CC-Executor*
*Basis: `docs/PHASE-9-RECON.md`, commit `889c333`*

---

## § 1 — Context + Relation to the Recon

The load-bearing finding from the recon: `viewer.py` has had a silent bug since Phase 1 — it builds URLs of the form `https://playcanvas.com/supersplat/editor?load=http://127.0.0.1:8765/scene.ply`, which never worked in the browser because of mixed-content blocking (an HTTPS page cannot fetch an HTTP resource on localhost). PLY therefore always had to be loaded manually via drag-and-drop. Additionally, no HTTP server starts for the PLY file — `open_in_viewer` only builds the URL and opens the browser, without ever serving the file.

Option A solves both problems with a locally built SuperSplat instance (`http://localhost:3000`): same scheme + host as the PLY server → no CORS/mixed-content. SuperSplat is MIT, builds cleanly with Node.js+Rollup, and supports `?load=URL` natively.

**Explicit Out of Scope for Phase 9:** cloud share URL automation (`embed_view_url` stays manual), capture browser UI, mobile support, full WebUI, iframe fallback templating, preview screenshot generation.

---

## § 2 — Sub-Phase Architecture

### Sub-Phase 9.1 — Config Extension + URL-Builder Fix
*~0.5 day — no external dependencies, pure Python changes*

**Scope:** New `target` value `"supersplat-local"`, new config fields, correct URL builder.

**Commits:**
1. `feat(phase-9.1): ViewerConfig — supersplat-local target + supersplat_local_port + dist_path`
2. `feat(phase-9.1): viewer.py — URL-builder for supersplat-local; localhost instead of 127.0.0.1`
3. `test(phase-9.1): viewer URL-builder-Tests (supersplat-local, remote, playcanvas)`

**Tags:** `autosplat-pre-phase-9.1-config-url` → `autosplat-post-phase-9.1-config-url`

**Concrete code changes:**

`config.py` → `ViewerConfig`:
```python
# New fields:
supersplat_local_port: int = Field(default=3000, ge=1024, le=65535,
    description="Port for locally-built SuperSplat dev server.")
supersplat_dist_path: Path = Field(default=Path("target/supersplat/dist"),
    description="Path to built SuperSplat dist/ directory.")
# extend target:
target: Literal["supersplat", "supersplat-local", "playcanvas", "none"]
```

`config/default.toml` → `[viewer]`:
```toml
supersplat_local_port = 3000
supersplat_dist_path = "target/supersplat/dist"
```

`viewer.py` → `_build_viewer_url`:
- `"supersplat-local"` → `f"http://localhost:{supersplat_port}?load=http://localhost:{ply_port}/{ply_name}"`
- `"supersplat"` → still remote URL (for users without a local build)
- `serve_directory` binding: `"127.0.0.1"` stays for security; URL to the browser: `localhost` instead of `127.0.0.1`

`viewer.py` → `open_in_viewer` for `supersplat-local`:
- No inline `webbrowser.open()` (no server runs after pipeline exit)
- Logs `INFO viewer.local_hint`: `"Run: autosplat serve <output_dir> --with-supersplat"`

**DoD 9.1:**
- [ ] `target = "supersplat-local"` is a valid Pydantic value, config loads without error
- [ ] `_build_viewer_url("supersplat-local", "scene.ply", ply_port=8765, ss_port=3000)` → `"http://localhost:3000?load=http://localhost:8765/scene.ply"`
- [ ] `open_in_viewer` for `supersplat-local` opens no browser, logs hint
- [ ] All tests green (≥ 122 total)

**Test adds 9.1: ~6**
- URL builder: supersplat-local, supersplat-remote, playcanvas, none
- `open_in_viewer` with `target="supersplat-local"` → no `webbrowser.open`, hint logged
- Config roundtrip: `supersplat_local_port` + `supersplat_dist_path` from TOML

---

### Sub-Phase 9.2 — SuperSplat Setup Script + Doctor
*~0.5 day — requires Node.js/npm on the system*

**Scope:** Reproducible build script, doctor check for the local SuperSplat dist.

**Commits:**
1. `feat(phase-9.2): scripts/setup_supersplat.sh — clone, npm ci, npm run build, verify`
2. `feat(phase-9.2): doctor — supersplat-dist check (required=False, WARN if missing)`
3. `test(phase-9.2): doctor supersplat-check — OK + WARN + target≠supersplat-local → skip`

**Tags:** `autosplat-pre-phase-9.2-setup-doctor` → `autosplat-post-phase-9.2-setup-doctor`

**`scripts/setup_supersplat.sh` — design:**
```bash
#!/usr/bin/env bash
set -euo pipefail

SUPERSPLAT_REPO="https://github.com/playcanvas/supersplat"
SUPERSPLAT_PIN="main"          # pin to a known-good commit after first success
DEST="${REPO_ROOT}/target/supersplat"

# Precondition: node + npm
command -v node >/dev/null 2>&1 || { echo "ERROR: node not found. Install: brew install node"; exit 1; }
command -v npm  >/dev/null 2>&1 || { echo "ERROR: npm not found";  exit 1; }

# Clone or update
if [ -d "$DEST/.git" ]; then
  git -C "$DEST" fetch --quiet && git -C "$DEST" checkout "$SUPERSPLAT_PIN"
else
  git clone --depth 1 --branch "$SUPERSPLAT_PIN" "$SUPERSPLAT_REPO" "$DEST"
fi

cd "$DEST"
npm ci --prefer-offline --loglevel=warn
npm run build

# Verify
[ -f "$DEST/dist/index.html" ] || { echo "ERROR: dist/index.html missing after build"; exit 1; }
echo "SuperSplat built → $DEST/dist/"
```

**Doctor integration:**
```python
def _check_supersplat(config: Config) -> CheckResult | None:
    if config.viewer.target != "supersplat-local":
        return None   # Skip — not relevant for remote-only setup
    dist_index = config.viewer.supersplat_dist_path / "index.html"
    if dist_index.exists():
        return CheckResult(name="supersplat", ok=True,
            detail=f"dist at {dist_index.parent}", required=False)
    return CheckResult(name="supersplat", ok=False, required=False,
        detail=f"dist missing at {dist_index.parent} — run scripts/setup_supersplat.sh")
```
→ `run_doctor()` calls `_check_supersplat`, filters out `None`.

**DoD 9.2:**
- [ ] `bash scripts/setup_supersplat.sh` runs through, `target/supersplat/dist/index.html` exists
- [ ] `autosplat doctor` shows `supersplat WARN` when dist is missing (only when target=supersplat-local)
- [ ] `autosplat doctor` shows `supersplat OK` after setup
- [ ] All tests green (≥ 125 total)

**Gate-1 (manual, before 9.3):**
> Jay runs: `bash scripts/setup_supersplat.sh`
> Then: `python -m http.server 3000 --directory target/supersplat/dist &` and `open http://localhost:3000`
> Expectation: SuperSplat opens in the browser, shows the UI (no splat loaded — drag-and-drop still needed).
> Gate passes when SuperSplat loads. STOP on build error or blank page → report finding to Cowork.

**Test adds 9.2: ~3**
- Doctor check: dist present → OK
- Doctor check: dist missing + target=supersplat-local → WARN
- Doctor check: target=supersplat (remote) → no supersplat check in output

---

### Sub-Phase 9.3 — `autosplat serve` CLI Command
*~1 day — process management, graceful shutdown, subprocess control*

**Scope:** New CLI command that starts the PLY server + SuperSplat server, opens the browser, blocks until Ctrl+C.

**Commits:**
1. `feat(phase-9.3): viewer.py — serve_supersplat_local context manager`
2. `feat(phase-9.3): cli.py — serve command mit --with-supersplat, --ply-port, --no-open-browser`
3. `test(phase-9.3): serve-command lifecycle — beide Server starten, shutdown auf signal`

**Tags:** `autosplat-pre-phase-9.3-serve-cmd` → `autosplat-post-phase-9.3-serve-cmd`

**`viewer.py` — new context manager:**
```python
@contextmanager
def serve_supersplat_local(
    supersplat_dist: Path,
    supersplat_port: int,
    ply_dir: Path,
    ply_port: int,
) -> Iterator[dict[str, str]]:
    """Start both servers. Yields dict with supersplat_url + ply_url."""
    with serve_directory(supersplat_dist, supersplat_port) as ss_base:
        with serve_directory(ply_dir, ply_port) as ply_base:
            yield {"supersplat": ss_base, "ply": ply_base}
```

**`cli.py` — new command:**
```python
@app.command()
def serve(
    capture_dir: Path = typer.Argument(..., help="Directory containing scene.ply."),
    with_supersplat: bool = typer.Option(False, "--with-supersplat"),
    ply_port: int | None = typer.Option(None, "--ply-port"),
    supersplat_port: int | None = typer.Option(None, "--supersplat-port"),
    no_open_browser: bool = typer.Option(False, "--no-open-browser"),
    config: Path | None = typer.Option(None, "--config", "-c"),
) -> None:
    cfg = _load_or_die(config)
    ply_file = _find_ply(capture_dir)     # looks for scene.ply in capture_dir or capture_dir/output/
    effective_ply_port = ply_port or cfg.viewer.local_http_port
    effective_ss_port  = supersplat_port or cfg.viewer.supersplat_local_port
    ...
    # Blocks until Ctrl+C (signal.pause() or threading.Event.wait())
```

**`_find_ply(capture_dir)` logic:**
1. `capture_dir/scene.ply` → directly
2. `capture_dir/output/scene.ply` → in outputs subdir
3. First `*.ply` in `capture_dir` → fallback
4. No PLY → exit with error message

**Graceful shutdown:**
```python
import signal
stop_event = threading.Event()
signal.signal(signal.SIGINT,  lambda *_: stop_event.set())
signal.signal(signal.SIGTERM, lambda *_: stop_event.set())
# ...
with serve_supersplat_local(...) as urls:
    if not no_open_browser:
        ply_name = ply_file.name
        browser_url = f"{urls['supersplat']}?load={urls['ply']}/{ply_name}"
        webbrowser.open(browser_url)
    print(f"Serving. Press Ctrl+C to stop.")
    stop_event.wait()   # blocks here
```

**Port conflict (STOP trigger):**
`socketserver.ThreadingTCPServer` raises `OSError: [Errno 48] Address already in use` → exception propagates as exit code `EXIT_USER_ERROR` with message `"Port {port} already in use — use --ply-port / --supersplat-port to override"`.

**DoD 9.3:**
- [ ] `autosplat serve /path/to/capture --with-supersplat` → browser opens, PLY loads automatically (no drag-and-drop)
- [ ] Ctrl+C → both servers shut down, process exits cleanly
- [ ] Port conflict → clear error message, exit 1
- [ ] Smoke: manual test by Jay with the burgstall PLY
- [ ] All tests green (≥ 131 total)

**Test adds 9.3: ~6**
- `serve_supersplat_local`: both servers start, correct yield, shutdown
- `_find_ply`: direct path / output subdir / fallback / no PLY
- `serve` CLI: port conflict exit, `--no-open-browser` suppresses `webbrowser.open`

---

### Sub-Phase 9.4 — embed_url Auto-Fill After Pipeline Run
*~0.5 day — pipeline.py + obsidian.py, no new modules*

**Scope:** After successful training + export: automatically write `embed_url` with the localhost URL into the Obsidian note.

**Commits:**
1. `feat(phase-9.4): pipeline.py — build embed_url for supersplat-local target`
2. `test(phase-9.4): embed_url Auto-Fill — supersplat-local target, user-override preserved, remote target → None`

**Tags:** `autosplat-pre-phase-9.4-embed-url` → `autosplat-post-phase-9.4-embed-url`

**`pipeline.py` — change in `run_pipeline`:**
```python
# After export_capture, before obsidian.write_capture_note:
embed_url: str | None = None
if (
    config.obsidian.enabled
    and config.viewer.target == "supersplat-local"
):
    ply_name = exp.output_ply.name   # "scene.ply"
    embed_url = (
        f"http://localhost:{config.viewer.supersplat_local_port}"
        f"?load=http://localhost:{config.viewer.local_http_port}/{ply_name}"
    )

note_data = obsidian_mod.CaptureNoteData(
    ...
    embed_url=embed_url,   # was implicitly None until now
    ...
)
```

**Merge policy (already correct since Phase 8):**
`embed_url` is in `_COWORK_GENERATED_BUT_USER_OVERRIDABLE` → if the user has manually entered a superspl.at URL, it is preserved on re-run. No further code needed.

**Example result in the Obsidian note:**
```yaml
embed_url: "http://localhost:3000?load=http://localhost:8765/scene.ply"
```

**Gate-2 (manual, after 9.4):**
> Jay runs `autosplat process <video>`, opens the generated note.
> Expected: `embed_url` is set (not empty), the auto block shows `<iframe src="http://localhost:3000?load=...">`.
> With `autosplat serve <capture_dir> --with-supersplat` running: the iframe renders the splat in Obsidian reading mode.
> STOP if embed_url stays empty → report finding to Cowork.

**DoD 9.4:**
- [ ] `embed_url` is automatically set after a pipeline run (not `""`)
- [ ] Re-run on an existing note with a user-entered superspl.at URL: URL is preserved
- [ ] `target = "supersplat"` (remote) → `embed_url = None` (no local path)
- [ ] All tests green (≥ 135 total)

**Test adds 9.4: ~4**
- `embed_url` built correctly for supersplat-local target
- `embed_url = None` when target=supersplat (remote)
- Merge policy: user-override URL is preserved on re-run
- Pipeline integration: embed_url flows into `CaptureNoteData`

---

### Sub-Phase 9.5 — macOS Notification After Training Ends
*~0.5 day — new module, opt-in, isolated*

**Scope:** After successful Brush training: a macOS Notification Center message.

**Commits:**
1. `feat(phase-9.5): notification.py — osascript notify_training_complete, graceful no-op`
2. `feat(phase-9.5): config.py + default.toml — notify_on_complete (default false)`
3. `feat(phase-9.5): pipeline.py — call notify nach train stage`
4. `test(phase-9.5): notify — mock subprocess, non-macOS no-op, graceful failure`

**Tags:** `autosplat-pre-phase-9.5-notification` → `autosplat-post-phase-9.5-notification`

**`src/autosplat/notification.py`:**
```python
import platform, subprocess
from .logging import get_logger
logger = get_logger(__name__)

def notify_training_complete(
    capture_name: str, duration_s: float, gaussians: int
) -> None:
    if platform.system() != "Darwin":
        return
    mins = int(duration_s // 60)
    secs = int(duration_s % 60)
    duration_str = f"{mins}m {secs}s" if mins else f"{secs}s"
    msg = f"{capture_name} — {gaussians:,} Gaussians in {duration_str}"
    title = "autosplat: Training complete"
    script = f'display notification "{msg}" with title "{title}"'
    try:
        subprocess.run(["osascript", "-e", script],
                       capture_output=True, timeout=5, check=False)
    except Exception as exc:
        logger.debug("notification.failed", error=str(exc))
```

**`config.py` — `ViewerConfig` extension (or a new `[notifications]` block):**
```toml
[viewer]
notify_on_complete = false   # macOS Notification nach Training. Opt-in.
```

**`pipeline.py` — placement:**
```python
# After train_mod.run_brush(...), BEFORE export:
if getattr(config.viewer, "notify_on_complete", False):
    from . import notification as notif_mod
    notif_mod.notify_training_complete(
        capture_name=_make_capture_name(video_path),
        duration_s=training_duration,
        gaussians=0,   # not yet known — PLY not parsed; or omit until after export
    )
```

*Note: the Gaussian count comes from the PLY header (Phase 4 `read_ply_header`), which is only known after export. For the Phase 9 notification: either estimate it from the `train.py` progress parser, or leave it at 0/None and show the message without Gaussians. The core goal is placing the notification AFTER training.*

**DoD 9.5:**
- [ ] `notify_on_complete = true` in config → macOS notification appears after training ends
- [ ] Default `false` → no notification
- [ ] Non-macOS → silent no-op
- [ ] `osascript` error → debug log, no pipeline crash
- [ ] All tests green (≥ 139 total)

**Test adds 9.5: ~4**
- `notify_training_complete` calls `osascript` with the correct argument
- Non-macOS (mock `platform.system()` → "Linux") → no subprocess call
- `subprocess.run` raises an exception → no crash, debug log
- `config.viewer.notify_on_complete = false` → pipeline does not call notify

---

## § 3 — Test Strategy

| Sub-Phase | Test classes | Coverage focus | Smoke |
|---|---|---|---|
| 9.1 | Unit (URL builder, config parsing) | All target variants, localhost vs. 127.0.0.1, config defaults | Load TOML config with the new fields |
| 9.2 | Unit (doctor check) | dist present/missing, target check | `bash scripts/setup_supersplat.sh` → check dist |
| 9.3 | Unit (process lifecycle, _find_ply, port error) | Server start/stop, URL building, fallback PLY lookup | Manual: `autosplat serve <dir> --with-supersplat` |
| 9.4 | Unit (embed_url build, merge policy) | supersplat-local → URL correct; remote → None; user override | `autosplat process <video>` → check note content |
| 9.5 | Unit (osascript mock, platform mock) | Happy path, non-macOS, exception | Manual: notification appears after training |

**Test count estimate:**
- 9.1: +6 tests
- 9.2: +3 tests
- 9.3: +6 tests
- 9.4: +4 tests
- 9.5: +4 tests
- **Total new: ~23 tests → Phase-9 post-total: ~139** (currently 116)

---

## § 4 — STOP Triggers

| Trigger | Condition | Action |
|---|---|---|
| **Node.js/npm missing** | `setup_supersplat.sh` fails at `command -v node` | STOP. Report finding: "Node.js not installed. Options: (a) `brew install node`, (b) keep using target=supersplat (remote)". No auto-install — external dep, Jay decides. |
| **SuperSplat build error** | `npm run build` fails (Rollup error, TypeScript error) | STOP. Report the build log. Possible cause: SuperSplat `main` has a breaking change. Fix: set `SUPERSPLAT_PIN` to the last known-good commit. |
| **Port already in use** | `:3000` or `:8765` in use | Not a STOP — port is configurable via `--supersplat-port` / `--ply-port`. Clear error message + pointer to the override flags. No auto port scan (too magic). |
| **`?load=` takes no URL** | If a SuperSplat update removes the parameter | STOP. Plan assumption falsified. Solution: test after the local build, fall back to opening the PLY via a file-input dialog (document a post-9 workaround). |
| **Gate-1 fails (SuperSplat does not load)** | Blank page or JS error after setup | STOP before 9.3. Investigate: is the MIME type for `.js` files correct? `http.server` vs. dev server? Possibly `npm run serve` instead of static serving. |
| **Gate-2 fails (embed_url empty)** | Note shows `embed_url: ""` after a pipeline run | STOP before 9.5. Check the pipeline log for `obsidian.enabled=true` and `target=supersplat-local`. |

---

## § 5 — Rollback Path

**Tag convention (annotated, local-only):**

```
autosplat-pre-phase-9-recon         ← set, HEAD: 29f81f3
autosplat-post-phase-9-recon        ← set, HEAD: 889c333
autosplat-pre-phase-9-plan          ← set, HEAD: 889c333 (this burst)
autosplat-post-phase-9-plan         ← set after commit

autosplat-pre-phase-9.1-config-url  ← before Sub-Phase 9.1
autosplat-post-phase-9.1-config-url ← after Sub-Phase 9.1

autosplat-pre-phase-9.2-setup-doctor
autosplat-post-phase-9.2-setup-doctor

autosplat-pre-phase-9.3-serve-cmd
autosplat-post-phase-9.3-serve-cmd

autosplat-pre-phase-9.4-embed-url
autosplat-post-phase-9.4-embed-url

autosplat-pre-phase-9.5-notification
autosplat-post-phase-9.5-notification
```

**Rollback command:**
```bash
git reset --hard autosplat-pre-phase-9.X-<slug>^{}
```

`^{}` dereferences the annotated tag to the commit. `--hard` discards working-tree changes — always check the pre-tag first.

---

## § 6 — DoD per Sub-Phase (Overview)

| Sub-Phase | Unit tests green | Smoke | Manual Jay |
|---|---|---|---|
| **9.1** | ≥ 122 | `uv run autosplat config show` shows supersplat-local fields | — |
| **9.2** | ≥ 125 | `bash scripts/setup_supersplat.sh` → `dist/index.html` exists | **Gate-1:** `open http://localhost:3000` → SuperSplat loads |
| **9.3** | ≥ 131 | `uv run autosplat serve <dir> --no-open-browser` → curl :8765 + :3000 reachable, Ctrl+C clean | **Smoke by Jay:** PLY loads automatically, no drag-and-drop |
| **9.4** | ≥ 135 | `autosplat process <tiny_video>` → note file contains `embed_url: "http://localhost..."` | **Gate-2:** open note in Obsidian, iframe visible with the server running |
| **9.5** | ≥ 139 | `notify_on_complete = true` in config + mini pipeline run → notification | Manual: notification appears after a real training run |

---

## § 7 — Out-of-Scope (Phase 9)

Clearly delimited — **do not implement**, even if it seems "quick":

- Cloud share URL automation (filling `embed_view_url` manually stays the default)
- Capture browser UI (Obsidian Bases are sufficient)
- Mobile support (localhost URLs do not work on iOS/Android)
- iframe fallback templating for offline/mobile (Phase 10)
- Preview screenshot generation (Phase 10)
- `autosplat serve` without an explicit capture_dir (auto-latest detection, Phase 10)
- Multi-capture concurrent view
- SuperSplat cleanup automation (manual by definition)
- WebUI (Option B/C: dropped until usage volume rises)

---

## § 8 — Relation to the Concept Paper

**§5.2 Structural fragmentation** (3 tools → 2 tools):
Before: CLI pipeline → *manually open browser + navigate* → *manual drag-and-drop* → SuperSplat editor → *manual cloud upload* → *manually copy URL + enter it into the note*.
After Phase 9: CLI pipeline → `autosplat serve <dir> --with-supersplat` → SuperSplat with the PLY auto-loaded (cleanup stays manual). `embed_url` is automatically in the note.
Remaining manual steps: SuperSplat cleanup + cloud upload for mobile (both intentionally manual).

**§5.2 Tool/skill sprawl — Node.js as a new dep:**
Trade-off accepted deliberately: `node` + `npm` become a system prerequisite for the `supersplat-local` target. Counterweight: permanently offline-capable, no PlayCanvas cloud account, a 214 MB PLY loads from localhost without network transfer. ROI is rational. The setup script makes the one-time effort transparent.

---

## § 9 — Decision Gates Within the Implementation

**Gate-1 (after Sub-Phase 9.2, before 9.3):**

> **Checkpoint:** Jay runs manually:
> ```bash
> bash scripts/setup_supersplat.sh
> python -m http.server 3000 --directory target/supersplat/dist &
> open http://localhost:3000
> ```
> **Expectation:** the SuperSplat UI loads in the browser (empty canvas, no splat). Drag-and-drop of a small PLY (bench_chill) works.
> **GO:** SuperSplat UI visible → start 9.3.
> **STOP:** blank page, JS error, MIME-type problems → report finding to Cowork before 9.3.

**Gate-2 (after Sub-Phase 9.4, before 9.5):**

> **Checkpoint:** Jay runs:
> ```bash
> autosplat process <video_path>   # or autosplat process with an already-existing capture + skip-stages
> ```
> Opens the generated note in Obsidian. With `autosplat serve <output_dir> --with-supersplat` running: the iframe renders the splat.
> **GO:** embed works, embed_url is correct → start 9.5.
> **STOP:** iframe empty, embed_url empty or wrong → report finding to Cowork.

---

## Appendix — Sequence Diagram (step-by-step flow after Phase 9)

```
autosplat watch ~/inbox
    └── [Video dropped]
        └── run_pipeline(video)
            ├── preprocess → sfm → quality → train
            │       └── [50+ min for burgstall]
            │           └── notify_training_complete("burgstall", 3001s) → macOS Notification
            ├── export → scene.ply @ ~/AutoSplat/outputs/burgstall/scene.ply
            └── obsidian.write_capture_note(embed_url="http://localhost:3000?load=...")
                    └── burgstall.md has embed_url filled in automatically

# Separate review session (any time afterwards):
autosplat serve ~/AutoSplat/outputs/burgstall --with-supersplat
    ├── PLY server on :8765, serving scene.ply
    ├── SuperSplat server on :3000, serving target/supersplat/dist/
    └── Browser opens http://localhost:3000?load=http://localhost:8765/scene.ply
            └── PLY loads automatically — no drag-and-drop
                └── Cleanup (floaters, crop) manual
                    └── [optional] File → Publish → superspl.at URL → manually into embed_view_url
```
