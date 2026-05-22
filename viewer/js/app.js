import { createViewer } from './viewer.js';

const DEMO_URL = 'assets/demo/scene.sog';

const viewer = createViewer(document.getElementById('canvas-host'));
viewer.loadSplat(DEMO_URL, 'scene.sog');
