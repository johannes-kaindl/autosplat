# Embed Pose-Authoring Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `?pose=…&orbit=…&authoring=1` workflow to the existing `embed/` component so an author can interactively orbit/zoom a scene and copy the resulting camera pose into a ready-to-embed URL, bypassing auto-framing.

**Architecture:** Three new optional URL params extend the existing `parseParams`/`sceneLabel` API in `js/params.js` (plus a new pure `parsePose` function). `viewer.js`'s `loadSplat` accepts a `{ pose, orbit }` override and exposes a new `getPose()` reader. `main.js` wires an authoring-only "Copy pose" button that reads the live pose and writes a fully-formed URL to the clipboard. Spec: `pipeline/docs/superpowers/specs/2026-07-15-embed-pose-authoring-design.md`.

**Tech Stack:** Same as `embed/` — vanilla ES modules, no build step, `node:test` unit tests, `puppeteer-core` + system Chrome for e2e.

## Global Constraints

- **Kein Build-Step, keine neuen npm-Runtime-Deps.** `navigator.clipboard` /
  `document.execCommand('copy')` are browser built-ins — no new vendored code.
- **Zero-external bleibt erhalten** — diese Erweiterung fügt keine neuen
  Netzwerk-Requests hinzu.
- 2-Space-Indent, LF (Root-`.editorconfig`).
- Conventional Commits mit Trailer `Co-Authored-By: Claude <noreply@anthropic.com>`
  (bzw. dem Modell-spezifischen Trailer der ausführenden Session).
- **`cd embed && ./tests/run.sh` muss vor jedem Commit grün sein.**
- Alle Pfade und `cd`-Kommandos unten relativ zum Repo-Root.
- Aktueller Startzustand: 19 Dateien aus dem Basis-Plan sind bereits
  implementiert und getestet (11 Unit + 5 E2E grün) auf Branch
  `feat/embed-viewer`. Diese Tasks bauen darauf auf.

---

### Task 1: `parsePose` + `parseParams`-Erweiterung (`orbit`, `authoring`, `pose`)

**Files:**
- Modify: `embed/js/params.js`
- Modify: `embed/tests/unit/params.test.mjs`
- Create: `embed/tests/unit/pose.test.mjs`

**Interfaces:**
- Consumes: —
- Produces: `parsePose(raw: string|null) → [number,number,number,number,number,number] | null`; `parseParams` gibt zusätzlich `{ orbit: boolean, authoring: boolean, pose: number[]|null }` zurück (genutzt von Task 3 `main.js`).

- [ ] **Step 1: Failing Tests schreiben — `pose.test.mjs`**

`embed/tests/unit/pose.test.mjs`:

```js
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { parsePose } from '../../js/params.js';

test('parsePose: valid 6-number CSV → array of floats', () => {
  assert.deepEqual(parsePose('1,2,3,4,5,6'), [1, 2, 3, 4, 5, 6]);
});

test('parsePose: tolerates whitespace and decimals/negatives', () => {
  assert.deepEqual(parsePose(' -1.5 , 2, 3.25,4,5,6'), [-1.5, 2, 3.25, 4, 5, 6]);
});

test('parsePose: wrong arity → null', () => {
  assert.equal(parsePose('1,2,3'), null);
  assert.equal(parsePose('1,2,3,4,5,6,7'), null);
});

test('parsePose: non-numeric part → null', () => {
  assert.equal(parsePose('1,2,x,4,5,6'), null);
});

test('parsePose: null/empty input → null', () => {
  assert.equal(parsePose(null), null);
  assert.equal(parsePose(''), null);
});
```

- [ ] **Step 2: Failing Tests schreiben — `params.test.mjs` ergänzen**

Ans Ende von `embed/tests/unit/params.test.mjs` (nach dem letzten bestehenden
`test('sceneLabel: …')`-Block) anfügen:

```js

test('parseParams: orbit defaults true, "0" disables it, anything else stays true', () => {
  assert.equal(parseParams('?src=x.sog').orbit, true);
  assert.equal(parseParams('?src=x.sog&orbit=0').orbit, false);
  assert.equal(parseParams('?src=x.sog&orbit=yes').orbit, true);
});

test('parseParams: authoring only for exact "1"', () => {
  assert.equal(parseParams('?src=x.sog').authoring, false);
  assert.equal(parseParams('?src=x.sog&authoring=1').authoring, true);
  assert.equal(parseParams('?src=x.sog&authoring=true').authoring, false);
});

test('parseParams: valid pose is parsed through, invalid pose is null', () => {
  const p = parseParams('?src=x.sog&pose=1,2,3,4,5,6');
  assert.deepEqual(p.pose, [1, 2, 3, 4, 5, 6]);
  assert.equal(parseParams('?src=x.sog&pose=1,2,3').pose, null);
  assert.equal(parseParams('?src=x.sog').pose, null);
});
```

- [ ] **Step 3: Tests laufen lassen — müssen fehlschlagen**

Run: `cd embed && ./tests/run.sh unit`
Expected: FAIL — `parsePose is not a function` / `undefined` statt `orbit`/`authoring`/`pose` in den neuen Assertions.

- [ ] **Step 4: Implementierung**

`embed/js/params.js` (vollständige neue Datei):

```js
// Pure URL-parameter parsing for the embed page — unit-testable in node.
export function parseParams(search) {
  const q = new URLSearchParams(search);
  const src = (q.get('src') || '').trim() || null;
  const poster = (q.get('poster') || '').trim() || null;
  const autoplay = q.get('autoplay') === '1';
  const orbit = q.get('orbit') !== '0';
  const authoring = q.get('authoring') === '1';
  const pose = parsePose(q.get('pose'));
  const filename = src
    ? (src.split('?')[0].split('#')[0].split('/').pop() || 'scene.sog')
    : null;
  return { src, poster, autoplay, orbit, authoring, pose, filename };
}

// "max_strasse.sog" → "max strasse" — a quiet human label for the gate card.
export function sceneLabel(filename) {
  if (!filename) return '';
  return filename.replace(/\.(sog|ply)$/i, '').replace(/[-_]+/g, ' ');
}

// "cx,cy,cz,fx,fy,fz" → [6 floats] | null — camera position + focus point for
// the pose-authoring workflow (?pose=…). Invalid arity or non-numeric parts
// are ignored (null), letting the caller fall back to auto-frame.
export function parsePose(raw) {
  if (!raw) return null;
  const parts = raw.split(',').map((s) => s.trim());
  if (parts.length !== 6) return null;
  const nums = parts.map(Number);
  if (nums.some((n) => Number.isNaN(n))) return null;
  return nums;
}
```

- [ ] **Step 5: Tests laufen lassen — müssen bestehen**

Run: `cd embed && ./tests/run.sh unit`
Expected: PASS (19 Unit-Tests: 11 bestehend + 8 neu)

- [ ] **Step 6: Commit**

```bash
git add embed/js/params.js embed/tests/unit/params.test.mjs embed/tests/unit/pose.test.mjs
git commit -m "feat(embed): parse pose/orbit/authoring URL params"
```

---

### Task 2: Viewer-Runtime — Pose-Override + `getPose()`

**Files:**
- Modify: `embed/js/viewer.js`

**Interfaces:**
- Consumes: `parsePose`-Output (Task 1) als `opts.pose` in `loadSplat`.
- Produces: `loadSplat(url, filename, opts?: { pose?: number[], orbit?: boolean })` — bei gültigem `opts.pose` (6 Zahlen) wird `autoFrame()` übersprungen und die Kamera direkt via `cc.reset` positioniert; `setAutoOrbit(opts.orbit !== false)` ersetzt das bisher feste `setAutoOrbit(true)`. Neues `getPose() → { camPos: number[3], focus: number[3] }` am Viewer-Objekt (genutzt von Task 3 `main.js`).

**Kontext:** `cc.focusPoint` ist in `vendor/camera-controls.mjs` als Getter/Setter exponiert (`get focusPoint() { return this._pose.getFocus(tmpV1); }`) und liefert ein wiederverwendetes internes `Vec3` — die Komponenten müssen sofort in ein Array kopiert werden, keine Referenz behalten.

- [ ] **Step 1: Implementierung**

`embed/js/viewer.js` (vollständige neue Datei):

```js
// Core runtime for the embed viewer: engine bootstrap, splat loading,
// percentile auto-framing, auto-orbit. Imported lazily by main.js so the
// engine (vendor/playcanvas.mjs) is only fetched after the gate is clicked.
import {
  Application, Asset, AssetListLoader, Entity, Vec3,
  FILLMODE_FILL_WINDOW, RESOLUTION_AUTO
} from 'playcanvas';
import { frameBounds } from './autoframe.js';

const ORBIT_SPEED = 8; // degrees per second

// Generic pose for arbitrary splats — z:180 is the common Brush/COLMAP flip.
// The camera is re-framed from the splat centers right after loading.
const DEFAULT_POSE = {
  level: { x: 0, y: 0, z: 180 },
  cameraPos: { x: 0, y: 0, z: 4 },
  cameraFocus: { x: 0, y: 0, z: 0 }
};

export async function createViewer(hostElement) {
  const canvas = document.createElement('canvas');
  hostElement.appendChild(canvas);

  const app = new Application(canvas, {
    graphicsDeviceOptions: { antialias: false }
  });
  app.setCanvasFillMode(FILLMODE_FILL_WINDOW);
  app.setCanvasResolution(RESOLUTION_AUTO);
  app.start();
  window.addEventListener('resize', () => app.resizeCanvas());

  const camera = new Entity('camera');
  camera.addComponent('camera', { clearColor: [0.055, 0.059, 0.075, 1] });
  camera.setPosition(
    DEFAULT_POSE.cameraPos.x, DEFAULT_POSE.cameraPos.y, DEFAULT_POSE.cameraPos.z);
  app.root.addChild(camera);

  // camera-controls is a PlayCanvas ESM script; loading it through the asset
  // registry lets the engine attach it. Its `import 'playcanvas'` resolves to
  // the vendored engine via the importmap in index.html.
  const ccAsset = new Asset('camera-controls', 'script', {
    url: 'vendor/camera-controls.mjs'
  });
  await new Promise((res) => new AssetListLoader([ccAsset], app.assets).load(res));
  camera.addComponent('script');
  const cc = camera.script.create('cameraControls');

  // splatPivot rotates for the auto-orbit; splatEntity holds the static leveling
  let splatPivot = null;
  let splatEntity = null;
  let autoOrbit = true;
  const orbitListeners = [];

  function setAutoOrbit(on) {
    on = !!on;
    if (on === autoOrbit) return;
    autoOrbit = on;
    for (const fn of orbitListeners) {
      try { fn(on); } catch (e) { console.error(e); }
    }
  }

  app.on('update', (dt) => {
    if (autoOrbit && splatPivot) splatPivot.rotate(0, ORBIT_SPEED * dt, 0);
  });

  // Any manual interaction takes over from the auto-orbit.
  for (const ev of ['pointerdown', 'wheel']) {
    canvas.addEventListener(ev, () => setAutoOrbit(false));
  }

  // opts.pose: optional [cx,cy,cz,fx,fy,fz] from the pose-authoring workflow
  // (?pose=…) — when present, skips auto-frame and positions the camera
  // directly. opts.orbit: whether auto-orbit should start after loading
  // (default true, matching historical behavior when omitted).
  async function loadSplat(url, filename, opts = {}) {
    // loadFromUrlAndFilename: the filename drives format detection (.sog/.ply).
    let asset;
    try {
      asset = await new Promise((resolve, reject) => {
        app.assets.loadFromUrlAndFilename(url, filename, 'gsplat', (err, a) => {
          if (err) reject(err); else resolve(a);
        });
      });
    } catch {
      throw new Error('splat-load-failed');
    }

    if (splatPivot) splatPivot.destroy();
    splatPivot = new Entity('splat-pivot');
    splatEntity = new Entity('splat');
    splatEntity.addComponent('gsplat', { asset });
    splatEntity.setLocalEulerAngles(
      DEFAULT_POSE.level.x, DEFAULT_POSE.level.y, DEFAULT_POSE.level.z);
    splatPivot.addChild(splatEntity);
    app.root.addChild(splatPivot);

    cc.reset(
      new Vec3(DEFAULT_POSE.cameraFocus.x, DEFAULT_POSE.cameraFocus.y,
               DEFAULT_POSE.cameraFocus.z),
      new Vec3(DEFAULT_POSE.cameraPos.x, DEFAULT_POSE.cameraPos.y,
               DEFAULT_POSE.cameraPos.z));

    if (opts.pose) {
      const [cx, cy, cz, fx, fy, fz] = opts.pose;
      cc.reset(new Vec3(fx, fy, fz), new Vec3(cx, cy, cz));
    } else {
      await autoFrame();
    }
    setAutoOrbit(opts.orbit !== false);
  }

  // Frame the camera from the splat center positions (PC 2.x:
  // gsplat._instance.resource.centers — note the underscore) using per-axis
  // percentiles so floater outliers don't blow up the framing. Falls back
  // silently to DEFAULT_POSE if positions are unavailable.
  async function autoFrame() {
    const getCenters = () => {
      const g = splatEntity && splatEntity.gsplat;
      return (g && ((g._instance && g._instance.resource && g._instance.resource.centers) ||
                    (g.instance && g.instance.resource && g.instance.resource.centers))) || null;
    };
    let centers = null;
    for (let i = 0; i < 60 && !centers; i++) {
      centers = getCenters();
      if (!centers) await new Promise((r) => requestAnimationFrame(r));
    }
    if (!centers) return;

    const bounds = frameBounds(centers);
    if (!bounds) return;

    let center = new Vec3(bounds.center[0], bounds.center[1], bounds.center[2]);
    center = splatEntity.getWorldTransform().transformPoint(center.clone());
    const dist = bounds.radius * 2.4;
    const dir = new Vec3(0.8, 0.5, 0.8).normalize();
    const camPos = new Vec3(
      center.x + dir.x * dist,
      center.y + dir.y * dist,
      center.z + dir.z * dist);
    cc.reset(center, camPos);
  }

  // Current camera pose for the authoring "copy pose" workflow — reflects
  // manual orbiting/zooming, not just the pose at load time. cc.focusPoint
  // returns a reused internal Vec3, so its components are copied out
  // immediately.
  function getPose() {
    const camPos = camera.getPosition();
    const focus = cc.focusPoint;
    return {
      camPos: [camPos.x, camPos.y, camPos.z],
      focus: [focus.x, focus.y, focus.z],
    };
  }

  return {
    loadSplat,
    setAutoOrbit,
    isAutoOrbit() { return autoOrbit; },
    onAutoOrbitChange(fn) { orbitListeners.push(fn); },
    getPose,
  };
}
```

- [ ] **Step 2: Syntax-Gate + Regression**

Run: `node --check embed/js/viewer.js && cd embed && ./tests/run.sh`
Expected: kein Syntax-Fehler, 19 Unit + 5 E2E PASS (unverändert — `viewer.js` hat keine eigenen Unit-Tests, siehe Basis-Plan Task 4)

- [ ] **Step 3: Commit**

```bash
git add embed/js/viewer.js
git commit -m "feat(embed): pose override + getPose() in viewer runtime"
```

---

### Task 3: Authoring-UI (`main.js` + `index.html` + `embed.css`) + E2E

**Files:**
- Modify: `embed/index.html`
- Modify: `embed/css/embed.css`
- Modify: `embed/js/main.js`
- Create: `embed/tests/e2e/pose-authoring.test.mjs`

**Interfaces:**
- Consumes: `params.pose`/`params.orbit`/`params.authoring` (Task 1); `viewer.getPose()`, `viewer.isAutoOrbit()` (Task 2).
- Produces: sichtbares `#btn-copy-pose` (nur bei `?authoring=1` nach erfolgreichem Load), das die aktuelle Pose als vollständige Embed-URL in die Zwischenablage kopiert.

- [ ] **Step 1: Failing E2E-Tests schreiben**

`embed/tests/e2e/pose-authoring.test.mjs`:

```js
// E2E for pose-authoring: the ?authoring=1 copy-pose button's visibility
// gate. Real clipboard/pose-value verification is out of scope for headless
// E2E (see embed-smoke.test.mjs's rationale) — covered by the manual smoke
// in the pose-authoring design spec instead.
import { test, before, after } from 'node:test';
import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { setTimeout as wait } from 'node:timers/promises';
import puppeteer from 'puppeteer-core';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = dirname(fileURLToPath(import.meta.url));
const ROOT = resolve(HERE, '..', '..');          // embed/
const CHROME = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
const PORT = 8132;
const URL_BASE = `http://localhost:${PORT}`;

let server = null;
let browser = null;

before(async () => {
  server = spawn('python3', ['-m', 'http.server', String(PORT)], {
    cwd: ROOT, stdio: ['ignore', 'pipe', 'pipe'],
  });
  for (let i = 0; i < 30; i++) {
    try { const r = await fetch(URL_BASE + '/'); if (r.ok) break; }
    catch { /* still booting */ }
    await wait(100);
  }
  browser = await puppeteer.launch({
    executablePath: CHROME, headless: 'new',
    args: ['--no-sandbox', '--disable-features=Translate', '--hide-scrollbars'],
  });
});

after(async () => {
  if (browser) await browser.close();
  if (server) { server.kill(); await wait(200); }
});

test('authoring=1 with broken src: copy-pose button stays hidden through the error state', async () => {
  const page = await browser.newPage();
  await page.goto(URL_BASE + '/?src=does-not-exist.sog&authoring=1',
                  { waitUntil: 'domcontentloaded' });
  await page.click('#gate');
  await page.waitForFunction(
    () => !document.getElementById('error-card').hidden, { timeout: 30000 });
  const hidden = await page.evaluate(
    () => document.getElementById('btn-copy-pose').hidden);
  assert.equal(hidden, true, 'copy-pose button hidden while load failed');
  await page.close();
});

test('without authoring param: copy-pose button stays hidden regardless of state', async () => {
  const page = await browser.newPage();
  await page.goto(URL_BASE + '/?src=does-not-exist.sog',
                  { waitUntil: 'domcontentloaded' });
  const beforeClick = await page.evaluate(
    () => document.getElementById('btn-copy-pose').hidden);
  assert.equal(beforeClick, true, 'hidden before any interaction');
  await page.click('#gate');
  await page.waitForFunction(
    () => !document.getElementById('error-card').hidden, { timeout: 30000 });
  const afterError = await page.evaluate(
    () => document.getElementById('btn-copy-pose').hidden);
  assert.equal(afterError, true, 'still hidden after error state');
  await page.close();
});
```

- [ ] **Step 2: Test laufen lassen — muss fehlschlagen**

Run: `cd embed && ./tests/run.sh e2e`
Expected: FAIL — `document.getElementById('btn-copy-pose')` ist `null` (Element existiert noch nicht)

- [ ] **Step 3: `index.html` ändern**

In `embed/index.html` den `#controls`-Block ersetzen von:

```html
    <div id="controls" hidden>
      <button id="btn-orbit" type="button" aria-pressed="true"
              aria-label="Pause auto-orbit">⏸</button>
      <button id="btn-fullscreen" type="button" aria-label="Fullscreen">⛶</button>
    </div>
```

zu:

```html
    <div id="controls" hidden>
      <button id="btn-orbit" type="button" aria-pressed="true"
              aria-label="Pause auto-orbit">⏸</button>
      <button id="btn-fullscreen" type="button" aria-label="Fullscreen">⛶</button>
      <button id="btn-copy-pose" type="button" hidden>Copy pose</button>
    </div>
```

- [ ] **Step 4: `embed.css` ändern**

In `embed/css/embed.css` nach dem Block

```css
#controls button:hover { background: rgba(38, 41, 52, 0.85); }
```

einfügen:

```css
#btn-copy-pose {
  width: auto; padding: 0 0.75rem; font-size: 0.8rem; white-space: nowrap;
}
```

- [ ] **Step 5: `main.js` ändern**

`embed/js/main.js` (vollständige neue Datei):

```js
// Shell wiring for the embed page: poster gate, controls, error handling.
// The engine is imported only after the gate is clicked (or ?autoplay=1).
import { parseParams, sceneLabel } from './params.js';

const els = {
  stage: document.getElementById('stage'),
  host: document.getElementById('canvas-host'),
  gate: document.getElementById('gate'),
  gateLabel: document.getElementById('gate-label'),
  hint: document.getElementById('hint-card'),
  error: document.getElementById('error-card'),
  errorMsg: document.getElementById('error-msg'),
  retry: document.getElementById('btn-retry'),
  spinner: document.getElementById('spinner'),
  controls: document.getElementById('controls'),
  btnOrbit: document.getElementById('btn-orbit'),
  btnFullscreen: document.getElementById('btn-fullscreen'),
  btnCopyPose: document.getElementById('btn-copy-pose'),
};

const params = parseParams(location.search);
let viewer = null;

function hasWebGL2() {
  try { return !!document.createElement('canvas').getContext('webgl2'); }
  catch { return false; }
}

function showError(msg) {
  els.spinner.hidden = true;
  els.errorMsg.textContent = msg;
  els.error.hidden = false;
}

function syncOrbitButton(on) {
  els.btnOrbit.textContent = on ? '⏸' : '▶';
  els.btnOrbit.setAttribute('aria-pressed', String(on));
  els.btnOrbit.setAttribute('aria-label', on ? 'Pause auto-orbit' : 'Start auto-orbit');
}

// Builds the URL a scene author copies out of authoring mode: current src/
// poster/autoplay carried over, pose+orbit set from the live camera state,
// authoring itself dropped (the copied link is for end users).
function buildPoseUrl() {
  const pose = viewer.getPose();
  const poseStr = [...pose.camPos, ...pose.focus]
    .map((n) => n.toFixed(3)).join(',');
  const url = new URL(location.href);
  url.searchParams.set('pose', poseStr);
  url.searchParams.set('orbit', viewer.isAutoOrbit() ? '1' : '0');
  url.searchParams.delete('authoring');
  return url.toString();
}

async function copyPoseUrl() {
  const url = buildPoseUrl();
  const original = els.btnCopyPose.textContent;
  try {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      await navigator.clipboard.writeText(url);
    } else {
      const ta = document.createElement('textarea');
      ta.value = url;
      ta.style.position = 'fixed';
      ta.style.opacity = '0';
      document.body.appendChild(ta);
      ta.select();
      document.execCommand('copy');
      document.body.removeChild(ta);
    }
    els.btnCopyPose.textContent = 'Copied!';
  } catch {
    els.btnCopyPose.textContent = 'Copy failed';
  }
  setTimeout(() => { els.btnCopyPose.textContent = original; }, 1500);
}

function wireControls() {
  els.btnOrbit.addEventListener('click', () => {
    viewer.setAutoOrbit(!viewer.isAutoOrbit());
    syncOrbitButton(viewer.isAutoOrbit());
  });
  viewer.onAutoOrbitChange(syncOrbitButton);

  els.btnFullscreen.addEventListener('click', () => {
    const enter = els.stage.requestFullscreen || els.stage.webkitRequestFullscreen;
    const exit = document.exitFullscreen || document.webkitExitFullscreen;
    const fsEl = document.fullscreenElement || document.webkitFullscreenElement;
    // iOS Safari exposes no Fullscreen API for non-<video> elements — fall
    // back to a CSS pseudo-fullscreen (fills the iframe, not the screen).
    if (!enter) {
      document.body.classList.toggle('fs-fallback');
      window.dispatchEvent(new Event('resize'));
      return;
    }
    if (fsEl) {
      exit.call(document);
    } else {
      const result = enter.call(els.stage);
      if (result && result.catch) result.catch(() => {
        document.body.classList.add('fs-fallback');
        window.dispatchEvent(new Event('resize'));
      });
    }
  });

  els.btnCopyPose.addEventListener('click', copyPoseUrl);
}

async function start() {
  els.error.hidden = true;
  els.gate.hidden = true;
  els.spinner.hidden = false;

  if (!hasWebGL2()) {
    els.gate.hidden = false; // keep the poster as backdrop
    showError('Your browser does not support WebGL2.');
    return;
  }

  try {
    if (!viewer) {
      const { createViewer } = await import('./viewer.js');
      viewer = await createViewer(els.host);
      wireControls();
    }
    await viewer.loadSplat(params.src, params.filename,
      { pose: params.pose, orbit: params.orbit });
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
      viewer.setAutoOrbit(false);
    }
    els.spinner.hidden = true;
    els.controls.hidden = false;
    if (params.authoring) els.btnCopyPose.hidden = false;
    syncOrbitButton(viewer.isAutoOrbit());
  } catch (err) {
    console.error('[embed] load failed:', err);
    showError('Could not load the scene.');
  }
}

if (!params.src) {
  els.hint.hidden = false;
} else {
  els.gateLabel.textContent = sceneLabel(params.filename);
  if (params.poster) {
    els.gate.style.backgroundImage =
      'url("' + params.poster.replace(/"/g, '%22') + '")';
    els.gate.classList.add('has-poster');
  }
  if (params.autoplay) start();
  else els.gate.hidden = false;
}
els.gate.addEventListener('click', start);
els.retry.addEventListener('click', start);
```

- [ ] **Step 6: Tests laufen lassen — müssen bestehen**

Run: `cd embed && ./tests/run.sh`
Expected: 19 Unit + 7 E2E PASS (5 bestehend + 2 neu)

- [ ] **Step 7: Commit**

```bash
git add embed/index.html embed/css/embed.css embed/js/main.js embed/tests/e2e/pose-authoring.test.mjs
git commit -m "feat(embed): authoring mode — copy-pose button + URL builder"
```

---

### Task 4: Doku

**Files:**
- Modify: `embed/AGENTS.md`
- Modify: `CHANGELOG.md` (Root — `[Unreleased]`)

**Interfaces:**
- Consumes: alles aus Tasks 1–3 (beschreibt es nur).
- Produces: —

- [ ] **Step 1: `embed/AGENTS.md` — Architecture principles erweitern**

Die erste Zeile im Abschnitt „## Architecture principles" ersetzen von:

```markdown
- `index.html?src=…&poster=…&autoplay=1` is the entire public API.
```

zu:

```markdown
- `index.html?src=…&poster=…&autoplay=1&pose=…&orbit=…&authoring=1` is the
  entire public API. `pose=cx,cy,cz,fx,fy,fz` overrides auto-framing with a
  fixed camera position + focus point; `orbit=0` disables auto-orbit on load
  (default: on); `authoring=1` reveals a "Copy pose" button that captures the
  live camera into a ready-to-embed `pose=`/`orbit=` URL. Spec:
  `pipeline/docs/superpowers/specs/2026-07-15-embed-pose-authoring-design.md`.
```

- [ ] **Step 2: Root-`CHANGELOG.md` — bestehenden `embed/`-Eintrag erweitern**

Den Satz „`viewer/` is parked as the development viewer…" im bestehenden
`embed/`-Bullet unter `[Unreleased]` erweitern von:

```markdown
- **`embed/` — minimal, embeddable splat viewer.** A new self-contained
  monorepo component: a single iframe page
  (`embed/index.html?src=…&poster=…&autoplay=1`) with click-to-load gate,
  percentile auto-framing, auto-orbit and fullscreen — and a fully vendored
  PlayCanvas engine (**zero external requests**). `viewer/` is parked as the
  development viewer (walking mode, collision editor, landing page live there).
```

zu:

```markdown
- **`embed/` — minimal, embeddable splat viewer.** A new self-contained
  monorepo component: a single iframe page
  (`embed/index.html?src=…&poster=…&autoplay=1`) with click-to-load gate,
  percentile auto-framing, auto-orbit and fullscreen — and a fully vendored
  PlayCanvas engine (**zero external requests**). `viewer/` is parked as the
  development viewer (walking mode, collision editor, landing page live there).
  A pose-authoring workflow (`?pose=…&orbit=…&authoring=1`) lets you capture a
  curated camera view into a ready-to-embed link instead of relying on
  auto-framing.
```

- [ ] **Step 3: Regression + Commit**

Run: `cd embed && ./tests/run.sh`
Expected: alle Tests PASS (Doku-Änderungen brechen nichts)

```bash
git add embed/AGENTS.md CHANGELOG.md
git commit -m "docs(embed): pose-authoring workflow"
```

---

### Task 5: Vollverifikation + manueller Smoke

**Files:**
- Modify: keine (nur Verifikation)

**Interfaces:**
- Consumes: alles.
- Produces: verifizierter Endzustand.

- [ ] **Step 1: Alle Testsuiten**

```bash
cd embed && ./tests/run.sh
```

Expected: 19 Unit + 7 E2E, alle PASS.

- [ ] **Step 2: Zero-external-Check**

```bash
grep -rn "https://cdn\|http://cdn\|jsdelivr\|unpkg" embed/index.html embed/js/ embed/css/ || echo "OK: keine CDN-Referenzen im Runtime-Code"
```

Expected: `OK: keine CDN-Referenzen im Runtime-Code`

- [ ] **Step 3: Manueller Smoke (echtes Rendering — vom User oder mit Browser-Tools)**

```bash
cd embed && ./serve.sh
mkdir -p embed/c
cp viewer/assets/demo/scene.sog embed/c/scene.sog
```

Checkliste im Browser:

1. `http://localhost:8130/?src=c/scene.sog&authoring=1` — Gate klicken, Szene
   lädt, „Copy pose"-Button ist sichtbar (Autoren-Modus). Frei orbiten/zoomen,
   dann „Copy pose" klicken → Button-Text wechselt kurz zu „Copied!".
2. Die kopierte URL (aus der Zwischenablage) in einem neuen Tab öffnen —
   **ohne** `authoring`: Szene erscheint sofort in der zuvor gewählten
   Ansicht, kein Auto-Frame-Sprung, „Copy pose"-Button ist NICHT sichtbar.
3. Dieselbe URL mit angehängtem `&orbit=0` öffnen: Kamera bleibt exakt auf
   der kopierten Pose stehen, kein Auto-Orbit.
4. `http://localhost:8130/?src=c/scene.sog` (ohne jeden neuen Param): Verhalten
   unverändert gegenüber dem Basis-Plan — Auto-Frame + Auto-Orbit wie bisher.

Danach aufräumen:

```bash
rm -rf embed/c
git status --short   # muss leer sein
```

- [ ] **Step 4: Abschluss**

`git log --oneline` zeigt die 4 neuen Task-Commits zusätzlich zu den 7
bestehenden; Arbeitsbaum sauber.
