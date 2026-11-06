import {describe, expect, it} from 'vitest';
import type {BrainMap, BrainNews, BrainNote} from './brain';
import {brainDistance, brainScale, brainSeats, buildGraph, DEFAULT_LAYERS, EDGE_STYLE, edgeShown, focusNodes, frame, LAYERS, Layout, louvain,
  matchSeats, nearest, networkStats, nodeShown, OTHER, projector, REPORT_LINK, search, SLOTS} from './graph3d';

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

describe('portal maps', () => {
  it('draws the reports Gemini mapped in a portal around it, on a layer of their own', () => {
    const mapped: BrainMap = {...map, systems: [...map.systems, {id: 'asap', name: 'ASAP', kind: 'portal', reports: 3, documented_by: [],
      mapped: {mapped: 3, found: 5, updated: null}}],
      portal_reports: ['Sell-out by week', 'Stock by store', 'Share by brand'].map((name, i) => ({system: 'asap', id: `r${i}`, name, path: ['Sales'], status: 'mapped' as const}))};
    const graph = buildGraph(mapped, null);
    const asap = graph.byKey.get('system:asap')!;
    const reports = graph.nodes.filter(n => n.kind === 'report');
    expect(asap).toBeTruthy();  // no note documents ASAP: its mapped reports put it on the graph
    expect(reports.map(r => r.label)).toEqual(['Sell-out by week', 'Stock by store', 'Share by brand']);
    expect(reports.every(r => graph.neighbors[r.i].includes(asap.i))).toBe(true);
    expect(networkStats(graph).byKind.report).toBe(3);
    expect(networkStats(graph).byEdge.maps).toBe(3);
    expect(DEFAULT_LAYERS.has('reports')).toBe(true);
    const off = new Set([...DEFAULT_LAYERS].filter(l => l !== 'reports'));
    expect(reports.some(r => nodeShown(r, off))).toBe(false);
    expect(search(graph, 'stock by').map(n => n.label)).toEqual(['Stock by store']);
  });

  // Owner, 2 Nov 2026: "they're mapped but not interconnected no?": a report links to each note its map says defines it.
  const routed: BrainMap = {...map, systems: [...map.systems, {id: 'asap', name: 'ASAP', kind: 'portal', reports: null, documented_by: [],
    mapped: {mapped: 5, found: 5, updated: null, linked: 3, unlinked: 2}}],
  portal_reports: [
    {system: 'asap', id: 'si', name: 'Sell-in by week', path: [], status: 'mapped', definitions: ['sell-in', 'missing-note'], use_for: ['weekly sell-in']},
    {system: 'asap', id: 'both', name: 'Sell-in and dataset', path: [], status: 'mapped', definitions: ['sell-in', 'sell-in', 'bi-sell-in']},
    {system: 'asap', id: 'none', name: 'Not routed', path: [], status: 'mapped', definitions: []},
    {system: 'asap', id: 'old', name: 'From an older page', path: [], status: 'partial'},
    {system: 'asap', id: 'wide', name: 'Names every note', path: [], status: 'mapped',
      definitions: ['sell-in', 'bi-sell-in', 'terms', 'platform-gscm', 'platform-asap', 'a', 'b', 'c', 'd', 'e']},
  ]};
  const wide: BrainMap = {...routed, notes: [...routed.notes, ...['a', 'b', 'c', 'd', 'e'].map(id => note(id, 'glossary'))]};

  it('links a mapped report to each note that defines its terms, a link kind of its own, at most eight a report', () => {
    const graph = buildGraph(wide, null);
    const report = (id: string) => graph.byKey.get(`report:asap:${id}`)!;
    const named = (id: string) => graph.edges.filter(e => e.kind === 'defines' && e.a === report(id).i).map(e => graph.nodes[e.b].key);
    expect(named('si')).toEqual(['note:sell-in']);  // a note this knowledge base does not have is not drawn
    expect(named('both')).toEqual(['note:sell-in', 'note:bi-sell-in']);  // each note once
    expect(named('none')).toEqual([]);
    expect(named('wide')).toHaveLength(8);
    expect([report('si').linked, report('both').linked, report('none').linked, report('old').linked]).toEqual([1, 2, 0, undefined]);
    expect(networkStats(graph).byEdge.defines).toBe(1 + 2 + 8);
    expect(EDGE_STYLE.defines.layer).toBe('definitions');
    expect(LAYERS.find(l => l.id === 'definitions')?.edge).toBe('defines');
    expect(DEFAULT_LAYERS.has('definitions')).toBe(true);
    const link = graph.edges.find(e => e.kind === 'defines')!;
    expect(edgeShown(graph, link, DEFAULT_LAYERS)).toBe(true);
    expect(edgeShown(graph, link, new Set([...DEFAULT_LAYERS].filter(l => l !== 'definitions')))).toBe(false);
    expect(edgeShown(graph, link, new Set([...DEFAULT_LAYERS].filter(l => l !== 'reports')))).toBe(false);  // its report is hidden
    expect(REPORT_LINK).not.toBe(OTHER);
    expect(SLOTS).not.toContain(REPORT_LINK);  // never a community's colour
  });

  it('lays a report that names a note out nearer that note than one that names none', () => {
    const layout = new Layout(buildGraph(routed, null), 7, undefined, 2);
    layout.run(1000);
    const at = (key: string) => { const i = layout.graph.byKey.get(key)!.i; return [layout.pos[i * 3], layout.pos[i * 3 + 1]]; };
    const gap = (a: string, b: string) => Math.hypot(at(a)[0] - at(b)[0], at(a)[1] - at(b)[1]);
    expect(gap('report:asap:si', 'note:sell-in')).toBeLessThan(gap('report:asap:none', 'note:sell-in'));
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

// Owner, 6 Nov 2026: "Make /brain page an actual brain shape, keep the colors and dots".
describe('the brain', () => {
  it('is a brain: two hemispheres with a gap between them, the cerebellum under the back, the stem below', () => {
    const inside = (x: number, y: number, z: number) => brainDistance(x, y, z).e <= 1;
    expect(inside(0, 0.3, 0.42)).toBe(true);     // a hemisphere
    expect(inside(0, 0.3, -0.42)).toBe(true);    // the other
    expect(inside(0, 0.6, 0)).toBe(false);       // the gap between them
    expect(inside(0.85, 0.1, 0.4)).toBe(true);   // the front
    expect(inside(-0.55, -0.4, 0)).toBe(true);   // the cerebellum, across the middle
    expect(inside(-0.16, -0.75, 0)).toBe(true);  // the brain stem
    expect(inside(0.5, -0.75, 0.3)).toBe(false); // nothing under the front
    expect(inside(0, 0.9, 0.42)).toBe(false);    // nothing above the top
    expect(brainDistance(0, 0.6, 0, 2).e).toBeLessThanOrEqual(1);  // side on (2D) the hemispheres are one outline
    expect(brainScale(600)).toBeGreaterThan(brainScale(100));       // a bigger knowledge base makes a bigger brain
    expect(brainScale(1)).toBe(brainScale(3));                      // and a tiny one is still a brain
  });

  it('lays every point out inside the brain, in 2D and 3D, and the same every time', () => {
    const graph = buildGraph(map, news);
    for (const dims of [2, 3] as const) {
      const layout = new Layout(graph, 7, undefined, dims);
      layout.run(1000);
      expect(layout.settled).toBe(true);
      for (let i = 0; i < graph.nodes.length; i++) {
        const [x, y, z] = [0, 1, 2].map(k => layout.pos[i * 3 + k] / layout.brain);
        expect(brainDistance(x, y, z, dims).e).toBeLessThanOrEqual(1.0001);
      }
      const again = new Layout(graph, 7, undefined, dims);
      again.run(1000);
      expect(Array.from(again.pos)).toEqual(Array.from(layout.pos));
    }
  });

  it('gives each point a place of its own spread through the brain, and points that sit together places together', () => {
    const seats = brainSeats(200, 3, 100);
    for (let i = 0; i < 200; i++) expect(brainDistance(seats[i * 3] / 100, seats[i * 3 + 1] / 100, seats[i * 3 + 2] / 100).e).toBeLessThanOrEqual(1);
    expect(Array.from(brainSeats(200, 3, 100))).toEqual(Array.from(seats));
    // Two groups of points, one behind the other: each takes the places on its own side.
    const pos = new Float32Array(200 * 3);
    for (let i = 0; i < 200; i++) pos.set([i < 100 ? -500 - i : 500 + i, (i * 37) % 50, (i * 11) % 30], i * 3);
    const of = matchSeats(pos, seats, 200, 3);
    expect(new Set(of).size).toBe(200);  // every place taken once
    const back = Array.from(of.slice(0, 100), s => seats[s * 3]), front = Array.from(of.slice(100), s => seats[s * 3]);
    expect(Math.max(...back)).toBeLessThanOrEqual(Math.min(...front));
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
    expect(nearest(points, 83, 80, 5, 2)).toBeNull();  // only the first `count` points of a reused list are drawn
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
