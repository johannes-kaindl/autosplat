// SPDX-License-Identifier: AGPL-3.0-or-later
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync, readdirSync, statSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join, relative, sep } from 'node:path';

const HERE = dirname(fileURLToPath(import.meta.url));
const VIEWER = join(HERE, '..', '..');
const REPO = join(VIEWER, '..');

test('viewer loads the engine from vendor/, not a CDN', () => {
  const html = readFileSync(join(VIEWER, 'viewer.html'), 'utf8');
  assert.match(html, /"playcanvas":\s*"\.\/vendor\/playcanvas\.mjs"/);
  assert.doesNotMatch(html, /cdn\.jsdelivr\.net/);
});

function walk(dir) {
  let out = [];
  for (const entry of readdirSync(dir)) {
    const full = join(dir, entry);
    const st = statSync(full);
    if (st.isDirectory()) out = out.concat(walk(full));
    else out.push(full);
  }
  return out;
}

// The only URLs allowed to appear in the bundled surface: documentation /
// attribution links that are never fetched at runtime. Keyed by path relative
// to viewer/, value is the exact URL string(s) permitted in that file — narrow
// on purpose, so a new URL anywhere always fails closed until someone vets it
// and adds it here explicitly.
const ATTRIBUTION_EXEMPTIONS = new Map([
  ['viewer.html', new Set(['https://codeberg.org/jkaindl/autosplat'])],
  ['js/collision/mc-tables.js', new Set(['http://paulbourke.net/geometry/polygonise/'])],
]);

test('no bundled file loads a URL from an external host at runtime', () => {
  // Widened after a Critical review finding: the previous version of this
  // test only matched ES `import`/`from` specifiers, so a plain string
  // constant fed to PlayCanvas's Asset/AssetListLoader (CAMERA_CONTROLS_URL
  // in viewer.js, pointing at cdn.jsdelivr.net) was invisible to it and
  // shipped a live CDN call on the critical path inside AutoSplat.app.
  //
  // This instead scans every https?:// occurrence in every file
  // AutoSplat.spec actually bundles as viewer/js, viewer/css and viewer.html
  // itself. vendor/ is excluded here — it is third-party engine code (not
  // ours to rewrite) and is already guarded by the byte-identity test below;
  // icons/ is binary image data. Two documentation/attribution links are
  // legitimate and explicitly allowlisted above; anything else fails by
  // default, which is what should have caught CAMERA_CONTROLS_URL.
  const files = [
    join(VIEWER, 'viewer.html'),
    ...walk(join(VIEWER, 'js')),
    ...walk(join(VIEWER, 'css')),
  ];
  const urlRe = /https?:\/\/[^\s"'<>)]+/g;
  for (const file of files) {
    const rel = relative(VIEWER, file).split(sep).join('/');
    const text = readFileSync(file, 'utf8');
    const allowed = ATTRIBUTION_EXEMPTIONS.get(rel) ?? new Set();
    const matches = text.match(urlRe) ?? [];
    for (const url of matches) {
      assert.ok(allowed.has(url), `${rel} references external URL ${url} — not on the attribution allowlist`);
    }
  }
});

test('the vendored engine and camera-controls script have not drifted from embed/', () => {
  // Two copies of these files is a deliberate cost: embed/ is lifted whole
  // into every share bundle and must stay self-contained, and the Pages
  // deploy is a subtree split of viewer/ alone where ../embed/ does not
  // exist. This test is the only thing standing between two copies and a
  // silent version split. Both vendored files are checked so neither can be
  // updated alone.
  for (const name of ['playcanvas.mjs', 'camera-controls.mjs']) {
    const a = readFileSync(join(VIEWER, 'vendor', name));
    const b = readFileSync(join(REPO, 'embed', 'vendor', name));
    assert.ok(a.equals(b), `viewer/vendor/${name} and embed/vendor/${name} disagree — update both`);
  }
});
