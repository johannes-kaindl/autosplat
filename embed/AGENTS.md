# AGENTS.md

> **Workspace-Standards:** Die verbindliche Leitkonvention steht in `_docs/CONVENTIONS.md`
> (am Workspace-Root `/Users/Shared/code/`), Modell comply-or-explain.

Conventions for AI assistants working in `embed/`.

## Project character

Minimal, embeddable Gaussian-Splat viewer as a single self-contained iframe
page. Vanilla HTML/CSS/JS ES modules, no build step, **zero external
requests** — the PlayCanvas engine is vendored under `vendor/`. Spec:
`pipeline/docs/superpowers/specs/2026-07-14-embed-viewer-design.md`.

## Architecture principles

- `index.html?src=…&poster=…&autoplay=1` is the entire public API.
- The engine loads only after the click-gate (or `autoplay=1`) — the initial
  page stays a few KB.
- Pure logic (`js/params.js`, `js/autoframe.js`) is framework-free and
  unit-tested in node; DOM/engine glue lives in `js/main.js` / `js/viewer.js`.
- Deliberately NOT here: walking mode, collision editor, dropzone, PWA/service
  worker, demo scenes, marketing copy. That all stays in `viewer/` (the parked
  development viewer).

## Commands

- Tests: `./tests/run.sh` (or `./tests/run.sh unit` / `e2e`). Must pass
  before any commit.
- Local dev: `./serve.sh` → http://localhost:8130/?src=…

## Conventions

- Conventional Commits (`feat(embed): …`); `Co-Authored-By:` trailer for
  AI-pair commits.
- 2-space indent, LF (root `.editorconfig` applies).
- No bundlers, no transpilation, no npm runtime deps.

## Gotchas

- `vendor/playcanvas.mjs` is pinned (see `vendor/README.md`). Version bumps:
  re-download BOTH vendor files at the same version, then run all tests.
- The importmap in `index.html` maps `"playcanvas"` → `./vendor/playcanvas.mjs`;
  `camera-controls.mjs` resolves its `playcanvas` import through it. Don't
  rename the map key.
- Fullscreen inside an iframe needs `allow="fullscreen"` on the host's
  `<iframe>`; on iOS Safari the button falls back to CSS pseudo-fullscreen
  (fills only the iframe).
- e2e tests expect system Chrome at
  `/Applications/Google Chrome.app/Contents/MacOS/Google Chrome`.

## Memory

- Cross-session memory: `~/.claude/projects/-Users-Shared-code-autosplat/memory/`
- Coding-Cockpit: Pallas vault `25_Coding/autosplat/autosplat.md`.
