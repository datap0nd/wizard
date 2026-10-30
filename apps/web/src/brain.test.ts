import {describe, expect, it} from 'vitest';
import {ago, cumulative, demoArrival, itemKey, tourSteps, type BrainLive, type BrainMap, type BrainNews} from './brain';

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

describe('the tour', () => {
  it('says only numbers the page read, and the news when there is news', () => {
    const steps = tourSteps(map, live);
    expect(steps.map(s => s.id)).toEqual(['intro', 'area-platforms', 'area-datasets', 'area-glossary', 'systems', 'news', 'ask']);
    expect(steps[0].title).toBe('Everything Wizard knows, as one graph');
    expect(steps[0].body).toContain('4 notes across 3 topics, joined by 2 connections (1 declared link, the rest by shared tags)');
    expect(tourSteps({...map, counts: {...map.counts, mentions: 5}}, live)[0].body).toContain('1 declared link, 5 mentions of one note in another');
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
