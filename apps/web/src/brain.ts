// The Brain page (/brain): what Wizard can draw on, as one picture. Everything here is laid out from what the server
// read (services/api/wizard_api/brain.py): knowledge areas and notes, the links between notes, the systems, the news.
// Pure functions, so the picture and the tour are tested without a canvas.
import type {DataMode, SystemInfo} from './types';

export type NoteStage = 'SIGNED' | 'EXPERT_CHECKED' | 'DRAFT';

export interface BrainNote {
  id: string; title: string; area: string; type: string | null; stage: NoteStage; summary: string; tags: string[];
  terms: number | null; updated: string | null;
}
export interface BrainArea { id: string; name: string; description: string; notes: number }
export interface BrainLink { source: string; target: string; kind: 'related' | 'shared' }
export interface BrainSystem extends SystemInfo { reports: number | null; documented_by: string[] }
export interface BrainCounts {
  notes: number; areas: number; links: number; related: number; glossary_terms: number; datasets: number; metrics: number;
  signed: number; expert_checked: number; reports: number; systems: number;
}
export interface BrainMap {
  content: 'company' | 'examples' | 'none';
  areas: BrainArea[]; notes: BrainNote[]; links: BrainLink[]; systems: BrainSystem[]; counts: BrainCounts;
  knowledge_synced_at: string | null; pg_name: string;
}

export type LiveStatus = 'ok' | 'not_configured' | 'not_allowed' | 'not_found' | 'error';
export interface NewsItem { title: string; category?: string | null; source?: string | null; url?: string | null;
  summary?: string | null; market?: string | null; date?: string | null }
export interface BrainNews {
  status: LiveStatus; message?: string; read_at?: number; database?: string; table?: string;
  columns?: Record<string, string>; total?: number; first?: string | null; last?: string | null; last_added?: string | null;
  last_7_days?: number | null; last_day?: number | null; categories?: {name: string; count: number}[];
  weekly?: {week: string; count: number}[]; latest?: NewsItem[]; queries?: string[]; data_mode?: DataMode; elapsed_ms?: number;
}
export interface BrainDatabase { status: LiveStatus; message?: string; database?: string; relations?: number; schemas?: number; read_at?: number }
export interface BrainLive { name: string; database: BrainDatabase; news: BrainNews }

export type Point = {x: number; y: number};

/** Each knowledge area's colour on the dark page. An area not listed takes a spare colour by its name. */
const AREA_COLORS: Record<string, string> = {
  company: '#60a5fa', org: '#a78bfa', products: '#f472b6', markets: '#34d399', processes: '#fbbf24',
  platforms: '#38bdf8', datasets: '#c084fc', metrics: '#fb923c', glossary: '#2dd4bf', faq: '#e879f9',
  decisions: '#facc15', general: '#94a3b8',
};
const SPARE_COLORS = ['#f9a8d4', '#86efac', '#fcd34d', '#93c5fd', '#d8b4fe', '#fdba74', '#5eead4'];
export const NEWS_COLOR = '#fb7185';
export const NEWS = 'news';

function stableIndex(text: string, size: number): number {
  return Array.from(text).reduce((h, c) => (h * 31 + c.charCodeAt(0)) >>> 0, 7) % size;
}

export function areaColor(area: string): string {
  return AREA_COLORS[area] ?? (area === NEWS ? NEWS_COLOR : SPARE_COLORS[stableIndex(area, SPARE_COLORS.length)]);
}

const CATEGORY_COLORS = ['#fb7185', '#fbbf24', '#34d399', '#60a5fa', '#c084fc', '#f472b6', '#2dd4bf', '#fb923c', '#a3e635', '#38bdf8'];
export function categoryColor(name: string, order: string[]): string {
  const at = order.indexOf(name);
  return CATEGORY_COLORS[(at >= 0 ? at : stableIndex(name, CATEGORY_COLORS.length)) % CATEGORY_COLORS.length];
}

export interface LaidNode {
  key: string;          // note id, or news:<category>
  kind: 'note' | 'news';
  cluster: string;      // area id, or 'news'
  x: number; y: number; r: number;
  color: string;
  phase: number;        // for the twinkle
  note?: BrainNote;
  news?: {name: string; count: number};
}
/** `side`: where the label sits from its point: to the right, to the left, or centred above or below. */
export interface LaidCluster { id: string; name: string; count: number; color: string; x: number; y: number; radius: number;
  label: Point; side: 'right' | 'left' | 'above' | 'below'; angle: number }
export interface LaidSystem { id: string; system: BrainSystem; x: number; y: number }
/** A curve for the synapses and the pulses that run along them: from p0 through the pull of c to p1. */
export interface Path { from: string; to: string; p0: Point; c: Point; p1: Point; color: string; kind: 'link' | 'system' | 'axon' | 'spoke' }

export interface BrainLayout {
  width: number; height: number; center: Point; core: number; systemRing: number;
  clusters: LaidCluster[]; nodes: LaidNode[]; systems: LaidSystem[]; paths: Path[];
  byKey: Map<string, LaidNode>;
}

const GOLDEN = Math.PI * (3 - Math.sqrt(5));

/** Points of a sunflower: n dots evenly filling a disc, the first in the middle. */
export function sunflower(n: number, spacing: number): Point[] {
  return Array.from({length: n}, (_, i) => {
    const r = spacing * Math.sqrt(i + 0.5), a = i * GOLDEN;
    return {x: r * Math.cos(a), y: r * Math.sin(a)};
  });
}

function bend(p0: Point, p1: Point, toward: Point, pull: number): Point {
  const mid = {x: (p0.x + p1.x) / 2, y: (p0.y + p1.y) / 2};
  return {x: mid.x + (toward.x - mid.x) * pull, y: mid.y + (toward.y - mid.y) * pull};
}

export function along(path: Path, t: number): Point {
  const u = 1 - t;
  return {x: u * u * path.p0.x + 2 * u * t * path.c.x + t * t * path.p1.x, y: u * u * path.p0.y + 2 * u * t * path.c.y + t * t * path.p1.y};
}

/** The systems Wizard draws on, in the ring around it: the attached-files system is left out (it is the person's own
 *  file, not something Wizard knows). */
export function ringSystems(map: BrainMap): BrainSystem[] {
  return map.systems.filter(s => s.id !== 'attachment');
}

/**
 * The picture: the wizard in the middle, the systems in a ring around him, and each knowledge area as a cluster of
 * notes further out (the news as one more cluster, its categories sized by their articles). Synapses join linked notes,
 * notes to the systems they document, and every cluster to the middle.
 */
export function layoutBrain(map: BrainMap, news: BrainNews | null, width: number, height: number, bottom = 0): BrainLayout {
  // `bottom`: room kept free under the picture for the counters and the tour's caption.
  const center = {x: width / 2, y: (height - bottom) / 2 + 8};
  const short = Math.min(width, height);
  const core = Math.max(54, short * 0.1);
  const systems = ringSystems(map);
  const systemRing = Math.max(core + 70, short * 0.23);
  const rx = Math.max(systemRing + 80, width / 2 - 110), ry = Math.max(systemRing + 60, (height - bottom) / 2 - 52);
  const notesByArea = new Map<string, BrainNote[]>();
  for (const note of map.notes) notesByArea.set(note.area, [...(notesByArea.get(note.area) ?? []), note]);
  const groups: {id: string; name: string; size: number}[] = map.areas.filter(a => notesByArea.has(a.id))
    .map(a => ({id: a.id, name: a.name, size: notesByArea.get(a.id)!.length}));
  const categories = news?.status === 'ok' ? (news.categories ?? []).slice(0, 24) : [];
  if (news?.status === 'ok') groups.push({id: NEWS, name: 'Market news', size: Math.max(categories.length, 1)});

  // Each cluster takes a share of the ring by its width (the square root of its size), with a gap between.
  const weights = groups.map(g => Math.sqrt(g.size) + 1.6);
  const total = weights.reduce((a, b) => a + b, 0) || 1;
  const perimeter = Math.PI * (3 * (rx + ry) - Math.sqrt((3 * rx + ry) * (rx + 3 * ry)));
  const room = Math.min(...groups.map((g, i) => (perimeter * weights[i] / total) * 0.42 / Math.max(Math.sqrt(g.size), 1)), 16);
  const spacing = Math.max(3.2, Math.min(room, (Math.min(rx - systemRing, ry - systemRing) * 0.62) / Math.sqrt(Math.max(...groups.map(g => g.size), 1))));
  // News sits on the right, next to its panel; the areas run round from there.
  const newsAt = groups.findIndex(g => g.id === NEWS);
  let start = -Math.PI / 2;
  if (newsAt >= 0) {
    const before = weights.slice(0, newsAt).reduce((a, b) => a + b, 0) + weights[newsAt] / 2;
    start = -(before / total) * Math.PI * 2;
  }
  const clusters: LaidCluster[] = [];
  const nodes: LaidNode[] = [];
  let cursor = start;
  groups.forEach((group, i) => {
    const share = (weights[i] / total) * Math.PI * 2;
    const angle = cursor + share / 2;
    cursor += share;
    const radius = spacing * Math.sqrt(group.size) + 6;
    const pull = Math.min(1, (radius + 24) / Math.min(rx, ry));  // keep a big cluster inside the page
    const cx = center.x + (rx - radius * 0.6) * Math.cos(angle) * (1 - pull * 0.15);
    const cy = center.y + (ry - radius * 0.6) * Math.sin(angle) * (1 - pull * 0.15);
    const color = areaColor(group.id);
    // The name sits outside the cluster, away from the middle; where that would leave the page, above or below it.
    const outward = radius + 16, cos = Math.cos(angle), LABEL = 150;
    let side: LaidCluster['side'] = cos > 0.25 ? 'right' : cos < -0.25 ? 'left' : Math.sin(angle) < 0 ? 'above' : 'below';
    let label = {x: cx + outward * cos, y: cy + outward * Math.sin(angle)};
    if ((side === 'right' && label.x + LABEL > width - 6) || (side === 'left' && label.x - LABEL < 6)) {
      side = cy < center.y ? 'above' : 'below';
      label = {x: Math.min(width - LABEL / 2, Math.max(LABEL / 2, cx)), y: cy + (side === 'above' ? -1 : 1) * (radius + 22)};
    }
    clusters.push({id: group.id, name: group.name, count: group.id === NEWS ? (news?.total ?? 0) : group.size, color,
      x: cx, y: cy, radius, angle, label, side});
    if (group.id === NEWS) {
      const biggest = Math.max(1, ...categories.map(c => c.count));
      const points = sunflower(Math.max(categories.length, 1), spacing * 1.25);
      categories.forEach((category, k) => nodes.push({key: `news:${category.name}`, kind: 'news', cluster: NEWS,
        x: cx + points[k].x, y: cy + points[k].y, r: 2.6 + 6 * Math.sqrt(category.count / biggest), color,
        phase: (k * 1.37) % (Math.PI * 2), news: category}));
      return;
    }
    const members = notesByArea.get(group.id)!;
    const points = sunflower(members.length, spacing);
    members.forEach((note, k) => nodes.push({key: note.id, kind: 'note', cluster: group.id, x: cx + points[k].x, y: cy + points[k].y,
      r: noteRadius(note), color, phase: (stableIndex(note.id, 628) / 100), note}));
  });
  const byKey = new Map(nodes.map(n => [n.key, n]));

  const laidSystems: LaidSystem[] = systems.map((system, i) => {
    const a = -Math.PI / 2 + (i / Math.max(systems.length, 1)) * Math.PI * 2 + (systems.length % 2 ? 0 : Math.PI / systems.length);
    return {id: system.id, system, x: center.x + systemRing * 1.18 * Math.cos(a), y: center.y + systemRing * 0.86 * Math.sin(a)};
  });
  const systemAt = new Map(laidSystems.map(s => [s.id, s]));

  const paths: Path[] = [];
  for (const link of map.links) {
    const a = byKey.get(link.source), b = byKey.get(link.target);
    if (!a || !b) continue;
    const near = a.cluster === b.cluster;
    paths.push({from: a.key, to: b.key, p0: a, p1: b, c: bend(a, b, center, near ? 0.12 : 0.38), color: a.color, kind: 'link'});
  }
  for (const system of laidSystems) {
    for (const id of system.system.documented_by) {
      const note = byKey.get(id);
      if (note) paths.push({from: note.key, to: system.id, p0: note, p1: system, c: bend(note, system, center, 0.2), color: note.color, kind: 'system'});
    }
    paths.push({from: system.id, to: 'wizard', p0: system, p1: center, c: bend(system, center, center, 0), color: '#8ea2ff', kind: 'spoke'});
  }
  const database = systemAt.get('postgresql');
  for (const cluster of clusters) {
    const edge = {x: center.x + (cluster.x - center.x) * (core / Math.hypot(cluster.x - center.x, cluster.y - center.y)),
      y: center.y + (cluster.y - center.y) * (core / Math.hypot(cluster.x - center.x, cluster.y - center.y))};
    const target = cluster.id === NEWS && database ? database : edge;
    paths.push({from: cluster.id, to: target === edge ? 'wizard' : 'postgresql', p0: {x: cluster.x, y: cluster.y}, p1: target,
      c: bend({x: cluster.x, y: cluster.y}, target, center, 0.15), color: cluster.color, kind: 'axon'});
  }
  for (const node of nodes) {
    if (node.kind !== 'news') continue;
    const cluster = clusters.find(c => c.id === NEWS)!;
    paths.push({from: node.key, to: NEWS, p0: node, p1: {x: cluster.x, y: cluster.y}, c: bend(node, cluster, cluster, 0), color: node.color, kind: 'link'});
  }
  return {width, height, center, core, systemRing, clusters, nodes, systems: laidSystems, paths, byKey};
}

export function noteRadius(note: BrainNote): number {
  const base = note.stage === 'SIGNED' ? 3.6 : note.stage === 'EXPERT_CHECKED' ? 3.1 : 2.5;
  return note.terms ? Math.min(7, base + Math.sqrt(note.terms) * 0.45) : note.type === 'dataset' ? base + 0.5 : base;
}

/** What the page lights up: everything, one cluster, the systems, or one note and what it links to. */
export type Focus = {kind: 'all'} | {kind: 'cluster'; id: string} | {kind: 'systems'} | {kind: 'note'; id: string};

export function inFocus(focus: Focus, layout: BrainLayout, key: string): boolean {
  if (focus.kind === 'all') return true;
  const node = layout.byKey.get(key);
  if (focus.kind === 'cluster') return node ? node.cluster === focus.id : key === focus.id;
  if (focus.kind === 'systems') return !node && layout.systems.some(s => s.id === key);
  if (key === focus.id) return true;
  return layout.paths.some(p => p.kind !== 'spoke' && ((p.from === focus.id && p.to === key) || (p.to === focus.id && p.from === key)));
}

export function pathInFocus(focus: Focus, layout: BrainLayout, path: Path): boolean {
  if (focus.kind === 'all') return true;
  if (focus.kind === 'cluster') return layout.byKey.get(path.from)?.cluster === focus.id || path.from === focus.id;
  if (focus.kind === 'systems') return path.kind === 'spoke' || path.kind === 'system';
  return path.from === focus.id || path.to === focus.id;
}

/** The node under the pointer, if one is close enough. */
export function nodeAt(layout: BrainLayout, x: number, y: number, reach = 12): LaidNode | null {
  let best: LaidNode | null = null, distance = reach;
  for (const node of layout.nodes) {
    const d = Math.hypot(node.x - x, node.y - y) - node.r;
    if (d < distance) { distance = d; best = node; }
  }
  return best;
}

export function plural(n: number, one: string, many = `${one}s`): string {
  return `${n.toLocaleString()} ${n === 1 ? one : many}`;
}

/** The notes of an area that link most, for "including ..." lines. */
export function bestKnown(map: BrainMap, area: string, count = 3): BrainNote[] {
  const degree = new Map<string, number>();
  for (const link of map.links) for (const id of [link.source, link.target]) degree.set(id, (degree.get(id) ?? 0) + 1);
  const rank = (n: BrainNote) => (n.stage === 'SIGNED' ? 100 : n.stage === 'EXPERT_CHECKED' ? 50 : 0) + (degree.get(n.id) ?? 0);
  return map.notes.filter(n => n.area === area).sort((a, b) => rank(b) - rank(a) || a.title.localeCompare(b.title)).slice(0, count);
}

/** What one area holds, in a line, from its counts (the knowledge standard says what each folder is for). */
export function areaLine(map: BrainMap, area: BrainArea): string {
  const n = area.notes;
  switch (area.id) {
    case 'company': return `${plural(n, 'note')} on what the company is: business units, entities, locations and strategy.`;
    case 'org': return `${plural(n, 'note')} on who does what: functions, teams and who owns which topic.`;
    case 'products': return `${plural(n, 'note')} on product lines, families, naming and life cycle.`;
    case 'markets': return `${plural(n, 'note')} on our markets, regions, channels and key accounts.`;
    case 'processes': return `${plural(n, 'note')} on how work happens: planning, budgeting, month close, launches.`;
    case 'platforms': return `${plural(n, 'guide')} to the platforms we report from, and how to navigate each one.`;
    case 'datasets': return `${plural(n, 'dataset')} documented column by column, so Wizard writes its own SQL against them.`;
    case 'metrics': return `${plural(n, 'metric definition')}: how each number is computed, and what must never be summed.`;
    case 'glossary': return map.counts.glossary_terms
      ? `${plural(map.counts.glossary_terms, 'term')} and acronyms, so it speaks our language, ambiguous words included.`
      : `${plural(n, 'glossary note')}: our acronyms and jargon.`;
    case 'faq': return `${plural(n, 'recurring executive question')} and where each answer lives.`;
    case 'decisions': return `${plural(n, 'standing decision')} that change how our data is read.`;
    default: return area.description || `${plural(n, 'note')}.`;
  }
}

export interface TourStep { id: string; title: string; body: string; focus: Focus; examples?: string[] }

/** The guided tour for a presentation: built from what was read, so every number it says is on the page. */
export function tourSteps(map: BrainMap, live: BrainLive | null): TourStep[] {
  const c = map.counts;
  const steps: TourStep[] = [{id: 'intro', title: 'Everything Wizard knows, in one picture',
    body: `${plural(c.notes, 'note')} across ${plural(c.areas, 'topic')}, joined by ${plural(c.links, 'connection')}. Each dot is a note Wizard can look up while it answers.`,
    focus: {kind: 'all'}}];
  const areas = [...map.areas].filter(a => a.notes > 0);
  const shown = areas.length > 6 ? [...areas].sort((a, b) => b.notes - a.notes).slice(0, 6).sort((a, b) => areas.indexOf(a) - areas.indexOf(b)) : areas;
  for (const area of shown) {
    steps.push({id: `area-${area.id}`, title: area.name, body: areaLine(map, area), focus: {kind: 'cluster', id: area.id},
      examples: bestKnown(map, area.id).map(n => n.title)});
  }
  const systems = ringSystems(map).filter(s => s.id !== 'knowledge');
  if (systems.length) {
    const parts = systems.map(s => {
      if (s.id === 'postgresql' && live?.database.status === 'ok') return `${s.name} (${plural(live.database.relations ?? 0, 'table')} and views)`;
      if (s.reports) return `${s.name} (${plural(s.reports, 'report')} catalogued)`;
      if (s.kind === 'portal') return `${s.name} (read live)`;
      return s.name;
    });
    steps.push({id: 'systems', title: 'Connected to our systems', focus: {kind: 'systems'},
      body: `It reads ${parts.length > 1 ? `${parts.slice(0, -1).join(', ')} and ${parts.at(-1)}` : parts[0]}, only ever with your own rights.`});
  }
  const news = live?.news;
  if (news?.status === 'ok') {
    const categories = news.categories?.length ?? 0;
    const recent = news.last_7_days ? `, ${plural(news.last_7_days, 'article')} in the last 7 days` : '';
    steps.push({id: 'news', title: 'Reading the market, every day', focus: {kind: 'cluster', id: NEWS},
      body: `${plural(news.total ?? 0, 'news article')} curated and sorted into ${plural(categories, 'category', 'categories')}${recent}.`});
  }
  steps.push({id: 'ask', title: 'Ask it anything', focus: {kind: 'all'},
    body: 'Wizard decides where to look, reads the data and writes the answer. Every number opens to the rows it came from.'});
  return steps;
}

/** "3 min ago", "5 h ago", "2 days ago", or the date. */
export function ago(iso: string | null | undefined, now = Date.now()): string {
  if (!iso) return '';
  const at = new Date(iso).getTime();
  if (Number.isNaN(at)) return '';
  const minutes = Math.round((now - at) / 60_000);
  if (minutes < 1) return 'just now';
  if (minutes < 60) return `${minutes} min ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours} h ago`;
  const days = Math.round(hours / 24);
  if (days < 14) return `${days} day${days === 1 ? '' : 's'} ago`;
  return new Intl.DateTimeFormat(undefined, {dateStyle: 'medium'}).format(new Date(at));
}

/** Weekly counts as a running total, for the "and counting" line. */
export function cumulative(weekly: {week: string; count: number}[]): {week: string; count: number; total: number}[] {
  let total = 0;
  return weekly.map(w => ({...w, total: (total += w.count)}));
}
