import {describe, expect, it} from 'vitest';
import type {BrainMap, BrainNews, BrainNote} from './brain';
import {buildGraph, DEFAULT_LAYERS, edgeShown, focusNodes, frame, Layout, louvain, nearest, networkStats, nodeShown, OTHER, projector, search,
  SLOTS} from './graph3d';

const note = (id: string, area: string, extra: Partial<BrainNote> = {}): BrainNote =>
  ({id, title: id, area, type: null, stage: 'DRAFT', summary: '', tags: [], terms: null, updated: null, ...extra});
const base = {content: 'company' as const, knowledge_synced_at: null, pg_name: 'AI Team Database', systems: [], terms: [],
  counts: {notes: 0, areas: 0, links: 0, related: 0, glossary_terms: 0, datasets: 0, metrics: 0, signed: 0, expert_checked: 0, reports: 0, systems: 0}};

const map: BrainMap = {
  ...base,
  areas: [
    {id: 'platforms', name: 'Platforms', description: '', notes: 2},
    {id: 'datasets', name: 'Data dictionary', description: '', notes: 1},
    {id: 'metrics', name: 'Metrics', description: '', notes: 1},
    {id: 'glossary', name: 'Glossary', description: '', notes: 1},
    {id: 'faq', name: 'Executive questions', description: '', notes: 0},
  ],
  notes: [
    note('platform-gscm', 'platforms', {title: 'GSCM guide', type: 'platform', tags: ['gscm', 'sell-in', 'stock']}),
    note('platform-asap', 'platforms', {title: 'ASAP guide', type: 'platform', stage: 'SIGNED', tags: ['asap', 'stock']}),
    note('bi-sell-in', 'datasets', {title: 'bi.sell_in', type: 'dataset', tags: ['sell-in', 'weekly']}),
    note('sell-in', 'metrics', {title: 'Sell-in', type: 'metric', tags: ['sell-in', 'weekly', 'stock']}),
    note('terms', 'glossary', {title: 'Sales terms', type: 'glossary', tags: ['glossary'], terms: 2}),
  ],
  links: [
    {source: 'bi-sell-in', target: 'sell-in', kind: 'related'},
    {source: 'platform-gscm', target: 'sell-in', kind: 'mention', weight: 3},
    {source: 'platform-asap', target: 'platform-gscm', kind: 'shared', weight: 1},
  ],
  terms: [{note: 'terms', term: 'GSCM'}, {note: 'terms', term: 'SI'}, {note: 'missing', term: 'X'}],
  systems: [
    {id: 'gscm', name: 'GSCM', kind: 'portal', reports: 12, documented_by: ['platform-gscm']},
    {id: 'postgresql', name: 'AI Team Database', kind: 'database', reports: null, documented_by: ['bi-sell-in']},
    {id: 'knowledge', name: 'Knowledge base', kind: 'knowledge', notes: 5, reports: null, documented_by: []},
    {id: 'nerp', name: 'NERP', kind: 'portal', reports: 3, documented_by: []},
    {id: 'attachment', name: 'Attached files', kind: 'files', reports: null, documented_by: []},
  ],
};
const news: BrainNews = {status: 'ok', total: 1512, categories: [{name: 'Competitors', count: 342}, {name: 'Smartphones', count: 85}]};
/** Two triangles of notes joined by one link, and a note on its own. */
const twins: BrainMap = {...base, areas: [{id: 'a', name: 'A', description: '', notes: 4}, {id: 'b', name: 'B', description: '', notes: 3}],
  notes: ['a1', 'a2', 'a3', 'b1', 'b2', 'b3'].map(id => note(id, id === 'b1' ? 'a' : id[0])).concat(note('alone', 'a')),
  links: [['a1', 'a2'], ['a2', 'a3'], ['a3', 'a1'], ['b1', 'b2'], ['b2', 'b3'], ['b3', 'b1'], ['a1', 'b1']]
    .map(([source, target]) => ({source, target, kind: 'related' as const}))};

describe('the knowledge graph', () => {
  it('draws what was read: notes, links, shared tags, terms, documented systems and the news, with no made-up hubs', () => {
    const graph = buildGraph(map, news);
    const keys = (kind: string) => graph.nodes.filter(n => n.kind === kind).map(n => n.key);
    expect(keys('note')).toHaveLength(5);
    expect(keys('tag').sort()).toEqual(['tag:sell-in', 'tag:stock', 'tag:weekly']);  // tags on one note are not drawn
    expect(keys('term')).toEqual(['term:terms:GSCM', 'term:terms:SI']);  // a term of a note that is not loaded is left out
    expect(keys('system')).toEqual(['system:gscm', 'system:postgresql']);  // NERP documents nothing; the knowledge base is the graph
    expect(keys('news')).toEqual(['news']);
    expect(keys('category')).toEqual(['news:Competitors', 'news:Smartphones']);
    const kinds = graph.edges.map(e => `${e.kind}:${graph.nodes[e.a].key}>${graph.nodes[e.b].key}`);
    expect(kinds).toContain('related:note:bi-sell-in>note:sell-in');
    expect(kinds).toContain('mention:note:platform-gscm>note:sell-in');
    expect(kinds).toContain('documents:system:gscm>note:platform-gscm');
    expect(kinds).toContain('news:system:postgresql>news');
    expect(kinds).toContain('term:note:terms>term:terms:GSCM');
    expect(buildGraph(map, null).nodes.some(n => n.group === 'news')).toBe(false);
  });

  it('finds the communities the links form, names each by its most linked note and gathers the points without a link', () => {
    const graph = buildGraph(twins, null);
    const of = (id: string) => graph.byKey.get(`note:${id}`)!.community;
    expect(of('a1')).toBe(of('a2'));
    expect(of('a1')).toBe(of('a3'));
    expect(of('b2')).toBe(of('b3'));
    expect(of('b1')).toBe(of('b2'));  // the links decide, not the folder (b1 sits in area a)
    expect(of('a1')).not.toBe(of('b1'));
    expect(graph.communities.map(c => [c.name, c.size, !!c.alone])).toEqual([['a1', 3, false], ['b1', 3, false], ['Without links', 1, true]]);
    expect(graph.communities.map(c => c.color)).toEqual([SLOTS[0], SLOTS[1], OTHER]);
    expect(louvain(4, [{a: 0, b: 1, w: 1}, {a: 2, b: 3, w: 1}])).toEqual(Int32Array.from([0, 0, 1, 1]));
    expect(Array.from(louvain(6, twins.links.slice(0, 6).map((_, k) => ({a: Math.floor(k / 3) * 3 + (k % 3), b: Math.floor(k / 3) * 3 + ((k + 1) % 3), w: 1}))))).toEqual([0, 0, 0, 1, 1, 1]);
  });

  it('colours the eight largest communities from the validated palette, then grey', () => {
    const pairs: BrainMap = {...base, areas: [{id: 'x', name: 'X', description: '', notes: 20}],
      notes: Array.from({length: 20}, (_, k) => note(`n${String(k).padStart(2, '0')}`, 'x')),
      links: Array.from({length: 10}, (_, k) => ({source: `n${String(k * 2).padStart(2, '0')}`, target: `n${String(k * 2 + 1).padStart(2, '0')}`, kind: 'related' as const}))};
    const graph = buildGraph(pairs, null);
    expect(graph.communities).toHaveLength(10);
    expect(graph.communities.map(c => c.color)).toEqual([...SLOTS, OTHER, OTHER]);
    expect(graph.areaColors.get('x')).toBe(SLOTS[0]);
  });

  it('sizes a point by its links, so hubs stand out', () => {
    const graph = buildGraph(map, null);
    expect(graph.byKey.get('note:sell-in')!.size).toBeGreaterThan(graph.byKey.get('term:terms:SI')!.size);
  });

  it('switches layers off without dropping what they join', () => {
    const graph = buildGraph(map, news);
    const off = new Set(DEFAULT_LAYERS);
    off.delete('tags');
    expect(nodeShown(graph.byKey.get('tag:stock')!, off)).toBe(false);
    expect(nodeShown(graph.byKey.get('note:sell-in')!, off)).toBe(true);
    expect(graph.edges.filter(e => e.kind === 'tagged').every(e => !edgeShown(graph, e, off))).toBe(true);
    expect(DEFAULT_LAYERS.has('shared')).toBe(false);  // shared tags repeat what the tag points show; off at first
  });
});

describe('the layout', () => {
  const at = (layout: Layout, key: string) => { const i = layout.graph.byKey.get(key)!.i; return [0, 1, 2].map(k => layout.pos[i * 3 + k]); };
  const gap = (layout: Layout, a: string, b: string) => Math.hypot(...at(layout, a).map((v, k) => v - at(layout, b)[k]));

  it('settles the same way every time, flat in 2D, each community together', () => {
    const graph = buildGraph(twins, null);
    const first = new Layout(graph, 7, undefined, 2);
    expect(first.run(1000)).toBeLessThan(1000);
    expect(first.settled).toBe(true);
    const again = new Layout(graph, 7, undefined, 2);
    again.run(1000);
    expect(Array.from(again.pos)).toEqual(Array.from(first.pos));
    expect(graph.nodes.every(n => first.pos[n.i * 3 + 2] === 0)).toBe(true);
    expect(gap(first, 'note:a2', 'note:a3')).toBeLessThan(gap(first, 'note:a2', 'note:b3'));
    expect(gap(first, 'note:b2', 'note:b3')).toBeLessThan(gap(first, 'note:b2', 'note:a3'));
  });

  it('settles in 3D too, and keeps the places of a knowledge base it laid out before', () => {
    const graph = buildGraph(map, null);
    const before = new Layout(graph);
    before.run(1000);
    expect(Array.from(before.pos).every(Number.isFinite)).toBe(true);
    expect(graph.nodes.some(n => before.pos[n.i * 3 + 2] !== 0)).toBe(true);
    const after = new Layout(buildGraph(map, news), 7, {graph, pos: before.pos});
    const i = graph.byKey.get('note:sell-in')!.i, j = after.graph.byKey.get('note:sell-in')!.i;
    expect([after.pos[j * 3], after.pos[j * 3 + 1]]).toEqual([before.pos[i * 3], before.pos[i * 3 + 1]]);
    expect(after.alpha).toBeCloseTo(1 - (graph.nodes.length / after.graph.nodes.length));
    expect(new Layout(graph, 7, {graph, pos: before.pos}).alpha).toBe(0.08);
    const midway = new Layout(graph);
    midway.run(20);
    expect(new Layout(buildGraph(map, news), 7, {graph, pos: midway.pos, alpha: midway.alpha}).alpha).toBe(midway.alpha);  // still settling: it carries on
  });

  it('lays out a big knowledge base with the tree in reasonable time', () => {
    const notes = Array.from({length: 600}, (_, k) => note(`n${k}`, `a${k % 9}`, {tags: [`t${k % 40}`, `t${(k * 7) % 40}`]}));
    const big: BrainMap = {...base, notes, areas: Array.from({length: 9}, (_, k) => ({id: `a${k}`, name: `A${k}`, description: '', notes: 1})),
      links: notes.slice(1).map((n, k) => ({source: notes[k].id, target: n.id, kind: 'related' as const}))};
    const graph = buildGraph(big, null);
    const started = performance.now();
    const layout = new Layout(graph, 7, undefined, 2);
    layout.run(60);
    expect(performance.now() - started).toBeLessThan(6000);
    expect(Array.from(layout.pos).every(Number.isFinite)).toBe(true);
  });
});

describe('the camera', () => {
  it('projects the target to the middle, nearer points bigger, and frames what it is asked to', () => {
    const camera = {yaw: 0, pitch: 0, distance: 300, tx: 0, ty: 0, tz: 0};
    const project = projector(camera, 800, 600);
    expect(project(0, 0, 0)).toMatchObject({x: 400, y: 300, depth: 300});
    expect(project(0, 50, 0).y).toBeLessThan(300);  // up is up
    expect(project(0, 0, -100).scale).toBeGreaterThan(project(0, 0, 100).scale);
    expect(projector(camera, 800, 600, 200)(0, 0, 0).x).toBe(500);  // the panels on the left move the middle right
    expect(projector(camera, 800, 600, 0, 100)(0, 0, 0).y).toBe(250);  // and the strip along the bottom moves it up
    expect(projector({...camera, yaw: Math.PI / 2}, 800, 600)(100, 0, 0).x).toBeCloseTo(400);
    const pos = Float32Array.from([0, 0, 0, 100, 0, 0, -100, 0, 0]);
    const framed = frame(pos, [0, 1, 2]);
    expect(framed.tx).toBeCloseTo(0);
    const edge = projector({...camera, ...framed}, 800, 600)(100, 0, 0);
    expect(edge.x).toBeLessThan(800);
    expect(edge.x).toBeGreaterThan(400);
  });

  it('picks the nearest point under the pointer, the front one on a tie', () => {
    const points = [{i: 1, x: 10, y: 10, r: 4, depth: 200}, {i: 2, x: 11, y: 10, r: 4, depth: 100}, {i: 3, x: 80, y: 80, r: 2, depth: 50}];
    expect(nearest(points, 11, 10)).toBe(2);
    expect(nearest(points, 40, 40)).toBeNull();
    expect(nearest(points, 83, 80)).toBe(3);
  });
});

describe('focus and search', () => {
  it('lights an area, a community, the systems, the news with its database, or one point and its neighbours', () => {
    const graph = buildGraph(map, news);
    const names = (set: Set<number> | null) => set && [...set].map(i => graph.nodes[i].key).sort();
    expect(focusNodes(graph, {kind: 'all'})).toBeNull();
    expect(names(focusNodes(graph, {kind: 'cluster', id: 'glossary'}))).toEqual(['note:terms', 'term:terms:GSCM', 'term:terms:SI']);
    expect(names(focusNodes(graph, {kind: 'cluster', id: 'news'}))).toEqual(['news', 'news:Competitors', 'news:Smartphones', 'system:postgresql']);
    expect(names(focusNodes(graph, {kind: 'systems'}))).toContain('note:platform-gscm');
    expect(names(focusNodes(graph, {kind: 'note', id: 'note:bi-sell-in'}))).toEqual(['note:bi-sell-in', 'note:sell-in', 'system:postgresql', 'tag:sell-in', 'tag:weekly']);
    const glossary = graph.byKey.get('note:terms')!.community;
    expect(names(focusNodes(graph, {kind: 'community', id: glossary}))).toContain('term:terms:SI');
  });

  it('finds notes, terms and tags by name, exact names first', () => {
    const graph = buildGraph(map, news);
    expect(search(graph, 'gscm').map(n => n.key)).toEqual(['term:terms:GSCM', 'system:gscm', 'note:platform-gscm']);
    expect(search(graph, 'gscm g')[0].key).toBe('note:platform-gscm');
    expect(search(graph, '#stock')[0].key).toBe('tag:stock');
    expect(search(graph, 'sell_in')[0].key).toBe('note:bi-sell-in');
    expect(search(graph, '   ')).toEqual([]);
  });
});

describe('the network statistics', () => {
  it('measures a triangle and a note on its own', () => {
    const tri: BrainMap = {...base, areas: [{id: 'a', name: 'A', description: '', notes: 4}], notes: ['x', 'y', 'z', 'w'].map(id => note(id, 'a')),
      links: [['x', 'y'], ['y', 'z'], ['z', 'x']].map(([source, target]) => ({source, target, kind: 'related' as const}))};
    const stats = networkStats(buildGraph(tri, null));
    expect([stats.nodes, stats.edges, stats.maxDegree, stats.isolated, stats.components, stats.communities]).toEqual([4, 3, 2, 1, 2, 1]);
    expect(stats.density).toBeCloseTo(0.5);
    expect(stats.meanDegree).toBeCloseTo(1.5);
    expect(stats.largest).toBeCloseTo(0.75);
    expect(stats.clustering).toBeCloseTo(0.75);
    expect(stats.pathLength).toBeCloseTo(1);
    expect(stats.diameter).toBe(1);
    expect(stats.modularity).toBeCloseTo(0);  // one community holding every link
    expect(stats.histogram.map(b => [b.label, b.count])).toEqual([['0', 1], ['1', 0], ['2', 3]]);
  });

  it('measures two communities joined by one link', () => {
    const stats = networkStats(buildGraph(twins, null));
    expect(stats.communities).toBe(2);
    expect(stats.modularity).toBeCloseTo(2 * (3 / 7 - (7 / 14) ** 2));
    expect(stats.areaModularity).toBeLessThan(stats.modularity);  // the folders split b1 from its triangle
    expect(stats.diameter).toBe(3);
    expect(stats.byEdge.related).toBe(7);
  });
});
