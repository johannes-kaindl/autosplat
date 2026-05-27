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

function fmt(v) {
  // Six decimals is overkill for collision meshes; strip trailing zeros so
  // .obj files compress better and diff cleanly.
  const s = v.toFixed(6);
  return s.includes('.') ? s.replace(/0+$/, '').replace(/\.$/, '') : s;
}

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
