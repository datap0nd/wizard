import {useEffect, useMemo, useRef} from 'react';
import {along, inFocus, nodeAt, pathInFocus, type BrainLayout, type Focus, type LaidNode, type Path} from '@/brain';

/** A soft round glow in one colour, drawn once and stamped for every node and pulse (much cheaper than shadowBlur). */
function glowSprite(color: string): HTMLCanvasElement | null {
  if (typeof document === 'undefined') return null;
  const sprite = document.createElement('canvas');
  sprite.width = sprite.height = 64;
  const ctx = sprite.getContext('2d');
  if (!ctx) return null;
  const g = ctx.createRadialGradient(32, 32, 0, 32, 32, 32);
  g.addColorStop(0, color); g.addColorStop(0.25, `${color}aa`); g.addColorStop(1, `${color}00`);
  ctx.fillStyle = g; ctx.fillRect(0, 0, 64, 64);
  return sprite;
}

interface Pulse { path: Path; born: number; life: number; reverse: boolean; size: number }
interface Ripple { born: number }

const isJsdom = typeof navigator !== 'undefined' && /jsdom/i.test(navigator.userAgent);

function context(canvas: HTMLCanvasElement | null): CanvasRenderingContext2D | null {
  if (!canvas || isJsdom) return null;
  try { return canvas.getContext('2d'); } catch { return null; }
}

function curve(ctx: CanvasRenderingContext2D, path: Path) {
  ctx.moveTo(path.p0.x, path.p0.y);
  ctx.quadraticCurveTo(path.c.x, path.c.y, path.p1.x, path.p1.y);
}

/**
 * The brain itself: synapses (drawn once per layout and focus), notes as glowing dots that twinkle, and pulses that
 * run along the synapses into the wizard in the middle. The motion is decoration: it does not show Wizard reading.
 * `burst` grows when new articles arrive, sending a flurry along the news synapses.
 */
export function BrainCanvas({layout, focus, hovered, reduced, burst, onHover, onPick}: {
  layout: BrainLayout; focus: Focus; hovered: string | null; reduced: boolean; burst: number;
  onHover: (node: LaidNode | null) => void; onPick: (node: LaidNode | null) => void;
}) {
  const canvas = useRef<HTMLCanvasElement>(null);
  const staticLayer = useRef<HTMLCanvasElement | null>(null);
  const born = useRef<number>(0);
  const pulses = useRef<Pulse[]>([]);
  const ripples = useRef<Ripple[]>([]);
  const sprites = useRef(new Map<string, HTMLCanvasElement | null>());
  const sprite = (color: string) => {
    if (!sprites.current.has(color)) sprites.current.set(color, glowSprite(color));
    return sprites.current.get(color) ?? null;
  };
  const lit = useMemo(() => new Set(layout.nodes.filter(n => inFocus(focus, layout, n.key)).map(n => n.key)), [layout, focus]);
  const livePaths = useMemo(() => layout.paths.filter(p => pathInFocus(focus, layout, p)), [layout, focus]);
  const dpr = typeof window === 'undefined' ? 1 : Math.min(window.devicePixelRatio || 1, 2);

  useEffect(() => { born.current = performance.now(); pulses.current = []; }, [layout.nodes.length, layout.clusters.length]);

  // The synapses, once per layout and focus.
  useEffect(() => {
    const layer = staticLayer.current ?? document.createElement('canvas');
    staticLayer.current = layer;
    layer.width = Math.round(layout.width * dpr); layer.height = Math.round(layout.height * dpr);
    const ctx = context(layer);
    if (!ctx) return;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, layout.width, layout.height);
    ctx.globalCompositeOperation = 'lighter';
    ctx.lineCap = 'round';
    for (const path of layout.paths) {
      const on = pathInFocus(focus, layout, path);
      const strength = {link: 0.13, system: 0.11, axon: 0.2, spoke: 0.22}[path.kind];
      ctx.globalAlpha = on ? strength * (focus.kind === 'all' ? 1 : 1.9) : strength * 0.18;
      ctx.strokeStyle = path.color;
      ctx.lineWidth = path.kind === 'axon' ? 1.6 : path.kind === 'spoke' ? 1.2 : 0.8;
      ctx.beginPath(); curve(ctx, path); ctx.stroke();
    }
    ctx.globalAlpha = 1;
  }, [layout, focus, dpr]);

  useEffect(() => {
    const el = canvas.current;
    const ctx = context(el);
    if (!el || !ctx) return;
    el.width = Math.round(layout.width * dpr); el.height = Math.round(layout.height * dpr);
    let frame = 0, last = performance.now();
    const weighted = livePaths.flatMap(p => (p.kind === 'axon' || p.kind === 'spoke' ? [p, p, p] : [p]));
    const draw = (now: number) => {
      const dt = Math.min(0.05, (now - last) / 1000); last = now;
      const age = (now - born.current) / 1000;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.clearRect(0, 0, layout.width, layout.height);
      // The synapses fade in while the brain assembles.
      ctx.globalAlpha = reduced ? 1 : Math.min(1, Math.max(0, (age - 0.6) / 1.4));
      if (staticLayer.current) ctx.drawImage(staticLayer.current, 0, 0, layout.width, layout.height);
      ctx.globalCompositeOperation = 'lighter';
      // Ripples where pulses reach the wizard.
      ripples.current = ripples.current.filter(r => now - r.born < 1400);
      for (const ripple of ripples.current) {
        const t = (now - ripple.born) / 1400;
        ctx.globalAlpha = 0.35 * (1 - t);
        ctx.strokeStyle = '#9fb3ff'; ctx.lineWidth = 1.5;
        ctx.beginPath(); ctx.arc(layout.center.x, layout.center.y, layout.core * (1 + t * 0.5), 0, Math.PI * 2); ctx.stroke();
      }
      // Notes: each grows in from the middle of its cluster, then twinkles now and then.
      layout.nodes.forEach((node, i) => {
        const cluster = layout.clusters.findIndex(c => c.id === node.cluster);
        const delay = reduced ? 0 : 0.15 + cluster * 0.12 + (i % 60) * 0.012;
        const grow = Math.min(1, Math.max(0, (age - delay) / 0.7));
        if (grow <= 0) return;
        const on = lit.has(node.key);
        const twinkle = reduced ? 0 : Math.max(0, Math.sin(now / 900 + node.phase * 7)) ** 12;
        const hover = hovered === node.key;
        const r = node.r * (hover ? 1.8 : 1) * (0.4 + 0.6 * grow);
        const glow = sprite(node.color);
        ctx.globalAlpha = (on ? 0.55 + twinkle * 0.45 : 0.08) * grow;
        if (glow) ctx.drawImage(glow, node.x - r * 3.2, node.y - r * 3.2, r * 6.4, r * 6.4);
        ctx.globalAlpha = (on ? 0.95 : 0.22) * grow;
        ctx.fillStyle = node.color;
        ctx.beginPath(); ctx.arc(node.x, node.y, r * 0.62, 0, Math.PI * 2); ctx.fill();
        if (on && (node.note?.stage === 'SIGNED' || twinkle > 0.3 || hover)) {
          ctx.fillStyle = '#ffffff'; ctx.globalAlpha = (hover ? 1 : 0.5 + twinkle * 0.5) * grow;
          ctx.beginPath(); ctx.arc(node.x, node.y, Math.max(0.8, r * 0.28), 0, Math.PI * 2); ctx.fill();
        }
      });
      // Pulses run along the synapses.
      if (!reduced && age > 1.6 && weighted.length) {
        const rate = Math.min(26, 6 + weighted.length / 40);
        let spawn = rate * dt;
        while (spawn > 0 && pulses.current.length < 90) {
          if (spawn < 1 && Math.random() > spawn) break;
          spawn -= 1;
          const path = weighted[Math.floor(Math.random() * weighted.length)];
          const inward = path.kind === 'axon' || path.kind === 'spoke' || path.kind === 'system';
          pulses.current.push({path, born: now, life: 900 + Math.random() * 1400, reverse: !inward && Math.random() < 0.5, size: 2 + Math.random() * 2});
        }
      }
      pulses.current = pulses.current.filter(pulse => {
        const t = (now - pulse.born) / pulse.life;
        if (t >= 1) {
          if (pulse.path.to === 'wizard' && ripples.current.length < 5) ripples.current.push({born: now});
          return false;
        }
        const glow = sprite(pulse.path.color);
        for (let k = 0; k < 6; k++) {
          const at = t - k * 0.025;
          if (at < 0) break;
          const p = along(pulse.path, pulse.reverse ? 1 - at : at);
          const fade = Math.sin(Math.PI * t);
          ctx.globalAlpha = (k === 0 ? 0.95 : 0.5 / (k + 1)) * fade;
          const s = pulse.size * (k === 0 ? 3.4 : 2.2);
          if (glow) ctx.drawImage(glow, p.x - s, p.y - s, s * 2, s * 2);
          if (k === 0) { ctx.fillStyle = '#ffffff'; ctx.beginPath(); ctx.arc(p.x, p.y, pulse.size * 0.45, 0, Math.PI * 2); ctx.fill(); }
        }
        return true;
      });
      ctx.globalCompositeOperation = 'source-over';
      ctx.globalAlpha = 1;
      if (!reduced || age < 3) frame = requestAnimationFrame(draw);
    };
    frame = requestAnimationFrame(draw);
    return () => cancelAnimationFrame(frame);
  }, [layout, lit, livePaths, hovered, reduced, dpr]); // eslint-disable-line react-hooks/exhaustive-deps

  // New articles: a flurry along the news synapses.
  useEffect(() => {
    if (!burst || reduced) return;
    const news = layout.paths.filter(p => p.from.startsWith('news') || p.to === 'news');
    const now = performance.now();
    for (let i = 0; i < Math.min(40, news.length * 3); i++) {
      const path = news[i % news.length];
      pulses.current.push({path, born: now + i * 35, life: 1100 + Math.random() * 700, reverse: false, size: 3});
    }
  }, [burst]); // eslint-disable-line react-hooks/exhaustive-deps

  const point = (e: React.MouseEvent<HTMLCanvasElement>) => {
    const box = e.currentTarget.getBoundingClientRect();
    return nodeAt(layout, e.clientX - box.left, e.clientY - box.top);
  };
  return (
    <canvas ref={canvas} className="absolute inset-0 h-full w-full" style={{width: layout.width, height: layout.height}}
      onMouseMove={e => onHover(point(e))} onMouseLeave={() => onHover(null)} onClick={e => onPick(point(e))}
      data-testid="brain-canvas" role="img"
      aria-label={`${layout.nodes.length} notes in ${layout.clusters.length} clusters, joined by ${layout.paths.length} connections`} />
  );
}
