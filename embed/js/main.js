// Shell wiring for the embed page: poster gate, controls, error handling.
// The engine is imported only after the gate is clicked (or ?autoplay=1).
import { parseParams, sceneLabel, serializePose } from './params.js';

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
  const poseStr = serializePose([...pose.camPos, ...pose.focus, pose.yaw]);
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
    // Overrides any orbit=1 from the URL — accessibility wins over the
    // author's captured orbit state.
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
