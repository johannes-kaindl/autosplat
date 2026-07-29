// SPDX-License-Identifier: AGPL-3.0-or-later
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const HERE = dirname(fileURLToPath(import.meta.url));
const VIEWER = join(HERE, '..', '..');
const REPO = join(VIEWER, '..');

test('viewer loads the engine from vendor/, not a CDN', () => {
  const html = readFileSync(join(VIEWER, 'viewer.html'), 'utf8');
  assert.match(html, /"playcanvas":\s*"\.\/vendor\/playcanvas\.mjs"/);
  assert.doesNotMatch(html, /cdn\.jsdelivr\.net/);
});

test('no allowlisted module specifier points at an external host', () => {
  // The app bundles these files and claims to be zero-external. That claim
  // was already wrong once (v1.14.0 share bundles), so it gets a gate.
  const files = ['viewer.html', 'js/app.js', 'js/viewer.js', 'js/walking.js'];
  for (const rel of files) {
    const text = readFileSync(join(VIEWER, rel), 'utf8');
    const specifiers = [...text.matchAll(/(?:from|import)\s+['"]([^'"]+)['"]/g)].map((m) => m[1]);
    for (const spec of specifiers) {
      assert.ok(!/^https?:/.test(spec), `${rel} imports external ${spec}`);
    }
  }
});

test('the vendored engine has not drifted from embed/', () => {
  // Two copies of one engine is a deliberate cost: embed/ is lifted whole
  // into every share bundle and must stay self-contained, and the Pages
  // deploy is a subtree split of viewer/ alone where ../embed/ does not
  // exist. This test is the only thing standing between two copies and a
  // silent version split.
  const a = readFileSync(join(VIEWER, 'vendor', 'playcanvas.mjs'));
  const b = readFileSync(join(REPO, 'embed', 'vendor', 'playcanvas.mjs'));
  assert.ok(a.equals(b), 'viewer/vendor and embed/vendor disagree — update both');
});
