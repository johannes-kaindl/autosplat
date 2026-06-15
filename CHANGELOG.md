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
