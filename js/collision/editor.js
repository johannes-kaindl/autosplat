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
          const wx = this.bounds.min.x + (i + 0.5) * sx;
          const wy = this.bounds.min.y + (j + 0.5) * sy;
          const wz = this.bounds.min.z + (k + 0.5) * sz;
          const dx = wx - point[0], dy = wy - point[1], dz = wz - point[2];
          const d = Math.hypot(dx, dy, dz);
          if (d > radius) continue;
          const w = 1 - (d / radius) ** 2;
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
