import { test } from 'node:test';
import assert from 'node:assert/strict';

import { collisionFilename } from '../../js/filename.js';

// Anchor instant: 2026-05-27 22:33:04 UTC.
const FIXED = Date.UTC(2026, 4, 27, 22, 33, 4);

test('collisionFilename: appends UTC timestamp to collider.<ext>', () => {
  assert.equal(
    collisionFilename('obj', () => FIXED),
    'collider-2026-05-27T223304Z.obj'
  );
});

test('collisionFilename: handles compound .collision.json extension', () => {
  assert.equal(
    collisionFilename('collision.json', () => FIXED),
    'collider-2026-05-27T223304Z.collision.json'
  );
});

test('collisionFilename: defaults to Date.now() when no clock provided', () => {
  const out = collisionFilename('obj');
  assert.match(out, /^collider-\d{4}-\d{2}-\d{2}T\d{6}Z\.obj$/);
});

test('collisionFilename: zero-pads single-digit fields', () => {
  // 2026-01-02 03:04:05 UTC — every field 1-digit, should pad to 2.
  const t = Date.UTC(2026, 0, 2, 3, 4, 5);
  assert.equal(
    collisionFilename('obj', () => t),
    'collider-2026-01-02T030405Z.obj'
  );
});
