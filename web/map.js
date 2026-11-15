// CourseLens — Course Map renderer.
// A small force-directed graph on <canvas>, no graph library. Design choices:
//  • every source is a HUB — a big glowing dot on a ring — and its concepts burst
//    around it on thin spokes, so each lecture reads as its own constellation;
//  • a concept found in several sources hangs on several hubs, so shared ideas sit
//    BETWEEN constellations and are drawn as split-colour dots;
//  • "bridge" links (similar meaning, different sources) are the brightest lines and
//    carry travelling pulses, because they are the connections a student is least
//    likely to have noticed on their own;
//  • labels fade in with zoom (hubs are always labelled), so the zoomed-out view is
//    a clean field of dots and the zoomed-in view is readable.
// Texture: a dot grid that parallaxes with the camera and bends away from the
// cursor like a lens, slow "breathing" drift, glow on hover, a ripple on select.

const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));
const TAU = Math.PI * 2;
const SANS = `"Helvetica Neue", Helvetica, Arial, sans-serif`;
const PIXEL = `"Pixelify Sans", ui-monospace, monospace`;

function hash(str) {
  let h = 2166136261;
  for (let i = 0; i < str.length; i++) h = Math.imul(h ^ str.charCodeAt(i), 16777619);
  return ((h >>> 0) % 10000) / 10000;
}

export class CourseMap {
  constructor(canvas, { colorFor, onSelect }) {
    this.canvas = canvas;
    this.ctx = canvas.getContext("2d");
    this.colorFor = colorFor;
    this.onSelect = onSelect || (() => {});
    this.nodes = [];       // hubs + concepts
    this.links = [];       // drawn concept↔concept links (related, bridge)
    this.spokes = [];      // hub → concept
    this.byId = new Map();
    this.adj = new Map();  // concept id → [{node, kind, w}] (incl. undrawn "shared")
    this.sources = [];
    this.hidden = new Set();
    this.cam = { x: 0, y: 0, k: 1 };
    this.camAnim = null;
    this.hover = null;
    this.selected = null;
    this.selectedAt = 0;
    this.mouse = null;
    this.alpha = 0;
    this.raf = null;
    this.active = false;
    this.still = matchMedia("(prefers-reduced-motion: reduce)").matches;
    this.pointers = new Map();
    this.insetRight = 0;   // side panel on desktop
    this.insetBottom = 0;  // bottom sheet on phones
    this.w = 0;
    this.h = 0;
    this.theme = this.readTheme();
    this.bind();
    new ResizeObserver(() => this.resize()).observe(canvas);
    document.addEventListener("visibilitychange", () => this.start());
  }

  readTheme() {
    const s = getComputedStyle(document.documentElement);
    const v = (n) => s.getPropertyValue(n).trim();
    return { ink: v("--ink"), muted: v("--muted"), bg: "#08090c", accent: v("--blue-ink"), blue: v("--blue"), teal: v("--teal") };
  }

  // Keep animating only while the map is on screen.
  setActive(on) {
    this.active = on;
    if (on) this.start();
  }

  // ── data ─────────────────────────────────────────────────────────────────
  setData({ nodes, links, sources }) {
    this.sources = sources;
    const n = sources.length;
    const R = n <= 1 ? 0 : 100 + 42 * n;
    const anchor = new Map(sources.map((s, i) => {
      const a = (i / Math.max(n, 1)) * TAU - Math.PI / 2;
      return [s, { x: Math.cos(a) * R, y: Math.sin(a) * R }];
    }));

    const hubs = sources.map((s) => {
      const p = anchor.get(s);
      return { id: `hub:${s}`, label: s.replace(/_/g, " "), hub: true, source: s, sources: [s],
               ax: p.x, ay: p.y, x: p.x, y: p.y, vx: 0, vy: 0, fixed: false };
    });
    const concepts = nodes.map((d) => {
      const pts = d.sources.map((s) => anchor.get(s));
      const ax = pts.reduce((t, p) => t + p.x, 0) / pts.length;
      const ay = pts.reduce((t, p) => t + p.y, 0) / pts.length;
      const j = hash(d.id) * TAU;
      return { id: d.id, label: d.id, hub: false, sources: d.sources, ax, ay,
               x: ax + Math.cos(j) * 60, y: ay + Math.sin(j) * 60, vx: 0, vy: 0, fixed: false };
    });
    this.nodes = [...hubs, ...concepts];
    this.byId = new Map(this.nodes.map((d) => [d.id, d]));
    this.adj = new Map(concepts.map((d) => [d.id, []]));

    this.spokes = [];
    for (const c of concepts) for (const s of c.sources) {
      const hub = this.byId.get(`hub:${s}`);
      if (hub) this.spokes.push({ a: hub, b: c, kind: "spoke" });
    }
    const all = links
      .filter((l) => this.adj.has(l.source) && this.adj.has(l.target))
      .map((l) => ({ a: this.byId.get(l.source), b: this.byId.get(l.target), kind: l.kind, w: l.weight }));
    for (const l of all) {
      this.adj.get(l.a.id).push({ node: l.b, kind: l.kind, w: l.w });
      this.adj.get(l.b.id).push({ node: l.a, kind: l.kind, w: l.w });
    }
    // "shared" (same source) is already said by the spokes; drawing it as well
    // would turn every constellation into a hairball.
    this.links = all.filter((l) => l.kind !== "shared");

    for (const h of hubs) {
      h.members = this.spokes.filter((s) => s.a === h).map((s) => s.b);
      h.r = 7 + Math.sqrt(h.members.length) * 2.4;
      h.lw = h.label.length * 7.6;
    }
    for (const c of concepts) {
      const deg = this.adj.get(c.id).filter((e) => e.kind !== "shared").length;
      c.r = 3.6 + Math.sqrt(deg) * 1.3 + (c.sources.length > 1 ? 2 : 0);
      c.lw = c.label.length * 6.2;
      c.phase = hash(c.id) * TAU;
    }

    this.userMoved = false;
    this.selected = null;
    this.hover = null;
    this.alpha = 1;
    for (let i = 0; i < 480; i++) this.tick();   // settle before the first frame
    this.alpha = 0.1;
    this.fit(false);
    this.start();
  }

  isVisible(d) {
    return d.hub ? !this.hidden.has(d.source) : d.sources.some((s) => !this.hidden.has(s));
  }

  setHidden(source, hidden) {
    if (hidden) this.hidden.add(source); else this.hidden.delete(source);
    if (this.selected && !this.isVisible(this.selected)) this.select(null);
    this.draw();
  }

  neighbors(d) {
    const rank = { bridge: 0, related: 1, shared: 2 };
    const seen = new Map();
    for (const e of this.adj.get(d.id) || []) {
      const prev = seen.get(e.node.id);
      if (!prev || rank[e.kind] < rank[prev.kind]) seen.set(e.node.id, e);
    }
    return [...seen.values()]
      .filter((e) => this.isVisible(e.node))
      .sort((x, y) => rank[x.kind] - rank[y.kind] || y.w - x.w)
      .map((e) => ({ id: e.node.id, kind: e.kind, weight: e.w, sources: e.node.sources }));
  }

  // Everything one hop from d, for highlighting.
  nearSet(d) {
    const s = new Set([d.id]);
    if (d.hub) d.members.forEach((m) => s.add(m.id));
    else {
      d.sources.forEach((src) => s.add(`hub:${src}`));
      for (const e of this.adj.get(d.id)) if (e.kind !== "shared") s.add(e.node.id);
    }
    return s;
  }

  // ── simulation ───────────────────────────────────────────────────────────
  tick() {
    const N = this.nodes, a = this.alpha;
    for (let i = 0; i < N.length; i++) {
      for (let j = i + 1; j < N.length; j++) {
        const p = N[i], q = N[j];
        let dx = q.x - p.x, dy = q.y - p.y;
        let d2 = dx * dx + dy * dy;
        if (d2 < 0.01) { dx = 0.1; dy = 0.1; d2 = 0.02; }
        const d = Math.sqrt(d2);
        const strength = p.hub && q.hub ? 9000 : p.hub || q.hub ? 1400 : 1100;
        const f = Math.min(strength / d2, 4) * a;
        p.vx -= (dx / d) * f; p.vy -= (dy / d) * f;
        q.vx += (dx / d) * f; q.vy += (dy / d) * f;
        const min = p.r + q.r + 14;
        if (d < min) {
          const push = ((min - d) / d) * 0.5;
          p.x -= dx * push * 0.5; p.y -= dy * push * 0.5;
          q.x += dx * push * 0.5; q.y += dy * push * 0.5;
        }
        // Labels sit under their dot, so two dots on roughly the same row need
        // room for both labels side by side, not just for the dots.
        const ady = Math.abs(dy), need = (p.lw + q.lw) / 2 + 8;
        if (ady < 18 && Math.abs(dx) < need) {
          const s = Math.sign(dx) || (hash(p.id) > hash(q.id) ? 1 : -1);
          const shove = (need - Math.abs(dx)) * 0.08;
          p.x -= s * shove; q.x += s * shove;
          p.y -= Math.sign(dy || 1) * 0.5; q.y += Math.sign(dy || 1) * 0.5;
        }
      }
    }
    const spring = (A, B, target, k) => {
      const dx = B.x - A.x, dy = B.y - A.y;
      const d = Math.sqrt(dx * dx + dy * dy) || 1;
      const f = ((d - target) / d) * k * a;
      A.vx += dx * f; A.vy += dy * f;
      B.vx -= dx * f; B.vy -= dy * f;
    };
    // Long enough spokes that the hub's own label sits inside its ring of concepts.
    for (const s of this.spokes) spring(s.a, s.b, 86 + Math.sqrt(s.a.members.length) * 10, 0.06);
    for (const l of this.links) {
      if (l.kind === "bridge") spring(l.a, l.b, 170, 0.004);
      else spring(l.a, l.b, 80 - l.w * 20, 0.008 + l.w * 0.02);
    }
    // Keep concepts (dot + label) out of the strip under each hub where the
    // hub's own name is drawn.
    for (const h of N) {
      if (!h.hub) continue;
      const top = h.y + h.r + 2, bottom = h.y + h.r + 30;
      for (const c of N) {
        if (c.hub || Math.abs(c.x - h.x) > (h.lw + c.lw) / 2 + 4) continue;
        const cTop = c.y - c.r, cBottom = c.y + c.r + 20;
        if (cBottom < top || cTop > bottom) continue;
        const mid = (top + bottom) / 2;
        const push = c.y + 6 < mid ? -(cBottom - top) : bottom - cTop;
        c.y += clamp(push, -6, 6) * 0.35;
      }
    }
    for (const d of N) {
      const g = d.hub ? 0.09 : 0.004;
      d.vx += (d.ax - d.x) * g * a;
      d.vy += (d.ay - d.y) * g * a;
      if (d.fixed) { d.vx = d.vy = 0; continue; }
      d.vx *= 0.6; d.vy *= 0.6;
      d.x += d.vx; d.y += d.vy;
    }
    this.alpha *= 0.986;
  }

  start() {
    if (this.raf) return;
    const loop = (t) => {
      this.raf = null;
      this.now = t;
      let busy = false;
      if (this.alpha > 0.004) { this.tick(); busy = true; }
      if (this.camAnim) busy = this.stepCam(t) || busy;
      this.draw();
      const ambient = this.active && !this.still && !document.hidden && this.nodes.length;
      if (busy || ambient) this.raf = requestAnimationFrame(loop);
    };
    this.raf = requestAnimationFrame(loop);
  }

  reheat(v = 0.25) {
    this.alpha = Math.max(this.alpha, v);
    this.start();
  }

  // ── camera ───────────────────────────────────────────────────────────────
  resize() {
    const r = this.canvas.getBoundingClientRect();
    if (!r.width || !r.height) return;
    this.dpr = window.devicePixelRatio || 1;
    this.w = r.width; this.h = r.height;
    this.canvas.width = Math.round(r.width * this.dpr);
    this.canvas.height = Math.round(r.height * this.dpr);
    // Keep the whole map in view as the layout changes size (window resize, the
    // toolbar wrapping, the panel opening) until the user has panned or zoomed.
    if (this.nodes.length && !this.userMoved) this.fit(false);
    this.draw();
  }

  setInset(right, bottom = 0) { this.insetRight = right; this.insetBottom = bottom; }

  fit(animate = true) {
    const vis = this.nodes.filter((d) => this.isVisible(d));
    if (!vis.length || !this.w) return;
    const W = this.w - this.insetRight, H = this.h - 56;   // keep clear of the key
    // Labels keep a fixed on-screen size, so their footprint in world units
    // depends on the zoom being solved for: iterate a few times to converge.
    let k = 1, x0, y0, x1, y1;
    for (let pass = 0; pass < 4; pass++) {
      x0 = y0 = Infinity; x1 = y1 = -Infinity;
      for (const d of vis) {
        const mx = d.hub ? Math.max(d.r + 30, (d.lw / 2 + 12) / k) : d.r + 40 / k;
        x0 = Math.min(x0, d.x - mx); x1 = Math.max(x1, d.x + mx);
        y0 = Math.min(y0, d.y - d.r - 24 / k); y1 = Math.max(y1, d.y + d.r + 30 / k);
      }
      k = clamp(Math.min(W / (x1 - x0), H / (y1 - y0)), 0.3, 1.8);
    }
    const target = { k, x: W / 2 - ((x0 + x1) / 2) * k, y: H / 2 - ((y0 + y1) / 2) * k };
    this.userMoved = false;
    this.moveCam(target, animate);
  }

  focus(id) {
    const d = this.byId.get(id);
    if (!d) return;
    if (!this.isVisible(d)) d.sources.forEach((s) => this.hidden.delete(s));
    this.select(d);
    const k = Math.max(this.cam.k, 1.3);
    const W = this.w - this.insetRight, H = this.h - this.insetBottom;
    this.moveCam({ k, x: W / 2 - d.x * k, y: H / 2 - d.y * k }, true);
    this.userMoved = true;
  }

  ensureVisible(id) {
    const d = this.byId.get(id);
    if (!d || !this.w) return;
    const sx = d.x * this.cam.k + this.cam.x, sy = d.y * this.cam.k + this.cam.y;
    const W = this.w - this.insetRight, H = this.h - this.insetBottom, m = 50;
    if (sx > m && sx < W - m && sy > m && sy < H - m) return;
    this.moveCam({ k: this.cam.k, x: W / 2 - d.x * this.cam.k, y: H / 2 - d.y * this.cam.k }, true);
  }

  moveCam(target, animate) {
    if (!animate) { this.cam = target; this.camAnim = null; this.draw(); return; }
    this.camAnim = { from: { ...this.cam }, to: target, t0: performance.now(), ms: 520 };
    this.start();
  }

  stepCam(now) {
    const { from, to, t0, ms } = this.camAnim;
    const t = clamp((now - t0) / ms, 0, 1);
    const e = 1 - Math.pow(1 - t, 3);
    this.cam = { k: from.k + (to.k - from.k) * e, x: from.x + (to.x - from.x) * e, y: from.y + (to.y - from.y) * e };
    if (t >= 1) { this.camAnim = null; return false; }
    return true;
  }

  zoomAt(sx, sy, factor) {
    this.userMoved = true;
    const k = clamp(this.cam.k * factor, 0.25, 4);
    const f = k / this.cam.k;
    this.cam = { k, x: sx - (sx - this.cam.x) * f, y: sy - (sy - this.cam.y) * f };
    this.camAnim = null;
    this.draw();
  }

  toWorld(sx, sy) {
    return { x: (sx - this.cam.x) / this.cam.k, y: (sy - this.cam.y) / this.cam.k };
  }

  hit(sx, sy) {
    const p = this.toWorld(sx, sy);
    let best = null, bestD = Infinity;
    for (const d of this.nodes) {
      if (!this.isVisible(d)) continue;
      const dist = Math.hypot(d.x - p.x, d.y - p.y);
      if (dist < d.r + 9 / this.cam.k && dist < bestD) { best = d; bestD = dist; }
    }
    return best;
  }

  select(d) {
    if (d === this.selected) return;   // re-selecting must not refetch the panel
    this.selected = d;
    this.selectedAt = performance.now();
    this.start();
    if (!d) return this.onSelect(null);
    if (d.hub) {
      this.onSelect({ hub: true, id: d.id, source: d.source,
                      concepts: d.members.filter((m) => this.isVisible(m)).map((m) => ({ id: m.id, sources: m.sources })) });
    } else {
      this.onSelect({ id: d.id, sources: d.sources, neighbors: this.neighbors(d) });
    }
  }

  // ── input ────────────────────────────────────────────────────────────────
  bind() {
    const c = this.canvas;
    const pos = (e) => { const r = c.getBoundingClientRect(); return { x: e.clientX - r.left, y: e.clientY - r.top }; };

    c.addEventListener("pointerdown", (e) => {
      c.setPointerCapture(e.pointerId);
      const p = pos(e);
      this.pointers.set(e.pointerId, p);
      if (this.pointers.size === 1) {
        const node = this.hit(p.x, p.y);
        this.drag = { node, start: p, cam0: { ...this.cam }, moved: false };
        if (node) node.fixed = true;
      } else if (this.pointers.size === 2) {
        const [a, b] = [...this.pointers.values()];
        this.pinch = { d0: Math.hypot(a.x - b.x, a.y - b.y), k0: this.cam.k, cam0: { ...this.cam },
                       mid: { x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 } };
        if (this.drag?.node) this.drag.node.fixed = false;
        this.drag = null;
      }
    });

    c.addEventListener("pointermove", (e) => {
      const p = pos(e);
      if (e.pointerType === "mouse") { this.mouse = p; if (this.still) this.draw(); }
      if (!this.pointers.has(e.pointerId)) {
        if (e.pointerType === "mouse") {
          const h = this.hit(p.x, p.y);
          if (h !== this.hover) { this.hover = h; c.classList.toggle("pointing", !!h); this.draw(); }
        }
        return;
      }
      this.pointers.set(e.pointerId, p);
      if (this.pinch && this.pointers.size === 2) {
        const [a, b] = [...this.pointers.values()];
        const k = clamp(this.pinch.k0 * (Math.hypot(a.x - b.x, a.y - b.y) / this.pinch.d0), 0.25, 4);
        const { mid, cam0 } = this.pinch;
        const f = k / cam0.k;
        this.cam = { k, x: mid.x - (mid.x - cam0.x) * f, y: mid.y - (mid.y - cam0.y) * f };
        this.userMoved = true;
        this.draw();
        return;
      }
      const g = this.drag;
      if (!g) return;
      const dx = p.x - g.start.x, dy = p.y - g.start.y;
      if (!g.moved && Math.hypot(dx, dy) > 4) { g.moved = true; c.classList.add("dragging"); }
      if (!g.moved) return;
      if (g.node) {
        const w = this.toWorld(p.x, p.y);
        g.node.x = w.x; g.node.y = w.y;
        this.reheat(0.2);
      } else {
        this.cam = { ...g.cam0, x: g.cam0.x + dx, y: g.cam0.y + dy };
        this.userMoved = true;
        this.camAnim = null;
        this.draw();
      }
    });

    const end = (e) => {
      this.pointers.delete(e.pointerId);
      if (this.pointers.size < 2) this.pinch = null;
      const g = this.drag;
      if (g && this.pointers.size === 0) {
        if (g.node) {
          g.node.fixed = false;
          // A dragged hub stays where it was dropped: move its anchor too.
          if (g.moved && g.node.hub) { g.node.ax = g.node.x; g.node.ay = g.node.y; }
        }
        if (!g.moved) this.select(g.node || null);
        this.drag = null;
        c.classList.remove("dragging");
      }
    };
    c.addEventListener("pointerup", end);
    c.addEventListener("pointercancel", end);
    c.addEventListener("pointerleave", () => {
      this.mouse = null;
      if (this.hover) this.hover = null;
      this.draw();
    });
    c.addEventListener("wheel", (e) => {
      e.preventDefault();
      const p = pos(e);
      this.zoomAt(p.x, p.y, Math.exp(-e.deltaY * 0.0016));
    }, { passive: false });
    c.addEventListener("dblclick", (e) => { if (!this.hit(pos(e).x, pos(e).y)) this.fit(); });
  }

  // ── drawing ──────────────────────────────────────────────────────────────
  // Screen-space dot grid: drifts with the camera at a third of its speed
  // (parallax), and dots near the cursor swell, brighten and bend outward.
  drawGrid(ctx) {
    const S = 26, { x, y } = this.cam, m = this.mouse, R = 160;
    const ox = (((x * 0.33) % S) + S) % S, oy = (((y * 0.33) % S) + S) % S;
    const lens = [];
    ctx.fillStyle = "rgba(236, 232, 216, 0.075)";
    ctx.beginPath();
    for (let gx = ox - S; gx < this.w + S; gx += S) {
      for (let gy = oy - S; gy < this.h + S; gy += S) {
        if (m) {
          const dx = gx - m.x, dy = gy - m.y, d = Math.hypot(dx, dy);
          if (d < R) { lens.push([gx, gy, dx, dy, d]); continue; }
        }
        ctx.rect(gx - 0.75, gy - 0.75, 1.5, 1.5);
      }
    }
    ctx.fill();
    for (const [gx, gy, dx, dy, d] of lens) {
      const e = (1 - d / R) ** 2;
      const px = gx + (dx / (d || 1)) * e * 16, py = gy + (dy / (d || 1)) * e * 16;
      const s = 1.5 + e * 2.4;
      ctx.fillStyle = `rgba(147, 162, 255, ${0.08 + e * 0.5})`;
      ctx.fillRect(px - s / 2, py - s / 2, s, s);
    }
  }

  draw() {
    const ctx = this.ctx, T = this.theme, { k, x, y } = this.cam;
    if (!this.w) return;
    const now = this.now || performance.now();
    const t = now / 1000;
    ctx.setTransform(this.dpr, 0, 0, this.dpr, 0, 0);
    ctx.fillStyle = T.bg;
    ctx.fillRect(0, 0, this.w, this.h);
    this.drawGrid(ctx);
    if (!this.nodes.length) return;
    ctx.save();
    ctx.translate(x, y);
    ctx.scale(k, k);

    const focus = this.selected || this.hover;
    const near = focus ? this.nearSet(focus) : null;
    const px = (v) => v / k;   // constant on-screen size
    // Gentle drift so the graph feels alive; positions used for hit-testing
    // stay put (the drift is under 1.5px).
    const amp = this.still ? 0 : 1.4;
    const P = (d) => d.hub ? d : { x: d.x + Math.cos(t * 0.7 + d.phase) * amp, y: d.y + Math.sin(t * 0.9 + d.phase) * amp };

    // Hub glows first, under everything.
    for (const d of this.nodes) {
      if (!d.hub || !this.isVisible(d)) continue;
      const col = this.colorFor(d.source);
      const R = d.r * 7;
      const g = ctx.createRadialGradient(d.x, d.y, 0, d.x, d.y, R);
      g.addColorStop(0, col + (near && !near.has(d.id) ? "10" : "2a"));
      g.addColorStop(1, col + "00");
      ctx.fillStyle = g;
      ctx.beginPath(); ctx.arc(d.x, d.y, R, 0, TAU); ctx.fill();
    }

    // Spokes: thin teal threads from each hub to its concepts.
    ctx.lineCap = "round";
    for (const s of this.spokes) {
      if (!this.isVisible(s.a) || !this.isVisible(s.b)) continue;
      const touches = focus && (s.a === focus || s.b === focus);
      const a = P(s.a), b = P(s.b);
      ctx.strokeStyle = T.teal;
      ctx.globalAlpha = near ? (touches ? 0.85 : 0.06) : 0.38;
      ctx.lineWidth = px(touches ? 1.4 : 0.9);
      ctx.beginPath(); ctx.moveTo(a.x, a.y); ctx.lineTo(b.x, b.y); ctx.stroke();
    }

    // Related (dashed teal) and bridges (bright, curved, glowing).
    const curve = (l) => {
      const a = P(l.a), b = P(l.b);
      const bend = l.kind === "bridge" ? 0.2 : 0.08;
      const mx = (a.x + b.x) / 2, my = (a.y + b.y) / 2;
      return { a, b, cx: mx - (b.y - a.y) * bend, cy: my + (b.x - a.x) * bend };
    };
    for (const l of this.links) {
      if (!this.isVisible(l.a) || !this.isVisible(l.b)) continue;
      const touches = focus && (l.a === focus || l.b === focus);
      const dimmed = near && !touches;
      const { a, b, cx, cy } = curve(l);
      ctx.beginPath(); ctx.moveTo(a.x, a.y); ctx.quadraticCurveTo(cx, cy, b.x, b.y);
      if (l.kind === "bridge") {
        ctx.setLineDash([]);
        ctx.strokeStyle = T.blue;
        ctx.globalAlpha = dimmed ? 0.04 : 0.22;
        ctx.lineWidth = px(4 + l.w * 3);
        ctx.stroke();
        ctx.strokeStyle = T.accent;
        ctx.globalAlpha = dimmed ? 0.08 : 0.6 + l.w * 0.4;
        ctx.lineWidth = px(1.2 + l.w * 1.4 + (touches ? 0.6 : 0));
        ctx.stroke();
      } else {
        ctx.setLineDash([px(3), px(4)]);
        ctx.strokeStyle = T.teal;
        ctx.globalAlpha = dimmed ? 0.04 : touches ? 0.9 : 0.22 + l.w * 0.35;
        ctx.lineWidth = px(touches ? 1.3 : 0.9);
        ctx.stroke();
      }
    }
    ctx.setLineDash([]);

    // Pulses: light travelling along every bridge, and outward along the links
    // of whatever is hovered or selected.
    if (!this.still) {
      const pulse = (a, cx, cy, b, u, col, size) => {
        const v = 1 - u;
        const qx = v * v * a.x + 2 * v * u * cx + u * u * b.x;
        const qy = v * v * a.y + 2 * v * u * cy + u * u * b.y;
        const g = ctx.createRadialGradient(qx, qy, 0, qx, qy, px(size * 3));
        g.addColorStop(0, col); g.addColorStop(1, col.slice(0, 7) + "00");
        ctx.fillStyle = g;
        ctx.beginPath(); ctx.arc(qx, qy, px(size * 3), 0, TAU); ctx.fill();
      };
      ctx.globalAlpha = 1;
      for (const l of this.links) {
        if (l.kind !== "bridge" || !this.isVisible(l.a) || !this.isVisible(l.b)) continue;
        if (near && !(l.a === focus || l.b === focus)) continue;
        const { a, b, cx, cy } = curve(l);
        const u = (t / 2.6 + hash(l.a.id + l.b.id)) % 1;
        pulse(a, cx, cy, b, u, "#ece8d8ff", 2.2);
        pulse(b, cx, cy, a, (u + 0.5) % 1, "#93a2ffff", 1.8);
      }
      if (focus) {
        const out = [
          ...this.spokes.filter((s) => s.a === focus || s.b === focus),
          ...this.links.filter((l) => l.kind !== "bridge" && (l.a === focus || l.b === focus)),
        ];
        for (const l of out) {
          if (!this.isVisible(l.a) || !this.isVisible(l.b)) continue;
          const from = P(l.a === focus ? l.a : l.b), to = P(l.a === focus ? l.b : l.a);
          const u = (t / 1.4 + hash(l.a.id + l.b.id)) % 1;
          const mx = (from.x + to.x) / 2, my = (from.y + to.y) / 2;
          pulse(from, mx, my, to, u, "#5fd6cfcc", 1.6);
        }
      }
    }

    // Dots.
    for (const d of this.nodes) {
      if (!this.isVisible(d)) continue;
      const p = P(d);
      const dim = near && !near.has(d.id);
      ctx.globalAlpha = dim ? 0.13 : 1;
      const r = d.r * (d === this.hover ? 1.25 : 1);
      if (d === this.hover || d === this.selected) {
        const col = this.colorFor(d.sources[0]);
        const g = ctx.createRadialGradient(p.x, p.y, r * 0.5, p.x, p.y, r + px(18));
        g.addColorStop(0, col + "66"); g.addColorStop(1, col + "00");
        ctx.fillStyle = g;
        ctx.beginPath(); ctx.arc(p.x, p.y, r + px(18), 0, TAU); ctx.fill();
      }
      const n = d.sources.length;
      d.sources.forEach((s, i) => {
        ctx.fillStyle = this.colorFor(s);
        ctx.beginPath();
        if (n === 1) ctx.arc(p.x, p.y, r, 0, TAU);
        else {
          const a0 = -Math.PI / 2 + (i / n) * TAU, a1 = a0 + TAU / n;
          ctx.moveTo(p.x, p.y); ctx.arc(p.x, p.y, r, a0, a1); ctx.closePath();
        }
        ctx.fill();
      });
      if (d.hub) {   // a bright core makes hubs read as light sources
        ctx.fillStyle = "#ffffff";
        ctx.globalAlpha = (dim ? 0.13 : 1) * 0.55;
        ctx.beginPath(); ctx.arc(p.x, p.y, r * 0.38, 0, TAU); ctx.fill();
      }
      if (d === this.selected) {
        // Ripple: rings expanding out of the selected dot.
        ctx.globalAlpha = 1;
        const el = (now - this.selectedAt) / 1000;
        for (let i = 0; i < (this.still ? 1 : 2); i++) {
          const u = this.still ? 0.3 : ((el + i * 0.9) / 1.8) % 1;
          ctx.strokeStyle = T.ink;
          ctx.globalAlpha = (1 - u) * 0.7;
          ctx.lineWidth = px(1.2);
          ctx.beginPath(); ctx.arc(p.x, p.y, r + px(4 + u * 26), 0, TAU); ctx.stroke();
        }
      }
    }

    // Labels: hubs always; concepts fade in with zoom, or when highlighted.
    ctx.textAlign = "center";
    ctx.lineJoin = "round";
    // A short, crisp fade: half-transparent labels everywhere just look muddy.
    const zoomFade = clamp((k - 0.55) / 0.15, 0, 1);
    for (const d of this.nodes) {
      if (!this.isVisible(d)) continue;
      const strong = near && near.has(d.id);
      let alpha = d.hub ? 1 : strong ? 1 : zoomFade * (d.sources.length > 1 ? 1 : 0.85);
      if (near && !strong) alpha = Math.min(alpha, 0.14);
      if (alpha < 0.02) continue;
      const p = P(d);
      ctx.globalAlpha = alpha;
      if (d.hub) ctx.font = `500 ${px(14)}px ${PIXEL}`;
      else ctx.font = `${d === focus ? 600 : 400} ${px(d === focus ? 13.5 : 11.5)}px ${SANS}`;
      const ty = p.y + d.r + px(d.hub ? 18 : 14);
      let tx = p.x;
      if (d.hub) {   // never let a source name run off the screen edge
        const half = ctx.measureText(d.label).width / 2 + px(8);
        const left = -x / k + half, right = (this.w - x) / k - half;
        tx = left < right ? clamp(p.x, left, right) : (left + right) / 2;
      }
      ctx.strokeStyle = T.bg;
      ctx.lineWidth = px(4);
      ctx.strokeText(d.label, tx, ty);
      ctx.fillStyle = d.hub ? this.colorFor(d.source) : T.ink;
      ctx.fillText(d.label, tx, ty);
    }
    ctx.globalAlpha = 1;
    ctx.restore();
  }
}
