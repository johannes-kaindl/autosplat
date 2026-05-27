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
