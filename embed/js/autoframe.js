// Pure percentile framing math — no engine imports, unit-testable in node.
// centers: flat [x0,y0,z0, x1,y1,z1, …] array-like of splat center positions.
export function frameBounds(centers, { pct = 0.025, maxSamples = 60000 } = {}) {
  const n = Math.floor(centers.length / 3);
  if (n === 0) return null;

  const step = Math.max(1, Math.floor(n / maxSamples));
  const xs = [], ys = [], zs = [];
  for (let i = 0; i < n; i += step) {
    xs.push(centers[i * 3]); ys.push(centers[i * 3 + 1]); zs.push(centers[i * 3 + 2]);
  }

  const q = (arr, t) => {
    arr.sort((a, b) => a - b);
    return arr[Math.min(arr.length - 1, Math.max(0, Math.floor(t * (arr.length - 1))))];
  };
  const lo = [q(xs, pct), q(ys, pct), q(zs, pct)];
  const hi = [q(xs, 1 - pct), q(ys, 1 - pct), q(zs, 1 - pct)];
  const center = [(lo[0] + hi[0]) / 2, (lo[1] + hi[1]) / 2, (lo[2] + hi[2]) / 2];
  const radius = Math.max(
    (hi[0] - lo[0]) / 2, (hi[1] - lo[1]) / 2, (hi[2] - lo[2]) / 2, 0.5);
  return { lo, hi, center, radius };
}
