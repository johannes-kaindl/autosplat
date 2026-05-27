# Collision Mesh Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a collision-mesh editor to the autosplat-viewer — extract a triangle mesh from the Gaussian-Splat point cloud via marching cubes on a 64³ voxel-density grid, let the user voxel-brush-edit it, and use it for walking-mode collision, `.obj` export, and JSON sidecar save/load.

**Architecture:** New `js/collision/` module folder with six pure-ish JS files (voxelize → marching-cubes → mesh-bvh → editor → persist → collision-mode). Lazy-loaded from `viewer.js` analogous to walking-mode. `walking.js` gains a collider-strategy switch so heightmap remains default and mesh becomes opt-in.

**Tech Stack:** Vanilla ES modules, no build step, no runtime dependencies. PlayCanvas Engine (already loaded via CDN). Tests via `node:test` (unit) + `puppeteer-core` (e2e), all in `tests/`.

**Spec:** `docs/superpowers/specs/2026-05-27-collision-mesh-design.md`

---

## Conventions for this plan

- All tests use `node:test` and `assert/strict`, named `*.test.mjs`, placed in `tests/unit/` or `tests/e2e/`.
- All new JS modules use ES-module syntax (`export function …`), 2-space indent, LF, single quotes — matches existing files in `js/`.
- After each task: run `./tests/run.sh unit` (or `all` where noted) and commit. Failing tests are a stop-the-line condition; do not move on.
- Commit messages follow Conventional Commits (`feat(collision): …`, `test(collision): …`). Include the `Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>` trailer.
- The repo's `AGENTS.md` says tests must pass before any commit — do not skip.

---

## Task 1: Scaffold module folder + voxelize.js (TDD)

**Files:**
- Create: `js/collision/voxelize.js`
- Create: `tests/unit/voxelize.test.mjs`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/voxelize.test.mjs`:

```js
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { voxelize } from '../../js/collision/voxelize.js';

const bounds10 = { min: { x: 0, y: 0, z: 0 }, max: { x: 10, y: 10, z: 10 } };

function flat(...pts) {
  const f = new Float32Array(pts.length);
  for (let i = 0; i < pts.length; i++) f[i] = pts[i];
  return f;
}

test('voxelize: empty positions → all-zero grid', () => {
  const { density, resolution } = voxelize(new Float32Array(0), bounds10, 8);
  assert.equal(resolution, 8);
  assert.equal(density.length, 8 ** 3);
  for (const v of density) assert.equal(v, 0);
});

test('voxelize: single splat at centre → exactly one non-zero cell', () => {
  const { density, resolution } = voxelize(flat(5, 5, 5), bounds10, 8);
  let nonZero = 0;
  for (const v of density) if (v > 0) nonZero++;
  assert.equal(nonZero, 1);
  // cell (4,4,4) — floor(5/10 * 8) = 4
  const idx = 4 * 64 + 4 * 8 + 4;
  assert.equal(density[idx], 1);
});

test('voxelize: out-of-bounds splats are rejected', () => {
  const { density } = voxelize(flat(-1, -1, -1, 11, 11, 11), bounds10, 8);
  for (const v of density) assert.equal(v, 0);
});

test('voxelize: degenerate bounds (zero extent) → all-zero', () => {
  const bad = { min: { x: 0, y: 0, z: 0 }, max: { x: 0, y: 0, z: 0 } };
  const { density } = voxelize(flat(0, 0, 0), bad, 4);
  for (const v of density) assert.equal(v, 0);
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./tests/run.sh unit`
Expected: `tests/unit/voxelize.test.mjs` fails with `Cannot find module '../../js/collision/voxelize.js'`.

- [ ] **Step 3: Write minimal implementation**

Create `js/collision/voxelize.js`:

```js
// voxelize.js — turn a Gaussian-Splat point cloud into a voxel density grid.
// Pure module: no DOM, no PlayCanvas. Input positions are interleaved
// world-space (x, y, z) triples (Float32Array). Output is a flat Float32Array
// of length resolution³ indexed as density[k*res² + j*res + i] for cell
// (i, j, k) along (x, y, z).
//
// Each splat falling into a cell adds 1 to that cell's density. Callers
// typically apply a 3×3×3 box blur and a percentile-based iso threshold.

export function voxelize(positions, bounds, resolution = 64) {
  const cellCount = resolution ** 3;
  const density = new Float32Array(cellCount);
  const sx = bounds.max.x - bounds.min.x;
  const sy = bounds.max.y - bounds.min.y;
  const sz = bounds.max.z - bounds.min.z;
  if (sx <= 0 || sy <= 0 || sz <= 0) return { density, resolution };
  const minX = bounds.min.x, minY = bounds.min.y, minZ = bounds.min.z;
  const n = (positions.length / 3) | 0;
  for (let p = 0; p < n; p++) {
    const x = positions[p * 3];
    const y = positions[p * 3 + 1];
    const z = positions[p * 3 + 2];
    let i = Math.floor((x - minX) / sx * resolution);
    let j = Math.floor((y - minY) / sy * resolution);
    let k = Math.floor((z - minZ) / sz * resolution);
    if (i < 0 || i >= resolution) continue;
    if (j < 0 || j >= resolution) continue;
    if (k < 0 || k >= resolution) continue;
    density[k * resolution * resolution + j * resolution + i] += 1;
  }
  return { density, resolution };
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `./tests/run.sh unit`
Expected: all four `voxelize` tests pass; existing `heightmap`, `controls`, `sanity` tests still pass.

- [ ] **Step 5: Commit**

```bash
git add js/collision/voxelize.js tests/unit/voxelize.test.mjs
git commit -m "$(cat <<'EOF'
feat(collision): voxelize splat positions to a density grid

Pure module — interleaved Float32Array positions in, flat density grid
out, indexed (k*res² + j*res + i). First building block for the
collision-mesh editor.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: Density box-blur smoothing (TDD)

**Files:**
- Modify: `js/collision/voxelize.js`
- Modify: `tests/unit/voxelize.test.mjs`

- [ ] **Step 1: Append the failing test**

Append to `tests/unit/voxelize.test.mjs`:

```js
import { smoothDensity } from '../../js/collision/voxelize.js';

test('smoothDensity: single non-zero cell spreads to 3x3x3 neighbourhood', () => {
  const res = 5;
  const density = new Float32Array(res ** 3);
  // place 27 mass at centre cell (2,2,2)
  density[2 * 25 + 2 * 5 + 2] = 27;
  const out = smoothDensity(density, res);
  // centre cell is averaged with its 26 zero-neighbours → 27/27 = 1
  assert.equal(out[2 * 25 + 2 * 5 + 2], 1);
  // a neighbour cell averages 27 with 26 zeros → 1
  assert.equal(out[2 * 25 + 2 * 5 + 3], 1);
  // a non-neighbour stays zero
  assert.equal(out[0], 0);
});

test('smoothDensity: empty grid stays empty', () => {
  const out = smoothDensity(new Float32Array(64), 4);
  for (const v of out) assert.equal(v, 0);
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./tests/run.sh unit`
Expected: import error — `smoothDensity` is not exported yet.

- [ ] **Step 3: Append implementation**

Append to `js/collision/voxelize.js`:

```js
/**
 * One pass of a 3×3×3 box-blur over a flat density grid. Edge cells average
 * only the in-bounds neighbours (no wrap). Returns a new Float32Array; the
 * input is not mutated.
 */
export function smoothDensity(density, resolution) {
  const out = new Float32Array(density.length);
  const r = resolution;
  for (let k = 0; k < r; k++) {
    for (let j = 0; j < r; j++) {
      for (let i = 0; i < r; i++) {
        let sum = 0;
        // Always divide by 27 even on edges — gives edge cells a soft
        // "fade to zero" instead of an artificial bright rim.
        for (let dk = -1; dk <= 1; dk++) {
          const nk = k + dk;
          if (nk < 0 || nk >= r) continue;
          for (let dj = -1; dj <= 1; dj++) {
            const nj = j + dj;
            if (nj < 0 || nj >= r) continue;
            for (let di = -1; di <= 1; di++) {
              const ni = i + di;
              if (ni < 0 || ni >= r) continue;
              sum += density[nk * r * r + nj * r + ni];
            }
          }
        }
        out[k * r * r + j * r + i] = sum / 27;
      }
    }
  }
  return out;
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `./tests/run.sh unit`
Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add js/collision/voxelize.js tests/unit/voxelize.test.mjs
git commit -m "$(cat <<'EOF'
feat(collision): 3x3x3 box-blur smoothing for density grids

One blur pass removes voxel-noise from isolated splats so marching cubes
produces a connected surface instead of a cloud of tiny disjoint bits.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: Iso-default helper (TDD)

**Files:**
- Modify: `js/collision/voxelize.js`
- Modify: `tests/unit/voxelize.test.mjs`

- [ ] **Step 1: Append the failing test**

Append to `tests/unit/voxelize.test.mjs`:

```js
import { defaultIso } from '../../js/collision/voxelize.js';

test('defaultIso: empty grid → 1.5 fallback', () => {
  assert.equal(defaultIso(new Float32Array(64)), 1.5);
});

test('defaultIso: 50th-percentile of non-zero × 0.5, floored at 1.5', () => {
  // 100 cells, 10 of them are non-zero with values 1..10
  const density = new Float32Array(100);
  for (let i = 0; i < 10; i++) density[i] = i + 1;
  // median of [1..10] is 5.5 → * 0.5 = 2.75 → max(1.5, 2.75) = 2.75
  assert.equal(defaultIso(density), 2.75);
});

test('defaultIso: small values → falls back to 1.5', () => {
  const density = new Float32Array(10);
  density[0] = 1; density[1] = 2;
  // median = 1.5, * 0.5 = 0.75 → max(1.5, 0.75) = 1.5
  assert.equal(defaultIso(density), 1.5);
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./tests/run.sh unit`
Expected: import error — `defaultIso` is not exported.

- [ ] **Step 3: Append implementation**

Append to `js/collision/voxelize.js`:

```js
/**
 * Pick an iso threshold that survives both dense (church demo) and sparse
 * (outdoor) scans. Returns max(1.5, median(non-zero) * 0.5). 1.5 means
 * "more than one splat per cell after blur" — a useful baseline that avoids
 * meshing pure noise.
 */
export function defaultIso(density) {
  const nz = [];
  for (let i = 0; i < density.length; i++) {
    if (density[i] > 0) nz.push(density[i]);
  }
  if (nz.length === 0) return 1.5;
  nz.sort((a, b) => a - b);
  const median = nz[Math.floor((nz.length - 1) / 2)];
  return Math.max(1.5, median * 0.5);
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `./tests/run.sh unit`
Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add js/collision/voxelize.js tests/unit/voxelize.test.mjs
git commit -m "$(cat <<'EOF'
feat(collision): percentile-based default iso threshold

Median of non-zero cells x 0.5, floored at 1.5. Auto-picks a usable
surface for both dense and sparse scans.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: Marching-cubes lookup tables (one-shot copy)

**Files:**
- Create: `js/collision/mc-tables.js`
- Create: `tests/unit/mc-tables.test.mjs`

The Bourke marching-cubes tables (`edgeTable` 256 entries, `triTable` 256×16 entries) are a well-known fixed dataset. Copy them verbatim from the reference at <http://paulbourke.net/geometry/polygonise/> (or any standard implementation — the values are identical across sources). Do **not** hand-type them.

- [ ] **Step 1: Write the verification test**

Create `tests/unit/mc-tables.test.mjs`:

```js
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { edgeTable, triTable } from '../../js/collision/mc-tables.js';

test('mc-tables: edgeTable has 256 entries', () => {
  assert.equal(edgeTable.length, 256);
});

test('mc-tables: triTable has 256 rows of 16 entries', () => {
  assert.equal(triTable.length, 256);
  for (const row of triTable) assert.equal(row.length, 16);
});

test('mc-tables: known cases', () => {
  // Case 0 (all corners below iso): no triangles, no edges.
  assert.equal(edgeTable[0], 0x0);
  assert.equal(triTable[0][0], -1);
  // Case 255 (all corners above iso): also no triangles.
  assert.equal(edgeTable[255], 0x0);
  assert.equal(triTable[255][0], -1);
  // Case 1 (only corner 0 above): a single triangle on edges 0, 3, 8.
  assert.equal(edgeTable[1], 0x109);
  assert.deepEqual(triTable[1].slice(0, 4), [0, 8, 3, -1]);
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./tests/run.sh unit`
Expected: import error — file does not exist.

- [ ] **Step 3: Copy the tables from a reference source**

Create `js/collision/mc-tables.js` and copy the Bourke MC tables verbatim. The expected file layout:

```js
// mc-tables.js — standard Bourke marching-cubes lookup tables.
// Verbatim copy from http://paulbourke.net/geometry/polygonise/ — these
// values are identical across every reference implementation. Do not hand-
// edit; if a value looks wrong, re-copy from the source.
//
// edgeTable[cubeIndex] is a 12-bit bitmask of which cube edges the surface
// crosses. triTable[cubeIndex] is a length-16 list of edge indices (terminated
// by -1, in groups of 3) describing the triangles to emit.

export const edgeTable = new Uint16Array([
  0x0,   0x109, 0x203, 0x30a, 0x406, 0x50f, 0x605, 0x70c,
  0x80c, 0x905, 0xa0f, 0xb06, 0xc0a, 0xd03, 0xe09, 0xf00,
  // ... 240 more entries — paste from reference ...
]);

export const triTable = [
  [-1, -1, -1, -1, -1, -1, -1, -1, -1, -1, -1, -1, -1, -1, -1, -1],
  [ 0,  8,  3, -1, -1, -1, -1, -1, -1, -1, -1, -1, -1, -1, -1, -1],
  // ... 254 more rows — paste from reference ...
];
```

**Verification:** the test in Step 1 asserts the well-known values for cases 0, 1, 255 — these are stable across all reference implementations. If the test fails on these spot-checks, the paste is wrong.

- [ ] **Step 4: Run test to verify it passes**

Run: `./tests/run.sh unit`
Expected: all `mc-tables` tests pass.

- [ ] **Step 5: Commit**

```bash
git add js/collision/mc-tables.js tests/unit/mc-tables.test.mjs
git commit -m "$(cat <<'EOF'
feat(collision): marching-cubes lookup tables

Standard 256-case edge/tri tables (Bourke), with spot-check test against
known case 0/1/255 values to catch paste errors.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: Marching cubes — corner classification + edge interpolation (TDD)

**Files:**
- Create: `js/collision/marching-cubes.js`
- Create: `tests/unit/marching-cubes.test.mjs`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/marching-cubes.test.mjs`:

```js
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { marchingCubes } from '../../js/collision/marching-cubes.js';

const bounds = { min: { x: 0, y: 0, z: 0 }, max: { x: 1, y: 1, z: 1 } };

test('marchingCubes: all-zero grid → empty mesh', () => {
  const density = new Float32Array(4 ** 3);
  const mesh = marchingCubes({ density, resolution: 4, bounds, iso: 0.5 });
  assert.equal(mesh.positions.length, 0);
  assert.equal(mesh.indices.length, 0);
});

test('marchingCubes: all-one grid → empty mesh (no inside surface)', () => {
  const density = new Float32Array(4 ** 3).fill(1);
  const mesh = marchingCubes({ density, resolution: 4, bounds, iso: 0.5 });
  assert.equal(mesh.positions.length, 0);
});

test('marchingCubes: 2x2x2 single-cell with corner 0 above iso → 1 triangle', () => {
  // 2x2x2 grid → exactly one MC cell. Corner 0 = (0,0,0) cell index 0.
  const density = new Float32Array(8);
  density[0] = 1.0; // corner 0 above iso
  const mesh = marchingCubes({
    density, resolution: 2, bounds, iso: 0.5,
  });
  assert.equal(mesh.indices.length, 3); // exactly one triangle
  assert.equal(mesh.positions.length, 3 * 3); // 3 unique verts
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./tests/run.sh unit`
Expected: import error — `marchingCubes` not defined.

- [ ] **Step 3: Write the implementation**

Create `js/collision/marching-cubes.js`:

```js
// marching-cubes.js — extract a triangle mesh from a flat voxel-density grid.
// Pure module: no DOM, no PlayCanvas. Standard Bourke 256-case algorithm.
//
// Output is an indexed mesh: { positions: Float32Array (numVerts*3),
//   indices: Uint32Array (numTris*3), normals: Float32Array (numVerts*3) }.
// Vertices are de-duplicated by edge identity, so adjacent cells share verts
// and per-vertex normals can be accumulated for smooth shading.

import { edgeTable, triTable } from './mc-tables.js';

// Cube corner offsets (i, j, k) for corners 0..7 of an MC cell.
const CORNER_OFFSETS = [
  [0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0],
  [0, 0, 1], [1, 0, 1], [1, 1, 1], [0, 1, 1],
];

// Edge i connects corner EDGE_CORNERS[i][0] to EDGE_CORNERS[i][1].
const EDGE_CORNERS = [
  [0, 1], [1, 2], [2, 3], [3, 0],
  [4, 5], [5, 6], [6, 7], [7, 4],
  [0, 4], [1, 5], [2, 6], [3, 7],
];

export function marchingCubes({ density, resolution, bounds, iso }) {
  const r = resolution;
  const sx = (bounds.max.x - bounds.min.x) / r;
  const sy = (bounds.max.y - bounds.min.y) / r;
  const sz = (bounds.max.z - bounds.min.z) / r;
  const minX = bounds.min.x, minY = bounds.min.y, minZ = bounds.min.z;

  // Vertex de-dup map: edge identity → vertex index in positions[].
  // edgeKey = ((k * r + j) * r + i) * 3 + axis, where axis is 0=x, 1=y, 2=z
  // and (i,j,k) is the LOWER corner of the edge.
  const vertMap = new Map();
  const positions = [];
  const indices = [];

  function getDensity(i, j, k) {
    return density[k * r * r + j * r + i];
  }

  // Linearly interpolate the surface crossing along the edge between corners
  // c0 and c1 of the cell at (i, j, k).
  function getVertex(i, j, k, edgeIdx) {
    const [a, b] = EDGE_CORNERS[edgeIdx];
    const [aoi, aoj, aok] = CORNER_OFFSETS[a];
    const [boi, boj, bok] = CORNER_OFFSETS[b];
    const ax = i + aoi, ay = j + aoj, az = k + aok;
    const bx = i + boi, by = j + boj, bz = k + bok;
    // Canonical lower corner of this edge — used as the map key so two cells
    // sharing the edge produce the same key.
    const lx = Math.min(ax, bx), ly = Math.min(ay, by), lz = Math.min(az, bz);
    const axis = (ax !== bx) ? 0 : (ay !== by) ? 1 : 2;
    const key = ((lz * (r + 1) + ly) * (r + 1) + lx) * 3 + axis;
    const existing = vertMap.get(key);
    if (existing !== undefined) return existing;

    const va = getDensity(ax, ay, az);
    const vb = getDensity(bx, by, bz);
    let t = 0.5;
    const diff = vb - va;
    if (Math.abs(diff) > 1e-6) t = (iso - va) / diff;
    if (t < 0) t = 0; else if (t > 1) t = 1;

    const wx = minX + (ax + t * (bx - ax)) * sx;
    const wy = minY + (ay + t * (by - ay)) * sy;
    const wz = minZ + (az + t * (bz - az)) * sz;
    const vi = positions.length / 3;
    positions.push(wx, wy, wz);
    vertMap.set(key, vi);
    return vi;
  }

  for (let k = 0; k < r - 1; k++) {
    for (let j = 0; j < r - 1; j++) {
      for (let i = 0; i < r - 1; i++) {
        let cubeIndex = 0;
        for (let c = 0; c < 8; c++) {
          const [di, dj, dk] = CORNER_OFFSETS[c];
          if (getDensity(i + di, j + dj, k + dk) >= iso) cubeIndex |= (1 << c);
        }
        const edges = edgeTable[cubeIndex];
        if (edges === 0) continue;
        const tri = triTable[cubeIndex];
        for (let t = 0; tri[t] !== -1; t += 3) {
          const a = getVertex(i, j, k, tri[t]);
          const b = getVertex(i, j, k, tri[t + 1]);
          const c = getVertex(i, j, k, tri[t + 2]);
          indices.push(a, b, c);
        }
      }
    }
  }

  const pos = new Float32Array(positions);
  const idx = new Uint32Array(indices);
  return { positions: pos, indices: idx, normals: computeNormals(pos, idx) };
}

function computeNormals(positions, indices) {
  const normals = new Float32Array(positions.length);
  for (let t = 0; t < indices.length; t += 3) {
    const ia = indices[t] * 3, ib = indices[t + 1] * 3, ic = indices[t + 2] * 3;
    const ax = positions[ia], ay = positions[ia + 1], az = positions[ia + 2];
    const bx = positions[ib], by = positions[ib + 1], bz = positions[ib + 2];
    const cx = positions[ic], cy = positions[ic + 1], cz = positions[ic + 2];
    const ux = bx - ax, uy = by - ay, uz = bz - az;
    const vx = cx - ax, vy = cy - ay, vz = cz - az;
    const nx = uy * vz - uz * vy;
    const ny = uz * vx - ux * vz;
    const nz = ux * vy - uy * vx;
    for (const i of [ia, ib, ic]) {
      normals[i]     += nx;
      normals[i + 1] += ny;
      normals[i + 2] += nz;
    }
  }
  for (let i = 0; i < normals.length; i += 3) {
    const nx = normals[i], ny = normals[i + 1], nz = normals[i + 2];
    const len = Math.hypot(nx, ny, nz);
    if (len > 0) {
      normals[i]     = nx / len;
      normals[i + 1] = ny / len;
      normals[i + 2] = nz / len;
    }
  }
  return normals;
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `./tests/run.sh unit`
Expected: all `marching-cubes` tests pass.

- [ ] **Step 5: Commit**

```bash
git add js/collision/marching-cubes.js tests/unit/marching-cubes.test.mjs
git commit -m "$(cat <<'EOF'
feat(collision): marching cubes mesh extraction

Standard 256-case Bourke algorithm: classify cube corners against iso,
look up triangles, interpolate edge crossings, de-dup vertices by edge
identity, accumulate per-vertex normals for smooth shading.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: Marching cubes — sphere-shape sanity test

**Files:**
- Modify: `tests/unit/marching-cubes.test.mjs`

This is a defensive test: build a sphere-shaped density field, run MC, assert the output is plausible (closed-ish surface, non-trivial triangle count, vertices roughly on a sphere).

- [ ] **Step 1: Append the failing test**

Append to `tests/unit/marching-cubes.test.mjs`:

```js
test('marchingCubes: sphere density → closed-ish surface near unit radius', () => {
  const r = 16;
  const density = new Float32Array(r ** 3);
  // density = 1 - (distance from centre / radius)
  const cx = (r - 1) / 2, cy = cx, cz = cx;
  const radius = r * 0.3;
  for (let k = 0; k < r; k++) {
    for (let j = 0; j < r; j++) {
      for (let i = 0; i < r; i++) {
        const dx = i - cx, dy = j - cy, dz = k - cz;
        const d = Math.hypot(dx, dy, dz);
        density[k * r * r + j * r + i] = Math.max(0, 1 - d / radius);
      }
    }
  }
  const mesh = marchingCubes({
    density, resolution: r,
    bounds: { min: { x: -1, y: -1, z: -1 }, max: { x: 1, y: 1, z: 1 } },
    iso: 0.5,
  });
  // sanity: at least a few hundred triangles
  assert.ok(mesh.indices.length > 300,
    `expected > 100 tris, got ${mesh.indices.length / 3}`);
  // sanity: every vertex is roughly within the sphere's expected ring
  const cellX = 2 / r;
  const expectedR = radius * cellX * 0.5; // since iso=0.5 cuts halfway
  let inRange = 0;
  for (let v = 0; v < mesh.positions.length; v += 3) {
    const x = mesh.positions[v], y = mesh.positions[v + 1], z = mesh.positions[v + 2];
    const d = Math.hypot(x, y, z);
    if (d > expectedR * 0.5 && d < expectedR * 1.5) inRange++;
  }
  assert.ok(inRange / (mesh.positions.length / 3) > 0.8,
    'at least 80% of vertices should lie near the expected sphere radius');
});
```

- [ ] **Step 2: Run test to verify it passes immediately**

Run: `./tests/run.sh unit`

If the test fails, the MC implementation has a bug — re-examine Task 5 step 3. If the test passes on first run, the algorithm is solid for non-trivial inputs.

- [ ] **Step 3: Commit**

```bash
git add tests/unit/marching-cubes.test.mjs
git commit -m "$(cat <<'EOF'
test(collision): MC sphere-density sanity test

Defensive test — build a sphere density field, assert MC produces a
plausibly-sphere-shaped mesh. Catches regressions in corner-classification
or edge-interpolation.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 7: BVH build (TDD)

**Files:**
- Create: `js/collision/mesh-bvh.js`
- Create: `tests/unit/mesh-bvh.test.mjs`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/mesh-bvh.test.mjs`:

```js
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { buildBvh } from '../../js/collision/mesh-bvh.js';

test('buildBvh: empty mesh → null root', () => {
  const bvh = buildBvh(new Float32Array(0), new Uint32Array(0));
  assert.equal(bvh.root, null);
  assert.equal(bvh.triCount, 0);
});

test('buildBvh: single triangle → leaf root with that triangle', () => {
  const positions = new Float32Array([0, 0, 0, 1, 0, 0, 0, 1, 0]);
  const indices = new Uint32Array([0, 1, 2]);
  const bvh = buildBvh(positions, indices);
  assert.equal(bvh.triCount, 1);
  assert.ok(bvh.root);
  assert.equal(bvh.root.tris.length, 1);
  assert.equal(bvh.root.tris[0], 0);
});

test('buildBvh: 100 random triangles → internal-node tree', () => {
  const positions = new Float32Array(100 * 9);
  const indices = new Uint32Array(100 * 3);
  for (let t = 0; t < 100; t++) {
    for (let v = 0; v < 9; v++) positions[t * 9 + v] = Math.random();
    indices[t * 3]     = t * 3;
    indices[t * 3 + 1] = t * 3 + 1;
    indices[t * 3 + 2] = t * 3 + 2;
  }
  const bvh = buildBvh(positions, indices);
  assert.equal(bvh.triCount, 100);
  // root should be split (more than 4 tris)
  assert.ok(bvh.root.left && bvh.root.right);
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./tests/run.sh unit`
Expected: import error — `buildBvh` undefined.

- [ ] **Step 3: Write the implementation**

Create `js/collision/mesh-bvh.js`:

```js
// mesh-bvh.js — median-split bounding-volume hierarchy over triangle indices,
// plus a raycast and a capsule-sweep query. Pure module: no PlayCanvas
// dependency; takes the positions/indices arrays directly.

const LEAF_SIZE = 4;

export function buildBvh(positions, indices) {
  const triCount = indices.length / 3;
  if (triCount === 0) return { root: null, triCount: 0, positions, indices };

  // Precompute per-triangle centroid and bbox for fast partitioning.
  const centroids = new Float32Array(triCount * 3);
  const bboxes = new Float32Array(triCount * 6);
  for (let t = 0; t < triCount; t++) {
    const ia = indices[t * 3] * 3;
    const ib = indices[t * 3 + 1] * 3;
    const ic = indices[t * 3 + 2] * 3;
    const ax = positions[ia],     ay = positions[ia + 1], az = positions[ia + 2];
    const bx = positions[ib],     by = positions[ib + 1], bz = positions[ib + 2];
    const cx = positions[ic],     cy = positions[ic + 1], cz = positions[ic + 2];
    centroids[t * 3]     = (ax + bx + cx) / 3;
    centroids[t * 3 + 1] = (ay + by + cy) / 3;
    centroids[t * 3 + 2] = (az + bz + cz) / 3;
    bboxes[t * 6]     = Math.min(ax, bx, cx);
    bboxes[t * 6 + 1] = Math.min(ay, by, cy);
    bboxes[t * 6 + 2] = Math.min(az, bz, cz);
    bboxes[t * 6 + 3] = Math.max(ax, bx, cx);
    bboxes[t * 6 + 4] = Math.max(ay, by, cy);
    bboxes[t * 6 + 5] = Math.max(az, bz, cz);
  }

  const triIndices = new Int32Array(triCount);
  for (let t = 0; t < triCount; t++) triIndices[t] = t;

  const root = buildNode(triIndices, 0, triCount, centroids, bboxes);
  return { root, triCount, positions, indices };
}

function buildNode(tris, start, end, centroids, bboxes) {
  const node = { bbox: nodeBbox(tris, start, end, bboxes) };
  const count = end - start;
  if (count <= LEAF_SIZE) {
    node.tris = tris.slice(start, end);
    return node;
  }
  // Split on the axis with the largest centroid extent.
  let axisMin = [Infinity, Infinity, Infinity];
  let axisMax = [-Infinity, -Infinity, -Infinity];
  for (let i = start; i < end; i++) {
    const t = tris[i];
    for (let a = 0; a < 3; a++) {
      const c = centroids[t * 3 + a];
      if (c < axisMin[a]) axisMin[a] = c;
      if (c > axisMax[a]) axisMax[a] = c;
    }
  }
  let axis = 0;
  let ext = axisMax[0] - axisMin[0];
  if (axisMax[1] - axisMin[1] > ext) { axis = 1; ext = axisMax[1] - axisMin[1]; }
  if (axisMax[2] - axisMin[2] > ext) { axis = 2; }

  // Partition tris in-place by the axis median (Hoare partition).
  const slice = tris.subarray(start, end);
  // Convert to Array for the simple sort — typed-array sort is numeric-only
  // and we need a comparator on centroid component.
  const arr = Array.from(slice);
  arr.sort((a, b) => centroids[a * 3 + axis] - centroids[b * 3 + axis]);
  for (let i = 0; i < arr.length; i++) tris[start + i] = arr[i];
  const mid = start + (count >> 1);
  node.left  = buildNode(tris, start, mid, centroids, bboxes);
  node.right = buildNode(tris, mid, end, centroids, bboxes);
  return node;
}

function nodeBbox(tris, start, end, bboxes) {
  let mnx = Infinity, mny = Infinity, mnz = Infinity;
  let mxx = -Infinity, mxy = -Infinity, mxz = -Infinity;
  for (let i = start; i < end; i++) {
    const t = tris[i];
    if (bboxes[t * 6]     < mnx) mnx = bboxes[t * 6];
    if (bboxes[t * 6 + 1] < mny) mny = bboxes[t * 6 + 1];
    if (bboxes[t * 6 + 2] < mnz) mnz = bboxes[t * 6 + 2];
    if (bboxes[t * 6 + 3] > mxx) mxx = bboxes[t * 6 + 3];
    if (bboxes[t * 6 + 4] > mxy) mxy = bboxes[t * 6 + 4];
    if (bboxes[t * 6 + 5] > mxz) mxz = bboxes[t * 6 + 5];
  }
  return [mnx, mny, mnz, mxx, mxy, mxz];
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `./tests/run.sh unit`
Expected: all `mesh-bvh` tests pass.

- [ ] **Step 5: Commit**

```bash
git add js/collision/mesh-bvh.js tests/unit/mesh-bvh.test.mjs
git commit -m "$(cat <<'EOF'
feat(collision): median-split BVH build

Leaf size 4, axis chosen by largest centroid extent. Per-tri centroid
+ bbox precomputed once. Foundation for raycast picking and walking
capsule-sweep.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 8: BVH raycast (TDD)

**Files:**
- Modify: `js/collision/mesh-bvh.js`
- Modify: `tests/unit/mesh-bvh.test.mjs`

- [ ] **Step 1: Append the failing test**

Append to `tests/unit/mesh-bvh.test.mjs`:

```js
import { raycast } from '../../js/collision/mesh-bvh.js';

test('raycast: ray hits a single triangle at expected t', () => {
  // Triangle in XY plane at z=2, ray from origin along -Z hits at z=2 → t=2.
  const positions = new Float32Array([
    -1, -1, 2,  1, -1, 2,  0, 1, 2,
  ]);
  const indices = new Uint32Array([0, 1, 2]);
  const bvh = buildBvh(positions, indices);
  const hit = raycast(bvh, [0, 0, 0], [0, 0, 1]);
  assert.ok(hit, 'should hit');
  assert.ok(Math.abs(hit.t - 2) < 1e-4, `t=${hit.t}`);
});

test('raycast: ray misses (parallel) returns null', () => {
  const positions = new Float32Array([
    -1, -1, 2,  1, -1, 2,  0, 1, 2,
  ]);
  const indices = new Uint32Array([0, 1, 2]);
  const bvh = buildBvh(positions, indices);
  const hit = raycast(bvh, [0, 0, 0], [1, 0, 0]); // ray along X — never crosses z=2
  assert.equal(hit, null);
});

test('raycast: ray pointing away from triangle returns null', () => {
  const positions = new Float32Array([
    -1, -1, 2,  1, -1, 2,  0, 1, 2,
  ]);
  const indices = new Uint32Array([0, 1, 2]);
  const bvh = buildBvh(positions, indices);
  const hit = raycast(bvh, [0, 0, 0], [0, 0, -1]); // away from z=2
  assert.equal(hit, null);
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./tests/run.sh unit`
Expected: import error — `raycast` not exported.

- [ ] **Step 3: Append the implementation**

Append to `js/collision/mesh-bvh.js`:

```js
/**
 * Cast a ray (origin + direction, direction need not be unit) against the BVH.
 * Returns { t, triIndex, point } for the nearest hit, or null. Triangles are
 * single-sided in the geometric sense — but Möller-Trumbore is configured
 * here for two-sided hits since brush picking should work from either side.
 */
export function raycast(bvh, origin, direction) {
  if (!bvh.root) return null;
  const invDir = [
    direction[0] !== 0 ? 1 / direction[0] : Infinity,
    direction[1] !== 0 ? 1 / direction[1] : Infinity,
    direction[2] !== 0 ? 1 / direction[2] : Infinity,
  ];
  const state = { tNearest: Infinity, hitTri: -1 };
  raycastNode(bvh.root, origin, direction, invDir, bvh.positions, bvh.indices, state);
  if (state.hitTri < 0) return null;
  const t = state.tNearest;
  return {
    t,
    triIndex: state.hitTri,
    point: [
      origin[0] + t * direction[0],
      origin[1] + t * direction[1],
      origin[2] + t * direction[2],
    ],
  };
}

function raycastNode(node, origin, dir, invDir, positions, indices, state) {
  if (!intersectAabb(node.bbox, origin, invDir, state.tNearest)) return;
  if (node.tris) {
    for (const t of node.tris) {
      const ia = indices[t * 3] * 3;
      const ib = indices[t * 3 + 1] * 3;
      const ic = indices[t * 3 + 2] * 3;
      const tHit = intersectTriangle(
        origin, dir,
        positions[ia], positions[ia + 1], positions[ia + 2],
        positions[ib], positions[ib + 1], positions[ib + 2],
        positions[ic], positions[ic + 1], positions[ic + 2],
      );
      if (tHit > 0 && tHit < state.tNearest) {
        state.tNearest = tHit;
        state.hitTri = t;
      }
    }
    return;
  }
  // Visit nearer child first for early-out.
  raycastNode(node.left,  origin, dir, invDir, positions, indices, state);
  raycastNode(node.right, origin, dir, invDir, positions, indices, state);
}

function intersectAabb(bbox, origin, invDir, tMax) {
  let tmin = -Infinity, tCap = tMax;
  for (let a = 0; a < 3; a++) {
    const t1 = (bbox[a]     - origin[a]) * invDir[a];
    const t2 = (bbox[a + 3] - origin[a]) * invDir[a];
    const lo = Math.min(t1, t2);
    const hi = Math.max(t1, t2);
    if (lo > tmin) tmin = lo;
    if (hi < tCap) tCap = hi;
    if (tmin > tCap) return false;
  }
  return tCap >= 0;
}

function intersectTriangle(o, d, ax, ay, az, bx, by, bz, cx, cy, cz) {
  // Möller-Trumbore, two-sided.
  const ex = bx - ax, ey = by - ay, ez = bz - az;
  const fx = cx - ax, fy = cy - ay, fz = cz - az;
  const px = d[1] * fz - d[2] * fy;
  const py = d[2] * fx - d[0] * fz;
  const pz = d[0] * fy - d[1] * fx;
  const det = ex * px + ey * py + ez * pz;
  if (Math.abs(det) < 1e-8) return -1;
  const inv = 1 / det;
  const tx = o[0] - ax, ty = o[1] - ay, tz = o[2] - az;
  const u = (tx * px + ty * py + tz * pz) * inv;
  if (u < 0 || u > 1) return -1;
  const qx = ty * ez - tz * ey;
  const qy = tz * ex - tx * ez;
  const qz = tx * ey - ty * ex;
  const v = (d[0] * qx + d[1] * qy + d[2] * qz) * inv;
  if (v < 0 || u + v > 1) return -1;
  return (fx * qx + fy * qy + fz * qz) * inv;
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `./tests/run.sh unit`
Expected: all raycast tests pass.

- [ ] **Step 5: Commit**

```bash
git add js/collision/mesh-bvh.js tests/unit/mesh-bvh.test.mjs
git commit -m "$(cat <<'EOF'
feat(collision): BVH raycast with Moller-Trumbore tri-test

Slab AABB test for nodes, two-sided Moller-Trumbore for triangles.
Brush picking and walking ground-sample will both use this.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 9: BVH capsule-sweep (TDD)

**Files:**
- Modify: `js/collision/mesh-bvh.js`
- Modify: `tests/unit/mesh-bvh.test.mjs`

- [ ] **Step 1: Append the failing test**

Append to `tests/unit/mesh-bvh.test.mjs`:

```js
import { capsuleSweep } from '../../js/collision/mesh-bvh.js';

test('capsuleSweep: vertical capsule with no nearby tris → no penetration', () => {
  // A floor tri far below.
  const positions = new Float32Array([
    -10, -10, -10,  10, -10, -10,  0, -10, 10,
  ]);
  const indices = new Uint32Array([0, 1, 2]);
  const bvh = buildBvh(positions, indices);
  const result = capsuleSweep(bvh, [0, 5, 0], [0, 5, 0], 0.5, 1.5);
  assert.equal(result.hits.length, 0);
});

test('capsuleSweep: capsule moving into a wall is clipped', () => {
  // Wall at x=1, spanning some y/z. Capsule axis is vertical, sweep moves in +x.
  const positions = new Float32Array([
    1, -2, -2,  1, -2, 2,  1, 2, 0,
  ]);
  const indices = new Uint32Array([0, 1, 2]);
  const bvh = buildBvh(positions, indices);
  // Capsule radius 0.4, top/bot at y=0/y=1, starting at x=0, moving to x=2.
  const result = capsuleSweep(bvh, [0, 0, 0], [2, 1, 0], 0.4, 1.0);
  assert.ok(result.hits.length > 0);
  // clipped end x should be <= 0.6 (1 - radius)
  assert.ok(result.endX < 0.65, `endX=${result.endX}`);
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./tests/run.sh unit`
Expected: import error — `capsuleSweep` not exported.

- [ ] **Step 3: Append the implementation**

Append to `js/collision/mesh-bvh.js`:

```js
/**
 * Pragmatic capsule-vs-mesh sweep for walking-mode horizontal collision.
 *
 * Input:
 *   start, end:       capsule-bottom positions before/after the step [x, y, z]
 *   radius:           capsule radius
 *   height:           distance from capsule bottom to top
 *
 * Method:
 *   1. Build the swept-AABB of (start..end) ± radius/height.
 *   2. Walk the BVH for triangles whose bbox overlaps that AABB.
 *   3. For each candidate, compute closest-point-on-triangle to the
 *      *final* capsule axis (line segment from `end` to `end + height·Y`);
 *      if distance < radius, this triangle penetrates the destination.
 *   4. Approximate clipping: collect the maximum X / Z back-off that
 *      removes the penetration, applied independently to each axis.
 *      Coarse but sufficient for FPS walking — never zeros motion when
 *      the user is far from a wall.
 *
 * Returns { hits: triIndex[], endX, endZ } — endX/endZ are the clipped
 * destination XZ. Y is not clipped here (gravity/ground handle Y).
 */
export function capsuleSweep(bvh, start, end, radius, height) {
  const hits = [];
  let endX = end[0];
  let endZ = end[2];
  if (!bvh.root) return { hits, endX, endZ };

  const cy = end[1];
  const topY = cy + height;
  const aabb = [
    Math.min(start[0], end[0]) - radius,
    Math.min(start[1], end[1]) - radius,
    Math.min(start[2], end[2]) - radius,
    Math.max(start[0], end[0]) + radius,
    Math.max(start[1], end[1]) + height + radius,
    Math.max(start[2], end[2]) + radius,
  ];

  const candidates = [];
  collectCandidates(bvh.root, aabb, candidates);

  for (const t of candidates) {
    const i = bvh.indices[t * 3] * 3;
    const j = bvh.indices[t * 3 + 1] * 3;
    const k = bvh.indices[t * 3 + 2] * 3;
    const ax = bvh.positions[i],     ay = bvh.positions[i + 1], az = bvh.positions[i + 2];
    const bx = bvh.positions[j],     by = bvh.positions[j + 1], bz = bvh.positions[j + 2];
    const cx = bvh.positions[k],     cyv = bvh.positions[k + 1], cz = bvh.positions[k + 2];
    // closest point on triangle to vertical capsule segment (endX..endX, cy..topY, endZ..endZ)
    const cp = closestPointTriToSegment(
      ax, ay, az, bx, by, bz, cx, cyv, cz,
      endX, cy, endZ, endX, topY, endZ,
    );
    const dx = cp.tx - cp.sx;
    const dy = cp.ty - cp.sy;
    const dz = cp.tz - cp.sz;
    const distSq = dx * dx + dy * dy + dz * dz;
    if (distSq >= radius * radius) continue;
    hits.push(t);
    // Push the destination back along the horizontal direction of penetration.
    const dist = Math.sqrt(distSq);
    const push = radius - dist;
    const hx = dx, hz = dz;
    const hlen = Math.hypot(hx, hz);
    if (hlen > 1e-6) {
      endX += (hx / hlen) * push;
      endZ += (hz / hlen) * push;
    }
  }
  return { hits, endX, endZ };
}

function collectCandidates(node, aabb, out) {
  if (!aabbOverlap(node.bbox, aabb)) return;
  if (node.tris) {
    for (const t of node.tris) out.push(t);
    return;
  }
  collectCandidates(node.left, aabb, out);
  collectCandidates(node.right, aabb, out);
}

function aabbOverlap(a, b) {
  return a[0] <= b[3] && a[3] >= b[0]
      && a[1] <= b[4] && a[4] >= b[1]
      && a[2] <= b[5] && a[5] >= b[2];
}

// Returns { sx, sy, sz, tx, ty, tz } — sx/y/z is the closest point on the
// capsule axis segment, tx/y/z is the closest point on the triangle.
// Implementation: sample N points along the capsule segment, find closest
// point on triangle to each, return the best.  Coarse but sufficient.
function closestPointTriToSegment(ax, ay, az, bx, by, bz, cx, cy, cz,
                                  p0x, p0y, p0z, p1x, p1y, p1z) {
  const N = 5;
  let best = { sx: 0, sy: 0, sz: 0, tx: 0, ty: 0, tz: 0, d2: Infinity };
  for (let i = 0; i <= N; i++) {
    const t = i / N;
    const sx = p0x + t * (p1x - p0x);
    const sy = p0y + t * (p1y - p0y);
    const sz = p0z + t * (p1z - p0z);
    const cp = closestPointOnTri(ax, ay, az, bx, by, bz, cx, cy, cz, sx, sy, sz);
    const dx = cp.x - sx, dy = cp.y - sy, dz = cp.z - sz;
    const d2 = dx * dx + dy * dy + dz * dz;
    if (d2 < best.d2) {
      best = { sx, sy, sz, tx: cp.x, ty: cp.y, tz: cp.z, d2 };
    }
  }
  return best;
}

// Ericson, Real-Time Collision Detection §5.1.5.
function closestPointOnTri(ax, ay, az, bx, by, bz, cx, cy, cz, px, py, pz) {
  const abx = bx - ax, aby = by - ay, abz = bz - az;
  const acx = cx - ax, acy = cy - ay, acz = cz - az;
  const apx = px - ax, apy = py - ay, apz = pz - az;
  const d1 = abx * apx + aby * apy + abz * apz;
  const d2 = acx * apx + acy * apy + acz * apz;
  if (d1 <= 0 && d2 <= 0) return { x: ax, y: ay, z: az };
  const bpx = px - bx, bpy = py - by, bpz = pz - bz;
  const d3 = abx * bpx + aby * bpy + abz * bpz;
  const d4 = acx * bpx + acy * bpy + acz * bpz;
  if (d3 >= 0 && d4 <= d3) return { x: bx, y: by, z: bz };
  const vc = d1 * d4 - d3 * d2;
  if (vc <= 0 && d1 >= 0 && d3 <= 0) {
    const v = d1 / (d1 - d3);
    return { x: ax + v * abx, y: ay + v * aby, z: az + v * abz };
  }
  const cpx = px - cx, cpy = py - cy, cpz = pz - cz;
  const d5 = abx * cpx + aby * cpy + abz * cpz;
  const d6 = acx * cpx + acy * cpy + acz * cpz;
  if (d6 >= 0 && d5 <= d6) return { x: cx, y: cy, z: cz };
  const vb = d5 * d2 - d1 * d6;
  if (vb <= 0 && d2 >= 0 && d6 <= 0) {
    const w = d2 / (d2 - d6);
    return { x: ax + w * acx, y: ay + w * acy, z: az + w * acz };
  }
  const va = d3 * d6 - d5 * d4;
  if (va <= 0 && (d4 - d3) >= 0 && (d5 - d6) >= 0) {
    const w = (d4 - d3) / ((d4 - d3) + (d5 - d6));
    return {
      x: bx + w * (cx - bx),
      y: by + w * (cy - by),
      z: bz + w * (cz - bz),
    };
  }
  const denom = 1 / (va + vb + vc);
  const v = vb * denom;
  const w = vc * denom;
  return {
    x: ax + abx * v + acx * w,
    y: ay + aby * v + acy * w,
    z: az + abz * v + acz * w,
  };
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `./tests/run.sh unit`
Expected: both `capsuleSweep` tests pass.

- [ ] **Step 5: Commit**

```bash
git add js/collision/mesh-bvh.js tests/unit/mesh-bvh.test.mjs
git commit -m "$(cat <<'EOF'
feat(collision): capsule sweep against BVH for walking collision

Coarse but pragmatic: BVH-bbox-query plus closest-point-on-triangle-to-
segment with 5-sample subdivision along capsule axis. Independent X/Z
back-off clips destination XZ. Sufficient for FPS-speed walking, doesn't
zero motion at distance.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 10: persist.js — .obj writer + RLE pack (TDD)

**Files:**
- Create: `js/collision/persist.js`
- Create: `tests/unit/persist.test.mjs`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/persist.test.mjs`:

```js
import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  writeObj, rlePack, rleUnpack, encodeSidecar, decodeSidecar,
} from '../../js/collision/persist.js';

test('writeObj: single triangle round-trips through parser', () => {
  const positions = new Float32Array([0, 0, 0,  1, 0, 0,  0, 1, 0]);
  const normals   = new Float32Array([0, 0, 1,  0, 0, 1,  0, 0, 1]);
  const indices   = new Uint32Array([0, 1, 2]);
  const obj = writeObj({ positions, normals, indices });
  // Smoke checks: header + 3 vertices + 3 normals + 1 face line
  assert.match(obj, /^# autosplat-viewer collision mesh/);
  assert.equal((obj.match(/^v /gm) ?? []).length, 3);
  assert.equal((obj.match(/^vn /gm) ?? []).length, 3);
  assert.equal((obj.match(/^f /gm) ?? []).length, 1);
  // OBJ is 1-indexed.
  assert.match(obj, /^f 1\/\/1 2\/\/2 3\/\/3$/m);
});

test('rlePack / rleUnpack: round-trip with mixed runs', () => {
  const grid = new Float32Array([0, 0, 0, 1.5, 1.5, 2, 2, 2, 2, 0]);
  const packed = rlePack(grid);
  const out = rleUnpack(packed, grid.length);
  assert.equal(out.length, grid.length);
  for (let i = 0; i < grid.length; i++) {
    // packed values are quantised to 8-bit — allow ±0.05 tolerance for the
    // density range 0..10 (1 unit = ~0.039 after quantisation).
    assert.ok(Math.abs(out[i] - grid[i]) < 0.05, `idx ${i}: ${out[i]} vs ${grid[i]}`);
  }
});

test('encodeSidecar / decodeSidecar: full round-trip', () => {
  const density = new Float32Array(64);
  density[10] = 3.7; density[20] = 1.2;
  const bounds = { min: { x: -1, y: -1, z: -1 }, max: { x: 1, y: 1, z: 1 } };
  const json = encodeSidecar({ resolution: 4, bounds, iso: 1.5, density });
  const obj = JSON.parse(json);
  assert.equal(obj.version, 1);
  assert.equal(obj.resolution, 4);
  const round = decodeSidecar(json);
  assert.equal(round.resolution, 4);
  assert.equal(round.iso, 1.5);
  assert.deepEqual(round.bounds.min, bounds.min);
  assert.ok(Math.abs(round.density[10] - 3.7) < 0.05);
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./tests/run.sh unit`
Expected: import error.

- [ ] **Step 3: Write the implementation**

Create `js/collision/persist.js`:

```js
// persist.js — pure I/O helpers for the collision mesh: OBJ writer, RLE
// pack/unpack of the density grid, and the JSON sidecar codec.

const HEADER = '# autosplat-viewer collision mesh export\n';
const DENSITY_MAX = 10; // values above this clamp during 8-bit quantisation

export function writeObj({ positions, normals, indices }) {
  let out = HEADER;
  for (let i = 0; i < positions.length; i += 3) {
    out += `v ${fmt(positions[i])} ${fmt(positions[i + 1])} ${fmt(positions[i + 2])}\n`;
  }
  for (let i = 0; i < normals.length; i += 3) {
    out += `vn ${fmt(normals[i])} ${fmt(normals[i + 1])} ${fmt(normals[i + 2])}\n`;
  }
  for (let t = 0; t < indices.length; t += 3) {
    const a = indices[t] + 1, b = indices[t + 1] + 1, c = indices[t + 2] + 1;
    out += `f ${a}//${a} ${b}//${b} ${c}//${c}\n`;
  }
  return out;
}

function fmt(v) { return v.toFixed(6).replace(/\.?0+$/, ''); }

export function rlePack(density) {
  const out = [];
  let i = 0;
  while (i < density.length) {
    const q = quantise(density[i]);
    let n = 1;
    while (i + n < density.length && quantise(density[i + n]) === q) n++;
    out.push(n, q);
    i += n;
  }
  return out;
}

export function rleUnpack(packed, length) {
  const out = new Float32Array(length);
  let idx = 0;
  for (let p = 0; p < packed.length; p += 2) {
    const n = packed[p];
    const v = dequantise(packed[p + 1]);
    for (let k = 0; k < n; k++) out[idx++] = v;
  }
  return out;
}

function quantise(v) {
  const clamped = Math.max(0, Math.min(DENSITY_MAX, v));
  return Math.round((clamped / DENSITY_MAX) * 255);
}

function dequantise(q) {
  return (q / 255) * DENSITY_MAX;
}

export function encodeSidecar({ resolution, bounds, iso, density }) {
  return JSON.stringify({
    version: 1,
    resolution,
    bounds: {
      min: [bounds.min.x, bounds.min.y, bounds.min.z],
      max: [bounds.max.x, bounds.max.y, bounds.max.z],
    },
    iso,
    densityRLE: rlePack(density),
  });
}

export function decodeSidecar(json) {
  const obj = typeof json === 'string' ? JSON.parse(json) : json;
  if (obj.version !== 1) throw new Error(`unsupported sidecar version: ${obj.version}`);
  const length = obj.resolution ** 3;
  return {
    resolution: obj.resolution,
    bounds: {
      min: { x: obj.bounds.min[0], y: obj.bounds.min[1], z: obj.bounds.min[2] },
      max: { x: obj.bounds.max[0], y: obj.bounds.max[1], z: obj.bounds.max[2] },
    },
    iso: obj.iso,
    density: rleUnpack(obj.densityRLE, length),
  };
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `./tests/run.sh unit`
Expected: all `persist` tests pass.

- [ ] **Step 5: Commit**

```bash
git add js/collision/persist.js tests/unit/persist.test.mjs
git commit -m "$(cat <<'EOF'
feat(collision): persist helpers — OBJ writer, density RLE, sidecar JSON

8-bit quantised density (0..10 range), RLE-packed runs, sidecar v1 schema
stores bounds + iso + packed density. OBJ writer emits header + verts +
normals + 1-indexed face lines.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 11: editor.js — brush + undo ring (TDD)

**Files:**
- Create: `js/collision/editor.js`
- Create: `tests/unit/editor.test.mjs`

The editor is a pure state machine: it owns a voxel grid + an undo ring + a brush configuration; callers feed it world-space hit points and read back voxel diffs. It does **not** know about PlayCanvas or the DOM.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/editor.test.mjs`:

```js
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { CollisionEditor } from '../../js/collision/editor.js';

const bounds = { min: { x: 0, y: 0, z: 0 }, max: { x: 1, y: 1, z: 1 } };

function blank() {
  return new CollisionEditor({
    density: new Float32Array(8 ** 3),
    resolution: 8,
    bounds,
    iso: 1.5,
  });
}

test('editor: add-brush raises density inside radius', () => {
  const ed = blank();
  ed.beginStroke('add');
  ed.applyAt([0.5, 0.5, 0.5], 0.2, 5);
  ed.endStroke();
  // centre cell (4,4,4) should be increased
  const c = ed.density[4 * 64 + 4 * 8 + 4];
  assert.ok(c > 0, `centre density should be > 0, got ${c}`);
  // a far corner should still be zero
  assert.equal(ed.density[0], 0);
});

test('editor: remove-brush is the inverse of add (modulo clamp)', () => {
  const ed = blank();
  ed.beginStroke('add');
  ed.applyAt([0.5, 0.5, 0.5], 0.2, 5);
  ed.endStroke();
  const beforeRemove = ed.density.slice();
  ed.beginStroke('remove');
  ed.applyAt([0.5, 0.5, 0.5], 0.2, 5);
  ed.endStroke();
  // every cell touched by both strokes should now be ≤ its pre-add value
  for (let i = 0; i < ed.density.length; i++) {
    assert.ok(ed.density[i] <= beforeRemove[i] + 1e-6,
      `idx ${i}: ${ed.density[i]} > ${beforeRemove[i]}`);
    assert.ok(ed.density[i] >= 0);
  }
});

test('editor: undo restores pre-stroke density', () => {
  const ed = blank();
  const snapshot = ed.density.slice();
  ed.beginStroke('add');
  ed.applyAt([0.5, 0.5, 0.5], 0.2, 5);
  ed.endStroke();
  ed.undo();
  for (let i = 0; i < ed.density.length; i++) {
    assert.equal(ed.density[i], snapshot[i], `idx ${i}`);
  }
});

test('editor: undo ring is bounded to 8', () => {
  const ed = blank();
  for (let s = 0; s < 10; s++) {
    ed.beginStroke('add');
    ed.applyAt([0.5, 0.5, 0.5], 0.1, 1);
    ed.endStroke();
  }
  // 10 strokes pushed, only 8 retained → 8 undos must work, 9th is a no-op
  for (let u = 0; u < 8; u++) assert.equal(ed.undo(), true);
  assert.equal(ed.undo(), false);
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./tests/run.sh unit`
Expected: import error.

- [ ] **Step 3: Write the implementation**

Create `js/collision/editor.js`:

```js
// editor.js — pure brush + undo state machine over a flat voxel-density grid.
// No DOM, no PlayCanvas. Callers (collision-mode.js) feed it world-space hit
// points; the editor mutates `density` in place and records voxel diffs.

const UNDO_LIMIT = 8;

export class CollisionEditor {
  constructor({ density, resolution, bounds, iso }) {
    this.density = density;
    this.resolution = resolution;
    this.bounds = bounds;
    this.iso = iso;
    this._undoRing = [];
    this._currentStroke = null;
  }

  beginStroke(kind) {
    if (kind !== 'add' && kind !== 'remove') throw new Error(`bad stroke: ${kind}`);
    this._currentStroke = { kind, indices: [], deltas: [] };
  }

  /**
   * Apply the current brush at a world-space point. `radius` is world-space;
   * `strength` is the density addend at the brush centre. Falloff is
   * quadratic: weight = 1 - (d/r)².
   */
  applyAt(point, radius, strength) {
    if (!this._currentStroke) throw new Error('no active stroke');
    const r = this.resolution;
    const sx = (this.bounds.max.x - this.bounds.min.x) / r;
    const sy = (this.bounds.max.y - this.bounds.min.y) / r;
    const sz = (this.bounds.max.z - this.bounds.min.z) / r;
    const cx = (point[0] - this.bounds.min.x) / sx;
    const cy = (point[1] - this.bounds.min.y) / sy;
    const cz = (point[2] - this.bounds.min.z) / sz;
    const ri = Math.ceil(radius / sx);
    const rj = Math.ceil(radius / sy);
    const rk = Math.ceil(radius / sz);
    const sign = this._currentStroke.kind === 'add' ? 1 : -1;
    const stroke = this._currentStroke;

    for (let k = Math.max(0, Math.floor(cz - rk)); k <= Math.min(r - 1, Math.ceil(cz + rk)); k++) {
      for (let j = Math.max(0, Math.floor(cy - rj)); j <= Math.min(r - 1, Math.ceil(cy + rj)); j++) {
        for (let i = Math.max(0, Math.floor(cx - ri)); i <= Math.min(r - 1, Math.ceil(cx + ri)); i++) {
          // world-space distance from this cell centre to point
          const wx = this.bounds.min.x + (i + 0.5) * sx;
          const wy = this.bounds.min.y + (j + 0.5) * sy;
          const wz = this.bounds.min.z + (k + 0.5) * sz;
          const dx = wx - point[0], dy = wy - point[1], dz = wz - point[2];
          const d = Math.hypot(dx, dy, dz);
          if (d > radius) continue;
          const w = 1 - (d / radius) ** 2; // quadratic falloff
          const idx = k * r * r + j * r + i;
          const before = this.density[idx];
          let after = before + sign * strength * w;
          if (after < 0) after = 0;
          const delta = after - before;
          if (delta === 0) continue;
          this.density[idx] = after;
          stroke.indices.push(idx);
          stroke.deltas.push(delta);
        }
      }
    }
  }

  endStroke() {
    if (!this._currentStroke) return;
    if (this._currentStroke.indices.length > 0) {
      this._undoRing.push({
        indices: Int32Array.from(this._currentStroke.indices),
        deltas: Float32Array.from(this._currentStroke.deltas),
      });
      while (this._undoRing.length > UNDO_LIMIT) this._undoRing.shift();
    }
    this._currentStroke = null;
  }

  undo() {
    const stroke = this._undoRing.pop();
    if (!stroke) return false;
    for (let i = 0; i < stroke.indices.length; i++) {
      const idx = stroke.indices[i];
      this.density[idx] -= stroke.deltas[i];
      if (this.density[idx] < 0) this.density[idx] = 0;
    }
    return true;
  }

  setIso(iso) { this.iso = iso; }
  undoDepth() { return this._undoRing.length; }
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `./tests/run.sh unit`
Expected: all `editor` tests pass.

- [ ] **Step 5: Commit**

```bash
git add js/collision/editor.js tests/unit/editor.test.mjs
git commit -m "$(cat <<'EOF'
feat(collision): editor state machine — brush strokes + undo ring

Quadratic-falloff sphere brush, Add/Remove signs, voxel-diff undo ring
capped at 8 strokes. No DOM, no PlayCanvas — pure state.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 12: collision-mode.js — façade with PlayCanvas mesh-instance

**Files:**
- Create: `js/collision/collision-mode.js`

This is the integration layer. It owns the PlayCanvas mesh entity, runs the build pipeline on demand, exposes brush/undo/export/save methods to the UI, and reuses splat-position extraction from `walking.js`. No tests at this layer — it's thin glue and is covered by the e2e smoke test in Task 16.

- [ ] **Step 1: Write the module**

Create `js/collision/collision-mode.js`:

```js
// collision-mode.js — PlayCanvas integration for the collision-mesh editor.
// Lazy-loaded by viewer.js. Owns the mesh entity, drives the voxelize → MC
// pipeline, exposes the editor + persist surfaces to the UI layer.

import {
  Entity, Mesh, MeshInstance, StandardMaterial, BLEND_NORMAL, SEMANTIC_POSITION,
  SEMANTIC_NORMAL, VertexFormat, VertexBuffer, IndexBuffer, GraphicsDevice,
  Color, BUFFER_STATIC, INDEXFORMAT_UINT32, TYPE_FLOAT32, TYPE_UINT32,
  PRIMITIVE_TRIANGLES,
} from 'playcanvas';

import { voxelize, smoothDensity, defaultIso } from './voxelize.js';
import { marchingCubes } from './marching-cubes.js';
import { buildBvh, raycast } from './mesh-bvh.js';
import { CollisionEditor } from './editor.js';
import {
  writeObj, encodeSidecar, decodeSidecar,
} from './persist.js';

const RESOLUTION = 64;

export class CollisionMode {
  constructor({ app, camera, splatEntity, splatPivot, getSplatPositions }) {
    this.app = app;
    this.camera = camera;
    this.splatEntity = splatEntity;
    this.splatPivot = splatPivot;
    this.getSplatPositions = getSplatPositions; // () => { positions, bounds }

    this.editor = null;
    this.bvh = null;
    this.meshEntity = null;
    this._listeners = { built: [] };
  }

  /**
   * Build (or rebuild) the mesh from the loaded splat. Returns true on
   * success, false if no splat positions are available.
   */
  build() {
    const sp = this.getSplatPositions();
    if (!sp || !sp.positions || sp.positions.length === 0) return false;
    const { density } = voxelize(sp.positions, sp.bounds, RESOLUTION);
    const smoothed = smoothDensity(density, RESOLUTION);
    const iso = defaultIso(smoothed);
    this.editor = new CollisionEditor({
      density: smoothed,
      resolution: RESOLUTION,
      bounds: sp.bounds,
      iso,
    });
    this.rebuildMesh();
    return true;
  }

  /**
   * Load a sidecar — replaces the editor state entirely.
   */
  loadSidecar(json) {
    const { resolution, bounds, iso, density } = decodeSidecar(json);
    this.editor = new CollisionEditor({ density, resolution, bounds, iso });
    this.rebuildMesh();
  }

  /**
   * Apply one brush sample at a screen-space pointer position. If `continuing`
   * is true, the caller is mid-stroke (drag-brush) — beginStroke/endStroke
   * and the mesh-rebuild are the caller's responsibility, so the call is
   * cheap enough to run on every pointermove. If `continuing` is false (or
   * omitted), this is a one-shot stroke: begin + apply + end + rebuild.
   */
  applyBrushAt(screenX, screenY, kind, radius, strength, continuing = false) {
    if (!this.editor) return;
    const hit = this._raycastFromScreen(screenX, screenY);
    if (!hit) return;
    if (!continuing) {
      this.editor.beginStroke(kind);
      this.editor.applyAt(hit.point, radius, strength);
      this.editor.endStroke();
      this.rebuildMesh();
    } else {
      this.editor.applyAt(hit.point, radius, strength);
    }
  }

  setIso(iso) {
    if (!this.editor) return;
    this.editor.setIso(iso);
    this.rebuildMesh();
  }

  undo() {
    if (!this.editor) return;
    if (this.editor.undo()) this.rebuildMesh();
  }

  exportObj() {
    if (!this.lastMesh) return null;
    return writeObj(this.lastMesh);
  }

  exportSidecar() {
    if (!this.editor) return null;
    return encodeSidecar({
      resolution: this.editor.resolution,
      bounds: this.editor.bounds,
      iso: this.editor.iso,
      density: this.editor.density,
    });
  }

  onBuilt(fn) { this._listeners.built.push(fn); }

  /**
   * For walking-mode: return a collider strategy or null if no mesh exists.
   */
  getCollider() {
    if (!this.bvh) return null;
    return { kind: 'mesh', bvh: this.bvh, bounds: this.editor.bounds };
  }

  destroy() {
    if (this.meshEntity) {
      this.meshEntity.destroy();
      this.meshEntity = null;
    }
    this.editor = null;
    this.bvh = null;
    this.lastMesh = null;
  }

  // ---------- internals ----------

  rebuildMesh() {
    if (!this.editor) return;
    const mesh = marchingCubes({
      density: this.editor.density,
      resolution: this.editor.resolution,
      bounds: this.editor.bounds,
      iso: this.editor.iso,
    });
    this.lastMesh = mesh;
    this.bvh = buildBvh(mesh.positions, mesh.indices);
    this._updatePlayCanvasMesh(mesh);
    for (const fn of this._listeners.built) {
      try { fn({ triCount: mesh.indices.length / 3, iso: this.editor.iso }); }
      catch (e) { console.error(e); }
    }
  }

  _updatePlayCanvasMesh(mesh) {
    if (this.meshEntity) {
      this.meshEntity.destroy();
      this.meshEntity = null;
    }
    if (mesh.indices.length === 0) return;

    const device = this.app.graphicsDevice;
    const pcMesh = new Mesh(device);
    pcMesh.setPositions(mesh.positions);
    pcMesh.setNormals(mesh.normals);
    pcMesh.setIndices(mesh.indices);
    pcMesh.update(PRIMITIVE_TRIANGLES);

    const mat = new StandardMaterial();
    mat.diffuse = new Color(0.4, 0.7, 1.0);
    mat.opacity = 0.35;
    mat.blendType = BLEND_NORMAL;
    mat.useLighting = true;
    mat.update();

    const meshInstance = new MeshInstance(pcMesh, mat);
    const entity = new Entity('collision-mesh');
    entity.addComponent('render', { meshInstances: [meshInstance] });
    this.app.root.addChild(entity);
    this.meshEntity = entity;
  }

  _raycastFromScreen(screenX, screenY) {
    if (!this.bvh) return null;
    const canvas = this.app.graphicsDevice.canvas;
    const rect = canvas.getBoundingClientRect();
    const nx = ((screenX - rect.left) / rect.width) * 2 - 1;
    const ny = -(((screenY - rect.top) / rect.height) * 2 - 1);

    const camComp = this.camera.camera;
    const near = camComp.screenToWorld(screenX - rect.left, screenY - rect.top, camComp.nearClip);
    const far  = camComp.screenToWorld(screenX - rect.left, screenY - rect.top, camComp.farClip);
    const dir = [far.x - near.x, far.y - near.y, far.z - near.z];
    return raycast(this.bvh, [near.x, near.y, near.z], dir);
  }
}
```

- [ ] **Step 2: Manually verify the module loads without syntax errors**

Run: `node --input-type=module -e "import('./js/collision/collision-mode.js').then(() => console.log('ok')).catch(e => { console.error(e); process.exit(1); })"` from the repo root.

Note: this import will fail at runtime because `playcanvas` is not on the Node module path — that's expected. What you're verifying is that the parser accepts the file syntactically. If you see a `SyntaxError`, fix it. If you see `Cannot find module 'playcanvas'`, the file parses cleanly — continue.

- [ ] **Step 3: Run the unit test suite (sanity check)**

Run: `./tests/run.sh unit`
Expected: all unit tests still pass — `collision-mode.js` is not imported by any test yet.

- [ ] **Step 4: Commit**

```bash
git add js/collision/collision-mode.js
git commit -m "$(cat <<'EOF'
feat(collision): collision-mode facade with PlayCanvas integration

Lazy-loaded entry point. Drives voxelize → smooth → MC → BVH pipeline,
owns the mesh entity (translucent material, render component), exposes
build/undo/setIso/exportObj/exportSidecar to the UI.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 13: viewer.js — enterCollisionEditor / exitCollisionEditor

**Files:**
- Modify: `js/viewer.js`

- [ ] **Step 1: Read the current viewer.js to confirm line ranges**

Run: `wc -l js/viewer.js`
Expected: 228 lines (may grow slightly during this task — confirm before editing).

- [ ] **Step 2: Add helper to extract splat positions in world-space**

The walking-mode entry path already does this (in `js/walking.js#heightmapFromSplat`). Refactor that helper out so both modes can call it.

In `js/walking.js`, after the existing exports (around line 60), add:

```js
/**
 * Public helper: extract world-space splat positions + outlier-robust bounds.
 * Returns { positions: Float32Array, bounds } or null.
 */
export function splatWorldGeometry(splatEntity, splatPivot) {
  const root = splatPivot ?? splatEntity;
  const positions = extractSplatPositions(splatEntity);
  if (!positions || positions.length === 0) return null;
  const world = transformPositions(positions, root);
  const bounds = robustBounds(world);
  if (!bounds) return null;
  return { positions: world, bounds };
}
```

(`extractSplatPositions`, `transformPositions`, `robustBounds` are already defined in the same file / its imports.)

- [ ] **Step 3: Add collision-mode glue to viewer.js**

Insert after the walking-mode section (after `function exitWalking(input) { ... }`, before the final `return {` block) in `js/viewer.js`:

```js
  // ---------- Collision-editor glue ----------

  let collisionMode = null;
  const collisionEnterListeners = [];
  const collisionExitListeners = [];
  const collisionBuiltListeners = [];

  async function enterCollisionEditor() {
    if (collisionMode) return false;
    if (!splatEntity) throw new Error('no-splat-loaded');
    const [{ CollisionMode }, { splatWorldGeometry }] = await Promise.all([
      import('./collision/collision-mode.js'),
      import('./walking.js'),
    ]);
    collisionMode = new CollisionMode({
      app, camera, splatEntity, splatPivot,
      getSplatPositions: () => splatWorldGeometry(splatEntity, splatPivot),
    });
    collisionMode.onBuilt((info) => {
      for (const fn of collisionBuiltListeners) {
        try { fn(info); } catch (e) { console.error(e); }
      }
    });
    for (const fn of collisionEnterListeners) {
      try { fn({ mode: collisionMode }); } catch (e) { console.error(e); }
    }
    return true;
  }

  function exitCollisionEditor() {
    if (!collisionMode) return;
    collisionMode.destroy();
    collisionMode = null;
    for (const fn of collisionExitListeners) {
      try { fn(); } catch (e) { console.error(e); }
    }
  }

  function getCollisionMode() { return collisionMode; }
```

- [ ] **Step 4: Wire pointer-lock change to NOT exit walking when collision-editor is active**

Find the `lockChangeHandler` in `enterWalking` (currently around line 166). Replace:

```js
    lockChangeHandler = () => {
      if (document.pointerLockElement !== canvas && walkingMode) exitWalking(input);
    };
```

with:

```js
    lockChangeHandler = () => {
      if (document.pointerLockElement !== canvas && walkingMode) {
        // Don't auto-exit walking if the collision editor deliberately
        // released the lock for brush work.
        if (collisionMode && collisionMode._lockReleasedForBrush) return;
        exitWalking(input);
      }
    };
```

(The flag is set/cleared by the UI layer in Task 15.)

- [ ] **Step 5: Extend the returned API**

In the final `return { ... }` of `createViewer`, add (alphabetised with other listeners):

```js
    enterCollisionEditor,
    exitCollisionEditor,
    isCollisionEditor() { return collisionMode != null; },
    getCollisionMode,
    onCollisionEnter(fn) { collisionEnterListeners.push(fn); },
    onCollisionExit(fn)  { collisionExitListeners.push(fn); },
    onCollisionMeshBuilt(fn) { collisionBuiltListeners.push(fn); },
```

Also extend the WebGL2-unsupported fallback (top of `createViewer`) to add:

```js
      enterCollisionEditor: async () => false,
      exitCollisionEditor: () => {},
      isCollisionEditor: () => false,
      getCollisionMode: () => null,
      onCollisionEnter: () => {},
      onCollisionExit: () => {},
      onCollisionMeshBuilt: () => {},
```

(Inside the existing return-object literal in the WebGL2-fallback branch.)

- [ ] **Step 6: Run unit tests for regressions**

Run: `./tests/run.sh unit`
Expected: all unit tests still pass (no behaviour changes touched).

- [ ] **Step 7: Commit**

```bash
git add js/viewer.js js/walking.js
git commit -m "$(cat <<'EOF'
feat(collision): viewer.js entry points + walking.js splatWorldGeometry

Parallel pattern to enterWalking/exitWalking — lazy import of
collision-mode.js, listener registries for enter/exit/meshBuilt, fallback
no-ops for WebGL2-unsupported branch. lockChangeHandler now respects a
collision-editor brush-release flag.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 14: walking.js — setCollider() strategy

**Files:**
- Modify: `js/walking.js`

- [ ] **Step 1: Add setCollider() and a strategy-aware ground sample**

In the `WalkingMode` class in `js/walking.js`, find `_sampleGround()` (currently around line 252):

```js
  _sampleGround(x, z) {
    return sampleHeightmap(this.hm, this.bounds, x, z);
  }
```

Replace with:

```js
  setCollider(strategy) {
    // strategy: null | { kind: 'heightmap', hm, bounds }
    //               | { kind: 'mesh', bvh, bounds }
    this._collider = strategy ?? { kind: 'heightmap', hm: this.hm, bounds: this.bounds };
    if (strategy?.bounds) this.bounds = strategy.bounds;
  }

  _ensureCollider() {
    if (!this._collider) {
      this._collider = { kind: 'heightmap', hm: this.hm, bounds: this.bounds };
    }
    return this._collider;
  }

  _sampleGround(x, z) {
    const c = this._ensureCollider();
    if (c.kind === 'mesh') {
      // Cast a ray straight down from above the scene; return first hit's Y.
      const yHigh = this.bounds.max.y + 5;
      const hit = bvhRaycastDown(c.bvh, x, yHigh, z);
      if (hit) return hit.y;
      // fall back to heightmap if mesh has no surface here
      return sampleHeightmap(this.hm, this.bounds, x, z);
    }
    return sampleHeightmap(this.hm, this.bounds, x, z);
  }
```

- [ ] **Step 2: Add a local `bvhRaycastDown` helper at module scope**

In `js/walking.js`, near the top imports, add:

```js
import { raycast } from './collision/mesh-bvh.js';
```

And below the existing top-level helpers (after `transformPositions`), add:

```js
function bvhRaycastDown(bvh, x, yHigh, z) {
  const hit = raycast(bvh, [x, yHigh, z], [0, -1, 0]);
  if (!hit) return null;
  return { y: hit.point[1] };
}
```

- [ ] **Step 3: Apply capsule-sweep clipping in `_step()`**

In `_step()` (currently around line 285), find the block:

```js
    const pos = this.camera.getPosition();
    let nx = pos.x + fx;
    let nz = pos.z + fz;

    // soft clamp to scene bounds (Tier-2 "walls"). Fly mode keeps walls too —
    // they keep the user from drifting infinitely off-scene.
    if (nx < this.bounds.min.x) nx = this.bounds.min.x;
    if (nx > this.bounds.max.x) nx = this.bounds.max.x;
    if (nz < this.bounds.min.z) nz = this.bounds.min.z;
    if (nz > this.bounds.max.z) nz = this.bounds.max.z;
```

Insert *between* the two paragraphs (after the `nz = pos.z + fz` line and before the soft-clamp), add:

```js
    // Mesh-collider horizontal sweep: clip nx/nz against any wall triangles.
    const collider = this._ensureCollider();
    if (collider.kind === 'mesh' && (fx !== 0 || fz !== 0)) {
      // Lazy-imported at the top of the file.
      const r = this._eyeOffset / 3;
      const sweep = capsuleSweepImported(
        collider.bvh,
        [pos.x, pos.y - this._eyeOffset, pos.z],
        [nx,    pos.y - this._eyeOffset, nz],
        r, this._eyeOffset,
      );
      nx = sweep.endX;
      nz = sweep.endZ;
    }
```

And update the import line at the top of `walking.js`:

```js
import { raycast, capsuleSweep as capsuleSweepImported } from './collision/mesh-bvh.js';
```

(Aliased so the local hand-written `capsuleSweep` symbol — should there be one in future — doesn't collide.)

- [ ] **Step 4: Run unit tests**

Run: `./tests/run.sh unit`
Expected: all unit tests pass (walking has no unit tests beyond heightmap; this change is integration glue).

- [ ] **Step 5: Smoke-check the existing e2e walking test still passes**

Run: `./tests/run.sh e2e`
Expected: `tests/e2e/walking-smoke.test.mjs` passes — the heightmap path is unchanged by default.

- [ ] **Step 6: Commit**

```bash
git add js/walking.js
git commit -m "$(cat <<'EOF'
feat(collision): walking.js collider strategy + mesh sweep

setCollider() picks heightmap (default) or mesh strategy. Mesh path
raycasts straight down for ground-sample and capsule-sweeps for
horizontal-wall clipping. Heightmap fallback when ray misses.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 15: HUD + index.html + CSS — collision toolbar

**Files:**
- Modify: `js/hud.js`
- Modify: `index.html`
- Modify: `css/main.css` (or whichever existing CSS file holds stage-controls styles)

- [ ] **Step 1: Identify the CSS file holding stage-controls styles**

Run: `grep -ln 'stage-controls' css/*.css`
Note the filename (likely `css/main.css`) and continue.

- [ ] **Step 2: Add the toolbar HTML to `index.html`**

In `index.html`, find the `#stage-controls` block (the container with the Auto-orbit / Reset / Fullscreen buttons). Add a sibling button for entering collision mode:

```html
<button id="btn-collision" type="button" aria-pressed="false"
        aria-label="Toggle collision editor">⬛ Collider</button>
```

After `#stage-controls`'s closing tag and inside `#stage`, add the toolbar element (hidden by default):

```html
<aside id="collision-toolbar" hidden aria-label="Collision editor">
  <h3>Collision editor</h3>
  <button id="coll-build" type="button">Build from splats</button>
  <fieldset>
    <legend>Tool</legend>
    <label><input type="radio" name="coll-tool" value="view" checked> View</label>
    <label><input type="radio" name="coll-tool" value="add"> Add</label>
    <label><input type="radio" name="coll-tool" value="remove"> Remove</label>
  </fieldset>
  <label>Brush <input id="coll-brush" type="range" min="0.05" max="2" step="0.05" value="0.3"></label>
  <label>Iso <input id="coll-iso" type="range" min="0.5" max="8" step="0.1" value="1.5"></label>
  <div class="coll-row">
    <button id="coll-undo" type="button">Undo</button>
    <button id="coll-reset" type="button">Reset</button>
  </div>
  <div class="coll-row">
    <button id="coll-export-obj" type="button">Export .obj</button>
    <button id="coll-save" type="button">Save .json</button>
  </div>
  <p id="coll-status" aria-live="polite">No mesh.</p>
</aside>
```

- [ ] **Step 3: Add CSS for the toolbar**

In `css/main.css` (or the file from Step 1), append:

```css
#collision-toolbar {
  position: absolute;
  right: max(env(safe-area-inset-right), 1rem);
  top: 5rem;
  width: 18rem;
  max-width: calc(100vw - 2rem);
  padding: 0.8rem;
  background: rgba(14, 15, 19, 0.92);
  color: #d8dee9;
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 0.5rem;
  font: 0.85rem/1.4 system-ui, sans-serif;
  display: flex;
  flex-direction: column;
  gap: 0.55rem;
  z-index: 5;
}
#collision-toolbar h3 { margin: 0 0 0.25rem; font-size: 0.95rem; }
#collision-toolbar fieldset {
  margin: 0;
  padding: 0.35rem 0.5rem;
  border: 1px solid rgba(255, 255, 255, 0.1);
  border-radius: 0.3rem;
  display: flex; gap: 0.6rem; flex-wrap: wrap;
}
#collision-toolbar fieldset legend { padding: 0 0.3rem; }
#collision-toolbar label { display: flex; align-items: center; gap: 0.35rem; }
#collision-toolbar .coll-row { display: flex; gap: 0.5rem; }
#collision-toolbar .coll-row button { flex: 1; }
#collision-toolbar button {
  padding: 0.4rem 0.5rem;
  background: rgba(255, 255, 255, 0.05);
  color: inherit;
  border: 1px solid rgba(255, 255, 255, 0.12);
  border-radius: 0.3rem;
  cursor: pointer;
}
#collision-toolbar button:hover { background: rgba(255, 255, 255, 0.1); }
#collision-toolbar #coll-status {
  margin: 0;
  font-size: 0.75rem;
  color: rgba(255, 255, 255, 0.6);
}
@media (max-width: 600px) {
  #collision-toolbar {
    right: 0; left: 0; bottom: 0; top: auto;
    width: 100%; max-width: 100%;
    border-radius: 0.5rem 0.5rem 0 0;
    padding-bottom: max(env(safe-area-inset-bottom), 0.8rem);
  }
}
```

- [ ] **Step 4: Add HUD methods**

In `js/hud.js`, append a section after `setEyeHeight()`:

```js
  // ---------- Collision editor ----------

  enterCollisionUI(handlers) {
    this._collisionHandlers = handlers;
    const t = this.stage.querySelector('#collision-toolbar');
    if (!t) return;
    t.hidden = false;
    // Wire once — these handlers re-read state on each event, so re-wiring
    // would just leak listeners.
    if (!this._collisionWired) {
      t.querySelector('#coll-build')?.addEventListener('click', () => handlers.onBuild?.());
      t.querySelector('#coll-undo')?.addEventListener('click', () => handlers.onUndo?.());
      t.querySelector('#coll-reset')?.addEventListener('click', () => handlers.onReset?.());
      t.querySelector('#coll-export-obj')?.addEventListener('click', () => handlers.onExportObj?.());
      t.querySelector('#coll-save')?.addEventListener('click', () => handlers.onSaveSidecar?.());
      t.querySelector('#coll-iso')?.addEventListener('input', (e) =>
        handlers.onIsoChange?.(parseFloat(e.target.value)));
      t.querySelectorAll('input[name="coll-tool"]').forEach((r) =>
        r.addEventListener('change', (e) => handlers.onToolChange?.(e.target.value)));
      this._collisionWired = true;
    }
  }

  exitCollisionUI() {
    const t = this.stage.querySelector('#collision-toolbar');
    if (t) t.hidden = true;
    this._collisionHandlers = null;
  }

  setCollisionStatus(text) {
    const s = this.stage.querySelector('#coll-status');
    if (s) s.textContent = text;
  }

  getCollisionTool() {
    const r = this.stage.querySelector('input[name="coll-tool"]:checked');
    return r?.value ?? 'view';
  }

  getCollisionBrushSize() {
    const r = this.stage.querySelector('#coll-brush');
    return r ? parseFloat(r.value) : 0.3;
  }
```

- [ ] **Step 5: Run unit tests**

Run: `./tests/run.sh unit`
Expected: all pass (this task is DOM/CSS only).

- [ ] **Step 6: Commit**

```bash
git add js/hud.js index.html css/main.css
git commit -m "$(cat <<'EOF'
feat(collision): HUD toolbar + button + safe-area-aware CSS

Right-rail toolbar on desktop, bottom-sheet on mobile (≤600px). Tool
radios (View/Add/Remove), brush + iso sliders, action buttons (Build/
Undo/Reset/Export/Save), status line. HUD wires once per session.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 16: app.js — wire toggle + brush events

**Files:**
- Modify: `js/app.js`

- [ ] **Step 1: Add the wiring after the walking-mode wiring section**

In `js/app.js`, after the walking-mode wiring (after the last `viewer.onLoad?.(...)`/canvas-host click handler), add:

```js
// ---------- Collision-editor wiring ----------

const btnCollision = document.getElementById('btn-collision');

function syncCollisionButton() {
  const on = viewer.isCollisionEditor?.();
  btnCollision?.setAttribute('aria-pressed', String(!!on));
  if (btnCollision) {
    btnCollision.textContent = on ? '⬛ Exit collider' : '⬛ Collider';
  }
}

btnCollision?.addEventListener('click', async () => {
  if (viewer.isCollisionEditor?.()) {
    viewer.exitCollisionEditor?.();
    return;
  }
  try {
    await viewer.enterCollisionEditor?.();
  } catch (err) {
    console.error('[collision] enter failed:', err);
    showError('Load a splat before opening the collision editor.');
  }
});
setInterval(syncCollisionButton, 500);

viewer.onCollisionEnter?.(({ mode }) => {
  hud.enterCollisionUI({
    onBuild: () => {
      if (!mode.build()) showError('No usable splat geometry to mesh.');
    },
    onUndo: () => mode.undo(),
    onReset: () => mode.build(),
    onExportObj: () => downloadString(mode.exportObj(), 'collider.obj', 'text/plain'),
    onSaveSidecar: () => downloadString(mode.exportSidecar(), 'collider.collision.json', 'application/json'),
    onIsoChange: (v) => mode.setIso(v),
    onToolChange: (v) => {
      // Brush tools release pointer-lock so the cursor can interact.
      if (v === 'add' || v === 'remove') {
        if (document.pointerLockElement && document.exitPointerLock) {
          mode._lockReleasedForBrush = true;
          document.exitPointerLock();
        }
      } else {
        mode._lockReleasedForBrush = false;
      }
    },
  });
  syncCollisionButton();
});

viewer.onCollisionExit?.(() => {
  hud.exitCollisionUI();
  syncCollisionButton();
});

viewer.onCollisionMeshBuilt?.(({ triCount, iso }) => {
  hud.setCollisionStatus(`${triCount.toLocaleString()} tris · iso ${iso.toFixed(2)}`);
});

// Brush input: pointerdown starts a stroke that continues while the pointer
// moves, ends on pointerup. Single stroke = single undo step. The UI is the
// source of truth for tool + brush size on every event.
const canvasHost = document.getElementById('canvas-host');
let strokeActive = false;

function strokeKindNow() {
  const t = hud.getCollisionTool();
  return (t === 'add' || t === 'remove') ? t : null;
}

canvasHost?.addEventListener('pointerdown', (e) => {
  const mode = viewer.getCollisionMode?.();
  if (!mode || !mode.editor) return;
  const kind = strokeKindNow();
  if (!kind) return;
  e.preventDefault();
  canvasHost.setPointerCapture?.(e.pointerId);
  mode.editor.beginStroke(kind);
  strokeActive = true;
  mode.applyBrushAt(e.clientX, e.clientY, kind, hud.getCollisionBrushSize(), 3, /*continuing=*/true);
});

canvasHost?.addEventListener('pointermove', (e) => {
  if (!strokeActive) return;
  const mode = viewer.getCollisionMode?.();
  if (!mode) return;
  mode.applyBrushAt(e.clientX, e.clientY, strokeKindNow(), hud.getCollisionBrushSize(), 3, /*continuing=*/true);
});

function endStroke(e) {
  if (!strokeActive) return;
  strokeActive = false;
  const mode = viewer.getCollisionMode?.();
  if (mode && mode.editor) {
    mode.editor.endStroke();
    // Single mesh rebuild at stroke end — far cheaper than per-move rebuild.
    mode.rebuildMesh();
  }
  if (e?.pointerId != null) canvasHost?.releasePointerCapture?.(e.pointerId);
}
canvasHost?.addEventListener('pointerup', endStroke);
canvasHost?.addEventListener('pointercancel', endStroke);

function downloadString(text, filename, mime) {
  if (text == null) return;
  const blob = new Blob([text], { type: mime });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
```

- [ ] **Step 2: Run unit tests**

Run: `./tests/run.sh unit`
Expected: all pass.

- [ ] **Step 3: Manual smoke test in browser**

Run: `./serve.sh` (or `python3 -m http.server 8000` if the script doesn't exist), open <http://localhost:8000>, wait for the demo splat to load, then:

1. Click "⬛ Collider" → toolbar appears.
2. Click "Build from splats" → mesh appears overlaid (translucent blue), status shows tri-count.
3. Select "Remove", click on a part of the mesh → that area dents/disappears.
4. Click "Undo" → previous state returns.
5. Click "Export .obj" → file downloads.
6. Click "Save .json" → file downloads.
7. Click "⬛ Exit collider" → toolbar hides, mesh removed.

If any step fails, fix it before committing.

- [ ] **Step 4: Commit**

```bash
git add js/app.js
git commit -m "$(cat <<'EOF'
feat(collision): app.js wiring — toggle, brush events, download helpers

Pointer-down on canvas drives the brush, tool radio releases pointer-
lock so the cursor can interact. Mesh-built handler updates the HUD
status line. Download helper for OBJ + sidecar JSON.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 17: dropzone.js — accept .collision.json

**Files:**
- Modify: `js/dropzone.js`
- Modify: `js/app.js` (to route the sidecar drop)

- [ ] **Step 1: Read dropzone.js**

Run: `cat js/dropzone.js`
Confirm the current accepted-extension logic.

- [ ] **Step 2: Update dropzone.js**

Replace the file-acceptance logic so `.collision.json` is recognised alongside `.ply`. The current dropzone uses `onFile(file, badName)` — extend it to a second callback `onSidecar(text)`.

Specifically, in `js/dropzone.js`, change the `initDropzone({stage, hint, fileInput, openButton, onFile})` signature to `initDropzone({stage, hint, fileInput, openButton, onFile, onSidecar})`. In the file-dispatch logic, branch on extension:

```js
async function handleFile(file) {
  if (!file) return;
  const name = file.name.toLowerCase();
  if (name.endsWith('.collision.json')) {
    if (onSidecar) {
      const text = await file.text();
      onSidecar(text);
    }
    return;
  }
  if (name.endsWith('.ply') || name.endsWith('.sog')) {
    onFile(file);
    return;
  }
  onFile(null, file.name);
}
```

Use this `handleFile` from all the existing entry points (drop, file-input change). Keep the rest of the file's UI feedback unchanged.

(If the current dropzone doesn't have a single dispatcher, factor one out as part of this change — the new branch is the same for every input path.)

- [ ] **Step 3: Route the sidecar in app.js**

In `js/app.js`, update the `initDropzone({...})` call to pass `onSidecar`:

```js
initDropzone({
  stage: document.getElementById('stage'),
  hint: document.getElementById('drop-hint'),
  fileInput: document.getElementById('file-input'),
  openButton: document.getElementById('btn-load'),
  onFile: (file, badName) => {
    if (file) load(file);
    else showError(`Unsupported: ${badName} — only .ply is allowed`);
  },
  onSidecar: async (text) => {
    if (!viewer.isCollisionEditor?.()) {
      try { await viewer.enterCollisionEditor?.(); }
      catch { showError('Load a splat before dropping a sidecar.'); return; }
    }
    const mode = viewer.getCollisionMode?.();
    try { mode?.loadSidecar(text); }
    catch (err) {
      console.error('[collision] sidecar load failed:', err);
      showError('Sidecar load failed — file format may be wrong.');
    }
  },
});
```

- [ ] **Step 4: Run unit tests**

Run: `./tests/run.sh unit`
Expected: all pass.

- [ ] **Step 5: Manual smoke test**

1. Save a sidecar (from Task 16's manual test).
2. Reload the page.
3. Drag the saved `.collision.json` onto the viewer.
4. Expected: collision editor opens automatically, mesh appears.

- [ ] **Step 6: Commit**

```bash
git add js/dropzone.js js/app.js
git commit -m "$(cat <<'EOF'
feat(collision): dropzone accepts .collision.json sidecars

Drop opens the collision editor (if not open) and loads the mesh.
Unknown extensions still produce the existing 'Unsupported' error.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 18: E2E smoke test for collision editor

**Files:**
- Create: `tests/e2e/collision-smoke.test.mjs`

Mirror the existing `walking-smoke.test.mjs` style.

- [ ] **Step 1: Read the existing e2e test to match style**

Run: `cat tests/e2e/walking-smoke.test.mjs`
Note: setup helpers (server start, browser launch, page open), selectors used, timeout values.

- [ ] **Step 2: Write the e2e test**

Create `tests/e2e/collision-smoke.test.mjs` mirroring the walking smoke-test's structure. The body should:

```js
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import puppeteer from 'puppeteer-core';

// Reuse the helper pattern from walking-smoke.test.mjs — extract anything
// shared into a sibling helpers.mjs file if not already done.

test('collision editor: toggle → build → undo → exit', async () => {
  // 1. start the dev server
  // 2. launch puppeteer-core against the system Chrome
  // 3. await page goto / wait for demo splat to load
  // 4. click #btn-collision → assert #collision-toolbar visible
  // 5. click #coll-build → wait for #coll-status to update (poll up to 5s)
  //    assert it contains 'tris'
  // 6. click #coll-undo → status updates (no-op on first build, just sanity)
  // 7. click #btn-collision (now 'Exit collider') → toolbar hidden
  // 8. teardown
});
```

Use the exact selectors introduced in Task 15 (`#btn-collision`, `#collision-toolbar`, `#coll-build`, `#coll-status`, `#coll-undo`). Mirror the server-start / browser-launch helpers from `walking-smoke.test.mjs` — if those are inline in that file, copy them; if extracted to a helpers module, import them.

For the status-wait, poll up to 5 seconds:

```js
async function waitForStatusContains(page, substr, timeoutMs = 5000) {
  const start = Date.now();
  while (Date.now() - start < timeoutMs) {
    const txt = await page.$eval('#coll-status', el => el.textContent);
    if (txt.includes(substr)) return txt;
    await new Promise(r => setTimeout(r, 100));
  }
  throw new Error(`#coll-status never contained "${substr}"`);
}
```

- [ ] **Step 3: Run e2e tests**

Run: `./tests/run.sh e2e`
Expected: both `walking-smoke` and `collision-smoke` pass.

If puppeteer-core can't find Chrome, set `PUPPETEER_EXECUTABLE_PATH` env var per the existing test's setup (check how `walking-smoke.test.mjs` handles this).

- [ ] **Step 4: Commit**

```bash
git add tests/e2e/collision-smoke.test.mjs
git commit -m "$(cat <<'EOF'
test(collision): e2e smoke test for collision-editor toggle + build

Toggles the editor, runs Build, polls the status line until tri-count
appears, clicks Undo, exits. Mirrors walking-smoke.test.mjs.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 19: README + CHANGELOG + AGENTS.md updates

**Files:**
- Modify: `README.md`
- Modify: `CHANGELOG.md`
- Modify: `AGENTS.md`

- [ ] **Step 1: Add a feature-table row in README.md**

In `README.md`, find the feature/highlights table. Add a row like:

```markdown
| **Collision editor** | Extract a triangle mesh from the splat (marching cubes on a voxel-density grid), brush-edit it, export as `.obj`, save/reload via JSON sidecar. Optional walking-mode collider. |
```

(Adjust column count to match the existing table — read it first.)

- [ ] **Step 2: Add an Unreleased entry in CHANGELOG.md**

In `CHANGELOG.md`, under `## [Unreleased]` (create the section if missing), add:

```markdown
### Added
- Collision editor (slice 1): extract a triangle mesh from the loaded splat
  via marching cubes on a 64³ voxel-density grid, voxel-brush edit it
  (Add/Remove + iso slider), export as `.obj`, save/load via JSON sidecar.
  Optional walking-mode collider replaces the heightmap when a mesh exists.
```

- [ ] **Step 3: Document the new module in AGENTS.md**

In `AGENTS.md`, in the **Architecture notes** section, after the **Walking-mode** bullet, add:

```markdown
- **Collision editor** (`js/collision/*.js`) is loaded lazily via dynamic
  import in `viewer.js#enterCollisionEditor` — not part of the initial
  shell. The editor owns a voxel-density grid (64³) and runs marching
  cubes (Bourke tables in `mc-tables.js`) to produce a translucent mesh
  overlay. `walking.js` can opt in to using the mesh as a collider via
  `walkingMode.setCollider({ kind: 'mesh', bvh, bounds })`.
```

- [ ] **Step 4: Run the full test suite**

Run: `./tests/run.sh all`
Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add README.md CHANGELOG.md AGENTS.md
git commit -m "$(cat <<'EOF'
docs: collision editor — README/CHANGELOG/AGENTS notes

Feature-table row, Unreleased changelog entry, AGENTS architecture
note (lazy-load + voxel-grid + walking collider hook).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Final verification

- [ ] Run `./tests/run.sh all` from the repo root — every test passes.
- [ ] Run `./serve.sh` and walk the manual checklist from Task 16 Step 3 once more (build, brush, undo, export, save, reload-and-drop sidecar, walking with mesh collider).
- [ ] Check the git log — every task has its own commit, each commit references the slice or component (`feat(collision): …`, `test(collision): …`, `docs: …`).
- [ ] Open the OBJ export in a separate viewer (Blender, MeshLab, or `https://3dviewer.net/`) — the mesh imports correctly with normals.

The implementation is complete when all of the above check out.
