// The knowledge base as a graph (/brain): what is drawn, the communities its links form, where each point sits (in 2D or
// 3D), how the camera sees it, and the network's statistics. Pure functions over what the server read (brain.ts types),
// so the layout, the communities, the projection and every number on the page are tested without a canvas. Nothing here
// is invented: a node is a note, a tag on two or more notes, a glossary term, a system or the news; an edge is a link the
// server found. The look follows graphify's knowledge graphs (owner, 30 Oct 2026: "was hoping it looked like this").
import {NEWS, ringSystems, type BrainMap, type BrainNews, type BrainNote, type BrainSystem, type Focus} from './brain';

/** The page's surface and inks (dark only: the page is made for a meeting-room screen). */
export const SURFACE = '#0f1117';
export const INK = {primary: '#f0efec', secondary: '#c3c2b7', muted: '#8a8f98'};
/** Community and area colours: the validated dark categorical palette (dataviz skill, checked against SURFACE), by
 *  size, largest first. A ninth group and beyond share a neutral grey; every group is named in the legend. */
export const SLOTS = ['#3987e5', '#d95926', '#199e70', '#c98500', '#d55181', '#008300', '#9085e9', '#e66767'];
export const OTHER = '#7d8590';
const COMMON_TAG = 60;    // a tag on more notes than this is not drawn: it says little about how they relate
const MAX_TAGS = 1500;

export type NodeKind = 'note' | 'tag' | 'term' | 'system' | 'news' | 'category';
export type EdgeKind = 'related' | 'mention' | 'shared' | 'tagged' | 'term' | 'documents' | 'news';
/** What the legend switches on and off. Notes are always shown. */
export type LayerId = 'related' | 'mention' | 'shared' | 'tags' | 'terms' | 'systems' | 'news';

export interface GNode {
  i: number; key: string; kind: NodeKind; label: string;
  group: string;        // the area of a note or term; 'tags', 'systems' or 'news' otherwise
  community: number;    // index into graph.communities
  size: number; charge: number;
  note?: BrainNote; system?: BrainSystem; count?: number; area?: string;
}
export interface GEdge { a: number; b: number; kind: EdgeKind; weight: number }
/** `alone`: the points without a link, gathered in one group (not a community the links formed). */
export interface Community { id: number; name: string; size: number; color: string; hub: number; alone?: boolean }
export interface Graph {
  nodes: GNode[]; edges: GEdge[]; byKey: Map<string, GNode>;
  neighbors: number[][];      // node index -> neighbour indexes (each once)
  communities: Community[];   // largest first; the last one gathers the points without a link, when there are any
  areaColors: Map<string, string>;
  areas: {id: string; name: string; size: number; color: string}[];
}

/** How each kind of edge pulls, and how much it counts when communities are found. */
export const EDGE_STYLE: Record<EdgeKind, {layer: LayerId; length: number; strength: number; weight: number}> = {
  related: {layer: 'related', length: 34, strength: 0.7, weight: 2},
  mention: {layer: 'mention', length: 42, strength: 0.5, weight: 1},
  shared: {layer: 'shared', length: 52, strength: 0.15, weight: 0.4},
  tagged: {layer: 'tags', length: 36, strength: 0.6, weight: 1},
  term: {layer: 'terms', length: 26, strength: 1, weight: 1},
  documents: {layer: 'systems', length: 40, strength: 0.5, weight: 1},
  news: {layer: 'news', length: 26, strength: 1, weight: 1},
};
const NODE_LAYER: Partial<Record<NodeKind, LayerId>> = {tag: 'tags', term: 'terms', system: 'systems', news: 'news', category: 'news'};
export const LAYERS: {id: LayerId; label: string; edge?: EdgeKind; nodes?: NodeKind}[] = [
  {id: 'related', label: 'Related (declared)', edge: 'related'},
  {id: 'mention', label: 'Mentions in the text', edge: 'mention'},
  {id: 'shared', label: 'Shared tags (2 or more)', edge: 'shared'},
  {id: 'tags', label: 'Tags', nodes: 'tag'},
  {id: 'terms', label: 'Glossary terms', nodes: 'term'},
  {id: 'systems', label: 'Systems documented', nodes: 'system'},
  {id: 'news', label: 'Market news', nodes: 'category'},
];
export const DEFAULT_LAYERS: ReadonlySet<LayerId> = new Set<LayerId>(['related', 'mention', 'tags', 'terms', 'systems', 'news']);

export function nodeShown(node: GNode, layers: ReadonlySet<LayerId>): boolean {
  const layer = NODE_LAYER[node.kind];
  return !layer || layers.has(layer);
}
export function edgeShown(graph: Graph, edge: GEdge, layers: ReadonlySet<LayerId>): boolean {
  return layers.has(EDGE_STYLE[edge.kind].layer) && nodeShown(graph.nodes[edge.a], layers) && nodeShown(graph.nodes[edge.b], layers);
}

/** The graph: the notes and their links, the tags two or more notes share, the glossary terms, the systems the notes
 *  document and the news (when it was read), with the communities its links form. */
export function buildGraph(map: BrainMap, news: BrainNews | null): Graph {
  const nodes: GNode[] = [];
  const edges: GEdge[] = [];
  const byKey = new Map<string, GNode>();
  const add = (node: Omit<GNode, 'i' | 'community'>): GNode => {
    const made = {...node, i: nodes.length, community: 0};
    nodes.push(made); byKey.set(made.key, made);
    return made;
  };
  const join = (a: GNode | undefined, b: GNode | undefined, kind: EdgeKind, weight = 1) => {
    if (a && b && a !== b) edges.push({a: a.i, b: b.i, kind, weight});
  };
  for (const note of map.notes) add({key: `note:${note.id}`, kind: 'note', label: note.title, group: note.area, size: 2, charge: 1, note, area: note.area});
  for (const link of map.links) join(byKey.get(`note:${link.source}`), byKey.get(`note:${link.target}`), link.kind, link.weight ?? 1);

  const tagged = new Map<string, GNode[]>();
  for (const note of map.notes) {
    for (const tag of new Set(note.tags.map(t => t.toLocaleLowerCase()))) tagged.set(tag, [...(tagged.get(tag) ?? []), byKey.get(`note:${note.id}`)!]);
  }
  const tags = [...tagged].filter(([, members]) => members.length > 1 && members.length <= COMMON_TAG)
    .sort((x, y) => y[1].length - x[1].length || x[0].localeCompare(y[0])).slice(0, MAX_TAGS);
  for (const [tag, members] of tags) {
    const node = add({key: `tag:${tag}`, kind: 'tag', label: `#${tag}`, group: 'tags', size: 2, charge: 0.8, count: members.length});
    for (const member of members) join(member, node, 'tagged');
  }
  for (const entry of map.terms ?? []) {
    const owner = byKey.get(`note:${entry.note}`);
    if (!owner || byKey.has(`term:${entry.note}:${entry.term}`)) continue;
    const node = add({key: `term:${entry.note}:${entry.term}`, kind: 'term', label: entry.term, group: owner.group, size: 2, charge: 0.5, area: owner.area});
    join(owner, node, 'term');
  }
  const newsOk = news?.status === 'ok';
  for (const system of ringSystems(map)) {
    if (system.id === 'knowledge') continue;
    const documented = system.documented_by.map(id => byKey.get(`note:${id}`)).filter((n): n is GNode => !!n);
    if (!documented.length && !(newsOk && system.id === 'postgresql')) continue;
    const node = add({key: `system:${system.id}`, kind: 'system', label: system.name, group: 'systems', size: 2, charge: 1.5, system});
    for (const note of documented) join(node, note, 'documents');
  }
  if (newsOk) {
    const hub = add({key: NEWS, kind: 'news', label: 'Market news', group: NEWS, size: 2, charge: 1.5, count: news.total ?? 0});
    join(byKey.get('system:postgresql'), hub, 'news');
    for (const category of (news.categories ?? []).slice(0, 40)) {
      join(hub, add({key: `news:${category.name}`, kind: 'category', label: category.name, group: NEWS, size: 2, charge: 0.6, count: category.count}), 'news');
    }
  }

  const sets = nodes.map(() => new Set<number>());
  for (const edge of edges) { sets[edge.a].add(edge.b); sets[edge.b].add(edge.a); }
  const neighbors = sets.map(set => [...set]);
  // A point's size grows with its links, as in graphify: hubs stand out, leaves stay small.
  for (const node of nodes) node.size = Math.min(9, 2.2 + Math.sqrt(neighbors[node.i].length) * 0.85);

  const found = louvain(nodes.length, edges.map(e => ({a: e.a, b: e.b, w: EDGE_STYLE[e.kind].weight})));
  const communities = nameCommunities(nodes, neighbors, found);
  const presentAreas = map.areas.filter(a => map.notes.some(n => n.area === a.id));
  const areaColors = new Map(presentAreas.map((a, k) => [a.id, SLOTS[k] ?? OTHER]));
  const areas = presentAreas.map(a => ({id: a.id, name: a.name, size: map.notes.filter(n => n.area === a.id).length, color: areaColors.get(a.id)!}));
  return {nodes, edges, byKey, neighbors, communities, areaColors, areas};
}

/**
 * Communities by modularity (Louvain: Blondel and others, 2008): every point starts alone; each in turn joins the
 * neighbouring community that raises modularity most, until none moves; the communities then become single points and
 * it starts again, until nothing changes. Points are visited in a fixed order, so the same graph gives the same
 * communities. Returns each point's community, numbered from 0.
 */
export function louvain(n: number, links: {a: number; b: number; w: number}[]): Int32Array {
  let member = Int32Array.from({length: n}, (_, i) => i);   // original point -> current community
  let size = n;
  let adj: Map<number, number>[] = Array.from({length: n}, () => new Map());
  let loops = new Float64Array(n);
  for (const {a, b, w} of links) {
    if (a === b) { loops[a] += 2 * w; continue; }
    adj[a].set(b, (adj[a].get(b) ?? 0) + w); adj[b].set(a, (adj[b].get(a) ?? 0) + w);
  }
  for (let level = 0; level < 20; level++) {
    const strength = Float64Array.from({length: size}, (_, i) => loops[i] + [...adj[i].values()].reduce((s, w) => s + w, 0));
    const m2 = strength.reduce((s, v) => s + v, 0);
    if (m2 === 0) break;
    const comm = Int32Array.from({length: size}, (_, i) => i);
    const tot = Float64Array.from(strength);
    let moved = false;
    for (let pass = 0; pass < 50; pass++) {
      let changed = 0;
      for (let i = 0; i < size; i++) {
        const own = comm[i];
        const into = new Map<number, number>();
        for (const [j, w] of adj[i]) into.set(comm[j], (into.get(comm[j]) ?? 0) + w);
        tot[own] -= strength[i];
        let best = own, gain = (into.get(own) ?? 0) - tot[own] * strength[i] / m2;
        for (const [c, w] of into) {
          const g = w - tot[c] * strength[i] / m2;
          if (g > gain + 1e-12) { gain = g; best = c; }  // move only for a strictly better community
        }
        tot[best] += strength[i];
        if (best !== own) { comm[i] = best; changed++; }
      }
      if (!changed) break;
      moved = true;
    }
    if (!moved) break;
    // Renumber, then fold each community into one point.
    const index = new Map<number, number>();
    for (let i = 0; i < size; i++) if (!index.has(comm[i])) index.set(comm[i], index.size);
    member = member.map(c => index.get(comm[c])!);
    const next: Map<number, number>[] = Array.from({length: index.size}, () => new Map());
    const nextLoops = new Float64Array(index.size);
    for (let i = 0; i < size; i++) {
      const ci = index.get(comm[i])!;
      nextLoops[ci] += loops[i];
      for (const [j, w] of adj[i]) {
        const cj = index.get(comm[j])!;
        if (ci === cj) nextLoops[ci] += w; else next[ci].set(cj, (next[ci].get(cj) ?? 0) + w);
      }
    }
    adj = next; loops = nextLoops; size = index.size;
  }
  // Number communities by first appearance, so the numbering does not depend on the levels.
  const order = new Map<number, number>();
  return member.map(c => { if (!order.has(c)) order.set(c, order.size); return order.get(c)!; });
}

/** Each community named by its most linked note (or point), largest first and coloured in that order; the points
 *  without a link gather in one last group. Writes each node's community. */
function nameCommunities(nodes: GNode[], neighbors: number[][], found: Int32Array): Community[] {
  const groups = new Map<number, number[]>();
  const alone: number[] = [];
  nodes.forEach(node => {
    if (!neighbors[node.i].length) alone.push(node.i);
    else groups.set(found[node.i], [...(groups.get(found[node.i]) ?? []), node.i]);
  });
  const rank = (i: number) => neighbors[i].length + (nodes[i].kind === 'note' ? 1000 : nodes[i].kind === 'system' || nodes[i].kind === 'news' ? 500 : 0);
  const sorted = [...groups.values()].map(members => ({members, hub: members.reduce((a, b) => (rank(b) > rank(a) ? b : a))}))
    .sort((x, y) => y.members.length - x.members.length || nodes[x.hub].label.localeCompare(nodes[y.hub].label));
  const out: Community[] = sorted.map(({members, hub}, id) => {
    members.forEach(i => { nodes[i].community = id; });
    return {id, name: nodes[hub].label, size: members.length, color: SLOTS[id] ?? OTHER, hub};
  });
  if (alone.length) {
    const id = out.length;
    alone.forEach(i => { nodes[i].community = id; });
    out.push({id, name: 'Without links', size: alone.length, color: OTHER, hub: alone[0], alone: true});
  }
  return out;
}

// The layout: a force simulation in 2D or 3D (springs along the edges, every point repelling every other through a
// Barnes-Hut tree, a weak pull towards its community and the middle), seeded so the same knowledge base settles the
// same way.

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
const CHARGE = 30;
const THETA2 = 0.81;
const GRAVITY = 0.02;
const COHESION = 0.04;  // the pull towards the community's centre

/** An octree over the points for one tick (a quadtree in effect when every z is 0): each cell holds its total charge
 *  and the charge-weighted centre. */
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

  /** Push point i away from the others: exactly from nearby points, by the centre of a far cell's charge otherwise. */
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

/** The simulation, in `dims` 2 (every z stays 0) or 3. `pos` holds x, y, z per point. Positions carried over from an
 *  earlier layout of the same knowledge base keep their place, so a refresh does not reshuffle the picture. */
export class Layout {
  readonly pos: Float32Array;
  private readonly vel: Float32Array;
  private readonly strength: Float64Array;
  private readonly tree: Octree;
  private readonly stack: Int32Array;
  private readonly bias: Float64Array;
  private readonly linkStrength: Float64Array;
  private readonly centre: Float64Array;
  alpha = 1;

  constructor(readonly graph: Graph, seed = 7, previous?: {graph: Graph; pos: Float32Array; alpha?: number}, readonly dims: 2 | 3 = 3) {
    const n = graph.nodes.length;
    this.pos = new Float32Array(n * 3);
    this.vel = new Float32Array(n * 3);
    this.strength = Float64Array.from(graph.nodes, node => -CHARGE * node.charge);
    this.tree = new Octree(Math.max(n, 1));
    this.stack = new Int32Array(n * 24 + 64);
    this.centre = new Float64Array(graph.communities.length * 4);
    const degree = graph.neighbors.map(list => list.length || 1);
    this.bias = Float64Array.from(graph.edges, e => degree[e.a] / (degree[e.a] + degree[e.b]));
    this.linkStrength = Float64Array.from(graph.edges, e => EDGE_STYLE[e.kind].strength / Math.min(degree[e.a], degree[e.b]));
    const carried = this.place(seed, previous);
    // Settle what is new, moving the rest as little as it needs; a layout still settling carries on where it was.
    if (carried > 0) this.alpha = Math.max(0.08, 1 - carried, previous?.alpha ?? 0);
  }

  /** Starting places: each community around its own point on a circle (a sphere in 3D), each point beside what it joins.
   *  Returns the share of points carried over from `previous`. */
  private place(seed: number, previous?: {graph: Graph; pos: Float32Array}): number {
    const rand = random(seed);
    const {nodes, neighbors, communities} = this.graph;
    const flat = this.dims === 2 ? 0 : 1;
    const set = new Uint8Array(nodes.length);
    let carried = 0;
    const put = (i: number, x: number, y: number, z: number) => { this.pos.set([x, y, z * flat], i * 3); set[i] = 1; };
    if (previous) {
      for (const node of nodes) {
        const old = previous.graph.byKey.get(node.key);
        if (old) { put(node.i, previous.pos[old.i * 3], previous.pos[old.i * 3 + 1], previous.pos[old.i * 3 + 2]); carried++; }
      }
    }
    const spread = 60 + Math.sqrt(nodes.length) * 9;
    const home = communities.map((_, k) => {
      if (this.dims === 2) { const a = k * Math.PI * (3 - Math.sqrt(5)), r = spread * Math.sqrt((k + 0.5) / communities.length); return [r * Math.cos(a), r * Math.sin(a), 0]; }
      const y = 1 - (2 * (k + 0.5)) / communities.length, r = Math.sqrt(1 - y * y), a = k * Math.PI * (3 - Math.sqrt(5));
      return [spread * r * Math.cos(a), spread * y, spread * r * Math.sin(a)];
    });
    // Hubs first, so each point can start beside a placed neighbour.
    const order = [...nodes].sort((a, b) => neighbors[b.i].length - neighbors[a.i].length || a.i - b.i);
    for (const node of order) {
      if (set[node.i]) continue;
      const placed = neighbors[node.i].filter(j => set[j]);
      const at = placed.length ? [0, 1, 2].map(k => placed.reduce((s, j) => s + this.pos[j * 3 + k], 0) / placed.length) : home[node.community] ?? [0, 0, 0];
      const jitter = placed.length ? 14 : 30;
      put(node.i, at[0] + (rand() - 0.5) * jitter, at[1] + (rand() - 0.5) * jitter, at[2] + (rand() - 0.5) * jitter);
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
    // A weak pull towards the centre of the point's community, so communities read as groups.
    const centre = this.centre;
    centre.fill(0);
    for (const node of graph.nodes) {
      const c = node.community * 4;
      centre[c] += pos[node.i * 3]; centre[c + 1] += pos[node.i * 3 + 1]; centre[c + 2] += pos[node.i * 3 + 2]; centre[c + 3]++;
    }
    const alone = graph.communities.findIndex(c => c.alone);
    for (const node of graph.nodes) {
      if (node.community === alone) continue;
      const c = node.community * 4, i = node.i * 3;
      for (let k = 0; k < 3; k++) vel[i + k] += (centre[c + k] / centre[c + 3] - pos[i + k]) * COHESION * alpha;
    }
    for (let k = 0; k < n * 3; k++) {
      vel[k] = (vel[k] - pos[k] * GRAVITY * alpha) * VELOCITY_KEEP;
      pos[k] += vel[k];
    }
    if (this.dims === 2) for (let k = 2; k < n * 3; k += 3) { pos[k] = 0; vel[k] = 0; }
  }

  /** Run until settled or `ticks` have run; returns how many ran. */
  run(ticks: number): number {
    let ran = 0;
    while (ran < ticks && !this.settled) { this.tick(); ran++; }
    return ran;
  }
}

// The camera: it looks at a target point; in 3D it orbits it (yaw turns around the vertical axis, pitch tilts).

export interface Camera { yaw: number; pitch: number; distance: number; tx: number; ty: number; tz: number }
export const FOV = 0.5;  // narrow, so points near the camera do not swell as the graph turns
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

/** The camera target and distance that frame these points (all but the farthest few in a hundred, so one stray point
 *  does not shrink the picture). `margin` below 1 frames tighter, as for a 3D cloud, which never fills its sphere. */
export function frame(pos: Float32Array, indexes: number[], aspect = 1, margin = 1.06): Pick<Camera, 'tx' | 'ty' | 'tz' | 'distance'> {
  if (!indexes.length) return {tx: 0, ty: 0, tz: 0, distance: 400};
  const c = [0, 0, 0];
  for (const i of indexes) for (let k = 0; k < 3; k++) c[k] += pos[i * 3 + k] / indexes.length;
  const reach = indexes.map(i => Math.hypot(pos[i * 3] - c[0], pos[i * 3 + 1] - c[1], pos[i * 3 + 2] - c[2])).sort((a, b) => a - b);
  const radius = Math.max(24, reach[Math.min(reach.length - 1, Math.floor(reach.length * 0.98))]);
  const half = Math.min(FOV / 2, Math.atan(Math.tan(FOV / 2) * Math.max(aspect, 0.2)));
  return {tx: c[0], ty: c[1], tz: c[2], distance: radius / Math.sin(half) * margin};
}

/** The points a focus lights up, or null for all of them: an area (or the news), a community, the systems with what
 *  they document, or one point and its neighbours. */
export function focusNodes(graph: Graph, focus: Focus | {kind: 'community'; id: number}): Set<number> | null {
  if (focus.kind === 'all') return null;
  if (focus.kind === 'note') {
    const node = graph.byKey.get(focus.id);
    return node ? new Set([node.i, ...graph.neighbors[node.i]]) : null;
  }
  const lit = new Set<number>();
  if (focus.kind === 'community') {
    for (const node of graph.nodes) if (node.community === focus.id) lit.add(node.i);
    return lit;
  }
  if (focus.kind === 'systems') {
    for (const node of graph.nodes) if (node.kind === 'system') { lit.add(node.i); graph.neighbors[node.i].forEach(j => lit.add(j)); }
    return lit;
  }
  for (const node of graph.nodes) if (node.group === focus.id) lit.add(node.i);
  if (focus.id === NEWS) { const db = graph.byKey.get('system:postgresql'); if (db) lit.add(db.i); }
  return lit;
}

/** The point under the pointer: the nearest drawn point within reach of its edge, the front one on a tie. */
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

const KIND_RANK: Record<NodeKind, number> = {note: 0, term: 1, system: 2, tag: 3, category: 4, news: 5};
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

// The network's statistics, over the whole graph.

export interface NetworkStats {
  nodes: number; edges: number; byKind: Record<NodeKind, number>; byEdge: Record<EdgeKind, number>;
  density: number; meanDegree: number; maxDegree: number; isolated: number;
  components: number; largest: number; clustering: number;
  communities: number; modularity: number; areaModularity: number;
  pathLength: number | null; diameter: number | null; sampled: boolean;
  histogram: {label: string; from: number; to: number; count: number}[];
}

/** Modularity of a partition: Q = sum over groups of (links inside / m) - (the group's degree / 2m)^2. */
export function modularity(links: [number, number][], group: (i: number) => string | number): number {
  const m = links.length;
  if (!m) return 0;
  const inner = new Map<string | number, number>(), total = new Map<string | number, number>();
  for (const [a, b] of links) {
    const ga = group(a), gb = group(b);
    total.set(ga, (total.get(ga) ?? 0) + 1); total.set(gb, (total.get(gb) ?? 0) + 1);
    if (ga === gb) inner.set(ga, (inner.get(ga) ?? 0) + 1);
  }
  let q = 0;
  for (const [g, sum] of total) q += (inner.get(g) ?? 0) / m - (sum / (2 * m)) ** 2;
  return q;
}

export function networkStats(graph: Graph): NetworkStats {
  const byKind = {note: 0, tag: 0, term: 0, system: 0, news: 0, category: 0} as Record<NodeKind, number>;
  const byEdge = {related: 0, mention: 0, shared: 0, tagged: 0, term: 0, documents: 0, news: 0} as Record<EdgeKind, number>;
  for (const node of graph.nodes) byKind[node.kind]++;
  for (const edge of graph.edges) byEdge[edge.kind]++;
  const n = graph.nodes.length;
  const adj = graph.neighbors.map(list => new Set(list));
  const degrees = adj.map(set => set.size);
  const pairs = new Set<string>();
  const links: [number, number][] = [];
  for (const e of graph.edges) {
    const key = e.a < e.b ? `${e.a}-${e.b}` : `${e.b}-${e.a}`;
    if (!pairs.has(key)) { pairs.add(key); links.push([e.a, e.b]); }
  }
  const m = links.length;
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
  // Average local clustering (points with fewer than two neighbours count as 0, as in Watts and Strogatz).
  let clustering = 0;
  for (let v = 0; v < n; v++) {
    const list = [...adj[v]], k = list.length;
    if (k < 2) continue;
    let closed = 0;
    for (let x = 0; x < k; x++) for (let y = x + 1; y < k; y++) if (adj[list[x]].has(list[y])) closed++;
    clustering += closed / (k * (k - 1) / 2);
  }
  // Mean shortest path and diameter in the largest component (from every point, or from 200 when there are many).
  const members = big < 0 ? [] : [...Array(n).keys()].filter(v => component[v] === big);
  const sampled = members.length > 800;
  const sources = sampled ? members.filter((_, k) => k % Math.ceil(members.length / 200) === 0) : members;
  let paths = 0, reached = 0, diameter = 0;
  const dist = new Int32Array(n);
  for (const s of sources) {
    dist.fill(-1); dist[s] = 0;
    const queue = [s];
    for (let q = 0; q < queue.length; q++) {
      const v = queue[q];
      for (const u of adj[v]) if (dist[u] < 0) { dist[u] = dist[v] + 1; paths += dist[u]; reached++; diameter = Math.max(diameter, dist[u]); queue.push(u); }
    }
  }
  // Degree distribution in doubling bins: 0, 1, 2, 3-4, 5-8, ...
  const maxDegree = Math.max(0, ...degrees);
  const bins: NetworkStats['histogram'] = [0, 1, 2].map(d => ({label: `${d}`, from: d, to: d, count: 0}));
  for (let to = 4; bins[bins.length - 1].to < maxDegree; to *= 2) bins.push({label: `${to / 2 + 1}–${to}`, from: to / 2 + 1, to, count: 0});
  for (const d of degrees) { const bin = bins.find(b => d >= b.from && d <= b.to); if (bin) bin.count++; }
  const linked = graph.communities.filter(c => !c.alone).length;
  return {
    nodes: n, edges: m, byKind, byEdge,
    density: n > 1 ? (2 * m) / (n * (n - 1)) : 0, meanDegree: n ? (2 * m) / n : 0, maxDegree,
    isolated: degrees.filter(d => d === 0).length, components: sizes.length, largest: n ? Math.max(0, ...sizes) / n : 0,
    clustering: n ? clustering / n : 0,
    communities: linked, modularity: modularity(links, i => graph.nodes[i].community),
    areaModularity: modularity(links, i => graph.nodes[i].group),
    pathLength: reached ? paths / reached : null, diameter: reached ? diameter : null, sampled, histogram: bins,
  };
}
