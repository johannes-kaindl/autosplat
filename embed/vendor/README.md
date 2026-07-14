# vendor/ — pinned runtime dependencies

Vendored so the embed page makes **zero external requests**.

| File | Version | Source | License |
|---|---|---|---|
| `playcanvas.mjs` | 2.18.1 | <https://cdn.jsdelivr.net/npm/playcanvas@2.18.1/build/playcanvas.mjs> | MIT |
| `camera-controls.mjs` | 2.18.1 | <https://cdn.jsdelivr.net/npm/playcanvas@2.18.1/scripts/esm/camera-controls.mjs> | MIT |

**Update:** change the version in BOTH URLs, re-download both files
(`curl -fsSL -o …`), then run `../tests/run.sh`.
