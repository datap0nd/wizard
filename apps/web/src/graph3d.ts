// The knowledge base as a 3D graph (/brain): what is drawn, where it sits, how the camera sees it, and the network's
// statistics. Pure functions over what the server read (brain.ts types), so the layout, the projection and every number
// on the page are tested without a canvas. Nothing here is invented: a node is a note, an area, a tag on two or more
// notes, a glossary term, a system or a news category; an edge is a link the server found.
import {NEWS, ringSystems, type BrainMap, type BrainNews, type BrainNote, type BrainSystem, type Focus} from './brain';

/** The page's surface and inks (dark only: the page is made for a meeting-room screen). */
export const SURFACE = '#0c1016';
export const INK = {primary: '#f0efec', secondary: '#c3c2b7', muted: '#8a8f98'};
/** Area colours: the validated dark categorical palette (dataviz skill, checked against SURFACE), in the areas' own
 *  order. A ninth area and beyond take a neutral grey; every area is also labelled in the graph and in the legend. */
export const AREA_SLOTS = ['#3987e5', '#d95926', '#199e70', '#c98500', '#d55181', '#008300', '#9085e9', '#e66767'];
export const OTHER_AREA = '#8b93a1';
const TAG_COLOR = '#6e7681', SYSTEM_COLOR = '#e6edf3', NEWS_NODE_COLOR = '#c3c2b7', ROOT_COLOR = '#f0efec';
const COMMON_TAG = 60;    // a tag on more notes than this is not drawn: it says little about how they relate
const MAX_TAGS = 1500;

export type NodeKind = 'root' | 'area' | 'note' | 'tag' | 'term' | 'system' | 'news' | 'category';
export type EdgeKind = 'area' | 'member' | 'related' | 'mention' | 'shared' | 'tagged' | 'term' | 'documents' | 'news';
/** What the legend switches on and off. Areas and notes are always shown. */
export type LayerId = 'member' | 'related' | 'mention' | 'shared' | 'tags' | 'terms' | 'systems' | 'news';

export interface GNode {
  i: number; key: string; kind: NodeKind; label: string;
  group: string;        // area id for the root's areas, their notes and terms; 'tags', 'systems' or 'news' otherwise
  color: string; size: number; charge: number;
  note?: BrainNote; system?: BrainSystem; count?: number; area?: string;
}
export interface GEdge { a: number; b: number; kind: EdgeKind; weight: number }
export interface Graph {
  nodes: GNode[]; edges: GEdge[]; byKey: Map<string, GNode>;
  neighbors: number[][];      // node index -> neighbour indexes (each once)
  areaColors: Map<string, string>;
}

/** How each kind of edge looks and pulls. Membership pulls hardest, so each area forms its own module and the links
 *  between notes of different areas show as the long edges between modules. */
export const EDGE_STYLE: Record<EdgeKind, {layer: LayerId | null; alpha: number; width: number; length: number; strength: number; dash?: number[]}> = {
  area: {layer: null, alpha: 0.28, width: 1, length: 200, strength: 0.8},
  member: {layer: 'member', alpha: 0.06, width: 0.6, length: 22, strength: 1},
  related: {layer: 'related', alpha: 0.62, width: 1.2, length: 40, strength: 0.25},
  mention: {layer: 'mention', alpha: 0.3, width: 0.8, length: 50, strength: 0.06},
  shared: {layer: 'shared', alpha: 0.16, width: 0.6, length: 46, strength: 0.03},
  tagged: {layer: 'tags', alpha: 0.07, width: 0.5, length: 40, strength: 0.02},
  term: {layer: 'terms', alpha: 0.16, width: 0.5, length: 9, strength: 0.9},
  documents: {layer: 'systems', alpha: 0.32, width: 0.8, length: 64, strength: 0.05, dash: [3, 3]},
  news: {layer: 'news', alpha: 0.3, width: 0.7, length: 18, strength: 0.6},
};
const NODE_LAYER: Partial<Record<NodeKind, LayerId>> = {tag: 'tags', term: 'terms', system: 'systems', news: 'news', category: 'news'};
export const LAYERS: {id: LayerId; label: string; edge?: EdgeKind; nodes?: NodeKind}[] = [
  {id: 'related', label: 'Related (declared)', edge: 'related'},
  {id: 'mention', label: 'Mentions in the text', edge: 'mention'},
  {id: 'shared', label: 'Shared tags (2 or more)', edge: 'shared'},
  {id: 'member', label: 'Note to its area', edge: 'member'},
  {id: 'tags', label: 'Tags', nodes: 'tag'},
  {id: 'terms', label: 'Glossary terms', nodes: 'term'},
  {id: 'systems', label: 'Systems documented', nodes: 'system'},
  {id: 'news', label: 'Market news', nodes: 'category'},
];
export const DEFAULT_LAYERS: ReadonlySet<LayerId> = new Set<LayerId>(['related', 'mention', 'member', 'tags', 'terms', 'systems', 'news']);

export function nodeShown(node: GNode, layers: ReadonlySet<LayerId>): boolean {
  const layer = NODE_LAYER[node.kind];
  return !layer || layers.has(layer);
}
export function edgeShown(graph: Graph, edge: GEdge, layers: ReadonlySet<LayerId>): boolean {
  const layer = EDGE_STYLE[edge.kind].layer;
  return (!layer || layers.has(layer)) && nodeShown(graph.nodes[edge.a], layers) && nodeShown(graph.nodes[edge.b], layers);
}

/** The graph: the knowledge base at the root, its areas, their notes, the notes' links, the tags two or more notes share,
 *  the glossary terms, the systems the notes document, and the news categories (when the news was read). */
export function buildGraph(map: BrainMap, news: BrainNews | null): Graph {
  const nodes: GNode[] = [];
  const edges: GEdge[] = [];
  const byKey = new Map<string, GNode>();
  const add = (node: Omit<GNode, 'i'>): GNode => {
    const made = {...node, i: nodes.length};
    nodes.push(made); byKey.set(made.key, made);
    return made;
  };
  const join = (a: GNode | undefined, b: GNode | undefined, kind: EdgeKind, weight = 1) => {
    if (a && b && a !== b) edges.push({a: a.i, b: b.i, kind, weight});
  };
  const areas = map.areas.filter(a => map.notes.some(n => n.area === a.id));
  const areaColors = new Map(areas.map((a, k) => [a.id, AREA_SLOTS[k] ?? OTHER_AREA]));
  const colorOf = (area: string) => areaColors.get(area) ?? OTHER_AREA;

  const root = add({key: 'kb', kind: 'root', label: 'Knowledge base', group: 'kb', color: ROOT_COLOR, size: 7, charge: 4});
  for (const area of areas) {
    const hub = add({key: `area:${area.id}`, kind: 'area', label: area.name, group: area.id, color: colorOf(area.id), size: 6,
      charge: 3, area: area.id, count: area.notes});
    join(root, hub, 'area');
  }
  for (const note of map.notes) {
    const node = add({key: `note:${note.id}`, kind: 'note', label: note.title, group: note.area, color: colorOf(note.area), size: 2.4,
      charge: 1, note, area: note.area});
    join(byKey.get(`area:${note.area}`), node, 'member');
  }
  for (const link of map.links) join(byKey.get(`note:${link.source}`), byKey.get(`note:${link.target}`), link.kind, link.weight ?? 1);

  const tagged = new Map<string, GNode[]>();
  for (const note of map.notes) {
    for (const tag of new Set(note.tags.map(t => t.toLocaleLowerCase()))) tagged.set(tag, [...(tagged.get(tag) ?? []), byKey.get(`note:${note.id}`)!]);
  }
  const tags = [...tagged].filter(([, members]) => members.length > 1 && members.length <= COMMON_TAG)
    .sort((x, y) => y[1].length - x[1].length || x[0].localeCompare(y[0])).slice(0, MAX_TAGS);
  for (const [tag, members] of tags) {
    const node = add({key: `tag:${tag}`, kind: 'tag', label: `#${tag}`, group: 'tags', color: TAG_COLOR, size: 1.2 + Math.sqrt(members.length) * 0.35,
      charge: 0.6, count: members.length});
    for (const member of members) join(member, node, 'tagged');
  }
  for (const entry of map.terms ?? []) {
    const owner = byKey.get(`note:${entry.note}`);
    if (!owner || byKey.has(`term:${entry.note}:${entry.term}`)) continue;
    const node = add({key: `term:${entry.note}:${entry.term}`, kind: 'term', label: entry.term, group: owner.group, color: owner.color,
      size: 0.9, charge: 0.25, area: owner.area});
    join(owner, node, 'term');
  }
  const newsOk = news?.status === 'ok';
  for (const system of ringSystems(map)) {
    if (system.id === 'knowledge') continue;
    const documented = system.documented_by.map(id => byKey.get(`note:${id}`)).filter((n): n is GNode => !!n);
    if (!documented.length && !(newsOk && system.id === 'postgresql')) continue;
    const node = add({key: `system:${system.id}`, kind: 'system', label: system.name, group: 'systems', color: SYSTEM_COLOR, size: 4.2,
      charge: 2, system});
    for (const note of documented) join(node, note, 'documents');
  }
  if (newsOk) {
    const hub = add({key: NEWS, kind: 'news', label: 'Market news', group: NEWS, color: NEWS_NODE_COLOR, size: 5, charge: 2.5, count: news.total ?? 0});
    join(byKey.get('system:postgresql'), hub, 'news');
    const biggest = Math.max(1, ...(news.categories ?? []).map(c => c.count));
    for (const category of (news.categories ?? []).slice(0, 40)) {
      const node = add({key: `news:${category.name}`, kind: 'category', label: category.name, group: NEWS, color: NEWS_NODE_COLOR,
        size: 1.4 + 3.2 * Math.sqrt(category.count / biggest), charge: 0.8, count: category.count});
      join(hub, node, 'news');
    }
  }

  const sets = nodes.map(() => new Set<number>());
  for (const edge of edges) { sets[edge.a].add(edge.b); sets[edge.b].add(edge.a); }
  const neighbors = sets.map(set => [...set]);
  // A note's size grows with its links to other notes (its degree in the note network).
  const semantic = new Map<number, number>();
  for (const edge of edges) {
    if (edge.kind === 'related' || edge.kind === 'mention' || edge.kind === 'shared') {
      semantic.set(edge.a, (semantic.get(edge.a) ?? 0) + 1); semantic.set(edge.b, (semantic.get(edge.b) ?? 0) + 1);
    }
  }
  for (const node of nodes) if (node.kind === 'note') node.size = Math.min(8, 2 + Math.sqrt(semantic.get(node.i) ?? 0) * 0.9);
  return {nodes, edges, byKey, neighbors, areaColors};
}

// The layout: a 3D force simulation (springs along the edges, every node repelling every other through a Barnes-Hut
// octree, a weak pull to the middle), seeded so the same knowledge base always settles the same way.

function random(seed: number): () => number {  // mulberry32
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

const ALPHA_MIN = 0.002;
const ALPHA_DECAY = 1 - Math.pow(0.001, 1 / 280);
const VELOCITY_KEEP = 0.6;
const CHARGE = 34;
const THETA2 = 0.81;
const GRAVITY = 0.012;

/** An octree over the nodes for one tick: each cell holds its total charge and the charge-weighted centre. */
class Octree {
  child: Int32Array; leaf: Int32Array; next: Int32Array;
  cx: Float64Array; cy: Float64Array; cz: Float64Array; half: Float64Array;
  value: Float64Array; mx: Float64Array; my: Float64Array; mz: Float64Array;
  cells = 0;

  constructor(n: number) {
    const cap = n * 24 + 64;
    this.child = new Int32Array(cap * 8); this.leaf = new Int32Array(cap); this.next = new Int32Array(n);
    this.cx = new Float64Array(cap); this.cy = new Float64Array(cap); this.cz = new Float64Array(cap); this.half = new Float64Array(cap);
    this.value = new Float64Array(cap); this.mx = new Float64Array(cap); this.my = new Float64Array(cap); this.mz = new Float64Array(cap);
  }

  private cell(x: number, y: number, z: number, half: number): number {
    const c = this.cells++;
    this.child.fill(-1, c * 8, c * 8 + 8);
    this.leaf[c] = -1; this.cx[c] = x; this.cy[c] = y; this.cz[c] = z; this.half[c] = half;
    this.value[c] = 0; this.mx[c] = 0; this.my[c] = 0; this.mz[c] = 0;
    return c;
  }

  private descend(c: number, x: number, y: number, z: number): number {
    const o = (x >= this.cx[c] ? 1 : 0) | (y >= this.cy[c] ? 2 : 0) | (z >= this.cz[c] ? 4 : 0);
    let d = this.child[c * 8 + o];
    if (d < 0) {
      const h = this.half[c] / 2;
      d = this.cell(this.cx[c] + (o & 1 ? h : -h), this.cy[c] + (o & 2 ? h : -h), this.cz[c] + (o & 4 ? h : -h), h);
      this.child[c * 8 + o] = d;
    }
    return d;
  }

  build(pos: Float32Array, strength: Float64Array): void {
    const n = strength.length;
    let lo = Infinity, hi = -Infinity;
    for (let k = 0; k < n * 3; k++) { lo = Math.min(lo, pos[k]); hi = Math.max(hi, pos[k]); }
    const mid = (lo + hi) / 2;
    this.cells = 0;
    this.cell(mid, mid, mid, Math.max((hi - lo) / 2, 1) + 1);
    for (let i = 0; i < n; i++) {
      const x = pos[i * 3], y = pos[i * 3 + 1], z = pos[i * 3 + 2], s = strength[i];
      this.next[i] = -1;
      let c = 0;
      for (;;) {
        this.value[c] += s; this.mx[c] += s * x; this.my[c] += s * y; this.mz[c] += s * z;
        const held = this.leaf[c];
        if (held === -1) { this.leaf[c] = i; break; }  // an empty leaf (a cell with children holds -2)
        if (held >= 0) {
          if (this.half[c] < 1e-3 || this.cells + 2 >= this.leaf.length) { this.next[i] = held; this.leaf[c] = i; break; }
          // Split: the point held here moves one level down.
          this.leaf[c] = -2;
          const jx = pos[held * 3], jy = pos[held * 3 + 1], jz = pos[held * 3 + 2], js = strength[held];
          const d = this.descend(c, jx, jy, jz);
          this.value[d] += js; this.mx[d] += js * jx; this.my[d] += js * jy; this.mz[d] += js * jz;
          this.leaf[d] = held;
        }
        c = this.descend(c, x, y, z);
      }
    }
  }

  /** Push node i away from the others: exactly from nearby nodes, by the centre of a far cell's charge otherwise. */
  repel(i: number, pos: Float32Array, strength: Float64Array, vel: Float32Array, alpha: number, stack: Int32Array): void {
    const x = pos[i * 3], y = pos[i * 3 + 1], z = pos[i * 3 + 2];
    let top = 0, vx = 0, vy = 0, vz = 0;
    stack[top++] = 0;
    while (top) {
      const c = stack[--top];
      const value = this.value[c];
      if (value === 0) continue;
      if (this.leaf[c] === -2) {
        const dx = this.mx[c] / value - x, dy = this.my[c] / value - y, dz = this.mz[c] / value - z;
        const l = dx * dx + dy * dy + dz * dz, w = this.half[c] * 2;
        if (w * w / THETA2 < l) {
          const f = value * alpha / l;
          vx += dx * f; vy += dy * f; vz += dz * f;
          continue;
        }
        for (let o = 0; o < 8; o++) { const d = this.child[c * 8 + o]; if (d >= 0) stack[top++] = d; }
        continue;
      }
      for (let j = this.leaf[c]; j >= 0; j = this.next[j]) {
        if (j === i) continue;
        const dx = pos[j * 3] - x, dy = pos[j * 3 + 1] - y, dz = pos[j * 3 + 2] - z;
        let l = dx * dx + dy * dy + dz * dz;
        if (l < 1) l = Math.sqrt(l) || 1;
        const f = strength[j] * alpha / l;
        vx += dx * f; vy += dy * f; vz += dz * f;
      }
    }
    vel[i * 3] += vx; vel[i * 3 + 1] += vy; vel[i * 3 + 2] += vz;
  }
}

/** The simulation. `pos` holds x, y, z per node. Positions carried over from an earlier layout of the same knowledge base
 *  keep their place, so a refresh does not reshuffle the picture. */
export class Layout {
  readonly pos: Float32Array;
  private readonly vel: Float32Array;
  private readonly strength: Float64Array;
  private readonly tree: Octree;
  private readonly stack: Int32Array;
  private readonly bias: Float64Array;
  private readonly linkStrength: Float64Array;
  alpha = 1;

  constructor(readonly graph: Graph, seed = 7, previous?: {graph: Graph; pos: Float32Array; alpha?: number}) {
    const n = graph.nodes.length;
    this.pos = new Float32Array(n * 3);
    this.vel = new Float32Array(n * 3);
    this.strength = Float64Array.from(graph.nodes, node => -CHARGE * node.charge);
    this.tree = new Octree(Math.max(n, 1));
    this.stack = new Int32Array(n * 24 + 64);
    const degree = graph.neighbors.map(list => list.length || 1);
    this.bias = Float64Array.from(graph.edges, e => degree[e.a] / (degree[e.a] + degree[e.b]));
    this.linkStrength = Float64Array.from(graph.edges, e => EDGE_STYLE[e.kind].strength / Math.min(degree[e.a], degree[e.b]));
    const carried = this.place(seed, previous);
    // Settle what is new, moving the rest as little as it needs; a layout still settling carries on where it was.
    if (carried > 0) this.alpha = Math.max(0.08, 1 - carried, previous?.alpha ?? 0);
  }

  /** Starting places: areas spread over a sphere around the knowledge base, notes around their area, the rest beside
   *  what they join. Returns the share of nodes carried over from `previous`. */
  private place(seed: number, previous?: {graph: Graph; pos: Float32Array}): number {
    const rand = random(seed);
    const {nodes, neighbors} = this.graph;
    const set = new Uint8Array(nodes.length);
    let carried = 0;
    const put = (i: number, x: number, y: number, z: number) => { this.pos.set([x, y, z], i * 3); set[i] = 1; };
    const near = (i: number, spread: number) => {
      const placed = neighbors[i].filter(j => set[j]);
      const at = [0, 0, 0];
      for (const j of placed) for (let k = 0; k < 3; k++) at[k] += this.pos[j * 3 + k] / placed.length;
      put(i, at[0] + (rand() - 0.5) * spread, at[1] + (rand() - 0.5) * spread, at[2] + (rand() - 0.5) * spread);
    };
    if (previous) {
      for (const node of nodes) {
        const old = previous.graph.byKey.get(node.key);
        if (old) { put(node.i, previous.pos[old.i * 3], previous.pos[old.i * 3 + 1], previous.pos[old.i * 3 + 2]); carried++; }
      }
    }
    const hubs = nodes.filter(n => n.kind === 'area' && !set[n.i]);
    hubs.forEach((hub, k) => {
      const y = 1 - (2 * (k + 0.5)) / hubs.length, r = Math.sqrt(1 - y * y), a = k * Math.PI * (3 - Math.sqrt(5));
      put(hub.i, 150 * r * Math.cos(a), 150 * y, 150 * r * Math.sin(a));
    });
    const order: NodeKind[] = ['root', 'note', 'tag', 'term', 'system', 'news', 'category'];
    for (const kind of order) {
      for (const node of nodes) {
        if (set[node.i] || node.kind !== kind) continue;
        if (kind === 'root') put(node.i, 0, 0, 0);
        else if (neighbors[node.i].some(j => set[j])) near(node.i, kind === 'term' ? 12 : kind === 'note' ? 70 : 40);
        else put(node.i, (rand() - 0.5) * 300, (rand() - 0.5) * 300, (rand() - 0.5) * 300);
      }
    }
    return nodes.length ? carried / nodes.length : 0;
  }

  get settled(): boolean { return this.alpha < ALPHA_MIN; }

  tick(): void {
    const {pos, vel, graph} = this;
    const n = graph.nodes.length;
    if (!n) { this.alpha = 0; return; }
    this.alpha += -this.alpha * ALPHA_DECAY;
    const alpha = this.alpha;
    graph.edges.forEach((edge, k) => {
      const a = edge.a * 3, b = edge.b * 3;
      let dx = pos[b] + vel[b] - pos[a] - vel[a], dy = pos[b + 1] + vel[b + 1] - pos[a + 1] - vel[a + 1],
        dz = pos[b + 2] + vel[b + 2] - pos[a + 2] - vel[a + 2];
      const l0 = Math.hypot(dx, dy, dz) || 1e-3;
      const l = (l0 - EDGE_STYLE[edge.kind].length) / l0 * alpha * this.linkStrength[k];
      dx *= l; dy *= l; dz *= l;
      const bias = this.bias[k];
      vel[b] -= dx * bias; vel[b + 1] -= dy * bias; vel[b + 2] -= dz * bias;
      vel[a] += dx * (1 - bias); vel[a + 1] += dy * (1 - bias); vel[a + 2] += dz * (1 - bias);
    });
    this.tree.build(pos, this.strength);
    for (let i = 0; i < n; i++) this.tree.repel(i, pos, this.strength, vel, alpha, this.stack);
    for (let k = 0; k < n * 3; k++) {
      vel[k] = (vel[k] - pos[k] * GRAVITY * alpha) * VELOCITY_KEEP;
      pos[k] += vel[k];
    }
  }

  /** Run until settled or `ticks` have run; returns how many ran. */
  run(ticks: number): number {
    let ran = 0;
    while (ran < ticks && !this.settled) { this.tick(); ran++; }
    return ran;
  }
}

// The camera: it orbits a target point; yaw turns around the vertical axis, pitch tilts.

export interface Camera { yaw: number; pitch: number; distance: number; tx: number; ty: number; tz: number }
export const FOV = 0.9;
export interface Projected { x: number; y: number; depth: number; scale: number }

/** Where a point lands on a canvas `width` x `height`, in the part the panels leave free: `inset` on the left, `bottom`
 *  along the bottom. */
export function projector(camera: Camera, width: number, height: number, inset = 0, bottom = 0): (x: number, y: number, z: number) => Projected {
  const cy = Math.cos(camera.yaw), sy = Math.sin(camera.yaw), cp = Math.cos(camera.pitch), sp = Math.sin(camera.pitch);
  const focal = ((height - bottom) / 2) / Math.tan(FOV / 2), mx = (width + inset) / 2, my = (height - bottom) / 2;
  return (x, y, z) => {
    const px = x - camera.tx, py = y - camera.ty, pz = z - camera.tz;
    const x1 = cy * px - sy * pz, z1 = sy * px + cy * pz;
    const y2 = cp * py - sp * z1, z2 = sp * py + cp * z1;
    const depth = z2 + camera.distance, scale = focal / Math.max(depth, 1e-3);
    return {x: mx + x1 * scale, y: my - y2 * scale, depth, scale};
  };
}

/** The camera target and distance that frame these nodes (most of them: the farthest tenth may fall outside). */
export function frame(pos: Float32Array, indexes: number[], aspect = 1): Pick<Camera, 'tx' | 'ty' | 'tz' | 'distance'> {
  if (!indexes.length) return {tx: 0, ty: 0, tz: 0, distance: 400};
  const c = [0, 0, 0];
  for (const i of indexes) for (let k = 0; k < 3; k++) c[k] += pos[i * 3 + k] / indexes.length;
  const reach = indexes.map(i => Math.hypot(pos[i * 3] - c[0], pos[i * 3 + 1] - c[1], pos[i * 3 + 2] - c[2])).sort((a, b) => a - b);
  const radius = Math.max(24, reach[Math.min(reach.length - 1, Math.floor(reach.length * 0.92))]);
  const half = Math.min(FOV / 2, Math.atan(Math.tan(FOV / 2) * Math.max(aspect, 0.2)));
  return {tx: c[0], ty: c[1], tz: c[2], distance: radius / Math.sin(half) * 1.08};
}

/** The nodes a focus lights up, or null for all of them. */
export function focusNodes(graph: Graph, focus: Focus): Set<number> | null {
  if (focus.kind === 'all') return null;
  if (focus.kind === 'note') {
    const node = graph.byKey.get(focus.id);
    return node ? new Set([node.i, ...graph.neighbors[node.i]]) : null;
  }
  const lit = new Set<number>();
  if (focus.kind === 'systems') {
    for (const node of graph.nodes) if (node.kind === 'system') { lit.add(node.i); graph.neighbors[node.i].forEach(j => lit.add(j)); }
    return lit;
  }
  for (const node of graph.nodes) if (node.group === focus.id) lit.add(node.i);
  if (focus.id === NEWS) { const db = graph.byKey.get('system:postgresql'); if (db) lit.add(db.i); }
  return lit;
}

/** The node under the pointer: the nearest drawn point within reach of its edge, the front one on a tie. */
export function nearest(points: {i: number; x: number; y: number; r: number; depth: number}[], x: number, y: number, reach = 5): number | null {
  let best: number | null = null, score = Infinity;
  for (const p of points) {
    const gap = Math.hypot(p.x - x, p.y - y) - p.r;
    if (gap > reach) continue;
    const s = Math.max(gap, 0) * 1000 + p.depth;
    if (s < score) { score = s; best = p.i; }
  }
  return best;
}

const KIND_RANK: Record<NodeKind, number> = {note: 0, area: 1, term: 2, system: 3, tag: 4, category: 5, news: 6, root: 7};
/** Search the graph by name: exact names first, then names that start with the words, then names that contain them. */
export function search(graph: Graph, query: string, limit = 8): GNode[] {
  const q = query.trim().toLocaleLowerCase().replace(/^#/, '');
  if (!q) return [];
  const scored: [number, GNode][] = [];
  for (const node of graph.nodes) {
    const name = node.label.toLocaleLowerCase().replace(/^#/, '');
    const extra = node.note ? `${node.note.id} ${node.note.tags.join(' ')}`.toLocaleLowerCase() : '';
    const rank = name === q ? 0 : name.startsWith(q) ? 1 : name.includes(q) ? 2 : extra.includes(q) ? 3 : -1;
    if (rank >= 0) scored.push([rank * 10 + KIND_RANK[node.kind], node]);
  }
  return scored.sort((a, b) => a[0] - b[0] || a[1].label.localeCompare(b[1].label)).slice(0, limit).map(([, node]) => node);
}

// The network's statistics, over the note network: notes joined by related links, mentions and shared tags.

export interface NetworkStats {
  nodes: number; edges: number; byKind: Record<NodeKind, number>; byEdge: Record<EdgeKind, number>;
  notes: number; links: number; density: number; meanDegree: number; maxDegree: number; isolated: number;
  components: number; largest: number; clustering: number; modularity: number;
  pathLength: number | null; diameter: number | null; sampled: boolean;
  histogram: {label: string; from: number; to: number; count: number}[];
}

const NOTE_LINKS: ReadonlySet<EdgeKind> = new Set(['related', 'mention', 'shared']);

export function networkStats(graph: Graph): NetworkStats {
  const byKind = {root: 0, area: 0, note: 0, tag: 0, term: 0, system: 0, news: 0, category: 0} as Record<NodeKind, number>;
  const byEdge = {area: 0, member: 0, related: 0, mention: 0, shared: 0, tagged: 0, term: 0, documents: 0, news: 0} as Record<EdgeKind, number>;
  for (const node of graph.nodes) byKind[node.kind]++;
  for (const edge of graph.edges) byEdge[edge.kind]++;
  const notes = graph.nodes.filter(node => node.kind === 'note');
  const at = new Map(notes.map((node, k) => [node.i, k]));
  const adj = notes.map(() => new Set<number>());
  for (const edge of graph.edges) {
    if (!NOTE_LINKS.has(edge.kind)) continue;
    const a = at.get(edge.a), b = at.get(edge.b);
    if (a === undefined || b === undefined || a === b) continue;
    adj[a].add(b); adj[b].add(a);
  }
  const n = notes.length;
  const degrees = adj.map(set => set.size);
  const m = degrees.reduce((s, d) => s + d, 0) / 2;
  // Components.
  const component = new Int32Array(n).fill(-1);
  const sizes: number[] = [];
  for (let s = 0; s < n; s++) {
    if (component[s] >= 0) continue;
    const id = sizes.length, queue = [s];
    component[s] = id;
    for (let q = 0; q < queue.length; q++) for (const v of adj[queue[q]]) if (component[v] < 0) { component[v] = id; queue.push(v); }
    sizes.push(queue.length);
  }
  const big = sizes.length ? sizes.indexOf(Math.max(...sizes)) : -1;
  // Average local clustering (nodes with fewer than two neighbours count as 0, as in Watts and Strogatz).
  let clustering = 0;
  for (let v = 0; v < n; v++) {
    const list = [...adj[v]], k = list.length;
    if (k < 2) continue;
    let closed = 0;
    for (let x = 0; x < k; x++) for (let y = x + 1; y < k; y++) if (adj[list[x]].has(list[y])) closed++;
    clustering += closed / (k * (k - 1) / 2);
  }
  // Modularity of the areas as communities: Q = sum over areas of (inner links / m) - (area's degree / 2m)^2.
  let modularity = 0;
  if (m > 0) {
    const inner = new Map<string, number>(), total = new Map<string, number>();
    notes.forEach((node, v) => {
      total.set(node.group, (total.get(node.group) ?? 0) + degrees[v]);
      for (const u of adj[v]) if (u > v && notes[u].group === node.group) inner.set(node.group, (inner.get(node.group) ?? 0) + 1);
    });
    for (const [group, sum] of total) modularity += (inner.get(group) ?? 0) / m - (sum / (2 * m)) ** 2;
  }
  // Mean shortest path and diameter in the largest component (from every note, or from 200 when there are many).
  const members = big < 0 ? [] : [...Array(n).keys()].filter(v => component[v] === big);
  const sampled = members.length > 800;
  const sources = sampled ? members.filter((_, k) => k % Math.ceil(members.length / 200) === 0) : members;
  let paths = 0, pairs = 0, diameter = 0;
  const dist = new Int32Array(n);
  for (const s of sources) {
    dist.fill(-1); dist[s] = 0;
    const queue = [s];
    for (let q = 0; q < queue.length; q++) {
      const v = queue[q];
      for (const u of adj[v]) if (dist[u] < 0) { dist[u] = dist[v] + 1; paths += dist[u]; pairs++; diameter = Math.max(diameter, dist[u]); queue.push(u); }
    }
  }
  // Degree distribution in doubling bins: 0, 1, 2, 3-4, 5-8, ...
  const maxDegree = Math.max(0, ...degrees);
  const bins: NetworkStats['histogram'] = [0, 1, 2].map(d => ({label: `${d}`, from: d, to: d, count: 0}));
  for (let to = 4; bins[bins.length - 1].to < maxDegree; to *= 2) bins.push({label: `${to / 2 + 1}–${to}`, from: to / 2 + 1, to, count: 0});
  for (const d of degrees) { const bin = bins.find(b => d >= b.from && d <= b.to); if (bin) bin.count++; }
  return {
    nodes: graph.nodes.length, edges: graph.edges.length, byKind, byEdge,
    notes: n, links: m, density: n > 1 ? (2 * m) / (n * (n - 1)) : 0, meanDegree: n ? (2 * m) / n : 0, maxDegree,
    isolated: degrees.filter(d => d === 0).length, components: sizes.length, largest: n ? Math.max(0, ...sizes) / n : 0,
    clustering: n ? clustering / n : 0, modularity, pathLength: pairs ? paths / pairs : null, diameter: pairs ? diameter : null,
    sampled, histogram: bins,
  };
}
