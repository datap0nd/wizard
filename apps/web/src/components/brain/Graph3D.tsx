import {useEffect, useRef} from 'react';
import {edgeShown, FOV, frame, INK, Layout, nearest, nodeShown, projector, SURFACE, type Camera, type Graph, type GNode, type LayerId} from '@/graph3d';

export interface GraphControl { zoom: (factor: number) => void; reset: () => void }

const isJsdom = typeof navigator !== 'undefined' && /jsdom/i.test(navigator.userAgent);
const START_3D = {yaw: 0.65, pitch: 0.38};
const NEAR = 8;
const FOG = [1, 0.8, 0.6];

/**
 * The knowledge graph on a plain canvas, drawn the way graphify draws one: small points sized by their links, thin
 * slightly curved edges in the colour of the hub they leave, no labels until a point is pointed at or picked (or the
 * tour names it). In 3D (the default) the graph turns slowly by itself and a drag turns it; in 2D a drag pans and the
 * wheel zooms at the pointer. The layout settles a few ticks per frame (graph3d.ts, Layout); a double click frames it again.
 */
export function Graph3D({graph, layers, visible, colors, lit, frameOn, frameKey, selected, hovered, labelled, hubs, dims, reduced, rotate,
  inset, bottom, control, onHover, onPick, onProgress}: {
  graph: Graph; layers: ReadonlySet<LayerId>; visible: Uint8Array; colors: string[]; lit: Set<number> | null; frameOn: number[] | null;
  frameKey: string; selected: string | null; hovered: string | null; labelled: Set<number>; hubs: boolean; dims: 2 | 3; reduced: boolean;
  rotate: boolean; inset: number; bottom: number; control?: {current: GraphControl | null};
  onHover: (node: GNode | null) => void; onPick: (node: GNode | null) => void; onProgress?: (settled: boolean, ticks: number) => void;
}) {
  const canvas = useRef<HTMLCanvasElement>(null);
  const live = {graph, layers, visible, colors, lit, frameOn, selected, hovered, labelled, hubs, dims, reduced, rotate, inset, bottom, onHover, onPick, onProgress};
  const props = useRef(live);
  props.current = live;
  const state = useRef<{layouts: Partial<Record<2 | 3, Layout>>; layout: Layout | null; ticks: number; camera: Camera;
    goal: Pick<Camera, 'tx' | 'ty' | 'tz' | 'distance'>; steered: boolean; touched: number; dirty: boolean; size: {w: number; h: number};
    points: {i: number; x: number; y: number; r: number; depth: number}[]; hover: number | null}>({
    layouts: {}, layout: null, ticks: 0, camera: {yaw: 0, pitch: 0, distance: 600, tx: 0, ty: 0, tz: 0}, goal: {tx: 0, ty: 0, tz: 0, distance: 600},
    steered: false, touched: 0, dirty: true, size: {w: 0, h: 0}, points: [], hover: null,
  });
  const fit = () => {
    const s = state.current, p = props.current;
    if (!s.layout) return;
    const shown = p.frameOn ?? p.graph.nodes.filter(n => p.visible[n.i] && nodeShown(n, p.layers)).map(n => n.i);
    s.goal = frame(s.layout.pos, shown.length ? shown : p.graph.nodes.map(n => n.i), aspect(s.size, p.inset, p.bottom), p.dims === 3 ? 0.78 : 1.06);
  };

  // A new graph keeps the places of the points it shares with the one before; 2D and 3D each have their own layout.
  useEffect(() => {
    const s = state.current;
    for (const d of [2, 3] as const) {
      const old = s.layouts[d];
      s.layouts[d] = old || d === dims ? new Layout(graph, 7, old ? {graph: old.graph, pos: old.pos, alpha: old.alpha} : undefined, d) : undefined;
    }
    s.layout = s.layouts[dims]!; s.ticks = 0; s.dirty = true;
  }, [graph]); // eslint-disable-line react-hooks/exhaustive-deps

  // 2D faces the graph; 3D starts from an angle.
  useEffect(() => {
    const s = state.current;
    s.layout = s.layouts[dims] ??= new Layout(graph, 7, undefined, dims);
    s.camera = {...s.camera, ...(dims === 2 ? {yaw: 0, pitch: 0} : START_3D)};
    s.steered = false; s.ticks = 0; s.dirty = true;
    fit();
  }, [dims]); // eslint-disable-line react-hooks/exhaustive-deps

  // A new focus: frame it (the person's own zoom and moves are kept until then).
  useEffect(() => { state.current.steered = false; fit(); state.current.dirty = true; }, [frameKey]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { state.current.dirty = true; }, [layers, visible, colors, lit, selected, hovered, labelled, hubs, inset, bottom, rotate]);

  useEffect(() => {
    if (!control) return;
    control.current = {
      zoom: factor => {
        const s = state.current;
        s.goal = {...s.goal, distance: s.goal.distance * factor}; s.steered = true; s.touched = performance.now(); s.dirty = true;
      },
      reset: () => {
        const s = state.current;
        s.camera = {...s.camera, ...(props.current.dims === 2 ? {yaw: 0, pitch: 0} : START_3D)}; s.steered = false; s.dirty = true;
        fit();
      },
    };
    return () => { control.current = null; };
  }, [control]); // eslint-disable-line react-hooks/exhaustive-deps

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

    let raf = 0, last = performance.now(), first = true, dragging = false;
    const loop = (now: number) => {
      const p = props.current, layout = s.layout;
      const dt = Math.min(0.05, (now - last) / 1000);
      last = now;
      let moved = false;
      if (layout && !layout.settled) {
        const started = performance.now(), budget = first ? 140 : 9;
        do { layout.tick(); s.ticks++; } while (!layout.settled && performance.now() - started < budget);
        first = false; moved = true;
        if (!s.steered) fit();  // while it settles, keep it framed (unless the person has taken the camera)
        p.onProgress?.(layout.settled, s.ticks);
      }
      const c = s.camera, g = s.goal, k = p.reduced ? 1 : 1 - Math.exp(-dt * 3.2);
      const far = Math.abs(c.tx - g.tx) + Math.abs(c.ty - g.ty) + Math.abs(c.tz - g.tz) + Math.abs(c.distance - g.distance);
      if (far > 0.05) {
        s.camera = {...c, tx: c.tx + (g.tx - c.tx) * k, ty: c.ty + (g.ty - c.ty) * k, tz: c.tz + (g.tz - c.tz) * k,
          distance: c.distance + (g.distance - c.distance) * k};
        moved = true;
      }
      if (p.dims === 3 && p.rotate && !p.reduced && !dragging && now - s.touched > 2500) { s.camera = {...s.camera, yaw: s.camera.yaw + dt * 0.1}; moved = true; }
      if ((moved || s.dirty) && layout && (!p.reduced || layout.settled)) { draw(ctx!); s.dirty = false; }
      raf = requestAnimationFrame(loop);
    };

    const draw = (ctx: CanvasRenderingContext2D) => {
      const p = props.current, layout = s.layout!, {graph, colors} = p, pos = layout.pos, {w, h} = s.size;
      const n = graph.nodes.length;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.clearRect(0, 0, w, h);
      const project = projector(s.camera, w, h, p.inset, p.bottom);
      const sx = new Float32Array(n), sy = new Float32Array(n), sd = new Float32Array(n), ss = new Float32Array(n);
      const on = new Uint8Array(n);
      let dmin = Infinity, dmax = -Infinity;
      for (let i = 0; i < n; i++) {
        const q = project(pos[i * 3], pos[i * 3 + 1], pos[i * 3 + 2]);
        sx[i] = q.x; sy[i] = q.y; sd[i] = q.depth; ss[i] = q.scale;
        if (!p.visible[i] || !nodeShown(graph.nodes[i], p.layers) || q.depth < NEAR) continue;
        on[i] = 1;
        dmin = Math.min(dmin, q.depth); dmax = Math.max(dmax, q.depth);
      }
      const fog = (d: number) => (p.dims === 3 && dmax > dmin ? Math.min(2, Math.floor(((d - dmin) / (dmax - dmin)) * 3)) : 0);
      const radius = (i: number) => Math.max(1.2, Math.min(14, graph.nodes[i].size * ss[i]));
      const chosen = p.selected ? graph.byKey.get(p.selected)?.i ?? null : null;
      const pointed = p.hovered ? graph.byKey.get(p.hovered)?.i ?? null : null;

      // Edges, slightly curved, in the colour of the hub they leave; one stroke per colour and strength.
      const buckets = new Map<string, {color: string; alpha: number; width: number; path: number[]}>();
      for (const edge of graph.edges) {
        const {a, b} = edge;
        if (!on[a] || !on[b] || !edgeShown(graph, edge, p.layers)) continue;
        const hub = graph.nodes[a].size >= graph.nodes[b].size ? a : b;
        const picked = chosen !== null && (a === chosen || b === chosen);
        const inside = !p.lit || (p.lit.has(a) && p.lit.has(b));
        const alpha = picked ? 0.85 : (inside ? (p.lit ? 0.6 : 0.38) : 0.05) * FOG[fog((sd[a] + sd[b]) / 2)];
        const width = picked ? 1.3 : 0.8;
        const color = colors[hub];
        const key = `${color}|${alpha.toFixed(3)}|${width}`;
        let bucket = buckets.get(key);
        if (!bucket) buckets.set(key, bucket = {color, alpha, width, path: []});
        const dx = sx[b] - sx[a], dy = sy[b] - sy[a];
        bucket.path.push(sx[a], sy[a], (sx[a] + sx[b]) / 2 - dy * 0.08, (sy[a] + sy[b]) / 2 + dx * 0.08, sx[b], sy[b]);
      }
      ctx.lineCap = 'round';
      for (const bucket of buckets.values()) {
        ctx.strokeStyle = bucket.color; ctx.globalAlpha = bucket.alpha; ctx.lineWidth = bucket.width;
        ctx.beginPath();
        const d = bucket.path;
        for (let k = 0; k < d.length; k += 6) { ctx.moveTo(d[k], d[k + 1]); ctx.quadraticCurveTo(d[k + 2], d[k + 3], d[k + 4], d[k + 5]); }
        ctx.stroke();
      }

      // Points: small first so hubs sit on top in 2D; back to front in 3D.
      const order: number[] = [];
      for (let i = 0; i < n; i++) if (on[i]) order.push(i);
      if (p.dims === 3) order.sort((x, y) => sd[y] - sd[x]); else order.sort((x, y) => graph.nodes[x].size - graph.nodes[y].size);
      const points: typeof s.points = [];
      for (const i of order) {
        const r = radius(i);
        const inside = !p.lit || p.lit.has(i);
        ctx.globalAlpha = (inside ? 1 : 0.13) * (0.5 + 0.5 * FOG[fog(sd[i])]);
        ctx.fillStyle = colors[i];
        ctx.beginPath(); ctx.arc(sx[i], sy[i], r, 0, Math.PI * 2); ctx.fill();
        if (r > 3.5) { ctx.strokeStyle = SURFACE; ctx.lineWidth = 0.75; ctx.globalAlpha *= 0.7; ctx.stroke(); }
        if (i === chosen || i === pointed) {
          ctx.globalAlpha = 1; ctx.strokeStyle = INK.primary; ctx.lineWidth = i === chosen ? 1.8 : 1.3;
          ctx.beginPath(); ctx.arc(sx[i], sy[i], r + 3, 0, Math.PI * 2); ctx.stroke();
        }
        points.push({i, x: sx[i], y: sy[i], r, depth: sd[i]});
      }
      s.points = points;

      // Labels only where they are asked for: the picked point and what it joins, the point under the pointer, the
      // points a tour step names, and (with Labels on) each community's hub and the most linked points.
      const wanted = new Map<number, number>();
      const want = (i: number, priority: number) => { if (on[i]) wanted.set(i, Math.max(wanted.get(i) ?? 0, priority)); };
      if (chosen !== null) { want(chosen, 100); graph.neighbors[chosen].slice(0, 40).forEach(j => want(j, 70)); }
      if (pointed !== null) want(pointed, 99);
      p.labelled.forEach(i => want(i, 80));
      if (p.hubs) {
        graph.communities.forEach(c => { if (!c.alone) want(c.hub, 60); });
        [...graph.nodes].sort((x, y) => y.size - x.size).slice(0, 24).forEach(node => want(node.i, 40));
      }
      const placed: number[][] = [];
      ctx.lineJoin = 'round'; ctx.textBaseline = 'middle';
      for (const [i, priority] of [...wanted].sort((x, y) => y[1] - x[1] || sd[x[0]] - sd[y[0]])) {
        const node = graph.nodes[i];
        ctx.font = priority >= 99 ? '600 12px Inter, system-ui, sans-serif' : '11px Inter, system-ui, sans-serif';
        const text = node.label.length > 48 ? `${node.label.slice(0, 46)}…` : node.label;
        const width = ctx.measureText(text).width, gap = radius(i) + 5, y = sy[i];
        const x = sx[i] + gap + width > w - 4 ? sx[i] - gap - width : sx[i] + gap;  // flipped left at the right edge
        const box = [x - 2, y - 8, x + width + 2, y + 8];
        if (box[0] < p.inset || box[1] < 2 || box[3] > h - p.bottom - 2) continue;
        if (priority < 99 && placed.some(b => b[0] < box[2] && box[0] < b[2] && b[1] < box[3] && box[1] < b[3])) continue;
        placed.push(box);
        ctx.globalAlpha = !p.lit || p.lit.has(i) || i === chosen ? 1 : 0.4;
        ctx.lineWidth = 3.5; ctx.strokeStyle = SURFACE; ctx.strokeText(text, x, y);
        ctx.fillStyle = priority >= 70 ? INK.primary : INK.secondary;
        ctx.fillText(text, x, y);
      }
      ctx.globalAlpha = 1;
    };

    // Pointer: drag to pan (2D) or turn (3D), wheel to zoom, hover to report, click to pick, double click to frame.
    let downX = 0, downY = 0, lastX = 0, lastY = 0, travelled = 0;
    const at = (e: PointerEvent | MouseEvent) => {
      const box = el.getBoundingClientRect();
      const found = nearest(s.points, e.clientX - box.left, e.clientY - box.top);
      return found === null ? null : props.current.graph.nodes[found];
    };
    const scale = () => ((s.size.h - props.current.bottom) / 2) / Math.tan(FOV / 2) / s.camera.distance;
    const down = (e: PointerEvent) => {
      dragging = true; downX = lastX = e.clientX; downY = lastY = e.clientY; travelled = 0;
      el.setPointerCapture?.(e.pointerId);
    };
    const move = (e: PointerEvent) => {
      if (dragging) {
        const dx = e.clientX - lastX, dy = e.clientY - lastY;
        lastX = e.clientX; lastY = e.clientY; travelled = Math.max(travelled, Math.hypot(e.clientX - downX, e.clientY - downY));
        if (travelled > 4) {
          if (props.current.dims === 2) {
            const f = scale();
            s.camera = {...s.camera, tx: s.camera.tx - dx / f, ty: s.camera.ty + dy / f};
            s.goal = {...s.goal, tx: s.camera.tx, ty: s.camera.ty};
          } else {
            s.camera = {...s.camera, yaw: s.camera.yaw + dx * 0.006, pitch: Math.max(-1.45, Math.min(1.45, s.camera.pitch + dy * 0.006))};
          }
          s.steered = true; s.touched = performance.now(); s.dirty = true;
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
      const p = props.current;
      if (p.dims === 2) {
        // Zoom at the pointer: the point under it stays under it.
        const box = el.getBoundingClientRect(), f = scale();
        const ox = e.clientX - box.left - (s.size.w + p.inset) / 2, oy = e.clientY - box.top - (s.size.h - p.bottom) / 2;
        const wx = s.camera.tx + ox / f, wy = s.camera.ty - oy / f, f2 = f / factor;
        s.camera = {...s.camera, distance: s.camera.distance * factor, tx: wx - ox / f2, ty: wy + oy / f2};
        s.goal = {tx: s.camera.tx, ty: s.camera.ty, tz: s.camera.tz, distance: s.camera.distance};
      } else {
        s.goal = {...s.goal, distance: s.goal.distance * factor};
        s.camera = {...s.camera, distance: s.camera.distance * factor};
      }
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
      aria-label={`Knowledge graph in ${dims}D: ${graph.nodes.length} points (${notes} notes) in ${graph.communities.length} communities, joined by ${graph.edges.length} edges. ${dims === 2 ? 'Drag to move' : 'Drag to turn'}, scroll to zoom.`} />
  );
}

function aspect(size: {w: number; h: number}, inset: number, bottom: number): number {
  return size.h > bottom ? Math.max(0.3, (size.w - inset) / (size.h - bottom)) : 1;
}
