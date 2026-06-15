import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  writeObj, rlePack, rleUnpack, encodeSidecar, decodeSidecar,
} from '../../js/collision/persist.js';

test('writeObj: single triangle round-trips through parser', () => {
  const positions = new Float32Array([0, 0, 0,  1, 0, 0,  0, 1, 0]);
  const normals   = new Float32Array([0, 0, 1,  0, 0, 1,  0, 0, 1]);
  const indices   = new Uint32Array([0, 1, 2]);
  const obj = writeObj({ positions, normals, indices });
  assert.match(obj, /^# autosplat-viewer collision mesh/);
  assert.equal((obj.match(/^v /gm) ?? []).length, 3);
  assert.equal((obj.match(/^vn /gm) ?? []).length, 3);
  assert.equal((obj.match(/^f /gm) ?? []).length, 1);
  assert.match(obj, /^f 1\/\/1 2\/\/2 3\/\/3$/m);
});

test('rlePack / rleUnpack: round-trip with mixed runs', () => {
  const grid = new Float32Array([0, 0, 0, 1.5, 1.5, 2, 2, 2, 2, 0]);
  const packed = rlePack(grid);
  const out = rleUnpack(packed, grid.length);
  assert.equal(out.length, grid.length);
  for (let i = 0; i < grid.length; i++) {
    assert.ok(Math.abs(out[i] - grid[i]) < 0.05, `idx ${i}: ${out[i]} vs ${grid[i]}`);
  }
});

test('rlePack: produces a compact representation', () => {
  // 1000 cells all the same value → expect a single run.
  const grid = new Float32Array(1000).fill(1.5);
  const packed = rlePack(grid);
  assert.equal(packed.length, 2);
  assert.equal(packed[0], 1000);
});

test('encodeSidecar / decodeSidecar: full round-trip', () => {
  const density = new Float32Array(64);
  density[10] = 3.7; density[20] = 1.2;
  const bounds = { min: { x: -1, y: -1, z: -1 }, max: { x: 1, y: 1, z: 1 } };
  const json = encodeSidecar({ resolution: 4, bounds, iso: 1.5, density });
  const obj = JSON.parse(json);
  assert.equal(obj.version, 1);
  assert.equal(obj.resolution, 4);
  const round = decodeSidecar(json);
  assert.equal(round.resolution, 4);
  assert.equal(round.iso, 1.5);
  assert.deepEqual(round.bounds.min, bounds.min);
  assert.ok(Math.abs(round.density[10] - 3.7) < 0.05);
});

test('decodeSidecar: rejects unsupported version', () => {
  const bad = JSON.stringify({ version: 99, resolution: 4, bounds: {min:[0,0,0],max:[1,1,1]}, iso: 1, densityRLE: [] });
  assert.throws(() => decodeSidecar(bad), /unsupported sidecar version/);
});
