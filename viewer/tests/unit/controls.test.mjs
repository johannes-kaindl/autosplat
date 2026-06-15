import { test } from 'node:test';
import assert from 'node:assert/strict';
import { KeyboardInput, TouchInput, CompositeInput } from '../../js/controls.js';

// Minimal EventTarget shim so the input class can attach/detach without a DOM.
class FakeTarget {
  constructor() { this.l = new Map(); }
  addEventListener(type, fn) {
    if (!this.l.has(type)) this.l.set(type, new Set());
    this.l.get(type).add(fn);
  }
  removeEventListener(type, fn) {
    this.l.get(type)?.delete(fn);
  }
  dispatch(type, event) {
    for (const fn of (this.l.get(type) ?? [])) fn(event);
  }
  listenerCount(type) {
    return this.l.get(type)?.size ?? 0;
  }
}

function key(code) { return { code, preventDefault: () => {} }; }

test('KeyboardInput: initial state is all zero/false', () => {
  const t = new FakeTarget();
  const input = new KeyboardInput();
  input.attach(t);
  const s = input.read();
  assert.equal(s.forward, 0);
  assert.equal(s.right, 0);
  assert.equal(s.vertical, 0);
  assert.equal(s.sprint, false);
  assert.equal(s.jump, false);
  assert.equal(s.fly, false);
  assert.equal(s.exit, false);
  assert.equal(s.lookDeltaX, 0);
  assert.equal(s.lookDeltaY, 0);
});

test('KeyboardInput: W → forward=1, S → forward=-1, W+S → 0', () => {
  const t = new FakeTarget();
  const input = new KeyboardInput();
  input.attach(t);

  t.dispatch('keydown', key('KeyW'));
  assert.equal(input.read().forward, 1);

  t.dispatch('keyup', key('KeyW'));
  t.dispatch('keydown', key('KeyS'));
  assert.equal(input.read().forward, -1);

  t.dispatch('keydown', key('KeyW'));
  assert.equal(input.read().forward, 0);  // both held → cancel
});

test('KeyboardInput: D/A and Arrow keys map to right axis', () => {
  const t = new FakeTarget();
  const input = new KeyboardInput();
  input.attach(t);

  t.dispatch('keydown', key('KeyD'));
  assert.equal(input.read().right, 1);
  t.dispatch('keyup', key('KeyD'));

  t.dispatch('keydown', key('ArrowLeft'));
  assert.equal(input.read().right, -1);
  t.dispatch('keyup', key('ArrowLeft'));

  t.dispatch('keydown', key('ArrowUp'));
  assert.equal(input.read().forward, 1);
});

test('KeyboardInput: Q/E map to vertical (fly-mode up/down)', () => {
  const t = new FakeTarget();
  const input = new KeyboardInput();
  input.attach(t);
  t.dispatch('keydown', key('KeyE'));
  assert.equal(input.read().vertical, 1);
  t.dispatch('keyup', key('KeyE'));
  t.dispatch('keydown', key('KeyQ'));
  assert.equal(input.read().vertical, -1);
});

test('KeyboardInput: Shift held → sprint=true (continuous)', () => {
  const t = new FakeTarget();
  const input = new KeyboardInput();
  input.attach(t);
  t.dispatch('keydown', key('ShiftLeft'));
  assert.equal(input.read().sprint, true);
  assert.equal(input.read().sprint, true);  // still held — still true
  t.dispatch('keyup', key('ShiftLeft'));
  assert.equal(input.read().sprint, false);
});

test('KeyboardInput: Space → jump=true once, then consumed', () => {
  const t = new FakeTarget();
  const input = new KeyboardInput();
  input.attach(t);
  t.dispatch('keydown', key('Space'));
  assert.equal(input.read().jump, true);
  assert.equal(input.read().jump, false);  // edge-triggered, consumed
});

test('KeyboardInput: Space repeats (key already down) do not re-fire jump', () => {
  const t = new FakeTarget();
  const input = new KeyboardInput();
  input.attach(t);
  t.dispatch('keydown', key('Space'));
  input.read();
  t.dispatch('keydown', key('Space'));  // OS auto-repeat
  assert.equal(input.read().jump, false);
  t.dispatch('keyup', key('Space'));
  t.dispatch('keydown', key('Space'));
  assert.equal(input.read().jump, true);  // fresh press fires again
});

test('KeyboardInput: KeyF → fly=true once, then consumed', () => {
  const t = new FakeTarget();
  const input = new KeyboardInput();
  input.attach(t);
  t.dispatch('keydown', key('KeyF'));
  assert.equal(input.read().fly, true);
  assert.equal(input.read().fly, false);
});

test('KeyboardInput: Escape → exit=true once, then consumed', () => {
  const t = new FakeTarget();
  const input = new KeyboardInput();
  input.attach(t);
  t.dispatch('keydown', key('Escape'));
  assert.equal(input.read().exit, true);
  assert.equal(input.read().exit, false);
});

test('KeyboardInput: mousemove accumulates lookDelta, read clears it', () => {
  const t = new FakeTarget();
  const input = new KeyboardInput();
  input.attach(t);
  t.dispatch('mousemove', { movementX: 5, movementY: -2 });
  t.dispatch('mousemove', { movementX: 3, movementY: 1 });
  const s = input.read();
  assert.equal(s.lookDeltaX, 8);
  assert.equal(s.lookDeltaY, -1);
  // read clears
  const s2 = input.read();
  assert.equal(s2.lookDeltaX, 0);
  assert.equal(s2.lookDeltaY, 0);
});

test('KeyboardInput: detach removes all listeners', () => {
  const t = new FakeTarget();
  const input = new KeyboardInput();
  input.attach(t);
  assert.ok(t.listenerCount('keydown') > 0);
  assert.ok(t.listenerCount('mousemove') > 0);
  input.detach();
  assert.equal(t.listenerCount('keydown'), 0);
  assert.equal(t.listenerCount('keyup'), 0);
  assert.equal(t.listenerCount('mousemove'), 0);
});

test('KeyboardInput: events stop firing after detach', () => {
  const t = new FakeTarget();
  const input = new KeyboardInput();
  input.attach(t);
  input.detach();
  t.dispatch('keydown', key('KeyW'));
  assert.equal(input.read().forward, 0);
});

test('KeyboardInput: reset() clears all held keys and pending edges', () => {
  const t = new FakeTarget();
  const input = new KeyboardInput();
  input.attach(t);
  t.dispatch('keydown', key('KeyW'));
  t.dispatch('keydown', key('Space'));
  t.dispatch('mousemove', { movementX: 10, movementY: 10 });
  input.reset();
  const s = input.read();
  assert.equal(s.forward, 0);
  assert.equal(s.jump, false);
  assert.equal(s.lookDeltaX, 0);
});

test('KeyboardInput: wheel events accumulate wheelDelta, read clears', () => {
  const t = new FakeTarget();
  const input = new KeyboardInput();
  input.attach(t);
  t.dispatch('wheel', { deltaY: 100, preventDefault: () => {} });
  t.dispatch('wheel', { deltaY: -30, preventDefault: () => {} });
  const s = input.read();
  assert.equal(s.wheelDelta, 70);
  assert.equal(input.read().wheelDelta, 0);
});

test('KeyboardInput: detach also removes wheel listener', () => {
  const t = new FakeTarget();
  const input = new KeyboardInput();
  input.attach(t);
  assert.ok(t.listenerCount('wheel') > 0);
  input.detach();
  assert.equal(t.listenerCount('wheel'), 0);
});

// ---------- TouchInput ----------

function touch(id, x, y) { return { identifier: id, clientX: x, clientY: y }; }
function touchEvent(touches, preventCalled = { ref: false }) {
  return {
    changedTouches: touches,
    preventDefault: () => { preventCalled.ref = true; },
    stopPropagation: () => {},
  };
}

test('TouchInput: initial read returns zero snapshot', () => {
  const root = new FakeTarget();
  root.clientWidth = 800;
  const input = new TouchInput();
  input.attach({ root });
  const s = input.read();
  assert.equal(s.forward, 0); assert.equal(s.right, 0);
  assert.equal(s.jump, false); assert.equal(s.lookDeltaX, 0);
});

test('TouchInput: left-half touchstart + move → stick deflects → forward/right', () => {
  const root = new FakeTarget();
  root.clientWidth = 800;
  const input = new TouchInput();
  input.attach({ root });
  // start at (100, 300) — left half
  root.dispatch('touchstart', touchEvent([touch(1, 100, 300)]));
  // drag down (forward toward user = back) and right
  root.dispatch('touchmove', touchEvent([touch(1, 156, 356)]));
  // 56 right, 56 down → at radius=56 → magnitude 1.0 in both axes pre-normalize
  const s = input.read();
  // expect right ≈ 0.707, forward ≈ -0.707 (dragging DOWN = away from user = negative forward)
  assert.ok(Math.abs(s.right - 0.707) < 0.01, `right=${s.right}`);
  assert.ok(Math.abs(s.forward + 0.707) < 0.01, `forward=${s.forward}`);
});

test('TouchInput: stick at full extension → sprint true', () => {
  const root = new FakeTarget();
  root.clientWidth = 800;
  const input = new TouchInput();
  input.attach({ root });
  root.dispatch('touchstart', touchEvent([touch(1, 100, 300)]));
  root.dispatch('touchmove', touchEvent([touch(1, 100, 240)]));  // straight up 60px
  const s = input.read();
  assert.equal(s.sprint, true);
  assert.ok(s.forward > 0.95, `forward=${s.forward}`);
});

test('TouchInput: dead-zone — tiny drag returns zero', () => {
  const root = new FakeTarget();
  root.clientWidth = 800;
  const input = new TouchInput();
  input.attach({ root });
  root.dispatch('touchstart', touchEvent([touch(1, 100, 300)]));
  root.dispatch('touchmove', touchEvent([touch(1, 103, 302)]));  // 3-4 px
  const s = input.read();
  assert.equal(s.forward, 0);
  assert.equal(s.right, 0);
});

test('TouchInput: right-half touchstart + drag → lookDelta accumulates', () => {
  const root = new FakeTarget();
  root.clientWidth = 800;
  const input = new TouchInput();
  input.attach({ root });
  root.dispatch('touchstart', touchEvent([touch(1, 600, 300)]));
  root.dispatch('touchmove', touchEvent([touch(1, 650, 310)]));
  root.dispatch('touchmove', touchEvent([touch(1, 660, 305)]));
  const s = input.read();
  // delta total: 60 right, 5 down. Scaled by LOOK_PIXEL_TO_KEYBOARD = 0.55.
  assert.ok(Math.abs(s.lookDeltaX - 33) < 0.5, `lookX=${s.lookDeltaX}`);
  assert.ok(Math.abs(s.lookDeltaY - 2.75) < 0.5, `lookY=${s.lookDeltaY}`);
});

test('TouchInput: button click fires edge event (jump/fly/exit)', () => {
  const root = new FakeTarget();
  root.clientWidth = 800;
  const jumpBtn = new FakeTarget();
  const flyBtn = new FakeTarget();
  const exitBtn = new FakeTarget();
  const input = new TouchInput();
  input.attach({ root, jumpBtn, flyBtn, exitBtn });
  jumpBtn.dispatch('click', { stopPropagation: () => {}, preventDefault: () => {} });
  assert.equal(input.read().jump, true);
  flyBtn.dispatch('touchstart', touchEvent([]));
  assert.equal(input.read().fly, true);
  exitBtn.dispatch('click', { stopPropagation: () => {}, preventDefault: () => {} });
  assert.equal(input.read().exit, true);
});

test('TouchInput: detach removes all listeners', () => {
  const root = new FakeTarget();
  root.clientWidth = 800;
  const jumpBtn = new FakeTarget();
  const input = new TouchInput();
  input.attach({ root, jumpBtn });
  assert.ok(root.listenerCount('touchstart') > 0);
  assert.ok(jumpBtn.listenerCount('click') > 0);
  input.detach();
  assert.equal(root.listenerCount('touchstart'), 0);
  assert.equal(root.listenerCount('touchmove'), 0);
  assert.equal(jumpBtn.listenerCount('click'), 0);
});

// ---------- CompositeInput ----------

test('CompositeInput: merges two inputs — booleans OR, deltas SUM', () => {
  const a = { read: () => ({ forward: 1, right: 0, vertical: 0, sprint: false,
                              jump: true, fly: false, exit: false,
                              lookDeltaX: 5, lookDeltaY: 0, wheelDelta: 0 }) };
  const b = { read: () => ({ forward: 0, right: 1, vertical: 0, sprint: true,
                              jump: false, fly: true, exit: false,
                              lookDeltaX: 3, lookDeltaY: -2, wheelDelta: 50 }) };
  const c = new CompositeInput(a, b);
  const s = c.read();
  assert.equal(s.forward, 1); assert.equal(s.right, 1);
  assert.equal(s.sprint, true); assert.equal(s.jump, true); assert.equal(s.fly, true);
  assert.equal(s.lookDeltaX, 8); assert.equal(s.lookDeltaY, -2);
  assert.equal(s.wheelDelta, 50);
});

test('CompositeInput: forward axis sums but clamps to [-1, 1]', () => {
  const a = { read: () => ({ ...ZERO_FOR_TEST, forward: 1 }) };
  const b = { read: () => ({ ...ZERO_FOR_TEST, forward: 1 }) };
  const c = new CompositeInput(a, b);
  assert.equal(c.read().forward, 1);
});

const ZERO_FOR_TEST = {
  forward: 0, right: 0, vertical: 0, sprint: false,
  jump: false, fly: false, exit: false,
  lookDeltaX: 0, lookDeltaY: 0, wheelDelta: 0,
};
