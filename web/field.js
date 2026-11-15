// CourseLens — the Ask view's background texture.
// A still pixel-dot grid (the same one the Course Map uses) that reacts only to
// the cursor: dots near it swell, tint blue and bend outward like a lens. Nothing
// moves on its own; it redraws only while the lens is easing toward the pointer.

export function startField(canvas, { isActive }) {
  const ctx = canvas.getContext("2d");
  const S = 24, R = 170;
  const still = matchMedia("(prefers-reduced-motion: reduce)").matches;
  let w = 0, h = 0, dpr = 1, raf = null;
  let target = null;                 // pointer position, or null when away
  const lens = { x: 0, y: 0, s: 0 }; // eased position + strength (0..1)

  function size() {
    const r = canvas.getBoundingClientRect();
    dpr = window.devicePixelRatio || 1;
    if (r.width === w && r.height === h) return;
    w = r.width; h = r.height;
    canvas.width = Math.round(w * dpr);
    canvas.height = Math.round(h * dpr);
  }

  function draw() {
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, w, h);
    const ox = (w % S) / 2, oy = (h % S) / 2;
    const near = [];
    ctx.fillStyle = "rgba(236, 232, 216, 0.07)";
    ctx.beginPath();
    for (let x = ox; x < w; x += S) {
      for (let y = oy; y < h; y += S) {
        const dx = x - lens.x, dy = y - lens.y, d = Math.hypot(dx, dy);
        if (lens.s > 0.01 && d < R) { near.push([x, y, dx, dy, d]); continue; }
        ctx.rect(x - 0.75, y - 0.75, 1.5, 1.5);
      }
    }
    ctx.fill();
    for (const [x, y, dx, dy, d] of near) {
      const e = (1 - d / R) ** 2 * lens.s;
      const px = x + (dx / (d || 1)) * e * 14, py = y + (dy / (d || 1)) * e * 14;
      const s = 1.5 + e * 2.6;
      ctx.fillStyle = `rgba(147, 162, 255, ${0.07 + e * 0.55})`;
      ctx.fillRect(px - s / 2, py - s / 2, s, s);
    }
  }

  function frame() {
    raf = null;
    if (!isActive()) return;
    size();
    let settled = true;
    if (target) {
      const k = still ? 1 : 0.22;
      lens.x += (target.x - lens.x) * k;
      lens.y += (target.y - lens.y) * k;
      lens.s += (1 - lens.s) * (still ? 1 : 0.15);
      settled = Math.hypot(target.x - lens.x, target.y - lens.y) < 0.5 && lens.s > 0.99;
    } else {
      lens.s *= still ? 0 : 0.85;
      settled = lens.s < 0.01;
    }
    draw();
    if (!settled) raf = requestAnimationFrame(frame);
  }
  const kick = () => { if (!raf) raf = requestAnimationFrame(frame); };

  // Listen on the whole view: the thread and composer sit on top of the canvas.
  const view = canvas.parentElement;
  view.addEventListener("pointermove", (e) => {
    if (e.pointerType !== "mouse") return;   // no lens on touch screens
    const r = canvas.getBoundingClientRect();
    if (!target) { lens.x = e.clientX - r.left; lens.y = e.clientY - r.top; }
    target = { x: e.clientX - r.left, y: e.clientY - r.top };
    kick();
  });
  view.addEventListener("pointerleave", () => { target = null; kick(); });
  new ResizeObserver(() => { w = 0; kick(); }).observe(canvas);
  kick();
  return kick;
}
