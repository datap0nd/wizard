import {describe, expect, it} from 'vitest';
import type {BrainMap, BrainNews} from './brain';
import {AREA_SLOTS, buildGraph, DEFAULT_LAYERS, edgeShown, focusNodes, frame, Layout, nearest, networkStats, nodeShown, OTHER_AREA, projector, search} from './graph3d';

const map: BrainMap = {
  content: 'company', knowledge_synced_at: null, pg_name: 'AI Team Database',
  areas: [
    {id: 'platforms', name: 'Platforms', description: '', notes: 2},
    {id: 'datasets', name: 'Data dictionary', description: '', notes: 1},
    {id: 'metrics', name: 'Metrics', description: '', notes: 1},
    {id: 'glossary', name: 'Glossary', description: '', notes: 1},
    {id: 'faq', name: 'Executive questions', description: '', notes: 0},
  ],
  notes: [
    {id: 'platform-gscm', title: 'GSCM guide', area: 'platforms', type: 'platform', stage: 'DRAFT', summary: '', tags: ['gscm', 'sell-in', 'stock'], terms: null, updated: null},
    {id: 'platform-asap', title: 'ASAP guide', area: 'platforms', type: 'platform', stage: 'SIGNED', summary: '', tags: ['asap', 'stock'], terms: null, updated: null},
    {id: 'bi-sell-in', title: 'bi.sell_in', area: 'datasets', type: 'dataset', stage: 'EXPERT_CHECKED', summary: '', tags: ['sell-in', 'weekly'], terms: null, updated: null},
    {id: 'sell-in', title: 'Sell-in', area: 'metrics', type: 'metric', stage: 'SIGNED', summary: '', tags: ['sell-in', 'weekly', 'stock'], terms: null, updated: null},
    {id: 'terms', title: 'Sales terms', area: 'glossary', type: 'glossary', stage: 'DRAFT', summary: '', tags: ['glossary'], terms: 2, updated: null},
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
  counts: {notes: 5, areas: 4, links: 3, related: 1, mentions: 1, glossary_terms: 2, datasets: 1, metrics: 1, signed: 2, expert_checked: 1, reports: 15, systems: 5},
};
const news: BrainNews = {status: 'ok', total: 1512, categories: [{name: 'Competitors', count: 342}, {name: 'Smartphones', count: 85}]};

describe('the knowledge graph', () => {
  it('draws what was read: the root, areas with notes, notes, links, shared tags, terms, documented systems and the news', () => {
    const graph = buildGraph(map, news);
    const keys = (kind: string) => graph.nodes.filter(n => n.kind === kind).map(n => n.key);
    expect(keys('root')).toEqual(['kb']);
    expect(keys('area')).toEqual(['area:platforms', 'area:datasets', 'area:metrics', 'area:glossary']);  // no empty area
    expect(keys('note')).toHaveLength(5);
    expect(keys('tag').sort()).toEqual(['tag:sell-in', 'tag:stock', 'tag:weekly']);  // tags on one note are not drawn
    expect(keys('term')).toEqual(['term:terms:GSCM', 'term:terms:SI']);  // a term of a note that is not loaded is left out
    expect(keys('system')).toEqual(['system:gscm', 'system:postgresql']);  // the knowledge base is the root; NERP documents nothing
    expect(keys('news')).toEqual(['news']);
    expect(keys('category')).toEqual(['news:Competitors', 'news:Smartphones']);
    const kinds = graph.edges.map(e => `${e.kind}:${graph.nodes[e.a].key}>${graph.nodes[e.b].key}`);
    expect(kinds).toContain('related:note:bi-sell-in>note:sell-in');
    expect(kinds).toContain('mention:note:platform-gscm>note:sell-in');
    expect(kinds).toContain('documents:system:gscm>note:platform-gscm');
    expect(kinds).toContain('news:system:postgresql>news');
    expect(kinds).toContain('term:note:terms>term:terms:GSCM');
    const noNews = buildGraph(map, null);
    expect(noNews.nodes.some(n => n.group === 'news')).toBe(false);
    expect(noNews.byKey.has('system:postgresql')).toBe(true);  // still documented by a dataset note
  });

  it('colours areas in their own order from the validated palette, then grey', () => {
    const many = {...map, areas: Array.from({length: 10}, (_, k) => ({id: `a${k}`, name: `A${k}`, description: '', notes: 1})),
      notes: Array.from({length: 10}, (_, k) => ({...map.notes[0], id: `n${k}`, area: `a${k}`}))};
    const colors = buildGraph(many, null).areaColors;
    expect([...colors.values()].slice(0, 8)).toEqual(AREA_SLOTS);
    expect(colors.get('a8')).toBe(OTHER_AREA);
    expect(buildGraph(map, null).byKey.get('term:terms:GSCM')!.color).toBe(buildGraph(map, null).byKey.get('area:glossary')!.color);
  });

  it('sizes a note by its links to other notes', () => {
    const graph = buildGraph(map, null);
    expect(graph.byKey.get('note:sell-in')!.size).toBeGreaterThan(graph.byKey.get('note:terms')!.size);
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
  it('settles the same way every time, areas apart and each note nearer its own area', () => {
    const graph = buildGraph(map, news);
    const first = new Layout(graph);
    expect(first.run(1000)).toBeLessThan(1000);
    expect(first.settled).toBe(true);
    const again = new Layout(graph);
    again.run(1000);
    expect(Array.from(again.pos)).toEqual(Array.from(first.pos));
    expect(Array.from(first.pos).every(Number.isFinite)).toBe(true);
    const at = (key: string) => { const i = graph.byKey.get(key)!.i; return [0, 1, 2].map(k => first.pos[i * 3 + k]); };
    const gap = (a: string, b: string) => Math.hypot(...at(a).map((v, k) => v - at(b)[k]));
    expect(gap('note:terms', 'area:glossary')).toBeLessThan(gap('note:terms', 'area:platforms'));
    expect(gap('term:terms:GSCM', 'note:terms')).toBeLessThan(gap('term:terms:GSCM', 'area:platforms'));
  });

  it('keeps the places of a knowledge base it laid out before', () => {
    const graph = buildGraph(map, null);
    const before = new Layout(graph);
    before.run(1000);
    const after = new Layout(buildGraph(map, news), 7, {graph, pos: before.pos});
    const i = graph.byKey.get('note:sell-in')!.i, j = after.graph.byKey.get('note:sell-in')!.i;
    expect([after.pos[j * 3], after.pos[j * 3 + 1]]).toEqual([before.pos[i * 3], before.pos[i * 3 + 1]]);
    expect(after.alpha).toBeCloseTo(1 - (graph.nodes.length / after.graph.nodes.length));
    expect(new Layout(graph, 7, {graph, pos: before.pos}).alpha).toBe(0.08);
    const midway = new Layout(graph);
    midway.run(20);
    expect(new Layout(buildGraph(map, news), 7, {graph, pos: midway.pos, alpha: midway.alpha}).alpha).toBe(midway.alpha);  // still settling: it carries on
  });

  it('lays out a big knowledge base with the octree in reasonable time', () => {
    const notes = Array.from({length: 600}, (_, k) => ({...map.notes[0], id: `n${k}`, title: `Note ${k}`, area: `a${k % 9}`,
      tags: [`t${k % 40}`, `t${(k * 7) % 40}`]}));
    const big: BrainMap = {...map, notes, areas: Array.from({length: 9}, (_, k) => ({id: `a${k}`, name: `A${k}`, description: '', notes: 1})),
      links: notes.slice(1).map((n, k) => ({source: notes[k].id, target: n.id, kind: 'related' as const})), terms: []};
    const layout = new Layout(buildGraph(big, null));
    const started = performance.now();
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
    const turned = projector({...camera, yaw: Math.PI / 2}, 800, 600)(100, 0, 0);
    expect(turned.x).toBeCloseTo(400);
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
  it('lights an area, the systems with what they document, the news with its database, or one node and its neighbours', () => {
    const graph = buildGraph(map, news);
    const names = (set: Set<number> | null) => set && [...set].map(i => graph.nodes[i].key).sort();
    expect(focusNodes(graph, {kind: 'all'})).toBeNull();
    expect(names(focusNodes(graph, {kind: 'cluster', id: 'glossary'}))).toEqual(['area:glossary', 'note:terms', 'term:terms:GSCM', 'term:terms:SI']);
    expect(names(focusNodes(graph, {kind: 'cluster', id: 'news'}))).toEqual(['news', 'news:Competitors', 'news:Smartphones', 'system:postgresql']);
    expect(names(focusNodes(graph, {kind: 'systems'}))).toContain('note:platform-gscm');
    expect(names(focusNodes(graph, {kind: 'note', id: 'note:bi-sell-in'}))).toEqual(['area:datasets', 'note:bi-sell-in', 'note:sell-in', 'system:postgresql', 'tag:sell-in', 'tag:weekly']);
  });

  it('finds notes, terms and tags by name, exact names first', () => {
    const graph = buildGraph(map, news);
    expect(search(graph, 'gscm').map(n => n.key)).toEqual(['term:terms:GSCM', 'system:gscm', 'note:platform-gscm']);
    expect(search(graph, 'GSCM')[0].key).toBe('term:terms:GSCM');
    expect(search(graph, 'gscm g')[0].key).toBe('note:platform-gscm');
    expect(search(graph, '#stock')[0].key).toBe('tag:stock');
    expect(search(graph, 'sell_in')[0].key).toBe('note:bi-sell-in');
    expect(search(graph, '   ')).toEqual([]);
  });
});

describe('the network statistics', () => {
  it('measures the note network: density, degree, clustering, components, modularity by area, paths', () => {
    const stats = networkStats(buildGraph(map, news));
    expect(stats.notes).toBe(5);
    expect(stats.links).toBe(3);
    expect(stats.density).toBeCloseTo(0.3);
    expect(stats.meanDegree).toBeCloseTo(1.2);
    expect(stats.maxDegree).toBe(2);
    expect(stats.isolated).toBe(1);
    expect(stats.components).toBe(2);
    expect(stats.largest).toBeCloseTo(0.8);
    expect(stats.clustering).toBe(0);  // a chain, no triangles
    expect(stats.pathLength).toBeCloseTo(20 / 12);  // the chain asap - gscm - sell-in - bi.sell_in
    expect(stats.diameter).toBe(3);
    expect(stats.byKind.term).toBe(2);
    expect(stats.byEdge.related).toBe(1);
    expect(stats.histogram.map(b => [b.label, b.count])).toEqual([['0', 1], ['1', 2], ['2', 2]]);
    // Areas as communities: no link inside an area here, so Q is below zero.
    expect(stats.modularity).toBeLessThan(0);
  });

  it('counts a triangle and a community', () => {
    const tri: BrainMap = {...map, links: [
      {source: 'platform-gscm', target: 'platform-asap', kind: 'related'},
      {source: 'platform-asap', target: 'bi-sell-in', kind: 'related'},
      {source: 'bi-sell-in', target: 'platform-gscm', kind: 'related'},
    ], terms: []};
    const stats = networkStats(buildGraph(tri, null));
    expect(stats.clustering).toBeCloseTo(3 / 5);
    expect(stats.modularity).toBeCloseTo(1 / 3 - (4 / 6) ** 2 - (2 / 6) ** 2);
  });
});
