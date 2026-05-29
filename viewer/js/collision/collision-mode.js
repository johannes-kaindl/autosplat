// collision-mode.js — PlayCanvas integration for the collision-mesh editor.
// Lazy-loaded by viewer.js. Owns the mesh entity, drives the voxelize → MC
// pipeline, exposes the editor + persist surfaces to the UI layer.

import {
  Entity, Mesh, MeshInstance, StandardMaterial, BLEND_NORMAL, Color,
  PRIMITIVE_TRIANGLES, CULLFACE_NONE,
} from 'playcanvas';

import { voxelize, smoothDensity, defaultIso } from './voxelize.js';
import { marchingCubes } from './marching-cubes.js';
import { buildBvh, raycast } from './mesh-bvh.js';
import { CollisionEditor, brushWorldRadius } from './editor.js';
import { writeObj, encodeSidecar, decodeSidecar } from './persist.js';

const RESOLUTION = 64;

export class CollisionMode {
  constructor({ app, camera, splatEntity, splatPivot, getSplatPositions }) {
    this.app = app;
    this.camera = camera;
    this.splatEntity = splatEntity;
    this.splatPivot = splatPivot;
    this.getSplatPositions = getSplatPositions; // () => { positions, bounds }

    this.editor = null;
    this.bvh = null;
    this.meshEntity = null;
    this.lastMesh = null;
    this._lockReleasedForBrush = false;
    this._listeners = { built: [] };
  }

  /**
   * Build (or rebuild) the mesh from the loaded splat. Returns true on
   * success, false if no splat positions are available.
   */
  build() {
    const sp = this.getSplatPositions();
    if (!sp || !sp.positions || sp.positions.length === 0) return false;
    const { density } = voxelize(sp.positions, sp.bounds, RESOLUTION);
    const smoothed = smoothDensity(density, RESOLUTION);
    const iso = defaultIso(smoothed);
    this.editor = new CollisionEditor({
      density: smoothed,
      resolution: RESOLUTION,
      bounds: sp.bounds,
      iso,
    });
    this.rebuildMesh();
    return true;
  }

  /**
   * Load a sidecar — replaces the editor state entirely. Returns a summary
   * `{ tris, iso, resolution }` of the restored state so the caller can log
   * a visible confirmation (sidecar restores are otherwise indistinguishable
   * from a deterministic re-build at the same iso).
   */
  loadSidecar(json) {
    const { resolution, bounds, iso, density } = decodeSidecar(json);
    this.editor = new CollisionEditor({ density, resolution, bounds, iso });
    this.rebuildMesh();
    return { tris: (this.lastMesh?.indices.length ?? 0) / 3, iso, resolution };
  }

  /**
   * Apply one brush sample at a screen-space pointer position. `brushFrac` is
   * the scene-relative slider value (0–2); it's converted to a world radius
   * against the editor bounds so the brush feels the same on any scene scale.
   * If `continuing` is true, the caller is mid-stroke (drag-brush) —
   * beginStroke/endStroke and the mesh-rebuild are the caller's
   * responsibility. If false, this is a one-shot stroke: begin+apply+end+rebuild.
   */
  applyBrushAt(screenX, screenY, kind, brushFrac, strength, continuing = false) {
    if (!this.editor) return;
    const hit = this._raycastFromScreen(screenX, screenY);
    if (!hit) return;
    const radius = brushWorldRadius(brushFrac, this.editor.bounds, this.editor.resolution);
    if (!continuing) {
      this.editor.beginStroke(kind);
      this.editor.applyAt(hit.point, radius, strength);
      this.editor.endStroke();
      this.rebuildMesh();
    } else {
      this.editor.applyAt(hit.point, radius, strength);
    }
  }

  setIso(iso) {
    if (!this.editor) return;
    this.editor.setIso(iso);
    this.rebuildMesh();
  }

  undo() {
    if (!this.editor) return;
    if (this.editor.undo()) this.rebuildMesh();
  }

  exportObj() {
    if (!this.lastMesh) return null;
    return writeObj(this.lastMesh);
  }

  exportSidecar() {
    if (!this.editor) return null;
    return encodeSidecar({
      resolution: this.editor.resolution,
      bounds: this.editor.bounds,
      iso: this.editor.iso,
      density: this.editor.density,
    });
  }

  onBuilt(fn) { this._listeners.built.push(fn); }

  /**
   * For walking-mode: return a collider strategy or null if no mesh exists.
   */
  getCollider() {
    if (!this.bvh) return null;
    return { kind: 'mesh', bvh: this.bvh, bounds: this.editor.bounds };
  }

  destroy() {
    if (this.meshEntity) {
      this.meshEntity.destroy();
      this.meshEntity = null;
    }
    this.editor = null;
    this.bvh = null;
    this.lastMesh = null;
  }

  // ---------- internals ----------

  rebuildMesh() {
    if (!this.editor) return;
    const mesh = marchingCubes({
      density: this.editor.density,
      resolution: this.editor.resolution,
      bounds: this.editor.bounds,
      iso: this.editor.iso,
    });
    this.lastMesh = mesh;
    this.bvh = buildBvh(mesh.positions, mesh.indices);
    this._updatePlayCanvasMesh(mesh);
    for (const fn of this._listeners.built) {
      try { fn({ triCount: mesh.indices.length / 3, iso: this.editor.iso }); }
      catch (e) { console.error(e); }
    }
  }

  _updatePlayCanvasMesh(mesh) {
    if (this.meshEntity) {
      this.meshEntity.destroy();
      this.meshEntity = null;
    }
    if (mesh.indices.length === 0) return;

    const device = this.app.graphicsDevice;
    const pcMesh = new Mesh(device);
    pcMesh.setPositions(mesh.positions);
    pcMesh.setNormals(mesh.normals);
    pcMesh.setIndices(mesh.indices);
    pcMesh.update(PRIMITIVE_TRIANGLES);

    const mat = new StandardMaterial();
    mat.diffuse = new Color(0.4, 0.7, 1.0);
    mat.opacity = 0.35;
    mat.blendType = BLEND_NORMAL;
    mat.cull = CULLFACE_NONE;  // 2-sided so MC normal direction doesn't matter
    mat.useLighting = true;
    mat.update();

    const meshInstance = new MeshInstance(pcMesh, mat);
    const entity = new Entity('collision-mesh');
    entity.addComponent('render', { meshInstances: [meshInstance] });
    this.app.root.addChild(entity);
    this.meshEntity = entity;
  }

  _raycastFromScreen(screenX, screenY) {
    if (!this.bvh) return null;
    const canvas = this.app.graphicsDevice.canvas;
    const rect = canvas.getBoundingClientRect();
    const localX = screenX - rect.left;
    const localY = screenY - rect.top;

    const camComp = this.camera.camera;
    const near = camComp.screenToWorld(localX, localY, camComp.nearClip);
    const far  = camComp.screenToWorld(localX, localY, camComp.farClip);
    const dir = [far.x - near.x, far.y - near.y, far.z - near.z];
    return raycast(this.bvh, [near.x, near.y, near.z], dir);
  }
}
