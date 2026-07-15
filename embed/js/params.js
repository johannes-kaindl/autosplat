// Pure URL-parameter parsing for the embed page — unit-testable in node.
export function parseParams(search) {
  const q = new URLSearchParams(search);
  const src = (q.get('src') || '').trim() || null;
  const poster = (q.get('poster') || '').trim() || null;
  const autoplay = q.get('autoplay') === '1';
  const orbit = q.get('orbit') !== '0';
  const authoring = q.get('authoring') === '1';
  const pose = parsePose(q.get('pose'));
  const filename = src
    ? (src.split('?')[0].split('#')[0].split('/').pop() || 'scene.sog')
    : null;
  return { src, poster, autoplay, orbit, authoring, pose, filename };
}

// "max_strasse.sog" → "max strasse" — a quiet human label for the gate card.
export function sceneLabel(filename) {
  if (!filename) return '';
  return filename.replace(/\.(sog|ply)$/i, '').replace(/[-_]+/g, ' ');
}

// "cx,cy,cz,fx,fy,fz,yaw" → [7 floats] | null — camera position, focus point,
// and splat-pivot yaw (degrees) for the pose-authoring workflow (?pose=…).
// Invalid arity or non-numeric parts are ignored (null), letting the caller
// fall back to auto-frame.
export function parsePose(raw) {
  if (!raw) return null;
  const parts = raw.split(',').map((s) => s.trim());
  if (parts.length !== 7) return null;
  const nums = parts.map(Number);
  if (nums.some((n) => Number.isNaN(n))) return null;
  return nums;
}

// [cx,cy,cz,fx,fy,fz,yaw] → "cx,cy,cz,fx,fy,fz,yaw" (3 decimal places,
// comma-joined) — the inverse of parsePose, used by the pose-authoring
// "copy pose" workflow (main.js) to keep string formatting pure and testable.
export function serializePose(pose) {
  return pose.map((n) => n.toFixed(3)).join(',');
}
