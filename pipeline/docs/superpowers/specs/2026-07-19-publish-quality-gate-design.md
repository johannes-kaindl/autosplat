# Publish Quality Gate — Design

**Date:** 2026-07-19
**Status:** Approved (brainstorm), pre-implementation
**Scope:** pipeline WebUI (`state.py`, `share_runner.py`, `routes/captures.py`,
`templates/capture/view.html` + `detail.html`)

## Problem

`ShareJobRunner` compresses `output/scene.ply` raw and publishes it via an
unlisted link with no review step in between. `output/scene.ply` is the
untouched SfM/training output — it commonly contains floaters, background
junk, or other artifacts a human would want to catch before the scene becomes
publicly reachable. The only existing look-before-you-publish opportunity is
the "View splat" button (`/captures/{id}/view`, embeds the local SuperSplat
editor), but it doesn't block or feed into the share flow — a user can create
a share bundle without ever having opened it.

`target/supersplat` (the locally-built PlayCanvas SuperSplat editor, gitignored,
mounted at `/supersplat` when present) exposes **no programmatic crop/delete
API** — `iframe-api.ts` only supports a `postMessage` dirty-scene query. Crop
(bounding-box tool) and floater removal (paint-select/brush) are purely
interactive browser actions. This rules out an automated "clean the scene for
me" step; the gate is a **human review checkpoint**, not an automated defect
detector.

## Goal

Before a capture's **first** share, force a review checkpoint: the user opens
the existing SuperSplat viewer and either (a) uploads a manually-cleaned PLY
exported from SuperSplat, or (b) explicitly confirms the scene is fine
unmodified. Only after that does "Create share bundle" become available.
Once reviewed, repeat shares work exactly as today — no re-review — until the
underlying `output/scene.ply` changes (e.g. via "Add video & rebuild"), which
automatically invalidates the review.

## Non-goals (YAGNI)

- Automated defect/artifact detection (no crop/outlier heuristics) — SuperSplat
  offers no API for it, and it's not what was asked for.
- Remote-controlling SuperSplat (e.g. via Puppeteer) to script the crop — pure
  interactive-UI tool, out of scope.
- A generic "capture state" store — `state.py` stays a read-only filesystem
  bridge; review status is computed the same way `has_ply` already is, not
  written to a new persistent store.
- Re-review on every share — only the first share (or after invalidation)
  requires it.
- A visible "reviewed" badge/chip on the detail page — the only observable
  effect is which control the share card shows.

## User flow

1. Detail page, `done` capture with `output/scene.ply`: the "web export ·
   share" card shows **"Review & Share"** (linking to `/captures/{id}/view`)
   instead of "Create share bundle" while `review_status == "unreviewed"`.
2. On the view page, a bottom panel appears (only when unreviewed): an upload
   field for a cleaned PLY exported from the embedded SuperSplat editor, and a
   **"Confirm unchanged →"** button for scenes that need no edits.
3. Either action marks the capture `reviewed` and redirects back to the detail
   page, where the card now shows the normal "Create share bundle" button.
4. Any later share of the same capture skips the review prompt — until
   `output/scene.ply`'s mtime changes (a rebuild), at which point the capture
   silently reverts to `unreviewed` and step 1 repeats.

## Architecture

### Review marker (`output/.review.json`)

```json
{"status": "reviewed", "reviewed_at": "2026-07-19T15:30:00", "source_ply_mtime": 1752936600.12}
```

Written by the two new routes below. `source_ply_mtime` is always the mtime of
`output/scene.ply` **at review time** — whether the user uploaded a cleaned
PLY or confirmed unchanged — and is the sole invalidation signal.

### `state.py` changes

- `CaptureInfo` (`state.py:28`) gains `review_status: Literal["unreviewed", "reviewed"]`.
- New `_review_status(capture_dir: Path) -> ReviewStatus`:
  1. No `.review.json` → `"unreviewed"`.
  2. `.review.json` present but `source_ply_mtime` doesn't match the current
     `output/scene.ply` mtime (or that file is gone) → `"unreviewed"` — this is
     the entire invalidation mechanism; `add-video`/`resume` routes need no
     awareness of review state at all.
  3. Otherwise → `"reviewed"`.
- New `resolve_publish_ply(capture_dir, review_status) -> Path | None`: returns
  `output/scene_reviewed.ply` when `review_status == "reviewed"` **and** that
  file exists, else falls back to the existing `_find_ply` candidate chain
  (`output/scene.ply`, `scene.ply`, glob). `_find_ply` is refactored to route
  through this so `has_ply`/`ply_path`/`ply_size_bytes`, the `/scene.ply`
  download route, and the "View splat" iframe all consistently show the
  reviewed file once one exists — a stale `scene_reviewed.ply` after a rebuild
  is automatically ignored the moment `review_status` flips back to
  `unreviewed`, no explicit cleanup needed.

### Routes (`routes/captures.py`)

- **`POST /captures/{id}/review/upload`** — multipart field `reviewed_ply`.
  Validates: non-empty, `.ply` filename suffix, `ply\n` magic-byte header. On
  success: saves to `output/scene_reviewed.ply`, writes `.review.json`
  (`source_ply_mtime` = mtime of the original `output/scene.ply`), redirects
  to `/captures/{id}`. On validation failure: re-renders `view.html` with an
  error banner (400), same pattern as the existing `add_video_error` path
  (`routes/captures.py:342-357`) — no redirect, user keeps context.
- **`POST /captures/{id}/review/confirm`** — no body. Writes `.review.json`
  (same `source_ply_mtime` logic), does **not** create `scene_reviewed.ply`.
  Redirects to `/captures/{id}`.
- **`POST /captures/{id}/share`** (existing, `routes/captures.py:419`) gains a
  gate check: if `capture.review_status == "unreviewed"`, redirect to
  `/captures/{id}/view` instead of starting `ShareJobRunner`. This is the real
  enforcement — the detail-page UI hiding the button is convenience only,
  since a direct POST could otherwise bypass it.

### `ShareJobRunner` changes (`share_runner.py:71`)

`_run()`'s hardcoded `ply = capture_dir / "output" / "scene.ply"` is replaced
by a call to the same `resolve_publish_ply()` used in `state.py`, so a share
always compresses the reviewed file when one exists.

### GUI

- **`templates/capture/view.html`** — new bottom panel (same visual family as
  the existing `as-viewer-hud-tl`/`-tr` overlays, `view.html:29-46`), rendered
  only when `capture.review_status == "unreviewed"`: an upload form
  (`multipart/form-data` → `/review/upload`) plus a `/review/confirm` form
  button. Panel is absent once reviewed — no persistent "reviewed" indicator.
- **`templates/capture/detail.html`** — share card (`:202-224`) branches on
  `review_status`: `unreviewed` renders a hint + **"Review & Share"** link
  button to `/captures/{id}/view`; `reviewed` renders the existing
  "Create share bundle" form unchanged.

## Error handling

- Invalid upload (wrong extension, empty, no PLY magic header) → 400,
  `view.html` re-rendered with an error banner; no marker written.
- No `output/scene.ply` (`capture.has_ply == False`) → the review panel never
  renders (the view page already falls back to its "No PLY" state,
  `view.html:76-95`); no extra check needed.
- Stale `scene_reviewed.ply` post-rebuild → left on disk untouched, simply
  stops being selected once `review_status` recomputes to `unreviewed`; a
  fresh review overwrites it if the user uploads again.
- "Free up space" (`cleanup.prune_intermediates`, `cleanup.py:45`) never
  touches `output/` — verified in source — so `scene_reviewed.ply` and
  `.review.json` survive every prune run unchanged.
- Delete capture (`shutil.rmtree`, `routes/captures.py:401`) removes review
  artifacts along with everything else — no special case.
- No new upload size cap — PLYs already run hundreds of MB through this WebUI
  today; relies on the same FastAPI/uvicorn path as everything else.

## Testing (TDD, red first)

Unit (`state.py`):

- `_review_status` — no marker → unreviewed; marker + matching mtime →
  reviewed; marker + stale/missing mtime → unreviewed.
- `resolve_publish_ply` — prefers `scene_reviewed.ply` only when reviewed
  *and* present; falls back to the existing chain otherwise.

Route (FastAPI `TestClient`):

- `POST /review/upload` — valid PLY → 303 + file saved to
  `output/scene_reviewed.ply` + marker written; invalid file → 400 + error
  banner, no marker written.
- `POST /review/confirm` — marker written, no `scene_reviewed.ply` created.
- `POST /share` — `unreviewed` → redirects to `/view`, `ShareJobRunner` never
  started; `reviewed` → unchanged existing behavior.

`ShareJobRunner`:

- Compresses `scene_reviewed.ply` when present, `scene.ply` otherwise (reuses
  the existing fake-`Compressor` injection pattern from the share-bundle test
  suite).

Templates:

- Share card renders "Review & Share" when unreviewed, normal form when
  reviewed; view page's review panel appears only when unreviewed.

## Open risks / notes

- **No automated quality check exists or is planned here** — this gate is
  purely procedural (a forced look + optional manual cleanup via SuperSplat's
  existing interactive tools). If SuperSplat ever grows a scriptable
  crop/export API, an automated pre-check could be layered on top later
  without changing this design's marker/invalidation mechanism.
- **Single-user, local-only WebUI**: the upload endpoint has no auth beyond
  what the rest of the WebUI already has (none — Mac-local process). Not a new
  exposure relative to the existing `/captures/{id}/share` POST.
