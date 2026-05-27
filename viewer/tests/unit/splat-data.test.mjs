import { test } from 'node:test';
import assert from 'node:assert/strict';

import { extractSplatPositions } from '../../js/splat-data.js';

// Mock PlayCanvas 2.18 GSplatComponent shape — discovered 2026-05-27 via
// runtime entity-tree dump on a freshly loaded splat:
// entity.gsplat._instance.resource.centers      (Float32Array, interleaved)
// entity.gsplat._instance.resource.gsplatData   ({ getProp(name), numSplats })

const makeEntity = (gsplat) => ({ gsplat });

test('extractSplatPositions: returns null when entity has no gsplat', () => {
  assert.equal(extractSplatPositions({}), null);
  assert.equal(extractSplatPositions(null), null);
});

test('extractSplatPositions: returns null when _instance is missing', () => {
  const e = makeEntity({ _resource: null, asset: { resource: null } });
  assert.equal(extractSplatPositions(e), null);
});

test('extractSplatPositions: prefers _instance.resource.centers (PC 2.18 fast path)', () => {
  const centers = new Float32Array([1, 2, 3, 4, 5, 6]);
  const e = makeEntity({
    _instance: { resource: { centers, gsplatData: null } },
  });
  const out = extractSplatPositions(e);
  assert.equal(out, centers, 'should return the same Float32Array, not a copy');
});

test('extractSplatPositions: falls back to gsplatData.getProp(x,y,z) when centers missing', () => {
  const x = new Float32Array([1, 4]);
  const y = new Float32Array([2, 5]);
  const z = new Float32Array([3, 6]);
  const gsplatData = {
    numSplats: 2,
    getProp: (name) => ({ x, y, z }[name]),
  };
  const e = makeEntity({
    _instance: { resource: { centers: null, gsplatData } },
  });
  const out = extractSplatPositions(e);
  assert.ok(out instanceof Float32Array);
  assert.equal(out.length, 6);
  assert.deepEqual(Array.from(out), [1, 2, 3, 4, 5, 6]);
});

test('extractSplatPositions: ignores non-Float32Array centers (e.g. promise placeholder)', () => {
  const e = makeEntity({
    _instance: { resource: { centers: { not: 'a typed array' }, gsplatData: null } },
  });
  assert.equal(extractSplatPositions(e), null);
});

test('extractSplatPositions: returns null when getProp returns nothing', () => {
  const e = makeEntity({
    _instance: { resource: { centers: null, gsplatData: { getProp: () => null } } },
  });
  assert.equal(extractSplatPositions(e), null);
});

test('extractSplatPositions: empty Float32Array → null (no usable geometry)', () => {
  const e = makeEntity({
    _instance: { resource: { centers: new Float32Array(0), gsplatData: null } },
  });
  assert.equal(extractSplatPositions(e), null);
});
