# Bedienablauf & Zugänge — Design

**Date:** 2026-07-29
**Status:** Approved (brainstorm), pre-implementation
**Scope:** `resources.py` [new], `config.py`, `desktop.py`, `cli.py`, `webui/app.py`,
`webui/routes/` (+ two new route modules), capture templates, `viewer/viewer.html`,
`scripts/build_app.sh`

**Context:** Sub-project 2 of 4 in the *Workflow-Rundumblick*. Builds on sub-project 1
(`2026-07-28-capture-lifecycle-design.md`, released as v1.16.0) — the lifecycle states
are what a surface can display in the first place. Sub-projects 3 (publishing chain) and
4 (input side) get their own spec each; see *Boundaries* below for what was deliberately
left to them.

## Problem

AutoSplat has three doors — CLI, WebUI in a browser, and `AutoSplat.app` — and three
viewer artifacts. Neither set has a stated division of labour, so both grew one. Four
concrete defects follow from that.

**1. No door can do everything.** The two command sets are complementary, not redundant:

| Only in the CLI | Only in the WebUI / app |
|---|---|
| `rescue`, `cleanup-rescue`, `migrate-storage`, `watch`, `doctor`, `compress`, `serve` | create capture via file picker, `delete`, **review gate**, **share bundle** + zip download |

The entire publishing path is GUI-only; the entire maintenance and diagnosis path is
CLI-only. (`cleanup-intermediates` is the exception — the WebUI's `prune` action already
covers it per capture.)

**2. The review viewer is missing from the shipped app.** `webui/app.py:96-100` resolves
`cfg.viewer.supersplat_dist_path` (default `target/supersplat/dist`) against
`Path.cwd()` and mounts it only if it exists. `scripts/build_app.sh` does not bundle it.
A Finder launch has no meaningful cwd, so in `/Applications/AutoSplat.app` the mount
never happens, `supersplat_available` is `False`, and `capture/view.html:18` silently
renders no viewer at all. The v1.15.0 review gate — mandatory before the first share —
therefore degrades to blind "confirm unchanged" for every app user. Verified 2026-07-29:
`pipeline/target/supersplat/dist` exists on the maintainer's checkout (23 MB) and is
absent from `/Applications/AutoSplat.app`.

**3. The app carries a viewer its own UI never offers.** `embed/` *is* bundled
(`/Applications/AutoSplat.app/Contents/Resources/embed`), because share bundles need it —
but no route points a capture at it.

**4. The walking viewer is a dead entrance.** `viewer/` is labelled "geparkt" in the root
`AGENTS.md`, yet it holds a feature nothing else has: first-person walk-through with
collision (`viewer/js/walking.js`, `heightmap.js`, `collision/`). The only way to reach
it is dragging a PLY onto the Pages site via `dropzone.js` — at 1,8 GB per scene, that
never happens. It is not redundant with `embed/`; it has a different job, and the label
hides that.

## Goal

State the division of labour, then make it true in code: the app becomes the door where
every step from import to publication is clickable, the CLI becomes scriptable for the
same steps, and each of the three viewers gets one named role and one working entrance.

## Non-goals (YAGNI)

- **Watch folder, `inbox/`, `import/`, the file picker** — sub-project 4. Not touched.
- **Publishing overview, revocation, update-after-rebuild, upload automation** —
  sub-project 3. `share` gains a CLI entrance here and nothing else.
- **Porting the walking mode into `embed/`** (which would leave two runtimes instead of
  three). Considered and deferred: the port of collision/heightmap/controls is large
  enough to turn this sub-project into a viewer refactor.
- **The marketing site** (`viewer/index.html`, `landing.js`, `assets/`) and the Pages
  deploy. Unchanged, and explicitly excluded from the app bundle.
- **`compress` / `serve` as GUI actions.** `compress` already runs inside the share path;
  `serve` is superseded by the in-app view.
- **A settings UI.** Config stays in `config/default.toml`.

## Charter of roles

The decision this sub-project exists to make. Everything below implements it.

| Artifact | Role | Reached via |
|---|---|---|
| `AutoSplat.app` | **the** door — every step from import to publication is clickable | canonical |
| CLI | equal footing for automation and batch; never the *only* way to a step | scripts |
| SuperSplat (`target/supersplat/dist`) | **clean up** — the review-gate editor | in the app |
| `embed/` | **share** — zero-external runtime inside share bundles | recipients |
| `viewer/` | **walk** — walking mode; plus the project website on Pages | in the app |

The three viewers overlap only on plain viewing. Naming the roles is what stops the next
one from being added by accident.

## Components

### `resources.py` (new)

One resolver for bundled assets, replacing two divergent ad-hoc resolutions:

```python
def bundled_path(name: str) -> Path:
    """Resolve a bundled resource dir: PyInstaller bundle, else repo-relative."""
```

- frozen (`sys._MEIPASS` present) → `<bundle>/<name>`
- otherwise → repo root `/ <name>` (`resources.py` → `autosplat` → `src` → `pipeline` →
  repo root), matching today's `_default_embed_src()` traversal

Callers: `embed` (moves out of `config.py:_default_embed_src`), `supersplat`, `viewer`.
`config.py` keeps `share.embed_src_path` and `viewer.supersplat_dist_path` as overrides;
only their defaults change. Their resolution stops depending on `Path.cwd()`.

### `packaging/AutoSplat.spec` (+ a `build_app.sh` preflight)

The bundle's data files are declared in the PyInstaller spec's `datas` list, not in
`build_app.sh`; `build_app.sh` only gains the preflight that refuses to build without a
SuperSplat dist. Two more trees are bundled:

- `supersplat` — the contents of `target/supersplat/dist` **without `*.map`** (9,5 MB
  measured; 23 MB with maps). The build fails with a clear message if the dist is absent,
  rather than shipping a bundle whose review gate is broken — `setup_supersplat.sh`
  becomes a build prerequisite instead of optional handiwork.
- `viewer` — **allowlist**, mirroring the share-bundle precedent: `viewer.html`, `js/`,
  `css/`, `icons/`, `vendor/`. Measured at 344 KB plus the vendored engine.
  `index.html`, `landing.js`, `assets/` (17 MB) and the legal pages stay out. `js/` is
  taken whole rather than file-by-file: `app.js` imports `dropzone.js`, so picking
  modules out breaks the viewer for a few kilobytes of savings.

Total bundle growth ≈ 13,5 MB on 167 MB.

### `viewer/` — vendored engine

`viewer/viewer.html:24-30` currently maps the `playcanvas` import specifier to
`https://cdn.jsdelivr.net/npm/playcanvas@2.18.1/+esm`. Bundling it unchanged would break
walking mode offline and void the app's zero-external property. The specifier is remapped
to `./vendor/playcanvas.mjs`, and `viewer/vendor/` receives a copy of the engine
`embed/vendor/` already holds (3,6 MB) — copied from there, not downloaded again.

It has to be a **second copy, not a shared one**, and that is a deliberate cost:
`embed/` is lifted wholesale into every share bundle and must stay self-contained, and
the Pages deploy is a `git subtree split` of `viewer/` alone, where `../embed/` does not
exist. Two copies of one engine in one repo is precisely the shape that drifts silently,
so a test asserts the two files are byte-identical and fails when one is updated alone.

`viewer/tests/` also gains a check that no allowlisted file contains an `http`-scheme
module specifier. This has a second beneficiary: the Pages deploy stops depending on a
CDN too.

### `webui/app.py`

The SuperSplat mount loses its cwd dependency and gains an honest failure mode. Today a
missing dist means "no viewer, no explanation". After: the mount still only happens when
the dist is present, but the absence is recorded on `app.state` so pages can say what is
missing instead of rendering emptiness.

### `webui/routes/system.py` (new)

`GET /system` — renders `run_doctor(cfg)`: each external tool (ffmpeg, colmap, brush,
splat-transform), its status and its version, plus which bundled viewers resolved. A
button re-runs the first-run setup via the existing `desktop.run_first_run_setup` path.

The information already exists — `desktop.main` calls `run_doctor` on every launch and
discards it, then spins in `while needs_first_run_setup(cfg): sleep(3)` with no visible
reason.

### `webui/routes/storage.py` (new)

`GET /storage` — disk usage grouped by lifecycle state (`failed` / `done` / `reviewed` /
`archived`, from `lifecycle.py`), plus what the retention rules consider reclaimable.

`POST /storage/reclaim` — runs the existing `migrate-storage` logic. **Preview is the
default and the only thing the GET renders**; the POST is the explicit apply, executed as
a job so a long sweep does not block the request. The protective predicates from
sub-project 1 are **called, not restated** — that rule has already been wrong twice when
written a second time.

### `webui/routes/captures.py`

`GET /captures/{id}/walk` — serves `viewer.html` pointed at
`/captures/{id}/scene.ply` through the existing `?src=` convention, the same one share
bundles use. A "Walk" action appears beside "View splat" on the detail page, enabled only
when the capture has a PLY.

### `cli.py`

Two commands, following the established `capture_dir: Path` argument convention
(`exists=True, file_okay=False`) used by `resume` / `cleanup-intermediates`:

```
autosplat review <capture_dir> --confirm-unchanged
autosplat review <capture_dir> --upload <cleaned.ply>
autosplat share  <capture_dir>
```

`review` writes the same `output/.review.json` marker the WebUI writes, through the same
function — mutually exclusive flags, one required. `share` builds the bundle
synchronously and prints the token and zip path.

**The gate moves down a layer while this happens.** Today it lives in the route
(`captures.py:588` redirects an unreviewed capture away), and `ShareJobRunner._run` would
bundle an unreviewed capture without complaint — so a CLI command calling the runner
would walk straight past the gate. The compress-and-assemble body is therefore extracted
out of `_run` into a synchronous function that raises on an unreviewed capture; the route
keeps its redirect for the UX, but the refusal itself sits underneath both surfaces.

Neither command introduces a second code path. Both make the review gate testable
without HTTP, which it currently is not.

## Data flow

```
launch (app)  →  doctor  →  /system              (today: discarded)
capture done  →  lifecycle state  →  /storage    (today: CLI only)
              →  SuperSplat (bundled)  →  review marker  →  share
              →  viewer/ (bundled)     →  walk
CLI           →  review / share  →  same marker, same bundler
```

## Error handling

**A missing resource is displayed, never silently hidden.** This is the leading defect
generalised: `capture/view.html` renders nothing when the dist is absent, and the user
cannot tell a broken install from an empty capture. Every surface that depends on a
bundled resource states what is missing and how to get it.

**Storage actions preview first.** `GET /storage` never mutates. The apply is a separate
POST and reuses sub-project 1's guards verbatim.

**Build-time failure beats runtime failure.** `build_app.sh` aborting on a missing
SuperSplat dist is preferable to a DMG whose review gate is quietly halved — exactly the
defect being fixed.

**CLI exit codes** follow the existing scheme: `EXIT_USER_ERROR` for a missing review or
an absent PLY.

## Testing

- `resources.py`: frozen and dev resolution, both without touching the real filesystem
  layout beyond a tmp fixture.
- New routes: **real HTTP tests** through the app, not function-level calls — a CORS bug
  once slipped past unit tests here.
- `viewer/`: a grep gate over the allowlisted files asserting no `http`-scheme module
  specifier survives, run in `viewer/tests/run.sh`.
- A drift test asserting `viewer/vendor/playcanvas.mjs` and `embed/vendor/playcanvas.mjs`
  are byte-identical — the only thing standing between two copies and a silent version
  split.
- A bundle test asserting `build_app.sh`'s allowlist excludes `assets/`, `index.html`,
  `landing.js` and `*.map` — the share-bundle allowlist precedent, applied to the app.
- `review` / `share` CLI: exercised without HTTP, including the refusal path.
- `/storage`: the apply path is tested against fixtures **plus** an assertion that it
  delegates to sub-project 1's predicates rather than reimplementing them. No test names
  a real path under `$HOME`.

## Config surface

No new keys. `share.embed_src_path` and `viewer.supersplat_dist_path` keep their meaning
as overrides; their defaults now come from `resources.bundled_path`.

## Expected outcome

- `AutoSplat.app` can review, walk, share, diagnose and reclaim — no step requires a
  terminal.
- The CLI can review and share — no step requires a mouse.
- Three viewers, three named roles, three working entrances, one vendored engine version
  (in two copies, guarded against drift).
- App bundle ≈ 180 MB (from 167 MB).
- Root `AGENTS.md` describes `viewer/` as what it is.

## Boundaries to sub-projects 3 and 4

Drawn deliberately, because the publishing question migrates otherwise:

- **3 (publishing chain)** owns everything *after* the bundle exists: the list of what is
  public, revocation, update-after-rebuild, upload automation, the unpacked-bundle-beside-
  its-own-zip duplication, and the 10 orphaned scenes.
- **4 (input side)** owns everything *before* a capture exists: watch folder, `inbox/`,
  `import/`, the file picker, `add-video`, and whether `source/` should hold anything.
