import { test } from 'node:test';
import assert from 'node:assert/strict';
import { CollisionEditor } from '../../js/collision/editor.js';

const bounds = { min: { x: 0, y: 0, z: 0 }, max: { x: 1, y: 1, z: 1 } };

function blank() {
  return new CollisionEditor({
    density: new Float32Array(8 ** 3),
    resolution: 8,
    bounds,
    iso: 1.5,
  });
}

test('editor: add-brush raises density inside radius', () => {
  const ed = blank();
  ed.beginStroke('add');
  ed.applyAt([0.5, 0.5, 0.5], 0.2, 5);
  ed.endStroke();
  const c = ed.density[4 * 64 + 4 * 8 + 4];
  assert.ok(c > 0, `centre density should be > 0, got ${c}`);
  assert.equal(ed.density[0], 0);
});

test('editor: remove-brush is the inverse of add (modulo clamp)', () => {
  const ed = blank();
  ed.beginStroke('add');
  ed.applyAt([0.5, 0.5, 0.5], 0.2, 5);
  ed.endStroke();
  const beforeRemove = ed.density.slice();
  ed.beginStroke('remove');
  ed.applyAt([0.5, 0.5, 0.5], 0.2, 5);
  ed.endStroke();
  for (let i = 0; i < ed.density.length; i++) {
    assert.ok(ed.density[i] <= beforeRemove[i] + 1e-6,
      `idx ${i}: ${ed.density[i]} > ${beforeRemove[i]}`);
    assert.ok(ed.density[i] >= 0);
  }
});

test('editor: undo restores pre-stroke density', () => {
  const ed = blank();
  const snapshot = ed.density.slice();
  ed.beginStroke('add');
  ed.applyAt([0.5, 0.5, 0.5], 0.2, 5);
  ed.endStroke();
  ed.undo();
  for (let i = 0; i < ed.density.length; i++) {
    assert.equal(ed.density[i], snapshot[i], `idx ${i}`);
  }
});

test('editor: undo ring is bounded to 8', () => {
  const ed = blank();
  for (let s = 0; s < 10; s++) {
    ed.beginStroke('add');
    ed.applyAt([0.5, 0.5, 0.5], 0.2, 1);
    ed.endStroke();
  }
  for (let u = 0; u < 8; u++) assert.equal(ed.undo(), true);
  assert.equal(ed.undo(), false);
});

test('editor: applyAt without active stroke throws', () => {
  const ed = blank();
  assert.throws(() => ed.applyAt([0.5, 0.5, 0.5], 0.2, 5), /no active stroke/);
});

test('editor: empty stroke is not pushed to undo ring', () => {
  const ed = blank();
  ed.beginStroke('add');
  // apply outside the bounds → no cells touched
  ed.applyAt([100, 100, 100], 0.01, 1);
  ed.endStroke();
  assert.equal(ed.undoDepth(), 0);
});
