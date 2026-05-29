/* ============================================================================
   AutoSplat — point-cloud mark generator
   Renders Gaussian-splat-style logo marks into <svg class="mark"> elements.
   Deterministic (seeded PRNG + Fibonacci distribution) so a logo never shifts
   between reloads. Drives all three concepts, the chosen lockup mark, the app
   icon, the favicons, and the decorative clouds on the OG / README art.

   data-* API on the host <svg>:
     data-shape   = "orb" | "cube" | "frame"
     data-variant = "full" | "phosphor"   (palette discipline)
     data-n       = point count            (default per shape)
     data-seed    = integer                (palette/jitter seed)
     data-rot     = "rx,ry" radians        (view rotation)
   ========================================================================== */
(function () {
  'use strict';

  var SVGNS = 'http://www.w3.org/2000/svg';

  // ---- Signal palette (dark-mode hexes) -----------------------------------
  var PHOSPHOR = '#39ff7a';
  var COOL = ['#39ff7a', '#4ac8d8', '#a878ff', '#7ab8c4', '#8bbf87', '#b49bd1'];
  var WARM = ['#ffb442', '#e8b979', '#e8a5a5', '#d9c566'];
  var PEARL = '#e8e4d8';
  // phosphor family — green-biased shades + sparse circuit/spectre
  var PHOS_FAMILY = ['#39ff7a', '#39ff7a', '#8bbf87', '#5fe6a0', '#4ac8d8', '#a878ff'];

  function mulberry32(a) {
    return function () {
      a |= 0; a = (a + 0x6d2b79f5) | 0;
      var t = Math.imul(a ^ (a >>> 15), 1 | a);
      t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
      return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
  }

  function pickColor(rng, variant) {
    if (variant === 'phosphor') {
      return PHOS_FAMILY[Math.floor(rng() * PHOS_FAMILY.length)];
    }
    var r = rng();
    if (r < 0.64) return COOL[Math.floor(rng() * COOL.length)];
    if (r < 0.90) return WARM[Math.floor(rng() * WARM.length)];
    return PEARL;
  }

  // ---- 3D helpers ----------------------------------------------------------
  function rotate(p, rx, ry) {
    var cy = Math.cos(ry), sy = Math.sin(ry);
    var x1 = p.x * cy + p.z * sy;
    var z1 = -p.x * sy + p.z * cy;
    var cx = Math.cos(rx), sx = Math.sin(rx);
    var y1 = p.y * cx - z1 * sx;
    var z2 = p.y * sx + z1 * cx;
    return { x: x1, y: y1, z: z2 };
  }

  // ---- Point set builders --------------------------------------------------
  function buildOrb(n, rng) {
    var pts = [], ga = Math.PI * (3 - Math.sqrt(5));
    for (var i = 0; i < n; i++) {
      var y = 1 - (i / (n - 1)) * 2;
      var r = Math.sqrt(Math.max(0, 1 - y * y));
      var th = i * ga;
      // small radial jitter so the shell reads organic, not gridded
      var rr = 1 - rng() * 0.18;
      pts.push({ x: Math.cos(th) * r * rr, y: y * rr, z: Math.sin(th) * r * rr });
    }
    return pts;
  }

  function buildCube(steps, rng) {
    var v = [];
    for (var xi = -1; xi <= 1; xi += 2)
      for (var yi = -1; yi <= 1; yi += 2)
        for (var zi = -1; zi <= 1; zi += 2) v.push([xi, yi, zi]);
    var edges = [];
    for (var a = 0; a < v.length; a++)
      for (var b = a + 1; b < v.length; b++) {
        var d = Math.abs(v[a][0] - v[b][0]) + Math.abs(v[a][1] - v[b][1]) + Math.abs(v[a][2] - v[b][2]);
        if (d === 2) edges.push([v[a], v[b]]);
      }
    var pts = [];
    edges.forEach(function (e) {
      for (var s = 0; s <= steps; s++) {
        var t = s / steps;
        var j = (rng() - 0.5) * 0.06;
        pts.push({
          x: e[0][0] + (e[1][0] - e[0][0]) * t + j,
          y: e[0][1] + (e[1][1] - e[0][1]) * t + j,
          z: e[0][2] + (e[1][2] - e[0][2]) * t + j
        });
      }
    });
    // a few interior points to suggest volume
    for (var k = 0; k < steps * 2; k++) {
      pts.push({ x: (rng() * 2 - 1) * 0.8, y: (rng() * 2 - 1) * 0.8, z: (rng() * 2 - 1) * 0.8 });
    }
    return pts;
  }

  // frame -> splat : a viewfinder square whose right edge dissolves into points
  function renderFrame(svg, n, variant, rng) {
    var C = 50, S = 30; // center, half-size of frame
    // viewfinder frame (left + top + bottom brackets, right side open)
    var fg = svg.getAttribute('data-fg') || 'currentColor';
    function bracket(d) {
      var p = document.createElementNS(SVGNS, 'path');
      p.setAttribute('d', d);
      p.setAttribute('fill', 'none');
      p.setAttribute('stroke', fg);
      p.setAttribute('stroke-width', '2.4');
      p.setAttribute('stroke-linecap', 'round');
      p.setAttribute('stroke-linejoin', 'round');
      p.setAttribute('opacity', '0.9');
      svg.appendChild(p);
    }
    var x0 = C - S, x1 = C + S, y0 = C - S, y1 = C + S, k = 11;
    bracket('M ' + (x0 + k) + ' ' + y0 + ' L ' + x0 + ' ' + y0 + ' L ' + x0 + ' ' + y1 + ' L ' + (x0 + k) + ' ' + y1); // left
    bracket('M ' + (x1 - k) + ' ' + y0 + ' L ' + x1 + ' ' + y0); // top-right tick
    bracket('M ' + (x1 - k) + ' ' + y1 + ' L ' + x1 + ' ' + y1); // bottom-right tick

    // points: dense inside the frame on the left, streaming/dispersing right
    for (var i = 0; i < n; i++) {
      var t = i / (n - 1);
      // bias x toward the right as t grows; spread y
      var bx = x0 + 8 + t * (2 * S + 16) + (rng() - 0.5) * 8;
      var spread = 6 + t * 22;
      var by = C + (rng() - 0.5) * spread * 2;
      // probability of existing thins out to the right (dissolve)
      if (bx > x1 - 4 && rng() > (1 - t) * 1.3) continue;
      var depth = rng();
      var rad = (1.1 + depth * 2.6) * (1 - t * 0.35);
      var col = (variant === 'phosphor')
        ? PHOS_FAMILY[Math.floor(rng() * PHOS_FAMILY.length)]
        : pickColor(rng, variant);
      circle(svg, bx, by, rad, col, 0.4 + depth * 0.6);
    }
  }

  function circle(svg, cx, cy, r, fill, op) {
    var c = document.createElementNS(SVGNS, 'circle');
    c.setAttribute('cx', cx.toFixed(2));
    c.setAttribute('cy', cy.toFixed(2));
    c.setAttribute('r', r.toFixed(2));
    c.setAttribute('fill', fill);
    c.setAttribute('opacity', op.toFixed(2));
    svg.appendChild(c);
  }

  function renderProjected(svg, pts, variant, rng, rx, ry, scale) {
    var proj = pts.map(function (p) { return rotate(p, rx, ry); });
    proj.sort(function (a, b) { return a.z - b.z; }); // far first (painter)
    proj.forEach(function (p) {
      var depth = (p.z + 1) / 2;               // 0 far .. 1 near
      var r = 1.0 + depth * 2.8;
      var op = 0.30 + depth * 0.68;
      var col = pickColor(rng, variant);
      circle(svg, 50 + p.x * scale, 50 - p.y * scale, r, col, op);
    });
  }

  function render(svg) {
    while (svg.firstChild) svg.removeChild(svg.firstChild);
    if (!svg.getAttribute('viewBox')) svg.setAttribute('viewBox', '0 0 100 100');
    var shape = svg.getAttribute('data-shape') || 'orb';
    var variant = svg.getAttribute('data-variant') || 'full';
    var seed = parseInt(svg.getAttribute('data-seed') || '7', 10);
    var rng = mulberry32(seed);
    var rotAttr = (svg.getAttribute('data-rot') || '').split(',');
    var rx = parseFloat(rotAttr[0]) || -0.42;
    var ry = parseFloat(rotAttr[1]) || 0.6;

    if (shape === 'orb') {
      var n = parseInt(svg.getAttribute('data-n') || '120', 10);
      renderProjected(svg, buildOrb(n, rng), variant, rng, rx, ry, 39);
    } else if (shape === 'cube') {
      var steps = parseInt(svg.getAttribute('data-n') || '8', 10);
      renderProjected(svg, buildCube(steps, rng), variant, rng, rx, ry, 30);
    } else if (shape === 'frame') {
      var nf = parseInt(svg.getAttribute('data-n') || '90', 10);
      renderFrame(svg, nf, variant, rng);
    } else if (shape === 'scatter') {
      // free decorative cloud for banners — elliptical gaussian field
      var ns = parseInt(svg.getAttribute('data-n') || '160', 10);
      for (var i = 0; i < ns; i++) {
        var a = rng() * Math.PI * 2;
        var rr = Math.pow(rng(), 0.6);
        var x = 50 + Math.cos(a) * rr * 46;
        var y = 50 + Math.sin(a) * rr * 30;
        circle(svg, x, y, 0.6 + rng() * 2.4, pickColor(rng, variant), 0.25 + rng() * 0.6);
      }
    }
  }

  function renderAll() {
    var nodes = document.querySelectorAll('svg.mark');
    for (var i = 0; i < nodes.length; i++) render(nodes[i]);
  }

  window.AutosplatMarks = { render: render, renderAll: renderAll };
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', renderAll);
  } else {
    renderAll();
  }
})();
