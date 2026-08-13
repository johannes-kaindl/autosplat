// import-collider.js — turn an externally authored collision mesh (OBJ) into
// the collider strategy walking.js consumes. PlayCanvas-free on purpose: the
// only thing it needs from the scene is the world transform of the splat
// pivot, so it stays unit-testable.
//
// Why the transform matters: the OBJ is authored in the splat's *model*
// space (blender-lab writes it back into original splat coordinates), while
// walking.js reasons in world space. Skipping this step leaves the mesh
// sitting beside the scene instead of on top of it.

import { readObj } from './persist.js';
import { buildBvh } from './mesh-bvh.js';
import { transformPositions, boundsFromPositions } from '../splat-data.js';

export function buildImportedCollider(objText, worldEntity) {
  const { positions, indices } = readObj(objText);
  if (indices.length === 0) return null;
  const world = transformPositions(positions, worldEntity);
  return {
    kind: 'mesh',
    bvh: buildBvh(world, indices),
    bounds: boundsFromPositions(world),
    triangles: indices.length / 3,
    // Kept so the mesh can be drawn for a visual check — an imported collider
    // that sits beside the scene instead of on it is otherwise invisible.
    mesh: { positions: world, normals: flatNormals(world, indices), indices },
  };
}

/**
 * Which collider walking-mode should use. An imported mesh always wins: the
 * user went out of their way to supply it. `null` means neither exists, and
 * walking.js falls back to its heightmap.
 */
export function pickCollider(imported, voxelised) {
  return imported ?? voxelised ?? null;
}

/**
 * Per-vertex normals accumulated from face normals. Computed here rather than
 * via the engine's helper so this module stays dependency-free (and so the
 * OBJ's missing `vn` records cost nothing).
 */
function flatNormals(positions, indices) {
  const out = new Float32Array(positions.length);
  for (let t = 0; t < indices.length; t += 3) {
    const a = indices[t] * 3, b = indices[t + 1] * 3, c = indices[t + 2] * 3;
    const ux = positions[b] - positions[a];
    const uy = positions[b + 1] - positions[a + 1];
    const uz = positions[b + 2] - positions[a + 2];
    const vx = positions[c] - positions[a];
    const vy = positions[c + 1] - positions[a + 1];
    const vz = positions[c + 2] - positions[a + 2];
    const nx = uy * vz - uz * vy;
    const ny = uz * vx - ux * vz;
    const nz = ux * vy - uy * vx;
    for (const i of [a, b, c]) {
      out[i] += nx; out[i + 1] += ny; out[i + 2] += nz;
    }
  }
  for (let i = 0; i < out.length; i += 3) {
    const len = Math.hypot(out[i], out[i + 1], out[i + 2]);
    if (len > 0) { out[i] /= len; out[i + 1] /= len; out[i + 2] /= len; }
  }
  return out;
}
