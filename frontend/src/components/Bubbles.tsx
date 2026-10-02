import { useEffect, useRef } from "react";

/** Background of glowing, pulsing bubbles (bright core fading to a transparent edge) with simple 2D physics: they drift, bounce off the edges and off
 * each other (elastic, mass ~ area), and drift away from the pointer. Decorative only: pointer-events none,
 * aria-hidden, paused while the tab is hidden, and a still frame when the user prefers reduced motion. */

interface Bubble { x: number; y: number; vx: number; vy: number; r: number; base: number; hue: number; phase: number; speed: number }

const HUES = [262, 190, 290, 210, 175]; // violet, cyan, magenta, blue, teal: the app's gradient family
const MAX_SPEED = 0.6; // px per frame at 60 fps
const POINTER_RADIUS = 160;

// Bubble count: set VITE_BUBBLE_COUNT in frontend/.env (0 turns them off), or change the fallback here.
// Read at build time (`npm run build`) or dev-server start.
const DEFAULT_BUBBLES = 14;
const MAX_BUBBLES = 40;
const envCount = Number(import.meta.env.VITE_BUBBLE_COUNT);
export const BUBBLE_COUNT = import.meta.env.VITE_BUBBLE_COUNT !== undefined && Number.isFinite(envCount)
  ? Math.min(MAX_BUBBLES, Math.max(0, Math.round(envCount))) : DEFAULT_BUBBLES;

function spawn(existing: Bubble[], w: number, h: number): Bubble | null {
  const base = 22 + Math.random() * Math.min(80, w / 12);
  // Try a few spots so a new bubble never starts overlapping (overlap would make it jump apart on frame 1).
  for (let t = 0; t < 40; t++) {
    const x = base + Math.random() * Math.max(1, w - 2 * base), y = base + Math.random() * Math.max(1, h - 2 * base);
    if (existing.every((b) => Math.hypot(b.x - x, b.y - y) > b.base + base + 4)) {
      const a = Math.random() * Math.PI * 2, s = 0.15 + Math.random() * 0.35;
      return { x, y, vx: Math.cos(a) * s, vy: Math.sin(a) * s, r: base, base, hue: HUES[existing.length % HUES.length],
        phase: Math.random() * Math.PI * 2, speed: 0.6 + Math.random() * 0.8 };
    }
  }
  return null; // screen too crowded: skip rather than overlap
}

/** Grows or shrinks the list to `count`, keeping the bubbles that are already moving. */
function fit(bs: Bubble[], count: number, w: number, h: number) {
  if (bs.length > count) bs.length = count;
  while (bs.length < count) {
    const b = spawn(bs, w, h);
    if (!b) break;
    bs.push(b);
  }
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

function draw(ctx: CanvasRenderingContext2D, bs: Bubble[], w: number, h: number, t: number) {
  ctx.clearRect(0, 0, w, h);
  ctx.globalCompositeOperation = "lighter"; // overlapping glows add up like light
  for (const b of bs) {
    // The core brightens and dims with the pulse, so each bubble "breathes" light, not just size.
    const glow = 0.75 + 0.25 * Math.sin(t * 0.0012 * b.speed + b.phase);
    const g = ctx.createRadialGradient(b.x, b.y, 0, b.x, b.y, b.r);
    g.addColorStop(0, `hsla(${b.hue}, 100%, 82%, ${0.55 * glow})`);
    g.addColorStop(0.18, `hsla(${b.hue}, 95%, 68%, ${0.32 * glow})`);
    g.addColorStop(0.5, `hsla(${b.hue}, 90%, 58%, ${0.12 * glow})`);
    g.addColorStop(1, `hsla(${b.hue}, 90%, 50%, 0)`);
    ctx.fillStyle = g;
    ctx.beginPath(); ctx.arc(b.x, b.y, b.r, 0, Math.PI * 2); ctx.fill();
  }
  ctx.globalCompositeOperation = "source-over";
}

export function Bubbles({ count = BUBBLE_COUNT }: { count?: number }) {
  const canvas = useRef<HTMLCanvasElement>(null);
  const target = useRef(count);
  const api = useRef<{ refit: () => void } | null>(null);
  useEffect(() => { target.current = count; api.current?.refit(); }, [count]);

  useEffect(() => {
    const el = canvas.current;
    const ctx = el?.getContext("2d");
    if (!el || !ctx) return; // e.g. jsdom in tests
    let w = 0, h = 0, frame = 0, last = 0;
    const bubbles: Bubble[] = [];
    let pointer: { x: number; y: number } | null = null;
    const still = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ?? false;

    const resize = () => {
      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      w = window.innerWidth; h = window.innerHeight;
      el.width = Math.round(w * dpr); el.height = Math.round(h * dpr);
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      fit(bubbles, target.current, w, h);
      for (const b of bubbles) { b.x = Math.min(Math.max(b.x, b.r), w - b.r); b.y = Math.min(Math.max(b.y, b.r), h - b.r); }
      draw(ctx, bubbles, w, h, performance.now());
    };
    const tick = (t: number) => {
      const dt = last ? Math.min(3, (t - last) / 16.67) : 1; // frame-rate independent; clamp after tab switches
      last = t;
      step(bubbles, w, h, t, dt, pointer);
      draw(ctx, bubbles, w, h, t);
      frame = requestAnimationFrame(tick);
    };
    const start = () => { if (!still && !frame) { last = 0; frame = requestAnimationFrame(tick); } };
    const stop = () => { cancelAnimationFrame(frame); frame = 0; };
    const onVisibility = () => (document.hidden ? stop() : start());
    const onMove = (e: PointerEvent) => { pointer = { x: e.clientX, y: e.clientY }; };
    const onLeave = () => { pointer = null; };

    api.current = { refit: () => { fit(bubbles, target.current, w, h); draw(ctx, bubbles, w, h, performance.now()); } };
    resize();
    start();
    window.addEventListener("resize", resize);
    window.addEventListener("pointermove", onMove, { passive: true });
    document.addEventListener("pointerleave", onLeave);
    document.addEventListener("visibilitychange", onVisibility);
    return () => {
      stop();
      api.current = null;
      window.removeEventListener("resize", resize);
      window.removeEventListener("pointermove", onMove);
      document.removeEventListener("pointerleave", onLeave);
      document.removeEventListener("visibilitychange", onVisibility);
    };
  }, []);

  return <canvas ref={canvas} className="bubbles" aria-hidden="true" />;
}
