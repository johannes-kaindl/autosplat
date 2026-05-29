# AutoSplat.app / .dmg — Design

**Date:** 2026-05-29
**Status:** Approved (autonomous implementation delegated)
**Target release:** v1.7.0

## Goal

Ship autosplat as a double-clickable macOS app distributed in a `.dmg`, aimed at
other Mac users (not just the maintainer). First launch runs a guided setup that
installs the heavy external tools; subsequent launches are one-click. Signing /
notarization are **optional, env-gated** steps — the app runs unsigned via
right-click → Open, and notarization can be added later once a Developer ID
exists.

## What is bundled vs installed

| Component | Strategy |
|---|---|
| autosplat (CLI + FastAPI WebUI + cv2/numpy/uvicorn/structlog) | **Frozen into the .app** via PyInstaller — always works, no system Python/uv needed |
| ffmpeg, **colmap**, Brush | **Installed at first run** via Homebrew + `fetch_brush.sh` — bundling colmap's dylibs + GPL compliance is the big-effort path we deliberately avoid |
| splat-transform (compress), SuperSplat | Optional; first-run can add via npx/setup, not required to launch |

Rationale: the app's own logic must never depend on a dev toolchain, but the
multi-hundred-MB GPL CV binaries are left to Homebrew, which already builds the
existing `install_deps.sh` path.

## Architecture

```
AutoSplat.app/Contents/
  MacOS/AutoSplat         ← PyInstaller-frozen entry (autosplat.desktop:main)
  Resources/…             ← webui templates/static, config/default.toml, icon
```

**`src/autosplat/desktop.py`** — the frozen app's entry point:
1. Load config; run `missing_required_tools(config)`.
2. If any are missing → launch first-run setup (below), poll `run_doctor` until
   the required tools report OK (or the user cancels).
3. Start the WebUI (uvicorn) on a free port in a background thread.
4. Open the default browser at `http://127.0.0.1:<port>`.
5. Show a **menubar item** (`rumps`): "AutoSplat ● running · Open · Quit".

**First-run setup** — reuses the existing `scripts/install_deps.sh` +
`fetch_brush.sh`. Driven through a visible **Terminal window** (via `osascript`)
so the user sees progress and can enter their password for Homebrew. The app
polls `run_doctor` every few seconds and proceeds once required tools are green.
No sudo is requested by the app itself; Homebrew handles its own escalation.

## Components & slices

**Slice 1 — setup logic (`desktop.py`, pure + TDD)**
- `missing_required_tools(config) -> list[str]` — filters `run_doctor` for
  `not ok and required`.
- `needs_first_run_setup(config) -> bool`.
- `build_setup_terminal_command(repo_or_bundle_dir) -> str` — the osascript/shell
  string that runs `install_deps.sh` in Terminal.
- `pick_free_port() -> int`.
All unit-tested with a stub doctor / fake config.

**Slice 2 — menubar launcher (`desktop.py:main` + `autosplat app` CLI command)**
- `autosplat app` runs the same launcher from a dev checkout (so it's runnable
  before any freezing). Starts uvicorn in a thread, opens the browser, shows the
  rumps menubar. The thread-start + browser-open orchestration has a thin
  testable core (`_serve_in_thread`, `_open_browser` injectable); rumps UI itself
  is integration-only.

**Slice 3 — packaging (`autosplat.spec` + `scripts/build_app.sh`)**
- PyInstaller spec bundling templates/static/config + hidden imports
  (uvicorn workers, cv2, rumps). Produces `dist/AutoSplat.app`.
- `build_app.sh`: freeze → `create-dmg` → `dist/AutoSplat.dmg`. Signing +
  notarization are **env-gated**: run only when `CODESIGN_IDENTITY` /
  `AC_NOTARY_PROFILE` are set, otherwise skipped with a logged note. Unsigned
  bundles get an ad-hoc `codesign -s -` to avoid dylib-load breakage on launch.
- README + `docs/` install section for the DMG path.

## Error handling

- `missing_required_tools` degrades to "show setup" rather than crashing if
  doctor itself errors.
- Launcher: if the port is taken, pick another; if the browser fails to open,
  the menubar still exposes "Open".
- Build script: fail loudly if PyInstaller/create-dmg are absent, with the exact
  install command; never silently produce a half-built bundle.

## Testing & verification

- **Unit-tested (TDD):** all of slice 1, plus the launcher's injectable core
  (port pick, serve-in-thread wiring, browser-open call).
- **Agent-verifiable:** run the frozen `AutoSplat.app/Contents/MacOS/AutoSplat`
  headlessly and `curl` the WebUI — confirms the freeze works end-to-end for the
  whole server stack. Confirm `.dmg` is produced and mountable.
- **Human-only (flagged):** the menubar item rendering, the Gatekeeper
  right-click→Open flow, and the first-run Terminal UX on a *fresh* Mac. These
  can't be automated; the maintainer verifies once.

## Out of scope

Bundling colmap/ffmpeg into the DMG; a native SwiftUI rewrite; the App Store;
auto-update. Notarization is wired as optional but not exercised here (no
Developer ID yet).
