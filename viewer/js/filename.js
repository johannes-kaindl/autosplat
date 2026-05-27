// filename.js — pure helpers for download filenames. Pure-JS, no DOM, so
// unit-testable without the browser.

/**
 * Build a collision-export filename with a UTC timestamp suffix, so
 * successive exports don't overwrite one another on disk.
 *
 *   collisionFilename('obj')             → 'collider-2026-05-27T223304Z.obj'
 *   collisionFilename('collision.json')  → 'collider-2026-05-27T223304Z.collision.json'
 *
 * `now` is injectable for deterministic tests.
 */
export function collisionFilename(ext, now = Date.now) {
  const t = now();
  const d = new Date(t);
  const pad = (n) => String(n).padStart(2, '0');
  const stamp = `${d.getUTCFullYear()}-${pad(d.getUTCMonth() + 1)}-${pad(d.getUTCDate())}T`
    + `${pad(d.getUTCHours())}${pad(d.getUTCMinutes())}${pad(d.getUTCSeconds())}Z`;
  return `collider-${stamp}.${ext}`;
}
