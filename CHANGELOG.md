# Changelog — autosplat

Unified changelog of the **autosplat** monorepo (`pipeline/` + `viewer/`),
starting at **v1.12.0**. The pre-merge history of each component is preserved
in [`pipeline/CHANGELOG.md`](pipeline/CHANGELOG.md) (up to `v1.11.0`) and
[`viewer/CHANGELOG.md`](viewer/CHANGELOG.md) (up to `v1.1.1`).

Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
This project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [Unreleased]

---

## [v1.16.0] — 2026-07-29 — Capture lifecycle & storage retention

### Changed

- **`pipeline/` only this release** — a capture now has an explicit, derived
  lifecycle (`failed` / `done` / `reviewed` / `archived`) and storage retention
  hangs off it: completing the publish-quality-gate review reclaims that
  capture's working directories, and a capture never reviewed is reclaimed after
  30 days on the next start (`[lifecycle] unreviewed_grace_days`, `0` disables).
  `rescue/clips/*.mp4` are always kept — they are a bisection-rescued capture's
  recorded origin, without which `resume`/`add-video` cannot work.
- **`export.copy_to_outputs` deprecated, now `false` by default** — `outputs_dir`
  was an unmanaged second copy of every PLY that nothing reclaimed.
- Compressed SOGs are kept at `output/scene.sog` and reused, turning a repeat
  share of an unchanged capture from minutes into seconds.

### Added

- **`autosplat migrate-storage`** — brings an existing backlog onto the retention
  policy. Preview by default, `--apply` executes. Never deletes an orphaned
  `outputs/` entry (the only surviving copy of a capture that was removed), a
  failed capture, or a directory burying a nested capture's only PLY — each is
  listed as kept with its reason. On the maintainer's machine: 27,8 GB → 13,1 GB.

See [`pipeline/CHANGELOG.md`](pipeline/CHANGELOG.md) for the full entry.

---

## [v1.15.0] — 2026-07-19 — Publish quality gate + capture cleanup

### Added

- **`pipeline/` only this release** — captures must be reviewed once in the
  SuperSplat viewer (upload a cleaned `.ply` or confirm unchanged) before
  their first share; auto-invalidates on rebuild. Also: `cleanup-intermediates`
  CLI command + WebUI "Free up space" button to reclaim disk space held by
  finished captures' working directories. See
  [`pipeline/CHANGELOG.md`](pipeline/CHANGELOG.md#v1150--2026-07-19--publish-quality-gate--capture-cleanup)
  for details.

---

## [v1.14.3] — 2026-07-19 — WebUI captures/detail papercut cleanup

### Fixed

- **`pipeline/` only this release** — share/_tmp compression leftover
  cleaned up, `finished_at` survives a WebUI restart for successful jobs
  too, COLMAP mapper no longer false-positives the liveness warning. See
  [`pipeline/CHANGELOG.md`](pipeline/CHANGELOG.md#v1143--2026-07-19--webui-capturesdetail-papercut-cleanup)
  for details.

### Added

- **`pipeline/` only this release** — captures list gets a per-row delete
  action and click-to-sort columns.

---

## [v1.14.2] — 2026-07-15 — Fix downloads in the desktop app window

### Fixed

- **`pipeline/` only this release** — "Download bundle (.zip)" did nothing in
  the packaged DMG app (pywebview's WKWebView window gates `<a download>`
  links behind a setting the app never enabled). See
  [`pipeline/CHANGELOG.md`](pipeline/CHANGELOG.md#v1142--2026-07-15--fix-downloads-in-the-desktop-app-window)
  for details.

---

## [v1.14.1] — 2026-07-15 — Share-bundle/embed migration

### Fixed

- **`pipeline/` only this release** — share bundles now bundle and use the
  `embed/` viewer runtime instead of `viewer/`, making them genuinely
  zero-external and fixing the feature being non-functional in the packaged
  DMG app. See [`pipeline/CHANGELOG.md`](pipeline/CHANGELOG.md#v1141--2026-07-15--share-bundleembed-migration)
  for details.

---

## [v1.14.0] — 2026-07-15 — Embed viewer + pose-authoring

### Added

- **`embed/` — minimal, embeddable splat viewer.** A new self-contained
  monorepo component: a single iframe page
  (`embed/index.html?src=…&poster=…&autoplay=1`) with click-to-load gate,
  percentile auto-framing, auto-orbit and fullscreen — and a fully vendored
  PlayCanvas engine (**zero external requests**). `viewer/` is parked as the
  development viewer (walking mode, collision editor, landing page live there).
  A pose-authoring workflow (`?pose=…&orbit=…&authoring=1`) lets you capture a
  curated camera view into a ready-to-embed link instead of relying on
  auto-framing.

---

## [v1.13.0] — 2026-07-14 — WebUI share bundles

### Changed

- **`pipeline/` only this release** — WebUI "Create share bundle" action and a
  capture-detail liveness fix. See [`pipeline/CHANGELOG.md`](pipeline/CHANGELOG.md#v1130--2026-07-14--webui-share-bundles)
  for details. No viewer changes.

---

## [v1.12.0] — 2026-06-15 — Monorepo merge

### Changed

- **`autosplat-pipeline` and `autosplat-viewer` merged into one monorepo.** The
  former pipeline repo (`video-to-3d-gaussian-splat`) and viewer repo
  (`autosplat-viewer`) now live side by side under [`pipeline/`](pipeline/) and
  [`viewer/`](viewer/), with full, lossless git history. Motivation: the two are
  tightly coupled through the export ↔ load interface — a single repo enables
  atomic cross-cutting commits, one release line, and a shared end-to-end test.
- **One shared version line, starting here at v1.12.0**, continuing the pipeline
  strand; the viewer joins from 1.1.1. One root CHANGELOG, one release tag for both.
- **Historical tags namespaced.** Pre-merge tags are now `pipeline-v*` / `viewer-v*`
  (resolving the `v1.1.0` / `v1.1.1` collision between the two repos). `git log
  --follow` reaches the full pre-merge history inside each subfolder.
- **Product-level files added at the root** (README, CHANGELOG, AGENTS, plus a
  consolidated LICENSE / LICENSING / CLA / SECURITY / CITATION / CONTRIBUTING set).
  Each component keeps its own AGENTS.md, CHANGELOG.md and license files unchanged.
- **Viewer Pages deploy** moves to `scripts/deploy-pages.sh` (subtree split of
  `viewer/` → `pages` branch). New live URL: <https://jkaindl.codeberg.page/autosplat/>.

### Migration notes

- The old Codeberg repos are **archived** (not deleted); their existing releases
  remain reachable there. The previous viewer Pages URL
  (`jkaindl.codeberg.page/autosplat-viewer/`) is retired.
- `feat/collision-mesh` (viewer, 8 commits) carried over and is available in this repo.
