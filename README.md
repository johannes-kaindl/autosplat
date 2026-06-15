# autosplat

[![License: AGPL v3](https://img.shields.io/badge/License-AGPL_v3-blue.svg)](https://www.gnu.org/licenses/agpl-3.0)
[![Codeberg Release](https://img.shields.io/badge/codeberg-v1.12.0-green)](https://codeberg.org/jkaindl/autosplat/releases)
[![Status: Active](https://img.shields.io/badge/status-active-brightgreen)](https://codeberg.org/jkaindl/autosplat)
[![Live viewer](https://img.shields.io/badge/live-jkaindl.codeberg.page-brightgreen)](https://jkaindl.codeberg.page/autosplat/)

**autosplat** turns ordinary video into a 3D Gaussian Splat you can fly through in
the browser — captured, reconstructed and rendered entirely on your own machine.
No cloud, no GPU server, no upload.

This monorepo holds the two halves of the product:

| Path | Component | What it is |
|---|---|---|
| [`pipeline/`](pipeline/) | **Capture → Splat pipeline** | Drone / handheld video → trained 3D Gaussian Splat. Python · `uv` · COLMAP · Brush (WebGPU). Apple-Silicon-only, macOS 15+. |
| [`viewer/`](viewer/) | **Splat viewer PWA** | Static, installable web app that loads and renders `.ply` / `.sog` splats locally. Vanilla HTML/CSS/JS, no build step. |

The pipeline **exports** compressed splat files; the viewer **loads** them — that
shared interface is why the two now live in one repo (atomic cross-cutting commits,
one CHANGELOG, one release line, room for a shared end-to-end test).

## Quickstart

```bash
# Pipeline (Apple Silicon, macOS 15+)
cd pipeline
uv run autosplat doctor            # check ffmpeg / colmap / brush
uv run autosplat <your-video>.mp4  # video → trained splat

# Viewer (any modern browser)
cd viewer
./serve.sh                         # http://localhost:8123/  (Service Workers need http, not file://)
```

The live viewer is published via Codeberg Pages: **<https://jkaindl.codeberg.page/autosplat/>**.

## Develop & test

Each component keeps its own conventions in `pipeline/AGENTS.md` and `viewer/AGENTS.md`.

```bash
cd pipeline && uv run pytest -q     # pipeline unit tests
cd viewer   && ./tests/run.sh       # viewer unit + e2e tests
```

Deploy the viewer to Codeberg Pages (subtree split of `viewer/` → `pages` branch):

```bash
scripts/deploy-pages.sh
```

## Layout

```
autosplat/
├─ README.md · CHANGELOG.md · AGENTS.md      product-level (this repo)
├─ LICENSE · LICENSING.md · CLA.md · SECURITY.md · CITATION.cff · CONTRIBUTING.md
├─ scripts/deploy-pages.sh                   viewer → Codeberg Pages
├─ pipeline/                                 the capture→splat pipeline (own AGENTS.md/CHANGELOG)
└─ viewer/                                   the splat viewer PWA (own AGENTS.md/CHANGELOG)
```

The unified version line starts at **v1.12.0** (continuing the pipeline strand;
the viewer joins from 1.1.1). Pre-merge history of each component is preserved
verbatim — historical tags are namespaced `pipeline-v*` / `viewer-v*`, and
`git log --follow` reaches the full history inside each subfolder. Per-component
changelogs: [`pipeline/CHANGELOG.md`](pipeline/CHANGELOG.md) ·
[`viewer/CHANGELOG.md`](viewer/CHANGELOG.md).

## License

[AGPL-3.0-or-later](LICENSE), with a dual-licensing / CLA model — see
[`LICENSING.md`](LICENSING.md) and [`CLA.md`](CLA.md).

---

> **Moved here in 2026-06.** Previously two repos: `video-to-3d-gaussian-splat`
> (pipeline) and `autosplat-viewer` (viewer). Both are now archived; this monorepo
> is the canonical home.
