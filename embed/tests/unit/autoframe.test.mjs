import { test } from 'node:test';
import assert from 'node:assert/strict';
import { frameBounds } from '../../js/autoframe.js';

test('empty input → null', () => {
  assert.equal(frameBounds(new Float32Array(0)), null);
});

test('single point: centered, minimum radius 0.5', () => {
  const b = frameBounds(new Float32Array([1, 2, 3]));
  assert.deepEqual(b.center, [1, 2, 3]);
  assert.equal(b.radius, 0.5);
});

test('percentiles ignore floater outliers', () => {
  // 200 points inside the unit cube + 2 extreme floaters
  const pts = [];
  for (let i = 0; i < 200; i++) pts.push(i / 200, (i % 10) / 10, ((i * 7) % 200) / 200);
  pts.push(1000, 1000, 1000, -1000, -1000, -1000);
  const b = frameBounds(new Float32Array(pts));
  assert.ok(b.radius < 5, `radius ${b.radius} should ignore outliers`);
  assert.ok(Math.abs(b.center[0]) < 2, `center.x was ${b.center[0]}`);
});

test('radius covers the largest half-extent', () => {
  // spread along x only: [0..10]
  const pts = [];
  for (let i = 0; i <= 100; i++) pts.push(i / 10, 0, 0);
  const b = frameBounds(new Float32Array(pts));
  assert.ok(b.radius > 4 && b.radius <= 5.1, `radius was ${b.radius}`);
});

test('sampling large clouds still frames correctly', () => {
  const n = 200000;
  const pts = new Float32Array(n * 3);
  for (let i = 0; i < n; i++) {
    pts[i * 3] = (i / n) * 4; pts[i * 3 + 1] = 0; pts[i * 3 + 2] = 0;
  }
  const b = frameBounds(pts, { maxSamples: 5000 });
  assert.ok(Math.abs(b.center[0] - 2) < 0.3, `center.x was ${b.center[0]}`);
});
