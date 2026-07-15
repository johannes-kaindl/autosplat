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

  // opts.pose: optional [cx,cy,cz,fx,fy,fz,yaw] from the pose-authoring
  // workflow (?pose=…) — when present, skips auto-frame, applies yaw (degrees)
  // to the splat pivot, and positions the camera directly. opts.orbit: whether
  // auto-orbit should start after loading (default true, matching historical
  // behavior when omitted).
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

    if (opts.pose) {
      const [cx, cy, cz, fx, fy, fz, yaw] = opts.pose;
      splatPivot.setLocalEulerAngles(0, yaw, 0);
      cc.reset(new Vec3(fx, fy, fz), new Vec3(cx, cy, cz));
    } else {
      cc.reset(
        new Vec3(DEFAULT_POSE.cameraFocus.x, DEFAULT_POSE.cameraFocus.y,
                 DEFAULT_POSE.cameraFocus.z),
        new Vec3(DEFAULT_POSE.cameraPos.x, DEFAULT_POSE.cameraPos.y,
                 DEFAULT_POSE.cameraPos.z));
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
  // manual orbiting/zooming AND the auto-orbit pivot's accumulated rotation,
  // not just the pose at load time. cc.focusPoint returns a reused internal
  // Vec3, so its components are copied out immediately.
  function getPose() {
    const camPos = camera.getPosition();
    const focus = cc.focusPoint;
    const yaw = splatPivot ? splatPivot.getLocalEulerAngles().y : 0;
    return {
      camPos: [camPos.x, camPos.y, camPos.z],
      focus: [focus.x, focus.y, focus.z],
      yaw,
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
