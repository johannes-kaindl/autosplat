// Render static brand assets (favicon/app-icon mark + OG image) from the
// AutoSplat generative point-cloud system. Ports the deterministic orb
// generator from marks.js so the static files match the live brand exactly.
//
//   node docs/brand/render_marks.mjs
//
// Writes SVGs into src/autosplat/webui/static/brand/. Rasterization to PNG/.icns
// is done by scripts/build_brand_assets.sh (rsvg-convert + iconutil).

import { mkdirSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..", "..");
const OUT = join(ROOT, "src", "autosplat", "webui", "static", "brand");

// ── palette (from marks.js / tokens.css) ────────────────────────────────────
const COOL = ["#39ff7a", "#4ac8d8", "#a878ff", "#7ab8c4", "#8bbf87", "#b49bd1"];
const WARM = ["#ffb442", "#e8b979", "#e8a5a5", "#d9c566"];
const PEARL = "#e8e4d8";
const PHOS_FAMILY = ["#39ff7a", "#39ff7a", "#8bbf87", "#5fe6a0", "#4ac8d8", "#a878ff"];
const BG = "#060709"; // --void-050 app background
const PHOSPHOR = "#39ff7a";
const FG = "#e8e4d8"; // --signal-pearl
const MUTED = "#828a97"; // --void-700 fg secondary

function mulberry32(a) {
  return function () {
    a |= 0;
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

function pickColor(rng, variant) {
  if (variant === "phosphor") return PHOS_FAMILY[Math.floor(rng() * PHOS_FAMILY.length)];
  const r = rng();
  if (r < 0.64) return COOL[Math.floor(rng() * COOL.length)];
  if (r < 0.9) return WARM[Math.floor(rng() * WARM.length)];
  return PEARL;
}

function rotate(p, rx, ry) {
  const cy = Math.cos(ry), sy = Math.sin(ry);
  const x1 = p.x * cy + p.z * sy;
  const z1 = -p.x * sy + p.z * cy;
  const cx = Math.cos(rx), sx = Math.sin(rx);
  const y1 = p.y * cx - z1 * sx;
  const z2 = p.y * sx + z1 * cx;
  return { x: x1, y: y1, z: z2 };
}

function buildOrb(n, rng) {
  const pts = [], ga = Math.PI * (3 - Math.sqrt(5));
  for (let i = 0; i < n; i++) {
    const y = 1 - (i / (n - 1)) * 2;
    const r = Math.sqrt(Math.max(0, 1 - y * y));
    const th = i * ga;
    const rr = 1 - rng() * 0.18;
    pts.push({ x: Math.cos(th) * r * rr, y: y * rr, z: Math.sin(th) * r * rr });
  }
  return pts;
}

// Returns the orb's <circle> elements as a string, centered in a 100×100 box.
function orbCircles({ n = 120, seed = 7, variant = "full", rx = -0.42, ry = 0.6, scale = 39 } = {}) {
  const rng = mulberry32(seed);
  const proj = buildOrb(n, rng).map((p) => rotate(p, rx, ry));
  proj.sort((a, b) => a.z - b.z);
  let out = "";
  for (const p of proj) {
    const depth = (p.z + 1) / 2;
    const r = 1.0 + depth * 2.8;
    const op = 0.3 + depth * 0.68;
    const col = pickColor(rng, variant);
    out += `<circle cx="${(50 + p.x * scale).toFixed(2)}" cy="${(50 - p.y * scale).toFixed(2)}" r="${r.toFixed(2)}" fill="${col}" opacity="${op.toFixed(2)}"/>`;
  }
  return out;
}

// ── 1. square mark — favicon + app icon (orb on dark rounded square) ─────────
const markSvg = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">
<rect width="100" height="100" rx="22" fill="${BG}"/>
<g>${orbCircles({ n: 120, seed: 7, variant: "full" })}</g>
</svg>
`;

// ── 2. OG image 1200×630 — orb + wordmark + tagline ──────────────────────────
const FONT = "Space Grotesk, -apple-system, BlinkMacSystemFont, Helvetica, Arial, sans-serif";
const MONO = "JetBrains Mono, ui-monospace, SF Mono, Menlo, monospace";
// orb placed left, scaled from the 100-box: scale 4.2, centre at (330, 315)
const ogOrb = `<g transform="translate(${(330 - 50 * 4.2).toFixed(1)}, ${(315 - 50 * 4.2).toFixed(1)}) scale(4.2)">${orbCircles({ n: 150, seed: 7, variant: "full" })}</g>`;
const ogSvg = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1200 630">
<rect width="1200" height="630" fill="${BG}"/>
${ogOrb}
<text x="600" y="300" font-family="${FONT}" font-size="96" font-weight="600" letter-spacing="-4" fill="${FG}">AutoSplat<tspan fill="${PHOSPHOR}">.</tspan></text>
<text x="602" y="356" font-family="${MONO}" font-size="29" fill="${MUTED}">Drone video → 3D Gaussian Splat</text>
<text x="602" y="398" font-family="${MONO}" font-size="29" fill="${MUTED}">Local. On your Mac.</text>
</svg>
`;

mkdirSync(OUT, { recursive: true });
writeFileSync(join(OUT, "favicon.svg"), markSvg);
writeFileSync(join(OUT, "mark.svg"), markSvg);
writeFileSync(join(OUT, "og.svg"), ogSvg);
console.log("wrote favicon.svg, mark.svg, og.svg →", OUT);
