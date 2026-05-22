import {
  Application, Asset, AssetListLoader, Entity, Vec3,
  FILLMODE_FILL_WINDOW, RESOLUTION_AUTO
} from 'playcanvas';

const CAMERA_CONTROLS_URL =
  'https://cdn.jsdelivr.net/npm/playcanvas@2.18.1/scripts/esm/camera-controls.mjs';
const ORBIT_SPEED = 8; // degrees per second

// Start pose for the church demo splat (tuned in Task 4).
const SPLAT_LEVEL = { x: -19, y: 10, z: 180 };
const SPLAT_OFFSET = { x: 2.4, y: 2.4, z: -1.2 };
const CAMERA_POS = { x: 1.878, y: 1.115, z: -5.222 };
const CAMERA_FOCUS = { x: 0.656, y: -0.107, z: 0.212 };

export function createViewer(hostElement) {
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
  camera.setPosition(CAMERA_POS.x, CAMERA_POS.y, CAMERA_POS.z);
  app.root.addChild(camera);

  let cc = null;
  const cameraReady = (async () => {
    const ccAsset = new Asset('camera-controls', 'script', { url: CAMERA_CONTROLS_URL });
    await new Promise(res => new AssetListLoader([ccAsset], app.assets).load(res));
    camera.addComponent('script');
    cc = camera.script.create('cameraControls');
  })();

  // splatPivot rotates for the auto-orbit; splatEntity holds the static leveling
  let splatPivot = null;
  let splatEntity = null;
  let autoOrbit = true;

  app.on('update', (dt) => {
    if (autoOrbit && splatPivot) splatPivot.rotate(0, ORBIT_SPEED * dt, 0);
  });

  for (const ev of ['pointerdown', 'wheel']) {
    canvas.addEventListener(ev, () => { autoOrbit = false; });
  }

  function applyStartPose() {
    if (cc) cc.reset(
      new Vec3(CAMERA_FOCUS.x, CAMERA_FOCUS.y, CAMERA_FOCUS.z),
      new Vec3(CAMERA_POS.x, CAMERA_POS.y, CAMERA_POS.z));
  }

  async function loadSplat(url, filename) {
    await cameraReady;
    const asset = new Asset('splat', 'gsplat', { url, filename });
    await new Promise((resolve, reject) => {
      asset.once('load', resolve);
      asset.once('error', reject);
      app.assets.add(asset);
      app.assets.load(asset);
    });
    if (splatPivot) splatPivot.destroy();
    splatPivot = new Entity('splat-pivot');
    splatEntity = new Entity('splat');
    splatEntity.addComponent('gsplat', { asset });
    splatEntity.setLocalEulerAngles(SPLAT_LEVEL.x, SPLAT_LEVEL.y, SPLAT_LEVEL.z);
    splatEntity.setLocalPosition(SPLAT_OFFSET.x, SPLAT_OFFSET.y, SPLAT_OFFSET.z);
    splatPivot.addChild(splatEntity);
    app.root.addChild(splatPivot);
    applyStartPose();
  }

  return {
    loadSplat,
    setAutoOrbit(on) { autoOrbit = on; },
    isAutoOrbit() { return autoOrbit; }
  };
}
