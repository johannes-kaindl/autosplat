// splat-data.js — pure (PlayCanvas-free) helpers for reading positions out
// of a freshly loaded gsplat entity. Kept separate from walking.js so it
// is unit-testable without mocking the PC ESM bundle.
//
// PC 2.18 stores per-component state on underscore-prefixed fields; the
// authoritative location for splat positions is:
//   entity.gsplat._instance.resource.centers     (Float32Array, interleaved xyz)
//   entity.gsplat._instance.resource.gsplatData  ({ getProp, numSplats, ... })
//
// `.asset.resource` is null until the asset reaches a different state machine
// step, but `_instance.resource` is the live runtime resource and is what
// the renderer itself reads. Discovered via runtime entity dump 2026-05-27.

/**
 * Pull a flat Float32Array of model-space positions (x0,y0,z0,x1,y1,z1,...)
 * out of a PlayCanvas gsplat entity. Returns null if no usable data is yet
 * reachable — caller should treat that as "splat not ready" and prompt the
 * user to retry.
 */
export function extractSplatPositions(splatEntity) {
  const res = splatEntity?.gsplat?._instance?.resource;
  if (!res) return null;

  // Fast path: PC 2.18 keeps an interleaved xyz centers buffer for the
  // sorter. Shared reference — DO NOT mutate. transformPositions copies
  // into a fresh buffer before world-space transforms anyway.
  if (res.centers instanceof Float32Array && res.centers.length > 0) {
    return res.centers;
  }

  // Public API fallback (more version-stable, ~57ms for 9M splats).
  const gd = res.gsplatData;
  const posX = gd?.getProp?.('x');
  const posY = gd?.getProp?.('y');
  const posZ = gd?.getProp?.('z');
  if (posX && posY && posZ && posX.length > 0) {
    const n = posX.length;
    const out = new Float32Array(n * 3);
    for (let i = 0; i < n; i++) {
      out[i * 3] = posX[i];
      out[i * 3 + 1] = posY[i];
      out[i * 3 + 2] = posZ[i];
    }
    return out;
  }

  return null;
}

/**
 * Lift model-space positions into world space using an entity's world
 * transform. Only `getWorldTransform().data` is read, so this stays free of
 * PlayCanvas types and testable in plain node.
 */
export function transformPositions(local, entity) {
  const m = entity.getWorldTransform();
  const d = m.data;  // column-major: see PlayCanvas Mat4
  const out = new Float32Array(local.length);
  for (let i = 0; i < local.length; i += 3) {
    const x = local[i], y = local[i + 1], z = local[i + 2];
    out[i]     = d[0] * x + d[4] * y + d[8]  * z + d[12];
    out[i + 1] = d[1] * x + d[5] * y + d[9]  * z + d[13];
    out[i + 2] = d[2] * x + d[6] * y + d[10] * z + d[14];
  }
  return out;
}

export function boundsFromPositions(positions) {
  let minX = Infinity, minY = Infinity, minZ = Infinity;
  let maxX = -Infinity, maxY = -Infinity, maxZ = -Infinity;
  for (let i = 0; i < positions.length; i += 3) {
    const x = positions[i], y = positions[i + 1], z = positions[i + 2];
    if (x < minX) minX = x; if (x > maxX) maxX = x;
    if (y < minY) minY = y; if (y > maxY) maxY = y;
    if (z < minZ) minZ = z; if (z > maxZ) maxZ = z;
  }
  return {
    min: { x: minX, y: minY, z: minZ },
    max: { x: maxX, y: maxY, z: maxZ },
  };
}
