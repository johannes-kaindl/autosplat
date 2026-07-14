# Embed-Viewer (`embed/`) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Eine neue self-contained Monorepo-Komponente `embed/` — ein minimaler, embed-fähiger Gaussian-Splat-Viewer als iframe-Seite mit Click-to-Load-Gate, Auto-Frame, Auto-Orbit, Fullscreen und komplett vendored Engine (zero-external).

**Architecture:** Eine einzige HTML-Seite (`embed/index.html?src=…&poster=…&autoplay=1`). Pure Logik (`js/params.js`, `js/autoframe.js`) ist framework-frei und node-unit-getestet; DOM-/Engine-Glue liegt in `js/main.js` (Shell) und `js/viewer.js` (Runtime). Die PlayCanvas-Engine liegt gepinnt unter `vendor/` und wird erst nach Gate-Klick per dynamic import geladen. Spec: `pipeline/docs/superpowers/specs/2026-07-14-embed-viewer-design.md`.

**Tech Stack:** Vanilla HTML/CSS/JS (ES-Module, kein Build-Step) · PlayCanvas 2.18.1 (vendored) · `node:test` (Unit) · `puppeteer-core` + System-Chrome (E2E).

## Global Constraints

- **Kein Build-Step, keine npm-Runtime-Deps, keine Transpilation** (Workspace-Konvention; nur `puppeteer-core` als gitignorierte Test-Dependency).
- **Zero-external:** Die Seite macht KEINE Requests an fremde Hosts. Engine-Version gepinnt auf **2.18.1**.
- **`viewer/` wird NICHT angefasst**, außer den zwei Park-Vermerken in Task 6.
- 2-Space-Indent, LF (Root-`.editorconfig`).
- Conventional Commits mit Trailer `Co-Authored-By: Claude <noreply@anthropic.com>` (bzw. dem Modell-spezifischen Trailer der ausführenden Session).
- **`cd embed && ./tests/run.sh` muss vor jedem Commit grün sein** (ab Task 1).
- Alle Pfade unten relativ zum Repo-Root `/Users/Shared/code/autosplat`.

---

### Task 1: Test-Harness + URL-Param-Parsing (`params.js`)

**Files:**
- Create: `embed/tests/run.sh`
- Create: `embed/tests/package.json`
- Create: `embed/.gitignore`
- Create: `embed/js/params.js`
- Test: `embed/tests/unit/params.test.mjs`

**Interfaces:**
- Consumes: —
- Produces: `parseParams(search: string) → { src: string|null, poster: string|null, autoplay: boolean, filename: string|null }` und `sceneLabel(filename: string|null) → string` aus `embed/js/params.js` (genutzt von Task 5 `main.js`).

- [ ] **Step 1: Harness-Dateien anlegen**

`embed/tests/run.sh` (danach `chmod +x embed/tests/run.sh`):

```bash
#!/usr/bin/env bash
# Run all embed tests. Pass `unit` or `e2e` to scope; defaults to both.
set -euo pipefail
cd "$(dirname "$0")"

scope="${1:-all}"

if [[ "$scope" == "unit" || "$scope" == "all" ]]; then
  echo "==> unit tests"
  node --test unit/*.test.mjs
fi

if [[ "$scope" == "e2e" || "$scope" == "all" ]]; then
  echo "==> e2e tests"
  if ls e2e/*.test.mjs >/dev/null 2>&1; then
    if [[ ! -d node_modules ]]; then
      echo "  (installing test deps…)"
      npm install --no-audit --no-fund --silent
    fi
    node --test e2e/*.test.mjs
  else
    echo "  (no e2e tests yet)"
  fi
fi
```

`embed/tests/package.json`:

```json
{
  "name": "autosplat-embed-tests",
  "version": "1.0.0",
  "private": true,
  "type": "module",
  "description": "Test harness for the embed viewer (gitignored node_modules).",
  "devDependencies": {
    "puppeteer-core": "^23.11.1"
  }
}
```

`embed/.gitignore`:

```
tests/node_modules/
```

- [ ] **Step 2: Failing Test schreiben**

`embed/tests/unit/params.test.mjs`:

```js
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { parseParams, sceneLabel } from '../../js/params.js';

test('parseParams: src + filename derived', () => {
  const p = parseParams('?src=c/scene.sog');
  assert.equal(p.src, 'c/scene.sog');
  assert.equal(p.filename, 'scene.sog');
  assert.equal(p.poster, null);
  assert.equal(p.autoplay, false);
});

test('parseParams: empty search → no src', () => {
  const p = parseParams('');
  assert.equal(p.src, null);
  assert.equal(p.filename, null);
});

test('parseParams: poster + autoplay flags', () => {
  const p = parseParams('?src=a/b/haus.ply&poster=p.jpg&autoplay=1');
  assert.equal(p.poster, 'p.jpg');
  assert.equal(p.autoplay, true);
  assert.equal(p.filename, 'haus.ply');
});

test('parseParams: autoplay only for exact "1"', () => {
  assert.equal(parseParams('?src=x.sog&autoplay=yes').autoplay, false);
});

test('parseParams: filename strips query and hash', () => {
  const p = parseParams('?src=' + encodeURIComponent('c/scene.sog?v=2#frag'));
  assert.equal(p.filename, 'scene.sog');
});

test('sceneLabel: strips extension, prettifies separators', () => {
  assert.equal(sceneLabel('max_strasse.sog'), 'max strasse');
  assert.equal(sceneLabel('wasser-turm.ply'), 'wasser turm');
  assert.equal(sceneLabel(null), '');
});
```

- [ ] **Step 3: Test laufen lassen — muss fehlschlagen**

Run: `cd embed && ./tests/run.sh unit`
Expected: FAIL — `Cannot find module … js/params.js`

- [ ] **Step 4: Implementierung**

`embed/js/params.js`:

```js
// Pure URL-parameter parsing for the embed page — unit-testable in node.
export function parseParams(search) {
  const q = new URLSearchParams(search);
  const src = (q.get('src') || '').trim() || null;
  const poster = (q.get('poster') || '').trim() || null;
  const autoplay = q.get('autoplay') === '1';
  const filename = src
    ? (src.split('?')[0].split('#')[0].split('/').pop() || 'scene.sog')
    : null;
  return { src, poster, autoplay, filename };
}

// "max_strasse.sog" → "max strasse" — a quiet human label for the gate card.
export function sceneLabel(filename) {
  if (!filename) return '';
  return filename.replace(/\.(sog|ply)$/i, '').replace(/[-_]+/g, ' ');
}
```

- [ ] **Step 5: Test laufen lassen — muss bestehen**

Run: `cd embed && ./tests/run.sh unit`
Expected: PASS (6 Tests), e2e-Teil meldet `(no e2e tests yet)`

- [ ] **Step 6: Commit**

```bash
git add embed/tests/run.sh embed/tests/package.json embed/.gitignore embed/js/params.js embed/tests/unit/params.test.mjs
git commit -m "feat(embed): test harness + URL-param parsing"
```

---

### Task 2: Perzentil-Auto-Frame-Mathe (`autoframe.js`)

**Files:**
- Create: `embed/js/autoframe.js`
- Test: `embed/tests/unit/autoframe.test.mjs`

**Interfaces:**
- Consumes: —
- Produces: `frameBounds(centers: ArrayLike<number>, opts?: { pct?: number, maxSamples?: number }) → { lo: number[3], hi: number[3], center: number[3], radius: number } | null` aus `embed/js/autoframe.js` (genutzt von Task 4 `viewer.js`). Gibt `null` bei leerem Input zurück; `radius` hat ein Minimum von `0.5`.

- [ ] **Step 1: Failing Test schreiben**

`embed/tests/unit/autoframe.test.mjs`:

```js
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
```

- [ ] **Step 2: Test laufen lassen — muss fehlschlagen**

Run: `cd embed && ./tests/run.sh unit`
Expected: FAIL — `Cannot find module … js/autoframe.js`

- [ ] **Step 3: Implementierung**

Die Logik ist 1:1 die floater-robuste Perzentil-Mathe aus `viewer/js/viewer.js#autoFrameCamera` (dort in-line und untestbar) — hier als pure Funktion ohne Engine-Imports.

`embed/js/autoframe.js`:

```js
// Pure percentile framing math — no engine imports, unit-testable in node.
// centers: flat [x0,y0,z0, x1,y1,z1, …] array-like of splat center positions.
export function frameBounds(centers, { pct = 0.025, maxSamples = 60000 } = {}) {
  const n = Math.floor(centers.length / 3);
  if (n === 0) return null;

  const step = Math.max(1, Math.floor(n / maxSamples));
  const xs = [], ys = [], zs = [];
  for (let i = 0; i < n; i += step) {
    xs.push(centers[i * 3]); ys.push(centers[i * 3 + 1]); zs.push(centers[i * 3 + 2]);
  }

  const q = (arr, t) => {
    arr.sort((a, b) => a - b);
    return arr[Math.min(arr.length - 1, Math.max(0, Math.floor(t * (arr.length - 1))))];
  };
  const lo = [q(xs, pct), q(ys, pct), q(zs, pct)];
  const hi = [q(xs, 1 - pct), q(ys, 1 - pct), q(zs, 1 - pct)];
  const center = [(lo[0] + hi[0]) / 2, (lo[1] + hi[1]) / 2, (lo[2] + hi[2]) / 2];
  const radius = Math.max(
    (hi[0] - lo[0]) / 2, (hi[1] - lo[1]) / 2, (hi[2] - lo[2]) / 2, 0.5);
  return { lo, hi, center, radius };
}
```

- [ ] **Step 4: Test laufen lassen — muss bestehen**

Run: `cd embed && ./tests/run.sh unit`
Expected: PASS (11 Tests gesamt)

- [ ] **Step 5: Commit**

```bash
git add embed/js/autoframe.js embed/tests/unit/autoframe.test.mjs
git commit -m "feat(embed): percentile auto-frame math as pure function"
```

---

### Task 3: Engine vendoren (zero-external)

**Files:**
- Create: `embed/vendor/playcanvas.mjs` (Download, ~3,7 MB)
- Create: `embed/vendor/camera-controls.mjs` (Download, ~22 KB)
- Create: `embed/vendor/README.md`

**Interfaces:**
- Consumes: —
- Produces: `vendor/playcanvas.mjs` (ESM-Engine, wird in Task 5 per Importmap auf den Specifier `"playcanvas"` gemappt) und `vendor/camera-controls.mjs` (PlayCanvas-ESM-Script, von Task 4 `viewer.js` als Script-Asset unter der URL `vendor/camera-controls.mjs` geladen).

- [ ] **Step 1: Dateien herunterladen (Version gepinnt)**

```bash
mkdir -p embed/vendor
curl -fsSL -o embed/vendor/playcanvas.mjs \
  https://cdn.jsdelivr.net/npm/playcanvas@2.18.1/build/playcanvas.mjs
curl -fsSL -o embed/vendor/camera-controls.mjs \
  https://cdn.jsdelivr.net/npm/playcanvas@2.18.1/scripts/esm/camera-controls.mjs
```

- [ ] **Step 2: Downloads verifizieren**

```bash
ls -l embed/vendor/
node --check embed/vendor/playcanvas.mjs && echo "playcanvas.mjs: syntax OK"
node --check embed/vendor/camera-controls.mjs && echo "camera-controls.mjs: syntax OK"
grep -c "2.18.1" embed/vendor/playcanvas.mjs
head -3 embed/vendor/camera-controls.mjs
```

Expected: `playcanvas.mjs` ≈ 3.695.517 Bytes, `camera-controls.mjs` ≈ 22.164 Bytes; beide `syntax OK`; grep ≥ 1; der head zeigt einen `import … from 'playcanvas'` (dieser Import wird zur Laufzeit von der Importmap aus Task 5 aufgelöst).

- [ ] **Step 3: vendor/README.md schreiben**

`embed/vendor/README.md`:

```markdown
# vendor/ — pinned runtime dependencies

Vendored so the embed page makes **zero external requests**.

| File | Version | Source | License |
|---|---|---|---|
| `playcanvas.mjs` | 2.18.1 | <https://cdn.jsdelivr.net/npm/playcanvas@2.18.1/build/playcanvas.mjs> | MIT |
| `camera-controls.mjs` | 2.18.1 | <https://cdn.jsdelivr.net/npm/playcanvas@2.18.1/scripts/esm/camera-controls.mjs> | MIT |

**Update:** change the version in BOTH URLs, re-download both files
(`curl -fsSL -o …`), then run `../tests/run.sh`.
```

- [ ] **Step 4: Tests laufen lassen (Regression)**

Run: `cd embed && ./tests/run.sh`
Expected: PASS (unverändert 11 Unit-Tests)

- [ ] **Step 5: Commit**

```bash
git add embed/vendor/
git commit -m "feat(embed): vendor PlayCanvas 2.18.1 engine + camera-controls (zero-external)"
```

---

### Task 4: Viewer-Runtime (`viewer.js`)

**Files:**
- Create: `embed/js/viewer.js`

**Interfaces:**
- Consumes: `frameBounds` aus `embed/js/autoframe.js` (Task 2); `vendor/camera-controls.mjs` (Task 3); Engine-Imports über den Specifier `"playcanvas"` (aufgelöst durch die Importmap aus Task 5).
- Produces: `createViewer(hostElement: HTMLElement) → Promise<{ loadSplat(url: string, filename: string): Promise<void>, setAutoOrbit(on: boolean): void, isAutoOrbit(): boolean, onAutoOrbitChange(fn: (on: boolean) => void): void }>`. `loadSplat` wirft `Error('splat-load-failed')` bei Ladefehlern. Genutzt von Task 5 `main.js` via `await import('./viewer.js')`.

**Kontext für den Implementierer:** Dieser Code ist eine destillierte Fassung von `viewer/js/viewer.js` (dem geparkten Dev-Viewer) — nur Orbit + Auto-Frame, ohne Walking/Collision/WebGL2-Fallback (der Fallback lebt in Task 5 `main.js`, VOR dem Engine-Import). Verhalten, das übernommen wird: z:180-Level-Flip (Brush/COLMAP-Konvention), Format-Detection über den Dateinamen via `loadFromUrlAndFilename`, Centers-Zugriff über den underscore-Pfad `gsplat._instance.resource.centers` (PlayCanvas-2.x-Eigenheit), Orbit-Pause bei Interaktion.

- [ ] **Step 1: Implementierung**

`embed/js/viewer.js`:

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

  async function loadSplat(url, filename) {
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

    await autoFrame();
    setAutoOrbit(true);
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

  return {
    loadSplat,
    setAutoOrbit,
    isAutoOrbit() { return autoOrbit; },
    onAutoOrbitChange(fn) { orbitListeners.push(fn); },
  };
}
```

- [ ] **Step 2: Syntax-Gate + Regression**

Verhalten wird in Task 5 per E2E getestet (braucht die Seite); hier nur das Syntax-Gate:

Run: `node --check embed/js/viewer.js && cd embed && ./tests/run.sh unit`
Expected: kein Syntax-Fehler, 11 Unit-Tests PASS

- [ ] **Step 3: Commit**

```bash
git add embed/js/viewer.js
git commit -m "feat(embed): viewer runtime — orbit, percentile auto-frame, vendored engine"
```

---

### Task 5: Die Embed-Seite (`index.html` + `embed.css` + `main.js`) + E2E

**Files:**
- Create: `embed/index.html`
- Create: `embed/css/embed.css`
- Create: `embed/js/main.js`
- Create: `embed/serve.sh`
- Test: `embed/tests/e2e/embed-smoke.test.mjs`

**Interfaces:**
- Consumes: `parseParams`/`sceneLabel` (Task 1), `createViewer` (Task 4, lazy via `import('./viewer.js')`), Importmap `"playcanvas"` → `./vendor/playcanvas.mjs` (Task 3).
- Produces: Die öffentliche API der Komponente: `index.html?src=…[&poster=…][&autoplay=1]`.

- [ ] **Step 1: Failing E2E-Tests schreiben**

`embed/tests/e2e/embed-smoke.test.mjs`:

```js
// End-to-end smoke for the embed page: DOM lifecycle of gate/hint/error.
// Uses puppeteer-core + system Chrome. Real splat rendering is verified
// manually with ../serve.sh — headless GL is not a fidelity reference,
// which is also why the error-message assertion tolerates the WebGL2 path.
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
const PORT = 8131;
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

test('no src: hint card shown, gate + controls stay hidden', async () => {
  const page = await browser.newPage();
  await page.goto(URL_BASE + '/', { waitUntil: 'domcontentloaded' });
  const s = await page.evaluate(() => ({
    hint: !document.getElementById('hint-card').hidden,
    gate: document.getElementById('gate').hidden,
    controls: document.getElementById('controls').hidden,
  }));
  assert.equal(s.hint, true, 'hint card visible');
  assert.equal(s.gate, true, 'gate hidden');
  assert.equal(s.controls, true, 'controls hidden');
  await page.close();
});

test('with src: gate shown with scene label, hint hidden', async () => {
  const page = await browser.newPage();
  await page.goto(URL_BASE + '/?src=c/max_strasse.sog',
                  { waitUntil: 'domcontentloaded' });
  const s = await page.evaluate(() => ({
    gateHidden: document.getElementById('gate').hidden,
    label: document.getElementById('gate-label').textContent,
    hintHidden: document.getElementById('hint-card').hidden,
  }));
  assert.equal(s.gateHidden, false, 'gate visible');
  assert.equal(s.label, 'max strasse');
  assert.equal(s.hintHidden, true, 'hint hidden');
  await page.close();
});

test('poster param: gate gets background image + has-poster class', async () => {
  const page = await browser.newPage();
  await page.goto(URL_BASE + '/?src=x.sog&poster=poster.jpg',
                  { waitUntil: 'domcontentloaded' });
  const s = await page.evaluate(() => ({
    cls: document.getElementById('gate').classList.contains('has-poster'),
    bg: document.getElementById('gate').style.backgroundImage,
  }));
  assert.equal(s.cls, true);
  assert.match(s.bg, /poster\.jpg/);
  await page.close();
});

test('gate click with broken src: error card with retry appears', async () => {
  const page = await browser.newPage();
  await page.goto(URL_BASE + '/?src=does-not-exist.sog',
                  { waitUntil: 'domcontentloaded' });
  await page.click('#gate');
  await page.waitForFunction(
    () => !document.getElementById('error-card').hidden, { timeout: 30000 });
  const s = await page.evaluate(() => ({
    msg: document.getElementById('error-msg').textContent,
    retry: !!document.getElementById('btn-retry'),
    spinnerHidden: document.getElementById('spinner').hidden,
  }));
  assert.match(s.msg, /Could not load|WebGL2/);
  assert.equal(s.retry, true, 'retry button present');
  assert.equal(s.spinnerHidden, true, 'spinner gone');
  await page.close();
});

test('autoplay=1: gate never shows, load starts immediately', async () => {
  const page = await browser.newPage();
  await page.goto(URL_BASE + '/?src=does-not-exist.sog&autoplay=1',
                  { waitUntil: 'domcontentloaded' });
  const gateHidden = await page.evaluate(
    () => document.getElementById('gate').hidden);
  assert.equal(gateHidden, true, 'gate stays hidden with autoplay');
  await page.waitForFunction(
    () => !document.getElementById('error-card').hidden, { timeout: 30000 });
  await page.close();
});
```

- [ ] **Step 2: Test laufen lassen — muss fehlschlagen**

Run: `cd embed && ./tests/run.sh e2e`
Expected: FAIL — Requests auf `/` liefern 404 (kein `index.html`), `document.getElementById(...)` ist `null`

- [ ] **Step 3: `index.html` schreiben**

`embed/index.html`:

```html
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
  <title>autosplat embed</title>
  <meta name="robots" content="noindex">
  <link rel="stylesheet" href="css/embed.css">
  <script type="importmap">
  {
    "imports": {
      "playcanvas": "./vendor/playcanvas.mjs"
    }
  }
  </script>
</head>
<body>
  <main id="stage">
    <div id="canvas-host"></div>

    <button id="gate" hidden>
      <span class="play-ico" aria-hidden="true">▶</span>
      <span id="gate-label"></span>
      <span class="gate-sub">Click to load 3D scene</span>
    </button>

    <div id="hint-card" hidden>
      <p>No scene specified.</p>
      <p class="muted">Embed this page with <code>?src=path/to/scene.sog</code></p>
    </div>

    <div id="error-card" role="alert" hidden>
      <p id="error-msg"></p>
      <button id="btn-retry" type="button">Retry</button>
    </div>

    <div id="spinner" hidden aria-live="polite">Loading…</div>

    <div id="controls" hidden>
      <button id="btn-orbit" type="button" aria-pressed="true"
              aria-label="Pause auto-orbit">⏸</button>
      <button id="btn-fullscreen" type="button" aria-label="Fullscreen">⛶</button>
    </div>

    <a id="badge" href="https://codeberg.org/jkaindl/autosplat"
       target="_blank" rel="noopener">autosplat</a>
  </main>
  <script type="module" src="js/main.js"></script>
</body>
</html>
```

- [ ] **Step 4: `embed.css` schreiben**

`embed/css/embed.css`:

```css
/* embed.css — minimal chrome for the embed viewer. Dark, quiet, iframe-first. */
* { box-sizing: border-box; margin: 0; padding: 0; }
html, body { height: 100%; }
body {
  background: #0e0f13;
  color: #e8eaf0;
  font: 15px/1.45 system-ui, -apple-system, "Segoe UI", sans-serif;
  overflow: hidden;
}
#stage { position: relative; width: 100%; height: 100%; }
#canvas-host, #canvas-host canvas {
  position: absolute; inset: 0; width: 100%; height: 100%; display: block;
}

/* --- click-to-load gate --- */
#gate {
  position: absolute; inset: 0; z-index: 3;
  display: flex; flex-direction: column; align-items: center; justify-content: center;
  gap: 0.6rem;
  width: 100%; border: 0; cursor: pointer;
  background-color: #14161d;
  background-size: cover; background-position: center;
  color: inherit; font: inherit;
}
#gate.has-poster::before {
  content: ""; position: absolute; inset: 0;
  background: rgba(10, 11, 15, 0.35);
}
#gate > * { position: relative; }
.play-ico {
  display: grid; place-items: center;
  width: 64px; height: 64px; border-radius: 50%;
  background: rgba(232, 234, 240, 0.14);
  border: 1px solid rgba(232, 234, 240, 0.4);
  font-size: 1.4rem; padding-left: 4px;
  transition: background 0.15s ease;
}
#gate:hover .play-ico,
#gate:focus-visible .play-ico { background: rgba(232, 234, 240, 0.28); }
#gate-label { font-weight: 600; letter-spacing: 0.01em; }
.gate-sub { font-size: 0.8rem; opacity: 0.6; }

/* --- cards (hint / error) --- */
#hint-card, #error-card {
  position: absolute; z-index: 4;
  left: 50%; top: 50%; transform: translate(-50%, -50%);
  max-width: min(85%, 26rem);
  padding: 1rem 1.25rem; border-radius: 10px;
  background: rgba(20, 22, 29, 0.92);
  border: 1px solid rgba(232, 234, 240, 0.12);
  text-align: center;
}
#hint-card .muted { font-size: 0.85rem; opacity: 0.65; margin-top: 0.35rem; }
#hint-card code { font-family: ui-monospace, monospace; font-size: 0.85em; }
#error-card { border-color: rgba(255, 120, 120, 0.35); }
#btn-retry {
  margin-top: 0.7rem; padding: 0.4rem 1.1rem;
  border-radius: 999px; border: 1px solid rgba(232, 234, 240, 0.35);
  background: transparent; color: inherit; font: inherit; cursor: pointer;
}
#btn-retry:hover { background: rgba(232, 234, 240, 0.12); }

/* --- spinner --- */
#spinner {
  position: absolute; z-index: 4;
  left: 50%; top: 50%; transform: translate(-50%, -50%);
  padding: 0.5rem 1rem; border-radius: 999px;
  background: rgba(20, 22, 29, 0.85); font-size: 0.9rem;
}

/* --- controls --- */
#controls {
  position: absolute; z-index: 5;
  right: max(0.6rem, env(safe-area-inset-right));
  bottom: max(0.6rem, env(safe-area-inset-bottom));
  display: flex; gap: 0.4rem;
}
#controls button {
  width: 38px; height: 38px; border-radius: 8px;
  border: 1px solid rgba(232, 234, 240, 0.18);
  background: rgba(20, 22, 29, 0.7); color: inherit;
  font-size: 1rem; cursor: pointer;
}
#controls button:hover { background: rgba(38, 41, 52, 0.85); }

/* --- badge --- */
#badge {
  position: absolute; z-index: 5;
  left: max(0.6rem, env(safe-area-inset-left));
  bottom: max(0.6rem, env(safe-area-inset-bottom));
  font-size: 0.75rem; letter-spacing: 0.02em;
  color: inherit; text-decoration: none; opacity: 0.55;
}
#badge:hover { opacity: 0.9; }

/* iOS pseudo-fullscreen fallback (fills the iframe viewport, not the screen) */
body.fs-fallback #stage { position: fixed; inset: 0; z-index: 999; }

[hidden] { display: none !important; }
```

- [ ] **Step 5: `main.js` schreiben**

`embed/js/main.js`:

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
    await viewer.loadSplat(params.src, params.filename);
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
      viewer.setAutoOrbit(false);
    }
    els.spinner.hidden = true;
    els.controls.hidden = false;
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
els.retry.addEventListener('click', start);
```

- [ ] **Step 6: `serve.sh` schreiben**

`embed/serve.sh` (danach `chmod +x embed/serve.sh`):

```bash
#!/usr/bin/env bash
# Serve embed/ locally for manual smoke testing.
cd "$(dirname "$0")"
echo "→ http://localhost:8130/?src=<path-to-scene.sog>"
python3 -m http.server 8130
```

- [ ] **Step 7: Tests laufen lassen — müssen bestehen**

Run: `cd embed && ./tests/run.sh`
Expected: 11 Unit + 5 E2E PASS. (Der Broken-src-E2E lädt die vendored Engine wirklich — das verifiziert nebenbei Importmap + Vendoring.)

- [ ] **Step 8: Commit**

```bash
git add embed/index.html embed/css/embed.css embed/js/main.js embed/serve.sh embed/tests/e2e/embed-smoke.test.mjs
git commit -m "feat(embed): embed page — click-to-load gate, minimal chrome, e2e smoke"
```

---

### Task 6: Doku + Repo-Integration

**Files:**
- Create: `embed/AGENTS.md`
- Modify: `AGENTS.md` (Root — Komponententabelle + Test-Zeile)
- Modify: `viewer/AGENTS.md` (Park-Vermerk nach der "What this is"-Sektion)
- Modify: `viewer/README.md` (Park-Vermerk nach der ersten Überschrift)
- Modify: `CHANGELOG.md` (Root — `[Unreleased]`)

**Interfaces:**
- Consumes: alles aus Tasks 1–5 (beschreibt es nur).
- Produces: —

- [ ] **Step 1: `embed/AGENTS.md` schreiben**

```markdown
# AGENTS.md

> **Workspace-Standards:** Die verbindliche Leitkonvention steht in `_docs/CONVENTIONS.md`
> (am Workspace-Root `/Users/Shared/code/`), Modell comply-or-explain.

Conventions for AI assistants working in `embed/`.

## Project character

Minimal, embeddable Gaussian-Splat viewer as a single self-contained iframe
page. Vanilla HTML/CSS/JS ES modules, no build step, **zero external
requests** — the PlayCanvas engine is vendored under `vendor/`. Spec:
`pipeline/docs/superpowers/specs/2026-07-14-embed-viewer-design.md`.

## Architecture principles

- `index.html?src=…&poster=…&autoplay=1` is the entire public API.
- The engine loads only after the click-gate (or `autoplay=1`) — the initial
  page stays a few KB.
- Pure logic (`js/params.js`, `js/autoframe.js`) is framework-free and
  unit-tested in node; DOM/engine glue lives in `js/main.js` / `js/viewer.js`.
- Deliberately NOT here: walking mode, collision editor, dropzone, PWA/service
  worker, demo scenes, marketing copy. That all stays in `viewer/` (the parked
  development viewer).

## Commands

- Tests: `./tests/run.sh` (or `./tests/run.sh unit` / `e2e`). Must pass
  before any commit.
- Local dev: `./serve.sh` → http://localhost:8130/?src=…

## Conventions

- Conventional Commits (`feat(embed): …`); `Co-Authored-By:` trailer for
  AI-pair commits.
- 2-space indent, LF (root `.editorconfig` applies).
- No bundlers, no transpilation, no npm runtime deps.

## Gotchas

- `vendor/playcanvas.mjs` is pinned (see `vendor/README.md`). Version bumps:
  re-download BOTH vendor files at the same version, then run all tests.
- The importmap in `index.html` maps `"playcanvas"` → `./vendor/playcanvas.mjs`;
  `camera-controls.mjs` resolves its `playcanvas` import through it. Don't
  rename the map key.
- Fullscreen inside an iframe needs `allow="fullscreen"` on the host's
  `<iframe>`; on iOS Safari the button falls back to CSS pseudo-fullscreen
  (fills only the iframe).
- e2e tests expect system Chrome at
  `/Applications/Google Chrome.app/Contents/MacOS/Google Chrome`.

## Memory

- Cross-session memory: `~/.claude/projects/-Users-Shared-code-autosplat/memory/`
- Coding-Cockpit: Pallas vault `25_Coding/autosplat/autosplat.md`.
```

- [ ] **Step 2: Root-`AGENTS.md` erweitern**

In der Komponententabelle (nach der `viewer/`-Zeile) ergänzen:

```markdown
| `embed/` | Minimaler, embed-fähiger Splat-Viewer: iframe-Seite mit vendored Engine, zero-external | `embed/AGENTS.md` |
```

Die `viewer/`-Zeile ändern von

```markdown
| `viewer/` | Statische Viewer-PWA für Gaussian Splats (Vanilla HTML/CSS/JS, kein Build-Step) | `viewer/AGENTS.md` |
```

zu

```markdown
| `viewer/` | Statische Viewer-PWA für Gaussian Splats (Vanilla HTML/CSS/JS, kein Build-Step) — geparkt als Entwicklungsviewer | `viewer/AGENTS.md` |
```

Und die Test-Zeile unter "Working in the monorepo" von

```markdown
- **Tests vor jedem Commit:** `cd pipeline && uv run pytest -q` bzw.
  `cd viewer && ./tests/run.sh`.
```

zu

```markdown
- **Tests vor jedem Commit:** `cd pipeline && uv run pytest -q` bzw.
  `cd viewer && ./tests/run.sh` bzw. `cd embed && ./tests/run.sh`.
```

- [ ] **Step 3: Park-Vermerke im Viewer**

In `viewer/AGENTS.md` direkt nach dem Absatz der Sektion "## What this is" einfügen:

```markdown
> **Status: geparkt als Entwicklungsviewer (2026-07).** Neue Features und
> Experimente (Walking-Mode, Collision-Editor, Landing) leben hier; der
> saubere, produktive Embed-Viewer ist die eigene Komponente `../embed/`
> (Spec: `pipeline/docs/superpowers/specs/2026-07-14-embed-viewer-design.md`).
```

In `viewer/README.md` direkt nach der ersten Überschrift (H1) denselben Hinweis in einer Zeile einfügen:

```markdown
> **Status (2026-07):** geparkt als Entwicklungsviewer — der saubere,
> embed-fähige Produktiv-Viewer lebt in [`../embed/`](../embed/).
```

- [ ] **Step 4: Root-`CHANGELOG.md` unter `[Unreleased]`**

Die leere `## [Unreleased]`-Sektion ersetzen durch:

```markdown
## [Unreleased]

### Added

- **`embed/` — minimal, embeddable splat viewer.** A new self-contained
  monorepo component: a single iframe page
  (`embed/index.html?src=…&poster=…&autoplay=1`) with click-to-load gate,
  percentile auto-framing, auto-orbit and fullscreen — and a fully vendored
  PlayCanvas engine (**zero external requests**). `viewer/` is parked as the
  development viewer (walking mode, collision editor, landing page live there).
```

- [ ] **Step 5: Regression + Commit**

Run: `cd embed && ./tests/run.sh`
Expected: alle Tests PASS (Doku-Änderungen brechen nichts)

```bash
git add embed/AGENTS.md AGENTS.md viewer/AGENTS.md viewer/README.md CHANGELOG.md
git commit -m "docs: embed/ component — AGENTS, park notes for viewer/, changelog"
```

---

### Task 7: Vollverifikation + manueller Smoke

**Files:**
- Modify: keine (nur Verifikation)

**Interfaces:**
- Consumes: alles.
- Produces: verifizierter Endzustand.

- [ ] **Step 1: Alle Testsuiten**

```bash
cd /Users/Shared/code/autosplat/embed && ./tests/run.sh
cd /Users/Shared/code/autosplat/viewer && ./tests/run.sh
```

Expected: beide komplett PASS (`viewer/` wurde nur in Doku-Zeilen angefasst — seine Tests müssen unverändert grün sein).

- [ ] **Step 2: Zero-external-Check**

```bash
grep -rn "https://cdn\|http://cdn\|jsdelivr\|unpkg" embed/index.html embed/js/ embed/css/ || echo "OK: keine CDN-Referenzen im Runtime-Code"
```

Expected: `OK: keine CDN-Referenzen im Runtime-Code` (Treffer in `embed/vendor/README.md` sind ok — das sind Doku-Links, kein Runtime-Code).

- [ ] **Step 3: Manueller Smoke (echtes Rendering — vom User oder mit Browser-Tools)**

```bash
cd /Users/Shared/code/autosplat/embed && ./serve.sh
```

Dann im Browser: `http://localhost:8130/?src=../viewer/assets/demo/scene.sog` — hier schlägt der Load fehl (Pfad außerhalb des Server-Roots), daher stattdessen die Demo-Szene einmalig für den Smoke kopieren:

```bash
mkdir -p /Users/Shared/code/autosplat/embed/c
cp /Users/Shared/code/autosplat/viewer/assets/demo/scene.sog /Users/Shared/code/autosplat/embed/c/scene.sog
```

Checkliste im Browser unter `http://localhost:8130/?src=c/scene.sog`:
- Gate erscheint mit Label "scene" + Play-Kreis; VOR dem Klick lädt kein `playcanvas.mjs` (Netzwerk-Tab).
- Klick → Spinner → Szene erscheint, auto-geframed, orbitet langsam.
- Drag/Wheel stoppt den Orbit; Orbit-Button zeigt ▶ und startet ihn wieder.
- Fullscreen-Button funktioniert; `?autoplay=1` lädt ohne Gate; ohne `?src` kommt die Hinweis-Karte.
- Netzwerk-Tab: ausschließlich `localhost`-Requests.

Danach die Smoke-Kopie wieder entfernen (sie ist nicht Teil der Komponente — `embed/c/` bleibt die Konvention für DEPLOYTE Szenen am Hosting-Ort):

```bash
rm -rf /Users/Shared/code/autosplat/embed/c
git status --short   # muss leer sein
```

- [ ] **Step 4: Abschluss**

`git log --oneline` zeigt die 6 Task-Commits; Arbeitsbaum sauber. Kein Release-Cut in dieser Session (bleibt `[Unreleased]`).

---

## Follow-ups (explizit NICHT Teil dieses Plans)

- Share-Bundle der Pipeline auf `embed/` als Bundle-Runtime umstellen (`ShareJobRunner`: `viewer_src_path` + Allowlist) — eigener Slice.
- Einbindung auf jkaindl.de (Ordner kopieren, `<iframe allow="fullscreen">` setzen).
- Web-Component-Wrapper.
