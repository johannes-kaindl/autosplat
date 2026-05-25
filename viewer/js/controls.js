// controls.js — input devices for walking-mode.
//
// Both KeyboardInput and TouchInput expose the same per-frame snapshot:
//   { forward, right, vertical, sprint, jump, fly, exit,
//     lookDeltaX, lookDeltaY, wheelDelta }
// Continuous axes reflect current held state; edge events fire once per
// fresh press then self-consume on read; lookDelta/wheelDelta accumulate
// between reads.
//
// CompositeInput merges multiple devices so keyboard + touch can coexist —
// useful on Mac laptops with a touch-screen-only mode, and lets the user
// switch input mid-session without re-wiring.

const HELD_AXIS = {
  KeyW: ['forward', +1], ArrowUp: ['forward', +1],
  KeyS: ['forward', -1], ArrowDown: ['forward', -1],
  KeyD: ['right', +1], ArrowRight: ['right', +1],
  KeyA: ['right', -1], ArrowLeft: ['right', -1],
  KeyE: ['vertical', +1],
  KeyQ: ['vertical', -1],
};

const SPRINT_KEYS = new Set(['ShiftLeft', 'ShiftRight']);
const EDGE_KEYS = { Space: 'jump', KeyF: 'fly', Escape: 'exit' };

export class KeyboardInput {
  constructor() {
    this._keys = new Set();
    this._pending = { jump: false, fly: false, exit: false };
    this._lookX = 0;
    this._lookY = 0;
    this._wheel = 0;
    this._target = null;
    this._handlers = null;
  }

  attach(target) {
    if (!target) return;
    if (this._target) this.detach();
    this._handlers = {
      keydown: (e) => this._onKeyDown(e),
      keyup: (e) => this._onKeyUp(e),
      mousemove: (e) => this._onMouseMove(e),
      wheel: (e) => this._onWheel(e),
    };
    target.addEventListener('keydown', this._handlers.keydown);
    target.addEventListener('keyup', this._handlers.keyup);
    target.addEventListener('mousemove', this._handlers.mousemove);
    target.addEventListener('wheel', this._handlers.wheel, { passive: false });
    this._target = target;
  }

  detach() {
    if (!this._target) return;
    this._target.removeEventListener('keydown', this._handlers.keydown);
    this._target.removeEventListener('keyup', this._handlers.keyup);
    this._target.removeEventListener('mousemove', this._handlers.mousemove);
    this._target.removeEventListener('wheel', this._handlers.wheel);
    this._target = null;
    this._handlers = null;
    this.reset();
  }

  reset() {
    this._keys.clear();
    this._pending.jump = false;
    this._pending.fly = false;
    this._pending.exit = false;
    this._lookX = 0;
    this._lookY = 0;
    this._wheel = 0;
  }

  _onKeyDown(e) {
    const k = e.code;
    if (!k) return;
    if (this._keys.has(k)) return;        // suppress OS auto-repeat
    this._keys.add(k);
    const edge = EDGE_KEYS[k];
    if (edge) this._pending[edge] = true;
    // some keys (Space, F, arrow keys) trigger browser defaults like
    // page-scroll; consumers can opt out via preventDefault in the event
    // since we already saw the key.
    if (k === 'Space' || k.startsWith('Arrow')) e.preventDefault?.();
  }

  _onKeyUp(e) {
    const k = e.code;
    if (k) this._keys.delete(k);
  }

  _onMouseMove(e) {
    // movementX/Y are only meaningful under PointerLock; when not locked
    // they fall back to 0 in most browsers, so this stays a no-op.
    this._lookX += e.movementX ?? 0;
    this._lookY += e.movementY ?? 0;
  }

  _onWheel(e) {
    // Used in walking-mode to tweak eye-height; suppress page scroll.
    this._wheel += e.deltaY ?? 0;
    e.preventDefault?.();
  }

  read() {
    const out = { forward: 0, right: 0, vertical: 0, sprint: false };
    for (const k of this._keys) {
      const axis = HELD_AXIS[k];
      if (axis) out[axis[0]] += axis[1];
      if (SPRINT_KEYS.has(k)) out.sprint = true;
    }
    out.jump = this._pending.jump;
    out.fly = this._pending.fly;
    out.exit = this._pending.exit;
    out.lookDeltaX = this._lookX;
    out.lookDeltaY = this._lookY;
    out.wheelDelta = this._wheel;
    this._pending.jump = false;
    this._pending.fly = false;
    this._pending.exit = false;
    this._lookX = 0;
    this._lookY = 0;
    this._wheel = 0;
    return out;
  }
}

// ---------- TouchInput ----------

const STICK_RADIUS = 56;      // pixels of travel for full-throttle
const STICK_DEAD   = 0.15;    // % of radius below which axis = 0
const SPRINT_AT    = 0.92;    // % of radius held → sprint
const LOOK_PIXEL_TO_KEYBOARD = 0.55; // touch-drag is coarser than mouse-look

export class TouchInput {
  constructor() {
    this._stickId = null;
    this._stickOX = 0; this._stickOY = 0;
    this._stickDX = 0; this._stickDY = 0;
    this._lookId = null;
    this._lookPX = 0; this._lookPY = 0;
    this._lookAcc = { x: 0, y: 0 };
    this._pending = { jump: false, fly: false, exit: false };
    this._root = null;
    this._handlers = null;
    this._halfWidth = null;
    this._btnHandlers = [];
  }

  attach({ root, jumpBtn, flyBtn, exitBtn, halfWidth }) {
    if (!root) return;
    if (this._root) this.detach();
    this._root = root;
    this._halfWidth = halfWidth ?? (() => root.clientWidth / 2);

    this._handlers = {
      touchstart: (e) => this._onStart(e),
      touchmove:  (e) => this._onMove(e),
      touchend:   (e) => this._onEnd(e),
    };
    root.addEventListener('touchstart',  this._handlers.touchstart, { passive: false });
    root.addEventListener('touchmove',   this._handlers.touchmove,  { passive: false });
    root.addEventListener('touchend',    this._handlers.touchend);
    root.addEventListener('touchcancel', this._handlers.touchend);

    const wireBtn = (el, key) => {
      if (!el) return;
      const h = (e) => { this._pending[key] = true; e.stopPropagation(); e.preventDefault?.(); };
      el.addEventListener('touchstart', h, { passive: false });
      // also accept mouse clicks for desktop touch-emulation
      el.addEventListener('click', h);
      this._btnHandlers.push({ el, h });
    };
    wireBtn(jumpBtn, 'jump');
    wireBtn(flyBtn,  'fly');
    wireBtn(exitBtn, 'exit');
  }

  detach() {
    if (!this._root) return;
    this._root.removeEventListener('touchstart',  this._handlers.touchstart);
    this._root.removeEventListener('touchmove',   this._handlers.touchmove);
    this._root.removeEventListener('touchend',    this._handlers.touchend);
    this._root.removeEventListener('touchcancel', this._handlers.touchend);
    for (const { el, h } of this._btnHandlers) {
      el.removeEventListener('touchstart', h);
      el.removeEventListener('click', h);
    }
    this._btnHandlers = [];
    this._root = null;
    this._handlers = null;
    this.reset();
  }

  reset() {
    this._stickId = null;
    this._stickDX = this._stickDY = 0;
    this._lookId = null;
    this._lookAcc.x = this._lookAcc.y = 0;
    this._pending.jump = this._pending.fly = this._pending.exit = false;
  }

  _onStart(e) {
    const half = this._halfWidth();
    for (const t of e.changedTouches) {
      if (this._stickId === null && t.clientX < half) {
        this._stickId = t.identifier;
        this._stickOX = t.clientX;
        this._stickOY = t.clientY;
        this._stickDX = 0; this._stickDY = 0;
      } else if (this._lookId === null && t.clientX >= half) {
        this._lookId = t.identifier;
        this._lookPX = t.clientX;
        this._lookPY = t.clientY;
      }
    }
  }

  _onMove(e) {
    for (const t of e.changedTouches) {
      if (t.identifier === this._stickId) {
        this._stickDX = t.clientX - this._stickOX;
        this._stickDY = t.clientY - this._stickOY;
      } else if (t.identifier === this._lookId) {
        this._lookAcc.x += t.clientX - this._lookPX;
        this._lookAcc.y += t.clientY - this._lookPY;
        this._lookPX = t.clientX;
        this._lookPY = t.clientY;
      }
    }
    if (this._stickId !== null || this._lookId !== null) e.preventDefault?.();
  }

  _onEnd(e) {
    for (const t of e.changedTouches) {
      if (t.identifier === this._stickId) {
        this._stickId = null;
        this._stickDX = 0; this._stickDY = 0;
      } else if (t.identifier === this._lookId) {
        this._lookId = null;
      }
    }
  }

  read() {
    const out = { forward: 0, right: 0, vertical: 0, sprint: false };
    const len = Math.hypot(this._stickDX, this._stickDY);
    if (len > STICK_RADIUS * STICK_DEAD) {
      const clamped = Math.min(1, len / STICK_RADIUS);
      const k = clamped / len;
      out.right = this._stickDX * k;
      out.forward = -this._stickDY * k; // dragging up on the screen = forward
      out.sprint = clamped >= SPRINT_AT;
    }
    out.jump = this._pending.jump;
    out.fly = this._pending.fly;
    out.exit = this._pending.exit;
    out.lookDeltaX = this._lookAcc.x * LOOK_PIXEL_TO_KEYBOARD;
    out.lookDeltaY = this._lookAcc.y * LOOK_PIXEL_TO_KEYBOARD;
    out.wheelDelta = 0;
    this._pending.jump = this._pending.fly = this._pending.exit = false;
    this._lookAcc.x = 0; this._lookAcc.y = 0;
    return out;
  }
}

// ---------- CompositeInput ----------

const ZERO_SNAPSHOT = {
  forward: 0, right: 0, vertical: 0, sprint: false,
  jump: false, fly: false, exit: false,
  lookDeltaX: 0, lookDeltaY: 0, wheelDelta: 0,
};

function clamp(v, lo, hi) { return v < lo ? lo : v > hi ? hi : v; }

export class CompositeInput {
  constructor(...inputs) { this.inputs = inputs; }
  read() {
    const out = { ...ZERO_SNAPSHOT };
    for (const i of this.inputs) {
      const s = i.read?.() ?? ZERO_SNAPSHOT;
      out.forward = clamp(out.forward + s.forward, -1, 1);
      out.right = clamp(out.right + s.right, -1, 1);
      out.vertical = clamp(out.vertical + s.vertical, -1, 1);
      out.sprint = out.sprint || s.sprint;
      out.jump = out.jump || s.jump;
      out.fly = out.fly || s.fly;
      out.exit = out.exit || s.exit;
      out.lookDeltaX += s.lookDeltaX;
      out.lookDeltaY += s.lookDeltaY;
      out.wheelDelta += s.wheelDelta;
    }
    return out;
  }
}
