import { useEffect, useRef } from "react";

/** Background of glowing, pulsing bubbles with simple 2D physics: they drift, bounce off the edges and off
 * each other (elastic, mass ~ area), and drift away from the pointer. Decorative only: pointer-events none,
 * aria-hidden, paused while the tab is hidden, and a still frame when the user prefers reduced motion. */

interface Bubble { x: number; y: number; vx: number; vy: number; r: number; base: number; hue: number; phase: number; speed: number }

const HUES = [262, 190, 290, 210, 175]; // violet, cyan, magenta, blue, teal: the app's gradient family
const MAX_SPEED = 0.6; // px per frame at 60 fps
const POINTER_RADIUS = 160;

function makeBubbles(w: number, h: number): Bubble[] {
  const count = Math.max(8, Math.min(22, Math.round((w * h) / 70000)));
  const out: Bubble[] = [];
  for (let i = 0; i < count && out.length < count; i++) {
    const base = 18 + Math.random() * Math.min(70, w / 14);
    // Try a few spots so bubbles never start overlapping (overlap would make them jump apart on frame 1).
    for (let t = 0; t < 30; t++) {
      const x = base + Math.random() * (w - 2 * base), y = base + Math.random() * (h - 2 * base);
      if (out.every((b) => Math.hypot(b.x - x, b.y - y) > b.base + base + 4)) {
        const a = Math.random() * Math.PI * 2, s = 0.15 + Math.random() * 0.35;
        out.push({ x, y, vx: Math.cos(a) * s, vy: Math.sin(a) * s, r: base, base, hue: HUES[i % HUES.length],
          phase: Math.random() * Math.PI * 2, speed: 0.6 + Math.random() * 0.8 });
        break;
      }
    }
  }
  return out;
}

function step(bs: Bubble[], w: number, h: number, t: number, dt: number, pointer: { x: number; y: number } | null) {
  for (const b of bs) {
    b.r = b.base * (1 + 0.09 * Math.sin(t * 0.0012 * b.speed + b.phase)); // the pulse
    if (pointer) {
      const dx = b.x - pointer.x, dy = b.y - pointer.y, d = Math.hypot(dx, dy);
      if (d > 0 && d < POINTER_RADIUS + b.r) {
        const f = (1 - d / (POINTER_RADIUS + b.r)) * 0.12 * dt;
        b.vx += (dx / d) * f; b.vy += (dy / d) * f;
      }
    }
    const s = Math.hypot(b.vx, b.vy);
    if (s > MAX_SPEED) { b.vx *= MAX_SPEED / s; b.vy *= MAX_SPEED / s; } // gentle cap so pushes calm down
    b.x += b.vx * dt; b.y += b.vy * dt;
    if (b.x < b.r) { b.x = b.r; b.vx = Math.abs(b.vx); } else if (b.x > w - b.r) { b.x = w - b.r; b.vx = -Math.abs(b.vx); }
    if (b.y < b.r) { b.y = b.r; b.vy = Math.abs(b.vy); } else if (b.y > h - b.r) { b.y = h - b.r; b.vy = -Math.abs(b.vy); }
  }
  // Pairwise elastic collisions: separate the overlap, then exchange momentum along the contact normal.
  for (let i = 0; i < bs.length; i++) {
    for (let j = i + 1; j < bs.length; j++) {
      const a = bs[i], b = bs[j];
      const dx = b.x - a.x, dy = b.y - a.y, d = Math.hypot(dx, dy), min = a.r + b.r;
      if (d === 0 || d >= min) continue;
      const nx = dx / d, ny = dy / d, ma = a.r * a.r, mb = b.r * b.r, overlap = min - d;
      a.x -= nx * overlap * (mb / (ma + mb)); a.y -= ny * overlap * (mb / (ma + mb));
      b.x += nx * overlap * (ma / (ma + mb)); b.y += ny * overlap * (ma / (ma + mb));
      const rel = (a.vx - b.vx) * nx + (a.vy - b.vy) * ny;
      if (rel <= 0) continue; // already separating
      const k = (2 * rel) / (ma + mb);
      a.vx -= k * mb * nx; a.vy -= k * mb * ny;
      b.vx += k * ma * nx; b.vy += k * ma * ny;
    }
  }
}

function draw(ctx: CanvasRenderingContext2D, bs: Bubble[], w: number, h: number) {
  ctx.clearRect(0, 0, w, h);
  ctx.globalCompositeOperation = "lighter"; // overlapping glows add up like light
  for (const b of bs) {
    const g = ctx.createRadialGradient(b.x - b.r * 0.35, b.y - b.r * 0.35, b.r * 0.1, b.x, b.y, b.r);
    g.addColorStop(0, `hsla(${b.hue}, 95%, 72%, 0.22)`);
    g.addColorStop(0.7, `hsla(${b.hue}, 90%, 60%, 0.08)`);
    g.addColorStop(1, `hsla(${b.hue}, 90%, 55%, 0)`);
    ctx.fillStyle = g;
    ctx.beginPath(); ctx.arc(b.x, b.y, b.r, 0, Math.PI * 2); ctx.fill();
    ctx.strokeStyle = `hsla(${b.hue}, 95%, 75%, 0.16)`; // thin rim so they read as bubbles, not blobs
    ctx.lineWidth = 1;
    ctx.beginPath(); ctx.arc(b.x, b.y, b.r * 0.97, 0, Math.PI * 2); ctx.stroke();
  }
  ctx.globalCompositeOperation = "source-over";
}

export function Bubbles() {
  const canvas = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const el = canvas.current;
    const ctx = el?.getContext("2d");
    if (!el || !ctx) return; // e.g. jsdom in tests
    let w = 0, h = 0, bubbles: Bubble[] = [], frame = 0, last = 0;
    let pointer: { x: number; y: number } | null = null;
    const still = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ?? false;

    const resize = () => {
      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      w = window.innerWidth; h = window.innerHeight;
      el.width = Math.round(w * dpr); el.height = Math.round(h * dpr);
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      if (!bubbles.length) bubbles = makeBubbles(w, h);
      for (const b of bubbles) { b.x = Math.min(Math.max(b.x, b.r), w - b.r); b.y = Math.min(Math.max(b.y, b.r), h - b.r); }
      draw(ctx, bubbles, w, h);
    };
    const tick = (t: number) => {
      const dt = last ? Math.min(3, (t - last) / 16.67) : 1; // frame-rate independent; clamp after tab switches
      last = t;
      step(bubbles, w, h, t, dt, pointer);
      draw(ctx, bubbles, w, h);
      frame = requestAnimationFrame(tick);
    };
    const start = () => { if (!still && !frame) { last = 0; frame = requestAnimationFrame(tick); } };
    const stop = () => { cancelAnimationFrame(frame); frame = 0; };
    const onVisibility = () => (document.hidden ? stop() : start());
    const onMove = (e: PointerEvent) => { pointer = { x: e.clientX, y: e.clientY }; };
    const onLeave = () => { pointer = null; };

    resize();
    start();
    window.addEventListener("resize", resize);
    window.addEventListener("pointermove", onMove, { passive: true });
    document.addEventListener("pointerleave", onLeave);
    document.addEventListener("visibilitychange", onVisibility);
    return () => {
      stop();
      window.removeEventListener("resize", resize);
      window.removeEventListener("pointermove", onMove);
      document.removeEventListener("pointerleave", onLeave);
      document.removeEventListener("visibilitychange", onVisibility);
    };
  }, []);

  return <canvas ref={canvas} className="bubbles" aria-hidden="true" />;
}
