// heightmap.js — turn a Gaussian-Splat point cloud into a sample-able ground
// surface for walking-mode collision. Pure module, no DOM or PlayCanvas deps.
//
// Grid layout: row-major Float32Array of length resolution*resolution, indexed
// as grid[j*resolution + i] where i is the X-bin and j is the Z-bin. Empty
// cells hold -Infinity so callers can detect "no ground here".

const EMPTY = -Infinity;

export function buildHeightmap(positions, bounds, resolution = 128) {
  const grid = new Float32Array(resolution * resolution);
  grid.fill(EMPTY);
  const sx = bounds.max.x - bounds.min.x;
  const sz = bounds.max.z - bounds.min.z;
  if (sx <= 0 || sz <= 0) return { grid, resolution };
  const minX = bounds.min.x, minZ = bounds.min.z;
  const n = (positions.length / 3) | 0;
  for (let p = 0; p < n; p++) {
    const x = positions[p * 3];
    const y = positions[p * 3 + 1];
    const z = positions[p * 3 + 2];
    let i = Math.floor((x - minX) / sx * resolution);
    let j = Math.floor((z - minZ) / sz * resolution);
    if (i < 0 || i > resolution || j < 0 || j > resolution) continue;
    if (i === resolution) i--;
    if (j === resolution) j--;
    const idx = j * resolution + i;
    if (y > grid[idx]) grid[idx] = y;
  }
  return { grid, resolution };
}

export function smoothHeightmap(hm) {
  const { grid, resolution } = hm;
  const out = new Float32Array(grid.length);
  for (let j = 0; j < resolution; j++) {
    for (let i = 0; i < resolution; i++) {
      let sum = 0;
      let count = 0;
      for (let dj = -1; dj <= 1; dj++) {
        for (let di = -1; di <= 1; di++) {
          const ni = i + di;
          const nj = j + dj;
          if (ni < 0 || ni >= resolution || nj < 0 || nj >= resolution) continue;
          const v = grid[nj * resolution + ni];
          if (v !== EMPTY) {
            sum += v;
            count++;
          }
        }
      }
      out[j * resolution + i] = count === 0 ? EMPTY : sum / count;
    }
  }
  return { grid: out, resolution };
}

export function sampleHeightmap(hm, bounds, x, z) {
  if (x < bounds.min.x || x > bounds.max.x ||
      z < bounds.min.z || z > bounds.max.z) {
    return EMPTY;
  }
  const { grid, resolution } = hm;
  const sx = bounds.max.x - bounds.min.x;
  const sz = bounds.max.z - bounds.min.z;
  // Cell (i, j) covers world range [i, i+1) × [j, j+1) in grid units;
  // its centre sits at grid-coords (i+0.5, j+0.5). Shift by -0.5 so the four
  // bilinear corners straddle the sample point properly.
  const gx = (x - bounds.min.x) / sx * resolution - 0.5;
  const gz = (z - bounds.min.z) / sz * resolution - 0.5;
  const i0 = Math.max(0, Math.floor(gx));
  const j0 = Math.max(0, Math.floor(gz));
  const i1 = Math.min(resolution - 1, i0 + 1);
  const j1 = Math.min(resolution - 1, j0 + 1);
  const fx = Math.max(0, Math.min(1, gx - i0));
  const fz = Math.max(0, Math.min(1, gz - j0));
  const a = grid[j0 * resolution + i0];
  const b = grid[j0 * resolution + i1];
  const c = grid[j1 * resolution + i0];
  const d = grid[j1 * resolution + i1];
  if (a === EMPTY || b === EMPTY || c === EMPTY || d === EMPTY) return EMPTY;
  const ab = a * (1 - fx) + b * fx;
  const cd = c * (1 - fx) + d * fx;
  return ab * (1 - fz) + cd * fz;
}
