import {useEffect, useRef} from 'react';
import {EDGE_STYLE, edgeShown, frame, INK, Layout, nearest, nodeShown, projector, SURFACE, type Camera, type GEdge, type GNode, type Graph,
  type LayerId} from '@/graph3d';

export interface GraphControl { zoom: (factor: number) => void; reset: () => void }

const isJsdom = typeof navigator !== 'undefined' && /jsdom/i.test(navigator.userAgent);
const START = {yaw: 0.65, pitch: 0.52};
const NEAR = 8;
const FOG = [1, 0.72, 0.48];
const GRID = 'rgba(240, 239, 236, 0.07)';
const AXES: [string, number[], string][] = [['x', [1, 0, 0], '#e66767'], ['y', [0, 1, 0], '#199e70'], ['z', [0, 0, 1], '#3987e5']];

function edgeColor(graph: Graph, edge: GEdge): string {
  const a = graph.nodes[edge.a], b = graph.nodes[edge.b];
  if (edge.kind === 'tagged') return a.kind === 'tag' ? a.color : b.color;
  if (edge.kind === 'documents' || edge.kind === 'news') return INK.secondary;
  return a.kind === 'note' || a.kind === 'term' ? a.color : b.color;
}

function shape(ctx: CanvasRenderingContext2D, node: GNode, x: number, y: number, r: number) {
  ctx.beginPath();
  if (node.kind === 'system') {
    const d = r * 1.3;
    ctx.moveTo(x, y - d); ctx.lineTo(x + d, y); ctx.lineTo(x, y + d); ctx.lineTo(x - d, y); ctx.closePath();
  } else if (node.kind === 'category' || node.kind === 'news') {
    const d = r * 0.9;
    ctx.rect(x - d, y - d, d * 2, d * 2);
  } else {
    ctx.arc(x, y, r, 0, Math.PI * 2);
  }
}

/**
 * The knowledge graph in 3D on a plain canvas: a perspective camera orbiting the graph, edges batched by style and
 * faded with depth, nodes drawn back to front, labels placed where they do not collide, a ground grid and an axis
 * triad for orientation. The layout settles a few ticks per frame (graph3d.ts, Layout). Drag turns the graph, the wheel
 * zooms, a double click frames it again; a point under the pointer is reported, a click picks it.
 */
export function Graph3D({graph, layers, lit, frameOn, frameKey, selected, hovered, labelled, reduced, rotate, inset, bottom, control,
  onHover, onPick, onProgress}: {
  graph: Graph; layers: ReadonlySet<LayerId>; lit: Set<number> | null; frameOn: number[] | null; frameKey: string;
  selected: string | null; hovered: string | null; labelled: Set<number>; reduced: boolean; rotate: boolean; inset: number; bottom: number;
  control?: {current: GraphControl | null};
  onHover: (node: GNode | null) => void; onPick: (node: GNode | null) => void; onProgress?: (settled: boolean, ticks: number) => void;
}) {
  const canvas = useRef<HTMLCanvasElement>(null);
  const props = useRef({graph, layers, lit, frameOn, selected, hovered, labelled, reduced, rotate, inset, bottom, onHover, onPick, onProgress});
  props.current = {graph, layers, lit, frameOn, selected, hovered, labelled, reduced, rotate, inset, bottom, onHover, onPick, onProgress};
  const state = useRef<{layout: Layout | null; ticks: number; camera: Camera; goal: Pick<Camera, 'tx' | 'ty' | 'tz' | 'distance'>;
    steered: boolean; touched: number; dirty: boolean; size: {w: number; h: number}; points: {i: number; x: number; y: number; r: number; depth: number}[];
    hover: number | null}>({
    layout: null, ticks: 0, camera: {...START, distance: 600, tx: 0, ty: 0, tz: 0}, goal: {tx: 0, ty: 0, tz: 0, distance: 600},
    steered: false, touched: 0, dirty: true, size: {w: 0, h: 0}, points: [], hover: null,
  });

  // A new graph keeps the places of the nodes it shares with the one before.
  useEffect(() => {
    const s = state.current;
    s.layout = new Layout(graph, 7, s.layout ? {graph: s.layout.graph, pos: s.layout.pos, alpha: s.layout.alpha} : undefined);
    s.ticks = 0; s.dirty = true;
  }, [graph]);

  // A new focus: frame it (the person's own zoom and turns are kept until then).
  useEffect(() => {
    const s = state.current;
    s.steered = false;
    if (s.layout) s.goal = frame(s.layout.pos, frameOn ?? graph.nodes.map(n => n.i), aspect(s.size, inset, bottom));
    s.dirty = true;
  }, [frameKey]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => { state.current.dirty = true; }, [layers, lit, selected, hovered, labelled, inset, bottom, rotate]);

  useEffect(() => {
    if (!control) return;
    control.current = {
      zoom: factor => {
        const s = state.current;
        s.goal = {...s.goal, distance: s.goal.distance * factor}; s.steered = true; s.touched = performance.now(); s.dirty = true;
      },
      reset: () => {
        const s = state.current;
        if (!s.layout) return;
        s.camera = {...s.camera, ...START}; s.steered = false;
        s.goal = frame(s.layout.pos, props.current.frameOn ?? props.current.graph.nodes.map(n => n.i), aspect(s.size, props.current.inset, props.current.bottom));
        s.dirty = true;
      },
    };
    return () => { control.current = null; };
  }, [control]);

  useEffect(() => {
    const el = canvas.current;
    if (!el || isJsdom) return;
    let ctx: CanvasRenderingContext2D | null = null;
    try { ctx = el.getContext('2d'); } catch { ctx = null; }
    if (!ctx) return;
    const s = state.current;
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    const resize = () => {
      const box = el.parentElement!.getBoundingClientRect();
      s.size = {w: Math.max(1, box.width), h: Math.max(1, box.height)};
      el.width = Math.round(s.size.w * dpr); el.height = Math.round(s.size.h * dpr);
      el.style.width = `${s.size.w}px`; el.style.height = `${s.size.h}px`;
      s.dirty = true;
    };
    resize();
    const observer = typeof ResizeObserver === 'undefined' ? null : new ResizeObserver(resize);
    observer?.observe(el.parentElement!);

    let raf = 0, last = performance.now(), first = true;
    const loop = (now: number) => {
      const p = props.current, layout = s.layout;
      const dt = Math.min(0.05, (now - last) / 1000);
      last = now;
      let moved = false;
      if (layout && !layout.settled) {
        const started = performance.now(), budget = first ? 140 : 9;
        do { layout.tick(); s.ticks++; } while (!layout.settled && performance.now() - started < budget);
        first = false; moved = true;
        // While it settles, keep it framed (unless the person has taken the camera).
        if (!s.steered) s.goal = frame(layout.pos, p.frameOn ?? p.graph.nodes.map(n => n.i), aspect(s.size, p.inset, p.bottom));
        p.onProgress?.(layout.settled, s.ticks);
      }
      const c = s.camera, g = s.goal, k = p.reduced ? 1 : 1 - Math.exp(-dt * 3.2);
      const far = Math.abs(c.tx - g.tx) + Math.abs(c.ty - g.ty) + Math.abs(c.tz - g.tz) + Math.abs(c.distance - g.distance);
      if (far > 0.05) {
        s.camera = {...c, tx: c.tx + (g.tx - c.tx) * k, ty: c.ty + (g.ty - c.ty) * k, tz: c.tz + (g.tz - c.tz) * k,
          distance: c.distance + (g.distance - c.distance) * k};
        moved = true;
      }
      if (p.rotate && !p.reduced && !dragging && now - s.touched > 2500) { s.camera = {...s.camera, yaw: s.camera.yaw + dt * 0.07}; moved = true; }
      if ((moved || s.dirty) && layout && (!p.reduced || layout.settled)) { draw(ctx!, dpr); s.dirty = false; }
      raf = requestAnimationFrame(loop);
    };

    const draw = (ctx: CanvasRenderingContext2D, dpr: number) => {
      const p = props.current, layout = s.layout!, {graph} = p, pos = layout.pos, {w, h} = s.size;
      const n = graph.nodes.length;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.clearRect(0, 0, w, h);
      const project = projector(s.camera, w, h, p.inset, p.bottom);
      // Where every node lands.
      const sx = new Float32Array(n), sy = new Float32Array(n), sd = new Float32Array(n), ss = new Float32Array(n);
      const shown: number[] = [];
      let dmin = Infinity, dmax = -Infinity, cx = 0, cy = 0, cz = 0, low = Infinity;
      for (let i = 0; i < n; i++) {
        const q = project(pos[i * 3], pos[i * 3 + 1], pos[i * 3 + 2]);
        sx[i] = q.x; sy[i] = q.y; sd[i] = q.depth; ss[i] = q.scale;
        cx += pos[i * 3] / n; cy += pos[i * 3 + 1] / n; cz += pos[i * 3 + 2] / n; low = Math.min(low, pos[i * 3 + 1]);
        if (!nodeShown(graph.nodes[i], p.layers) || q.depth < NEAR) continue;
        shown.push(i);
        dmin = Math.min(dmin, q.depth); dmax = Math.max(dmax, q.depth);
      }
      const fog = (d: number) => (dmax > dmin ? Math.min(2, Math.floor(((d - dmin) / (dmax - dmin)) * 3)) : 0);

      // The ground: rings and spokes under the graph, for depth.
      let radius = 0;
      for (let i = 0; i < n; i++) radius = Math.max(radius, Math.hypot(pos[i * 3] - cx, pos[i * 3 + 2] - cz));
      const ground = low - 40;
      ctx.strokeStyle = GRID; ctx.lineWidth = 1; ctx.globalAlpha = 1; ctx.setLineDash([]);
      ctx.beginPath();
      for (const share of [0.25, 0.5, 0.75, 1]) {
        let pen = false;
        for (let k = 0; k <= 72; k++) {
          const a = (k / 72) * Math.PI * 2, q = project(cx + Math.cos(a) * radius * share, ground, cz + Math.sin(a) * radius * share);
          if (q.depth < NEAR) { pen = false; continue; }
          if (pen) ctx.lineTo(q.x, q.y); else ctx.moveTo(q.x, q.y);
          pen = true;
        }
      }
      for (let k = 0; k < 12; k++) {
        const a = (k / 12) * Math.PI * 2, q0 = project(cx, ground, cz), q1 = project(cx + Math.cos(a) * radius, ground, cz + Math.sin(a) * radius);
        if (q0.depth < NEAR || q1.depth < NEAR) continue;
        ctx.moveTo(q0.x, q0.y); ctx.lineTo(q1.x, q1.y);
      }
      ctx.stroke();

      // Edges, one stroke per colour, weight and fade.
      const chosen = p.selected ? graph.byKey.get(p.selected)?.i ?? null : null;
      const buckets = new Map<string, {color: string; alpha: number; width: number; dash: number[]; segments: number[]}>();
      for (const edge of graph.edges) {
        if (!edgeShown(graph, edge, p.layers) || sd[edge.a] < NEAR || sd[edge.b] < NEAR) continue;
        const style = EDGE_STYLE[edge.kind];
        const on = !p.lit || (p.lit.has(edge.a) && p.lit.has(edge.b));
        const picked = chosen !== null && (edge.a === chosen || edge.b === chosen);
        const level = fog((sd[edge.a] + sd[edge.b]) / 2);
        const alpha = picked ? Math.min(0.95, style.alpha * 2 + 0.3) : style.alpha * FOG[level] * (on ? (p.lit ? 1.7 : 1) : 0.1);
        const width = style.width * (picked ? 1.7 : 1);
        const color = edgeColor(graph, edge);
        const key = `${color}|${alpha.toFixed(3)}|${width}|${edge.kind === 'documents' ? 1 : 0}`;
        let bucket = buckets.get(key);
        if (!bucket) buckets.set(key, bucket = {color, alpha, width, dash: style.dash ?? [], segments: []});
        bucket.segments.push(sx[edge.a], sy[edge.a], sx[edge.b], sy[edge.b]);
      }
      ctx.lineCap = 'round';
      for (const bucket of buckets.values()) {
        ctx.strokeStyle = bucket.color; ctx.globalAlpha = Math.min(1, bucket.alpha); ctx.lineWidth = bucket.width; ctx.setLineDash(bucket.dash);
        ctx.beginPath();
        for (let k = 0; k < bucket.segments.length; k += 4) { ctx.moveTo(bucket.segments[k], bucket.segments[k + 1]); ctx.lineTo(bucket.segments[k + 2], bucket.segments[k + 3]); }
        ctx.stroke();
      }
      ctx.setLineDash([]);

      // Nodes, back to front.
      shown.sort((a, b) => sd[b] - sd[a]);
      const hoveredAt = p.hovered ? graph.byKey.get(p.hovered)?.i ?? null : null;
      const points: typeof s.points = [];
      for (const i of shown) {
        const node = graph.nodes[i];
        const r = Math.max(0.7, Math.min(26, node.size * ss[i]));
        const on = !p.lit || p.lit.has(i);
        const fade = FOG[fog(sd[i])];
        ctx.globalAlpha = (on ? 1 : 0.14) * (node.kind === 'term' || node.kind === 'tag' ? 0.75 : 1) * (0.55 + 0.45 * fade);
        if (node.kind === 'root') {
          ctx.strokeStyle = node.color; ctx.lineWidth = 1.6;
          ctx.beginPath(); ctx.arc(sx[i], sy[i], r * 1.4, 0, Math.PI * 2); ctx.stroke();
          ctx.fillStyle = node.color; ctx.beginPath(); ctx.arc(sx[i], sy[i], r * 0.45, 0, Math.PI * 2); ctx.fill();
        } else {
          ctx.fillStyle = node.color;
          shape(ctx, node, sx[i], sy[i], r);
          ctx.fill();
          if (r > 2.2) { ctx.strokeStyle = SURFACE; ctx.lineWidth = 1; ctx.stroke(); }
          if (node.kind === 'area') {
            ctx.strokeStyle = node.color; ctx.lineWidth = 1; ctx.globalAlpha *= 0.55;
            ctx.beginPath(); ctx.arc(sx[i], sy[i], r * 1.7, 0, Math.PI * 2); ctx.stroke();
          }
          if (node.note && node.note.stage !== 'DRAFT' && r > 1.6) {
            ctx.strokeStyle = node.note.stage === 'SIGNED' ? INK.primary : INK.muted; ctx.lineWidth = 1;
            ctx.beginPath(); ctx.arc(sx[i], sy[i], r + 1.6, 0, Math.PI * 2); ctx.stroke();
          }
        }
        if (i === chosen || i === hoveredAt) {
          ctx.globalAlpha = 1; ctx.strokeStyle = INK.primary; ctx.lineWidth = i === chosen ? 2 : 1.4;
          ctx.beginPath(); ctx.arc(sx[i], sy[i], r + 4, 0, Math.PI * 2); ctx.stroke();
        }
        points.push({i, x: sx[i], y: sy[i], r, depth: sd[i]});
      }
      s.points = points;

      // Labels: the hubs always; the picked point, what it joins, the points a step names, the biggest notes otherwise.
      const wanted = new Map<number, number>();
      const want = (i: number, priority: number) => { if (sd[i] >= NEAR && nodeShown(graph.nodes[i], p.layers)) wanted.set(i, Math.max(wanted.get(i) ?? 0, priority)); };
      for (const node of graph.nodes) {
        if (node.kind === 'root') want(node.i, 95);
        else if (node.kind === 'area') want(node.i, 90);
        else if (node.kind === 'news') want(node.i, 92);
        else if (node.kind === 'system') want(node.i, 80);
      }
      if (chosen !== null) { want(chosen, 100); graph.neighbors[chosen].slice(0, 40).forEach(j => want(j, 70)); }
      if (hoveredAt !== null) want(hoveredAt, 99);
      p.labelled.forEach(i => want(i, 75));
      const big = graph.nodes.filter(node => node.kind === 'note' && (!p.lit || p.lit.has(node.i))).sort((a, b) => b.size - a.size).slice(0, p.lit ? 12 : 16);
      big.forEach(node => want(node.i, p.lit ? 60 : 40));
      const placed: number[][] = [];
      const order = [...wanted].sort((a, b) => b[1] - a[1] || sd[a[0]] - sd[b[0]]);
      ctx.lineJoin = 'round';
      for (const [i, priority] of order) {
        const node = graph.nodes[i];
        const hub = node.kind === 'area' || node.kind === 'root' || node.kind === 'news' || node.kind === 'system';
        ctx.font = hub ? '600 12.5px Inter, system-ui, sans-serif' : '11.5px Inter, system-ui, sans-serif';
        const text = node.label.length > 48 ? `${node.label.slice(0, 46)}…` : node.label;
        const width = ctx.measureText(text).width, r = Math.max(0.7, Math.min(26, node.size * ss[i]));
        const gap = r + (node.kind === 'area' ? r * 0.8 + 4 : 5), y = sy[i];
        // To the right of the point, or to its left where the right edge would cut it.
        const x = sx[i] + gap + width > w - 4 ? sx[i] - gap - width : sx[i] + gap;
        const box = [x - 2, y - 8, x + width + 2, y + 8];
        if (box[0] < p.inset || box[1] < 2 || box[3] > h - p.bottom - 2) continue;
        if (priority < 95 && placed.some(b => b[0] < box[2] && box[0] < b[2] && b[1] < box[3] && box[1] < b[3])) continue;
        placed.push(box);
        const on = !p.lit || p.lit.has(i) || i === chosen;
        ctx.globalAlpha = on ? 1 : 0.4;
        ctx.textBaseline = 'middle';
        ctx.lineWidth = 3.5; ctx.strokeStyle = SURFACE; ctx.strokeText(text, x, y);
        ctx.fillStyle = hub || priority >= 99 ? INK.primary : INK.secondary;
        ctx.fillText(text, x, y);
      }

      // The axis triad, bottom right, for orientation.
      const ox = w - 36, oy = h - p.bottom - 34, cyaw = Math.cos(s.camera.yaw), syaw = Math.sin(s.camera.yaw);
      const cp = Math.cos(s.camera.pitch), sp = Math.sin(s.camera.pitch);
      ctx.globalAlpha = 0.9; ctx.lineWidth = 1.5; ctx.font = '600 10px Inter, system-ui, sans-serif';
      for (const [name, [ux, uy, uz], color] of AXES) {
        const x1 = cyaw * ux - syaw * uz, z1 = syaw * ux + cyaw * uz, y2 = cp * uy - sp * z1;
        ctx.strokeStyle = color; ctx.fillStyle = color;
        ctx.beginPath(); ctx.moveTo(ox, oy); ctx.lineTo(ox + x1 * 18, oy - y2 * 18); ctx.stroke();
        ctx.fillText(name, ox + x1 * 25 - 3, oy - y2 * 25);
      }
      ctx.globalAlpha = 1;
    };

    // Pointer: drag to turn, wheel to zoom, hover to report, click to pick, double click to frame again.
    let dragging = false, downX = 0, downY = 0, lastX = 0, lastY = 0, travelled = 0;
    const at = (e: PointerEvent | MouseEvent) => {
      const box = el.getBoundingClientRect();
      const found = nearest(s.points, e.clientX - box.left, e.clientY - box.top);
      return found === null ? null : props.current.graph.nodes[found];
    };
    const down = (e: PointerEvent) => {
      dragging = true; downX = lastX = e.clientX; downY = lastY = e.clientY; travelled = 0;
      el.setPointerCapture?.(e.pointerId);
    };
    const move = (e: PointerEvent) => {
      if (dragging) {
        const dx = e.clientX - lastX, dy = e.clientY - lastY;
        lastX = e.clientX; lastY = e.clientY; travelled = Math.max(travelled, Math.hypot(e.clientX - downX, e.clientY - downY));
        if (travelled > 4) {
          s.camera = {...s.camera, yaw: s.camera.yaw + dx * 0.006, pitch: Math.max(-1.45, Math.min(1.45, s.camera.pitch + dy * 0.006))};
          s.touched = performance.now(); s.dirty = true;
        }
        return;
      }
      const node = at(e);
      if ((node?.i ?? null) !== s.hover) { s.hover = node?.i ?? null; props.current.onHover(node); }
    };
    const up = (e: PointerEvent) => {
      if (!dragging) return;
      dragging = false;
      if (travelled <= 4) props.current.onPick(at(e));
    };
    const leave = () => { if (s.hover !== null) { s.hover = null; props.current.onHover(null); } };
    const wheel = (e: WheelEvent) => {
      e.preventDefault();
      const factor = Math.exp(Math.max(-0.5, Math.min(0.5, e.deltaY * 0.0012)));
      s.goal = {...s.goal, distance: s.goal.distance * factor};
      s.camera = {...s.camera, distance: s.camera.distance * factor};
      s.steered = true; s.touched = performance.now(); s.dirty = true;
    };
    const twice = () => control?.current?.reset();
    el.addEventListener('pointerdown', down);
    el.addEventListener('pointermove', move);
    el.addEventListener('pointerup', up);
    el.addEventListener('pointerleave', leave);
    el.addEventListener('wheel', wheel, {passive: false});
    el.addEventListener('dblclick', twice);
    raf = requestAnimationFrame(loop);
    return () => {
      cancelAnimationFrame(raf);
      observer?.disconnect();
      el.removeEventListener('pointerdown', down);
      el.removeEventListener('pointermove', move);
      el.removeEventListener('pointerup', up);
      el.removeEventListener('pointerleave', leave);
      el.removeEventListener('wheel', wheel);
      el.removeEventListener('dblclick', twice);
    };
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const notes = graph.nodes.filter(n => n.kind === 'note').length;
  return (
    <canvas ref={canvas} className="absolute inset-0 block h-full w-full cursor-grab touch-none active:cursor-grabbing" data-testid="brain-canvas" role="img"
      aria-label={`Knowledge graph in 3D: ${graph.nodes.length} points (${notes} notes) joined by ${graph.edges.length} edges. Drag to turn, scroll to zoom.`} />
  );
}

function aspect(size: {w: number; h: number}, inset: number, bottom: number): number {
  return size.h > bottom ? Math.max(0.3, (size.w - inset) / (size.h - bottom)) : 1;
}
