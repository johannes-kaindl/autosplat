import { test } from 'node:test';
import assert from 'node:assert/strict';
import { initDropzone } from '../../js/dropzone.js';

// Minimal event-target stubs — dropzone.js only ever calls addEventListener
// and contains(), so no DOM library is needed.
function stubEl() {
  const handlers = {};
  return {
    hidden: true,
    addEventListener(kind, fn) { (handlers[kind] ??= []).push(fn); },
    contains() { return false; },
    click() {},
    fire(kind, ev) { for (const fn of handlers[kind] ?? []) fn(ev); },
  };
}

function harness() {
  const stage = stubEl(), hint = stubEl(), fileInput = stubEl(), openButton = stubEl();
  fileInput.files = [];
  const seen = { file: [], sidecar: [], collider: [] };
  initDropzone({
    stage, hint, fileInput, openButton,
    onFile: (f, name) => seen.file.push(f ? f.name : `rejected:${name}`),
    onSidecar: (text) => seen.sidecar.push(text),
    onCollider: (text, name) => seen.collider.push(name),
  });
  const drop = (file) => stage.fire('drop', {
    preventDefault() {}, dataTransfer: { files: [file] },
  });
  return { drop, seen };
}

const settle = () => new Promise(r => setImmediate(r));

test('dropzone: an .obj file is routed to the collider handler', async () => {
  const { drop, seen } = harness();
  drop(new File(['v 0 0 0\nf 1 1 1\n'], 'collider_a010b.obj'));
  await settle();
  assert.deepEqual(seen.collider, ['collider_a010b.obj']);
  assert.equal(seen.file.length, 0, 'not mistaken for a splat');
});

test('dropzone: .ply and .collision.json keep their existing routes', async () => {
  const { drop, seen } = harness();
  drop(new File(['ply'], 'scene.ply'));
  drop(new File(['{}'], 'scene.collision.json'));
  await settle();
  assert.deepEqual(seen.file, ['scene.ply']);
  assert.deepEqual(seen.sidecar, ['{}']);
  assert.equal(seen.collider.length, 0);
});
