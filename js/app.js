import { createViewer } from './viewer.js';
import { initDropzone } from './dropzone.js';

const DEMO_URL = 'assets/demo/scene.sog';

const viewer = createViewer(document.getElementById('canvas-host'));
viewer.loadSplat(DEMO_URL, 'scene.sog');

const btnOrbit = document.getElementById('btn-orbit');
const btnReset = document.getElementById('btn-reset');

function syncOrbitButton() {
  const on = viewer.isAutoOrbit();
  btnOrbit.textContent = `Auto-Orbit: ${on ? 'an' : 'aus'}`;
  btnOrbit.setAttribute('aria-pressed', String(on));
}

btnOrbit.addEventListener('click', () => {
  viewer.setAutoOrbit(!viewer.isAutoOrbit());
  syncOrbitButton();
});

// the canvas pauses auto-orbit on interaction — keep the button label in sync
setInterval(syncOrbitButton, 500);

btnReset.addEventListener('click', () => {
  viewer.loadSplat(DEMO_URL, 'scene.sog');
  viewer.setAutoOrbit(true);
  syncOrbitButton();
});

initDropzone({
  stage: document.getElementById('stage'),
  hint: document.getElementById('drop-hint'),
  fileInput: document.getElementById('file-input'),
  openButton: document.getElementById('btn-load'),
  onFile: (file) => {
    if (file) viewer.loadSplat(file);
  }
});
