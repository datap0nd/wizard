// The Brain page (/brain): the knowledge base as a 3D graph. Everything here comes from what the server read
// (services/api/wizard_api/brain.py): knowledge areas and notes, the links between notes, glossary terms, the systems,
// the news. The graph itself is built and laid out in graph3d.ts; this file holds the data's shape, the tour and the
// news helpers, as pure functions tested without a canvas.
import type {DataMode, SystemInfo} from './types';

export type NoteStage = 'SIGNED' | 'EXPERT_CHECKED' | 'DRAFT';

export interface BrainNote {
  id: string; title: string; area: string; type: string | null; stage: NoteStage; summary: string; tags: string[];
  terms: number | null; words?: number; updated: string | null;
}
export interface BrainArea { id: string; name: string; description: string; notes: number }
/** `related`: the note's own link; `mention`: one note names the other in its text; `shared`: tags in common.
 *  `weight`: how often it is named, or how many tags are shared. */
export interface BrainLink { source: string; target: string; kind: 'related' | 'mention' | 'shared'; weight?: number }
export interface BrainTerm { note: string; term: string }
/** `mapped`: a portal's map (portal_map.py): the reports Gemini mapped and all it found there. */
export interface BrainSystem extends SystemInfo { reports: number | null; documented_by: string[];
  mapped?: {mapped: number; found: number; updated: string | null} | null }
/** A report Gemini mapped in a portal: its name and menu path, nothing it holds. */
export interface BrainPortalReport { system: string; id: string; name: string; path: string[]; status: 'mapped' | 'partial' }
export interface BrainCounts {
  notes: number; areas: number; links: number; related: number; mentions?: number; glossary_terms: number; datasets: number;
  metrics: number; signed: number; expert_checked: number; reports: number; mapped_reports?: number; systems: number;
}
export interface BrainMap {
  content: 'company' | 'examples' | 'none';
  areas: BrainArea[]; notes: BrainNote[]; links: BrainLink[]; terms?: BrainTerm[]; systems: BrainSystem[]; portal_reports?: BrainPortalReport[];
  counts: BrainCounts;
  knowledge_synced_at: string | null; pg_name: string;
}

export type LiveStatus = 'ok' | 'not_configured' | 'not_allowed' | 'not_found' | 'error';
/** `origin`: on a demo arrival, the article (by its key) it re-shows. */
export interface NewsItem { title: string; category?: string | null; source?: string | null; url?: string | null;
  summary?: string | null; market?: string | null; date?: string | null; origin?: string }
export interface BrainNews {
  status: LiveStatus; message?: string; read_at?: number; database?: string; table?: string;
  columns?: Record<string, string>; total?: number; first?: string | null; last?: string | null; last_added?: string | null;
  last_7_days?: number | null; last_day?: number | null; categories?: {name: string; count: number}[];
  weekly?: {week: string; count: number}[]; latest?: NewsItem[]; queries?: string[]; data_mode?: DataMode; elapsed_ms?: number;
}
export interface BrainDatabase { status: LiveStatus; message?: string; database?: string; relations?: number; schemas?: number; read_at?: number }
export interface BrainLive { name: string; database: BrainDatabase; news: BrainNews }
/** The Brain page as the Pages site has it (site.py): the map and the news as read when the person published them. */
export interface BrainSnapshot { format: number; published_at: string; map: BrainMap; live: BrainLive | null }

export const NEWS = 'news';

function stableIndex(text: string, size: number): number {
  return Array.from(text).reduce((h, c) => (h * 31 + c.charCodeAt(0)) >>> 0, 7) % size;
}

const CATEGORY_COLORS = ['#fb7185', '#fbbf24', '#34d399', '#60a5fa', '#c084fc', '#f472b6', '#2dd4bf', '#fb923c', '#a3e635', '#38bdf8'];
export function categoryColor(name: string, order: string[]): string {
  const at = order.indexOf(name);
  return CATEGORY_COLORS[(at >= 0 ? at : stableIndex(name, CATEGORY_COLORS.length)) % CATEGORY_COLORS.length];
}

/** The systems Wizard draws on: the attached-files system is left out (it is the person's own file, not something
 *  Wizard knows). */
export function ringSystems(map: BrainMap): BrainSystem[] {
  return map.systems.filter(s => s.id !== 'attachment');
}

/** What the page lights up: everything, one area (or the news), the systems, or one node of the graph (by its key) and
 *  what it links to. */
export type Focus = {kind: 'all'} | {kind: 'cluster'; id: string} | {kind: 'systems'} | {kind: 'note'; id: string};

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
  const named = c.mentions ? `, ${plural(c.mentions, 'mention')} of one note in another` : '';
  const steps: TourStep[] = [{id: 'intro', title: 'Everything Wizard knows, as one graph',
    body: `${plural(c.notes, 'note')} across ${plural(c.areas, 'topic')}, joined by ${plural(c.links, 'connection')} (${plural(c.related, 'declared link')}${named}, the rest by shared tags). Each point is a note Wizard can look up while it answers.`,
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
      if (s.mapped?.mapped) return `${s.name} (${plural(s.mapped.mapped, 'report')} mapped)`;
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
    steps.push({id: 'news', title: 'Reading the market', focus: {kind: 'cluster', id: NEWS},
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

export function itemKey(item: NewsItem): string { return `${item.date ?? ''}|${item.title}`; }

/**
 * A demo arrival for a presentation (owner, 28 Oct 2026: "a fake 'new news article came in' animation"): one of the
 * table's own articles, shown again at the top as if it had just come in. The news table is not changed and no count
 * moves. It skips the articles already at the top and those already shown this way, and takes the next one down.
 */
export function demoArrival(latest: NewsItem[], shown: Set<string>, now: number): NewsItem | null {
  const pool = latest.slice(3).filter(item => !shown.has(itemKey(item)));
  const pick = pool[0] ?? latest.find(item => !shown.has(itemKey(item))) ?? null;
  return pick ? {...pick, date: new Date(now).toISOString(), origin: itemKey(pick)} : null;
}
