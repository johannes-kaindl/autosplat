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
