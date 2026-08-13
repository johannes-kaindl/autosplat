import { test } from 'node:test';
import assert from 'node:assert/strict';
import { buildImportedCollider, pickCollider } from '../../js/collision/import-collider.js';

// A stand-in for a PlayCanvas entity: transformPositions only ever reads
// getWorldTransform().data, so a plain column-major Mat4 is the real input.
function entityWith(data) {
  return { getWorldTransform: () => ({ data }) };
}
const IDENTITY = [1,0,0,0, 0,1,0,0, 0,0,1,0, 0,0,0,1];
const SHIFTED_UP_2 = [1,0,0,0, 0,1,0,0, 0,0,1,0, 0,2,0,1];

const UNIT_TRI = 'v 0 0 0\nv 4 0 0\nv 0 0 4\nf 1 2 3\n';

test('buildImportedCollider: returns a mesh collider strategy', () => {
  const c = buildImportedCollider(UNIT_TRI, entityWith(IDENTITY));
  assert.equal(c.kind, 'mesh');
  assert.ok(c.bvh, 'carries a BVH');
  assert.equal(c.triangles, 1);
});

test('buildImportedCollider: bounds come from the transformed mesh', () => {
  const c = buildImportedCollider(UNIT_TRI, entityWith(IDENTITY));
  assert.deepEqual(c.bounds.min, { x: 0, y: 0, z: 0 });
  assert.deepEqual(c.bounds.max, { x: 4, y: 0, z: 4 });
});

test('buildImportedCollider: applies the entity world transform', () => {
  const c = buildImportedCollider(UNIT_TRI, entityWith(SHIFTED_UP_2));
  assert.equal(c.bounds.min.y, 2, 'mesh is lifted into the splat world space');
  assert.equal(c.bounds.max.y, 2);
});

test('buildImportedCollider: a file without faces yields null', () => {
  assert.equal(buildImportedCollider('v 0 0 0\nv 1 0 0\n', entityWith(IDENTITY)), null);
});

test('buildImportedCollider: the resulting BVH is hit by a downward ray', async () => {
  const { raycast } = await import('../../js/collision/mesh-bvh.js');
  const c = buildImportedCollider(UNIT_TRI, entityWith(SHIFTED_UP_2));
  const hit = raycast(c.bvh, [1, 10, 1], [0, -1, 0]);
  assert.ok(hit, 'ray from above hits the ground triangle');
  assert.ok(Math.abs(hit.point[1] - 2) < 1e-6, `ground at y=2, got ${hit.point[1]}`);
});

test('pickCollider: an imported mesh wins over the voxelised one', () => {
  const imported = { kind: 'mesh', bvh: 'imported' };
  const voxel = { kind: 'mesh', bvh: 'voxel' };
  assert.equal(pickCollider(imported, voxel), imported);
});

test('pickCollider: without an import the voxelised mesh is used', () => {
  const voxel = { kind: 'mesh', bvh: 'voxel' };
  assert.equal(pickCollider(null, voxel), voxel);
});

test('pickCollider: with neither, null lets walking fall back to the heightmap', () => {
  assert.equal(pickCollider(null, null), null);
});

test('buildImportedCollider: flat normals point away from the surface', () => {
  // Triangle lying in the XZ plane, wound so its face normal is +Y.
  const c = buildImportedCollider('v 0 0 0\nv 0 0 4\nv 4 0 0\nf 1 2 3\n',
    entityWith(IDENTITY));
  assert.equal(c.mesh.normals.length, c.mesh.positions.length);
  const [nx, ny, nz] = c.mesh.normals;
  assert.ok(Math.abs(ny - 1) < 1e-6, `expected +Y normal, got ${ny}`);
  assert.ok(Math.abs(nx) < 1e-6 && Math.abs(nz) < 1e-6);
});
