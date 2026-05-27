# Collision Mesh — Design

**Status:** draft — awaiting user review
**Author:** Claude (autonomous mode after Variant-A approval)
**Date:** 2026-05-27
**Variant chosen:** A (MVP-Lean, ~600–850 LOC, single session)

## Goal

Extract an editable triangle mesh from a loaded Gaussian-Splat point cloud,
display it as an overlay in the viewer, let the user edit it with voxel-grid
brush tools, and use the result for (1) walking-mode collision, (2) `.obj`
export, and (3) JSON-sidecar save/load so a collider can be re-attached to the
same splat-set on next load.

## Non-Goals

- Smooth-brush, Redo, Region-Box-Cut, Hole-Fill (Variant B — deferred).
- `.glb` export, BVH-SAH-heuristics, Web-Worker build pipeline.
- Voxel resolution > 64³ for the MVP.
- Auto-persistence across page reloads (manual download-and-drop only).

## Lifecycle

```
Splats (positions Float32Array)
    │
    ▼  voxelize.js
Voxel-Density (Float32Array 64³, ≈ 1 MB)
    │
    ▼  marching-cubes.js
Mesh { positions, indices, normals }
    │
    ├──▶ PlayCanvas Mesh-Instance (Overlay-Render)
    ├──▶ mesh-bvh.js  ──▶  walking.js (capsule-sweep, optional)
    └──▶ persist.js
            ├──▶ .obj-Download
            └──▶ .collision.json sidecar (download / drop-load)

Editor-Loop:
  Pointer → raycast(mesh) → hitPoint
        → editor.js: brush.applyToVoxels(density, hitPoint, radius, sign)
        → marching-cubes.recompute(density)  → updateMeshBuffers()
        → undo-ring.push(diff)
```

## Module layout

All new code lives under `js/collision/` to match the existing flat-module
pattern in `js/`.

| File | LOC est. | Responsibility |
|---|---:|---|
| `voxelize.js` | 80 | Splat-positions → density grid + bounds (reuses `robustBounds` from `heightmap.js`) |
| `marching-cubes.js` | 250 | Standard 256-case lookup tables + indexed mesh build, per-vertex normals via accumulated face-normals |
| `mesh-bvh.js` | 150 | Median-split BVH on triangle centroids + capsule-sweep (down-ray + horizontal-sweep) |
| `editor.js` | 180 | Brush state, raycast picking against current mesh, voxel-diff undo ring (8 steps) |
| `persist.js` | 90 | `.obj` writer, sidecar JSON read/write, density RLE pack/unpack |
| `collision-mode.js` | 100 | Façade: lifecycle, lazy-loaded by `viewer.js#enterCollisionEditor()` |
| **Σ** | **~850** | |

## Integration with existing code

- **`viewer.js`** gains `enterCollisionEditor() / exitCollisionEditor() /
  isCollisionEditor()` plus listener registries (`onCollisionEnter`,
  `onCollisionExit`, `onCollisionMeshBuilt`). Pattern is parallel to the
  existing walking-mode plumbing, including dynamic `import()` so the editor
  is not in the initial bundle.
- **`walking.js`** gains a `setCollider(strategy)` method. Strategy is either
  `{ kind: 'heightmap', hm, bounds }` (today's behaviour) or
  `{ kind: 'mesh', bvh, bounds }`. `_step()` picks ground-sample +
  optional horizontal capsule-sweep based on strategy. Default remains
  heightmap.
- **`app.js`** wires the new toggle button and the editor-toolbar callbacks,
  parallel to the existing walking-mode wiring.
- **`hud.js`** gains an `enterCollisionUI()`/`exitCollisionUI()` pair that
  toggles a new `#collision-toolbar` element.
- **`index.html` / `css/`** get the toolbar markup + styling. `service-worker.js`
  `SHELL_FILES` and the `SHELL`/`RUNTIME` cache constants stay unchanged —
  collision-mode is lazy-loaded just like walking-mode.
- **Toggles are independent.** Walking-mode and collision-editor can be active
  simultaneously. When both are on:
  - The walking capsule continues to move; if a mesh exists, it is used as
    collider via `setCollider({ kind: 'mesh', ... })`.
  - Brush tools require pointer-lock release. When the user selects an editor
    tool (`Add`/`Remove`), walking pointer-lock is released and movement is
    paused; selecting the `View` tool returns control to walking. This avoids
    fighting over the cursor.
  - The existing `lockChangeHandler` in `viewer.js` currently auto-exits
    walking when pointer-lock is lost. It must be made collision-editor-aware:
    a deliberate lock-release for a brush tool does **not** trigger walking
    exit. Implementation: gate the auto-exit on `!isCollisionEditor()` or
    track a `lockReleasedByEditor` flag.

## Data structures

### Voxel grid

```js
{
  resolution: 64,                       // cubic
  bounds: { min: {x,y,z}, max: {x,y,z} },// world-space AABB
  density: Float32Array(64**3),          // 262 144 cells, ~1 MB
  iso: 1.5,                              // surface threshold (mutable)
}
```

Indexing: `density[k * res² + j * res + i]` for cell `(i, j, k)` along
`(x, y, z)`.

### Mesh

```js
{
  positions: Float32Array,   // length = numVerts * 3
  normals:   Float32Array,   // same length
  indices:   Uint32Array,    // length = numTris * 3
}
```

### Sidecar JSON

```json
{
  "version": 1,
  "resolution": 64,
  "bounds": { "min": [x, y, z], "max": [x, y, z] },
  "iso": 1.5,
  "densityRLE": [count, value, count, value, ...]
}
```

RLE keys: consecutive cells with equal density are folded into pairs. Density
quantised to 8 bits before packing (256 levels — more than enough for a
build-then-brush field whose interesting range is roughly 0–10). Expected
sidecar size for typical splat sets: < 200 KB.

## Algorithms

### Voxelize

For each splat position `(x, y, z)`:

1. Use `robustBounds(positions, 0.02, 0.98)` (already in `heightmap.js`) for
   the cube. Outlier-clamped Y, full X/Z extents — same rationale as walking.
2. Map to integer voxel `(i, j, k)`; reject if out-of-range.
3. Accumulate `density[idx] += 1`.

Then run one 3×3×3 box-blur pass to smooth out voxel-noise from isolated
splats. Output density grid + bounds.

**Default iso:** percentile-based. Compute the median of all
`density > 0` cells; iso starts at `max(1.5, median * 0.5)`. This survives
both dense scans (church demo) and sparse outdoor captures.

### Marching cubes

Standard implementation:

- 256-case `triTable[256][16]` and 256-entry `edgeTable[256]`.
- For each cell of the (res-1)³ inner grid: classify the 8 corners against
  `iso`, look up active edges, interpolate vertex positions linearly along
  edges, emit triangles via `triTable`.
- Vertex sharing: each edge is identified by its lower-corner cell-index and
  axis (`edgeKey = idx * 3 + axis`). A `Map<edgeKey, vertexIndex>` deduplicates.
- Normals: cross-product per triangle, accumulated onto each of the triangle's
  vertices, normalised at the end. (Smooth shading without a separate
  normal-recompute pass.)

**Recompute model (MVP):** the brush dirties a bounding box of voxels; we
recompute the **entire** mesh after each brush stroke. At 64³ this finishes
in ~30–60 ms on commodity hardware — well within an acceptable UI hitch.
Dirty-region-only recompute is a Variant-B optimisation; not in MVP.

### BVH + capsule-sweep

- Median-split BVH on triangle centroids, leaf size 4. Build is O(n log n);
  expected n ≤ 80 k tris → builds in < 50 ms.
- **Ground sample (downward ray):** start at `(x, y_high, z)`, cast `-Y`,
  return the first hit's Y.
- **Horizontal capsule-sweep:** axis-aligned capsule of radius `eyeOffset/3`
  along the requested XZ movement. BVH-bbox query → for each candidate
  triangle, compute closest-point-on-triangle-to-capsule-axis; if distance <
  radius, clip the motion. Pragmatic, not perfect — sufficient for FPS-style
  exploration.

### Brush

- Pointer-down on the canvas → screen-to-world ray through the camera →
  raycast against the current mesh BVH → world-space `hitPoint`.
- For each voxel within `brushRadius` of `hitPoint`:
  - **Add:** `density[idx] += strength * falloff(dist / radius)`.
  - **Remove:** `density[idx] -= strength * falloff(dist / radius)`,
    clamped at 0.
- `falloff` = simple `1 - (d/r)²` quadratic.
- On pointer-up: push a `{ voxelIndices: Int32Array, deltas: Float32Array }`
  diff onto the undo ring (max 8). Re-run marching cubes; rebuild BVH; swap
  PlayCanvas mesh-instance buffers.

### Undo

Ring buffer of voxel diffs. Apply-in-reverse on undo; the diff is symmetric
(`density[idx] -= delta`). No redo in MVP — once a stroke is undone, the
forward state is lost. Acceptable for a first cut.

## UI

A right-edge floating toolbar (`#collision-toolbar`) when the editor toggle
is on. Mobile: bottom-sheet variant via existing safe-area-inset pattern from
walking-mode.

```
┌─────────────────────────────┐
│ ⬛ Collision Editor          │
├─────────────────────────────┤
│ [Build from Splats]          │   ← runs voxelize + MC
│                              │
│ Tool: ( ) View               │   ← brush off, mesh visible
│       ( ) Add                │
│       (•) Remove             │
│                              │
│ Brush size ──○────────       │
│ Iso        ───○──────        │   ← live re-MC on release
│                              │
│ Show:  [✓] Mesh  [ ] Wires   │
│                              │
│ [Undo] [Reset]               │
│                              │
│ [Export .obj] [Save .json]   │
│                              │
│ 38 412 tris · iso 1.50       │
└─────────────────────────────┘
```

- **Entry point:** new `#btn-collision` button in `#stage-controls` (next to
  Walking-CTA). Click → `viewer.enterCollisionEditor()`.
- **Toggle is sticky:** mesh persists when the editor is closed (next open
  shows the same mesh). `Reset` discards mesh + voxel grid, `Build` rebuilds
  from current splat.
- **Status line** at the bottom shows tris, iso, undo-depth — debug-friendly,
  matches the walking-mode console-log conventions.

## Persistence

- **`Save .json`:** assemble sidecar object, JSON-stringify, RLE-pack the
  density, trigger blob download as `<splatname>.collision.json`. If splat
  is the demo, name is `scene.collision.json`. If splat was dropped (Blob,
  no name), prompt with a default `collision.json`.
- **Load:** the existing dropzone (`dropzone.js`) gains a `.collision.json`
  acceptor. On drop: parse → restore bounds + density + iso → run MC →
  display mesh. Bounds are stored absolutely (world-space), so a sidecar
  loaded against a different splat will silently mis-align — out of scope
  to detect for MVP; a future version can store a splat-position-hash.

## Walking-mode integration

When `viewer.enterWalking()` is called, the existing heightmap path runs as
today. After entry, if a collision mesh exists, the user can flip a
`Use mesh collider` checkbox (shown in the walking HUD when a mesh is
available). On flip:

```js
walkingMode.setCollider({
  kind: 'mesh',
  bvh: collisionMesh.bvh,
  bounds: collisionMesh.bounds,
});
```

`_step()` then:

1. Samples ground via a downward BVH-ray from `(x, currentY + eyeOffset*2, z)`.
2. Performs the horizontal capsule-sweep against the BVH to clip XZ motion.
3. Falls back to heightmap sample if the ray misses (no mesh in that
   column — e.g. user brushed a hole).

## Testing

Tests follow the existing `tests/unit/*.test.mjs` and
`tests/e2e/*.test.mjs` patterns (node:test, puppeteer-core).

### Unit tests (new)

| File | Coverage |
|---|---|
| `tests/unit/voxelize.test.mjs` | Empty input → all-zero grid; single splat → single non-zero cell; out-of-bounds splats rejected; bounds-degenerate (zero extent) returns empty grid cleanly |
| `tests/unit/marching-cubes.test.mjs` | All-empty grid → 0 tris; all-full grid → 0 tris (no inside-out surface); single cell at iso → 1–4 tris; sphere density-field → closed manifold (Euler V−E+F = 2) |
| `tests/unit/mesh-bvh.test.mjs` | Build on 1, 100, 10k synthetic tris (perf budget); raycast against known triangle returns expected `t`; capsule-sweep against a single wall-triangle clips motion |
| `tests/unit/brush.test.mjs` | Apply brush at voxel coord → exactly the cells within radius are modified; Add+Remove with same params is a no-op; undo ring respects max-depth |
| `tests/unit/persist.test.mjs` | RLE pack/unpack roundtrip; `.obj` writer output parses back to same vertex set; sidecar v1 round-trip |

### E2E (new)

| File | Coverage |
|---|---|
| `tests/e2e/collision-smoke.test.mjs` | Load demo → click `Build` → assert mesh-canvas-visible heuristic (pixel-diff vs. baseline screenshot or aria-status); click `Export .obj` → assert download attribute present; click `Save .json` → assert blob URL created |

### Acceptance criteria

- All existing tests still pass (`./tests/run.sh`).
- Build-from-splats on the church demo finishes in < 2 s on a Mac M1.
- Brush stroke → mesh update completes in < 100 ms per stroke at 64³.
- `.obj` export opens in Blender with correct geometry.
- Sidecar round-trip (save → reload page → drop sidecar → load → mesh
  visible) reconstructs an identical mesh.
- No console errors in normal flow.

## Risks and open questions

| Risk | Mitigation |
|---|---|
| 64³ too coarse for fine geometry (window frames, thin walls) | Variant-B raises to 128³ with Worker; MVP iso-slider lets users tune surface offset |
| MC produces non-manifold edges at iso-flat regions | Standard 256-case table handles common cases; ambiguous-face issues are visual, not topological — acceptable for MVP |
| Capsule-sweep is approximate (closest-point-on-tri); can let player slip through thin walls at high speed | `walkSpeed` is already capped to `sceneSize * 0.18`; document the limit, raise BVH leaf-size for thin geometry if reported |
| Sidecar loaded against a wrong splat | Out-of-scope to detect for MVP; future version stores a splat-position-fingerprint |
| Mesh overlay obscures splats | Material is translucent (`opacity = 0.35`) by default; toggle to wireframe-only for inspection |

## Out-of-scope (deferred / Variant B)

- 128³ + Web-Worker build pipeline
- Smooth-brush / Flatten-brush / Region-Box-Cut / Hole-Fill
- Redo, unbounded undo
- `.glb` export
- SAH-split BVH
- Splat-hash on sidecar for safe reload
- Per-tri material / vertex-colour painting

## File list (final)

**New:**
- `js/collision/voxelize.js`
- `js/collision/marching-cubes.js`
- `js/collision/mesh-bvh.js`
- `js/collision/editor.js`
- `js/collision/persist.js`
- `js/collision/collision-mode.js`
- `tests/unit/voxelize.test.mjs`
- `tests/unit/marching-cubes.test.mjs`
- `tests/unit/mesh-bvh.test.mjs`
- `tests/unit/brush.test.mjs`
- `tests/unit/persist.test.mjs`
- `tests/e2e/collision-smoke.test.mjs`

**Modified:**
- `js/viewer.js` — `enterCollisionEditor`/`exitCollisionEditor` + listeners
- `js/walking.js` — `setCollider()` strategy + mesh-collider `_step()` branch
- `js/app.js` — wire toggle button + editor-toolbar callbacks
- `js/hud.js` — `enterCollisionUI()`/`exitCollisionUI()`
- `js/dropzone.js` — accept `.collision.json`
- `index.html` — toolbar markup + button
- `css/*.css` — toolbar styles
- `README.md` — feature blurb in feature table
- `CHANGELOG.md` — `## [Unreleased]` entry
- `AGENTS.md` — note collision-mode is lazy-loaded (same as walking)
