import {describe, expect, it} from 'vitest';
import {ago, cumulative, demoArrival, inFocus, itemKey, layoutBrain, nodeAt, NEWS, sunflower, tourSteps, type BrainLive, type BrainMap, type BrainNews} from './brain';

const map: BrainMap = {
  content: 'company', knowledge_synced_at: null, pg_name: 'AI Team Database',
  areas: [
    {id: 'platforms', name: 'Platforms', description: '', notes: 2},
    {id: 'datasets', name: 'Data dictionary', description: '', notes: 1},
    {id: 'glossary', name: 'Glossary', description: '', notes: 1},
  ],
  notes: [
    {id: 'platform-gscm', title: 'GSCM guide', area: 'platforms', type: 'platform', stage: 'DRAFT', summary: '', tags: [], terms: null, updated: null},
    {id: 'platform-asap', title: 'ASAP guide', area: 'platforms', type: 'platform', stage: 'SIGNED', summary: '', tags: [], terms: null, updated: null},
    {id: 'bi-sell-in', title: 'bi.sell_in', area: 'datasets', type: 'dataset', stage: 'EXPERT_CHECKED', summary: '', tags: [], terms: null, updated: null},
    {id: 'terms', title: 'Sales terms', area: 'glossary', type: 'glossary', stage: 'DRAFT', summary: '', tags: [], terms: 40, updated: null},
  ],
  links: [{source: 'bi-sell-in', target: 'platform-gscm', kind: 'related'}, {source: 'platform-asap', target: 'platform-gscm', kind: 'shared'}],
  systems: [
    {id: 'gscm', name: 'GSCM', kind: 'portal', reports: 12, documented_by: ['platform-gscm']},
    {id: 'postgresql', name: 'AI Team Database', kind: 'database', reports: null, documented_by: ['bi-sell-in']},
    {id: 'knowledge', name: 'Knowledge base', kind: 'knowledge', notes: 4, reports: null, documented_by: []},
    {id: 'attachment', name: 'Attached files', kind: 'files', reports: null, documented_by: []},
  ],
  counts: {notes: 4, areas: 3, links: 2, related: 1, glossary_terms: 40, datasets: 1, metrics: 0, signed: 1, expert_checked: 1, reports: 12, systems: 4},
};
const news: BrainNews = {status: 'ok', total: 1512, last_7_days: 90, categories: [{name: 'Competitors', count: 342}, {name: 'Smartphones', count: 285}],
  latest: [], weekly: []};
const live: BrainLive = {name: 'AI Team Database', database: {status: 'ok', relations: 412, schemas: 9}, news};

describe('the brain picture', () => {
  it('lays every note out once, in its cluster, inside the page', () => {
    const layout = layoutBrain(map, news, 1200, 800, 84);
    expect(layout.nodes.filter(n => n.kind === 'note').map(n => n.key).sort()).toEqual(['bi-sell-in', 'platform-asap', 'platform-gscm', 'terms']);
    expect(layout.clusters.map(c => c.id)).toEqual(['platforms', 'datasets', 'glossary', NEWS]);
    for (const node of layout.nodes) {
      expect(node.x).toBeGreaterThan(0); expect(node.x).toBeLessThan(1200);
      expect(node.y).toBeGreaterThan(0); expect(node.y).toBeLessThan(800 - 84);
    }
    // News sits on the right, next to its panel, with its categories sized by their articles.
    const cluster = layout.clusters.find(c => c.id === NEWS)!;
    expect(cluster.x).toBeGreaterThan(layout.center.x);
    expect(cluster.count).toBe(1512);
    const [first, second] = layout.nodes.filter(n => n.kind === 'news');
    expect(first.r).toBeGreaterThan(second.r);
    // Attached files are the person's own, not something Wizard knows: not in the ring.
    expect(layout.systems.map(s => s.id)).toEqual(['gscm', 'postgresql', 'knowledge']);
  });

  it('joins linked notes, notes to the systems they document, and every cluster to the middle', () => {
    const layout = layoutBrain(map, null, 1000, 700);
    const kinds = (kind: string) => layout.paths.filter(p => p.kind === kind).map(p => `${p.from}>${p.to}`);
    expect(kinds('link')).toEqual(['bi-sell-in>platform-gscm', 'platform-asap>platform-gscm']);
    expect(kinds('system')).toEqual(['platform-gscm>gscm', 'bi-sell-in>postgresql']);
    expect(kinds('axon')).toEqual(['platforms>wizard', 'datasets>wizard', 'glossary>wizard']);
    expect(layout.clusters.some(c => c.id === NEWS)).toBe(false);
  });

  it('lights a note and what it links to, and finds the note under the pointer', () => {
    const layout = layoutBrain(map, null, 1000, 700);
    const focus = {kind: 'note', id: 'platform-gscm'} as const;
    expect(inFocus(focus, layout, 'bi-sell-in')).toBe(true);
    expect(inFocus(focus, layout, 'gscm')).toBe(true);
    expect(inFocus(focus, layout, 'terms')).toBe(false);
    const target = layout.byKey.get('terms')!;
    expect(nodeAt(layout, target.x + 1, target.y)?.key).toBe('terms');
    expect(nodeAt(layout, 2, 2)).toBeNull();
    expect(layoutBrain(map, null, 1000, 700).nodes.map(n => [n.x, n.y])).toEqual(layout.nodes.map(n => [n.x, n.y]));
  });

  it('keeps every cluster name on the page', () => {
    for (const width of [700, 1000, 1600]) {
      for (const cluster of layoutBrain(map, news, width, 700).clusters) {
        if (cluster.side === 'right') expect(cluster.label.x + 150).toBeLessThanOrEqual(width);
        if (cluster.side === 'left') expect(cluster.label.x - 150).toBeGreaterThanOrEqual(0);
      }
    }
  });

  it('fills a disc with a sunflower', () => {
    const points = sunflower(50, 6);
    expect(points).toHaveLength(50);
    expect(Math.max(...points.map(p => Math.hypot(p.x, p.y)))).toBeLessThanOrEqual(6 * Math.sqrt(50));
  });
});

describe('the tour', () => {
  it('says only numbers the page read, and the news when there is news', () => {
    const steps = tourSteps(map, live);
    expect(steps.map(s => s.id)).toEqual(['intro', 'area-platforms', 'area-datasets', 'area-glossary', 'systems', 'news', 'ask']);
    expect(steps[0].body).toContain('4 notes across 3 topics, joined by 2 connections');
    expect(steps[3].body).toContain('40 terms');
    expect(steps[4].body).toBe('It reads GSCM (12 reports catalogued) and AI Team Database (412 tables and views), only ever with your own rights.');
    expect(steps[5].title).toBe('Reading the market');
    expect(steps[5].body).toBe('1,512 news articles curated and sorted into 2 categories, 90 articles in the last 7 days.');
    expect(steps[1].examples).toEqual(['ASAP guide', 'GSCM guide']);
    const withoutNews = tourSteps(map, {...live, news: {status: 'not_found'}});
    expect(withoutNews.map(s => s.id)).not.toContain('news');
  });

  it('shows at most six topics, the biggest, in their usual order', () => {
    const areas = Array.from({length: 9}, (_, i) => ({id: `a${i}`, name: `A${i}`, description: '', notes: i + 1}));
    const big = {...map, areas, notes: [], links: []};
    expect(tourSteps(big, null).filter(s => s.id.startsWith('area-')).map(s => s.id)).toEqual(['area-a3', 'area-a4', 'area-a5', 'area-a6', 'area-a7', 'area-a8']);
  });
});

describe('news helpers', () => {
  it('runs the weekly counts into a total and says how long ago', () => {
    expect(cumulative([{week: 'a', count: 2}, {week: 'b', count: 3}]).map(w => w.total)).toEqual([2, 5]);
    const now = Date.parse('2026-10-28T10:00:00Z');
    expect(ago('2026-10-28T09:58:00Z', now)).toBe('2 min ago');
    expect(ago('2026-10-28T05:00:00Z', now)).toBe('5 h ago');
    expect(ago('2026-10-26T10:00:00Z', now)).toBe('2 days ago');
    expect(ago(null, now)).toBe('');
  });
});

describe('the demo arrival', () => {
  const latest = Array.from({length: 6}, (_, i) => ({title: `Article ${i}`, category: 'Competitors', date: `2026-10-0${i + 1}T08:00:00Z`}));
  it('re-shows one of the table\'s own articles as just in, below the top three, never the same one twice', () => {
    const shown = new Set<string>();
    const now = Date.parse('2026-10-28T10:00:00Z');
    const first = demoArrival(latest, shown, now)!;
    expect(first.title).toBe('Article 3');
    expect(first.date).toBe('2026-10-28T10:00:00.000Z');
    expect(first.origin).toBe(itemKey(latest[3]));
    shown.add(first.origin!);
    expect(demoArrival(latest, shown, now)!.title).toBe('Article 4');
    latest.forEach(item => shown.add(itemKey(item)));
    expect(demoArrival(latest, shown, now)).toBeNull();
    expect(demoArrival([], new Set(), now)).toBeNull();
  });
});
