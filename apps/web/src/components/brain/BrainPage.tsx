import {useCallback, useEffect, useMemo, useRef, useState} from 'react';
import {ArrowLeft, ArrowRight, BadgeCheck, ExternalLink, Maximize2, MessageSquareText, Minus, Pause, Play, Plus, RotateCcw, Search, Upload, X} from 'lucide-react';
import {api} from '@/api';
import {demoArrival, itemKey, NEWS, plural, ringSystems, tourSteps, type BrainLive, type BrainMap, type BrainSnapshot, type Focus, type NewsItem} from '@/brain';
import mark from '@/assets/wizard-mark.svg';
import {formatDate} from '@/format';
import {buildGraph, DEFAULT_LAYERS, focusNodes, LAYERS, networkStats, OTHER, search, type EdgeKind, type GNode, type Graph,
  type LayerId, type NetworkStats} from '@/graph3d';
import {cn} from '@/lib/utils';
import type {Bootstrap} from '@/types';
import {LoginScreen} from '../LoginScreen';
import {Graph3D, type GraphControl} from './Graph3D';
import {NewsMissing, NewsPanel} from './NewsPanel';

const REFRESH_MS = 10 * 60_000;
const FRESH_MS = 5 * 60_000;
const ARRIVE_AFTER_MS = 2500;  // on the tour's news step, the demo arrival comes this long after the step opens
const STAGE_NAMES = {SIGNED: 'Signed by its owner', EXPERT_CHECKED: 'Checked by an expert', DRAFT: 'Draft'} as const;
const PANEL = 252;             // the panels on the left of the graph; the camera centres on what is left
const STRIP = 52;              // the statistics along the bottom
const KIND_NAMES: Record<GNode['kind'], string> = {note: 'Note', tag: 'Tag', term: 'Glossary term', system: 'System', report: 'Portal report',
  news: 'News table', category: 'News category'};
const EDGE_NAMES: Record<EdgeKind, string> = {related: 'related', mention: 'mentions', shared: 'shared tags', tagged: 'tagged', term: 'term',
  documents: 'documents', maps: 'mapped', news: 'news'};
const EDGE_ORDER: EdgeKind[] = ['related', 'mention', 'documents', 'maps', 'shared', 'term', 'news', 'tagged'];
const UNGROUPED = '#6e7681';   // tags, systems and the news when colouring by area

type ColourBy = 'community' | 'area';
type Pin = {kind: 'community'; id: number} | {kind: 'cluster'; id: string} | null;

function useReducedMotion(): boolean {
  const [reduced] = useState(() => typeof matchMedia === 'function' && matchMedia('(prefers-reduced-motion: reduce)').matches);
  return reduced;
}

function fixed(value: number | null, digits: number): string {
  return value === null || Number.isNaN(value) ? '–' : value.toFixed(digits);
}

/** The graph's statistics (graph3d.ts, networkStats) as an instrument strip along the bottom: as many readings as there
 *  is room for (the rest wrap out of sight), each explained on hover, after the degree distribution. */
function StatsStrip({stats}: {stats: NetworkStats}) {
  const rows: [string, string, string][] = [
    ['Nodes', stats.nodes.toLocaleString(), `${stats.byKind.note} notes, ${stats.byKind.term} glossary terms, ${stats.byKind.tag} tags, ${stats.byKind.system} systems, ${stats.byKind.report} portal reports, ${stats.byKind.category} news categories`],
    ['Edges', stats.edges.toLocaleString(), `${stats.byEdge.related} related, ${stats.byEdge.mention} mentions, ${stats.byEdge.shared} shared tags, ${stats.byEdge.tagged} tagged, ${stats.byEdge.term} terms, ${stats.byEdge.documents} documenting a system, ${stats.byEdge.maps} reports mapped in a portal`],
    ['Communities', stats.communities.toLocaleString(), 'groups the links form (Louvain), each named by its most linked note'],
    ['Modularity Q', fixed(stats.modularity, 3), `how far links stay inside their community (by area: ${fixed(stats.areaModularity, 3)})`],
    ['⟨k⟩', fixed(stats.meanDegree, 2), 'mean degree: links per point'],
    ['k max', stats.maxDegree.toLocaleString(), 'the most linked point'],
    ['Density ρ', fixed(stats.density, 4), 'the share of all possible pairs of points that are linked'],
    ['Clustering ⟨C⟩', fixed(stats.clustering, 3), 'average local clustering coefficient (Watts and Strogatz)'],
    ['Components', stats.components.toLocaleString(), `the largest holds ${(stats.largest * 100).toFixed(1)}% of the points; ${stats.isolated} without a link`],
    ['Path ⟨ℓ⟩', fixed(stats.pathLength, 2), `mean shortest path in the largest component${stats.sampled ? ', from 200 points' : ''}`],
    ['Diameter D', stats.diameter === null ? '–' : `${stats.sampled ? '≥ ' : ''}${stats.diameter}`, 'the longest shortest path between two points'],
  ];
  const most = Math.max(1, ...stats.histogram.map(b => b.count));
  return (
    <div className="flex min-w-0 flex-1 items-center gap-4" data-testid="brain-stats">
      <figure className="h-[34px] shrink-0" title="Degree distribution: points by their number of links k">
        <figcaption className="text-[10px] leading-[14px] text-slate-500">P(k)</figcaption>
        <div className="flex h-[18px] w-[72px] items-end gap-[2px]" role="img" aria-label={`Degree distribution: ${stats.histogram.map(b => `k ${b.label}: ${b.count}`).join(', ')}`}>
          {stats.histogram.map(bin => (
            <div key={bin.label} className="flex h-full flex-1 flex-col justify-end" title={`k = ${bin.label}: ${plural(bin.count, 'point')}`}>
              <div className="rounded-t-[1.5px] bg-[#3987e5] hover:bg-[#6da7ec]" style={{height: `${Math.max(bin.count ? 8 : 0, (bin.count / most) * 100)}%`}} />
            </div>
          ))}
        </div>
      </figure>
      <dl className="flex h-[34px] min-w-0 flex-1 flex-wrap gap-x-4 overflow-hidden">
        {rows.map(([label, value, help]) => (
          <div key={label} className="h-[34px] shrink-0" title={help} data-testid="brain-stat">
            <dt className="text-[10px] leading-[14px] text-slate-500">{label}</dt>
            <dd className="font-mono text-[13px] leading-[20px] tabular-nums text-slate-100">{value}</dd>
          </div>
        ))}
      </dl>
    </div>
  );
}

/** One point of the graph: what it is, its community, its links by kind and the points it joins (each one opens). */
function NodeCard({graph, node, color, pinned, onClose, onOpen}: {graph: Graph; node: GNode; color: string; pinned: boolean; onClose: () => void;
  onOpen: (node: GNode) => void}) {
  const joined = useMemo(() => {
    const out: {node: GNode; kind: EdgeKind}[] = [];
    for (const edge of graph.edges) {
      if (edge.a === node.i) out.push({node: graph.nodes[edge.b], kind: edge.kind});
      else if (edge.b === node.i) out.push({node: graph.nodes[edge.a], kind: edge.kind});
    }
    return out.sort((a, b) => EDGE_ORDER.indexOf(a.kind) - EDGE_ORDER.indexOf(b.kind) || a.node.label.localeCompare(b.node.label));
  }, [graph, node]);
  const byKind = EDGE_ORDER.map(kind => [kind, joined.filter(j => j.kind === kind).length] as const).filter(([, n]) => n > 0);
  const area = node.area ? graph.areas.find(a => a.id === node.area)?.name : null;
  const community = graph.communities[node.community];
  const note = node.note;
  return (
    <div className="brain-pop absolute right-3 top-3 z-20 w-[min(340px,calc(100%-1.5rem))] rounded-xl border border-white/10 bg-[#161a23]/95 p-3 shadow-2xl backdrop-blur" data-testid="brain-card">
      <div className="flex items-start gap-2">
        <i className="mt-1.5 size-2.5 shrink-0 rounded-full" style={{background: color}} />
        <div className="min-w-0 flex-1">
          <p className="text-[14px] font-semibold leading-snug text-white">{node.label}</p>
          <p className="mt-0.5 text-[11.5px] text-slate-400">{[KIND_NAMES[node.kind], area, note?.type, note?.terms ? plural(note.terms, 'term') : null,
            node.count !== undefined ? (node.kind === 'tag' ? plural(node.count, 'note') : plural(node.count, 'article')) : null].filter(Boolean).join(' · ')}</p>
        </div>
        {pinned && <button type="button" onClick={onClose} aria-label="Close" className="rounded p-0.5 text-slate-400 hover:bg-white/10"><X className="size-3.5" /></button>}
      </div>
      {note?.summary && <p className="mt-2 text-[12.5px] leading-snug text-slate-200">{note.summary}</p>}
      {node.report && <p className="mt-2 text-[12px] leading-snug text-slate-300">{node.report.path.length ? node.report.path.join(' › ') : node.report.id}
        {node.report.status === 'partial' ? ' · partly mapped' : ' · mapped'}</p>}
      {note && (
        <p className={cn('mt-2 inline-flex items-center gap-1 text-[11.5px]', note.stage === 'DRAFT' ? 'text-slate-400' : 'text-emerald-300')}>
          {note.stage !== 'DRAFT' && <BadgeCheck className="size-3.5" />}{STAGE_NAMES[note.stage]}{note.updated ? ` · updated ${formatDate(note.updated)}` : ''}
          {note.words ? ` · ${note.words.toLocaleString()} words` : ''}</p>
      )}
      <p className="mt-2 font-mono text-[11px] tabular-nums text-slate-300">{plural(joined.length, 'edge')}{byKind.length ? ` (${byKind.map(([kind, n]) => `${n} ${EDGE_NAMES[kind]}`).join(', ')})` : ''}
        {community && !community.alone ? ` · community ${community.name}` : ''}</p>
      {pinned && joined.length > 0 && (
        <ul className="scroll-thin mt-1.5 max-h-[180px] space-y-0.5 overflow-y-auto pr-1" data-testid="brain-neighbours">
          {joined.slice(0, 60).map(({node: other, kind}) => (
            <li key={`${other.key}-${kind}`}>
              <button type="button" onClick={() => onOpen(other)} className="flex w-full items-center gap-2 rounded px-1 py-0.5 text-left text-[12px] hover:bg-white/5">
                <i className="size-2 shrink-0 rounded-full" style={{background: graph.communities[other.community]?.color ?? OTHER}} />
                <span className="min-w-0 flex-1 truncate text-slate-200">{other.label}</span>
                <span className="shrink-0 text-[10.5px] text-slate-500">{EDGE_NAMES[kind]}</span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

/** A row of the legend: a box that shows or hides the group, and its name, which lights it up and frames it. */
function GroupRow({color, name, count, shown, focused, dimmed, testid, data, onShow, onFocus}: {
  color: string; name: string; count: number; shown: boolean; focused: boolean; dimmed: boolean; testid: string; data: Record<string, string>;
  onShow: (shown: boolean) => void; onFocus: () => void;
}) {
  return (
    <li className="flex items-center gap-1.5">
      <input type="checkbox" checked={shown} onChange={e => onShow(e.target.checked)} aria-label={`Show ${name}`}
        className="size-3.5 shrink-0 cursor-pointer accent-[#3987e5]" data-testid={`${testid}-shown`} />
      <button type="button" onClick={onFocus} aria-pressed={focused} data-testid={testid} {...data}
        className={cn('flex min-w-0 flex-1 items-center gap-2 rounded px-1 py-[3px] text-left text-[12px] hover:bg-white/5', (dimmed || !shown) && 'opacity-45')}>
        <i className="size-2.5 shrink-0 rounded-full" style={{background: color}} />
        <span className="min-w-0 flex-1 truncate text-slate-200">{name}</span>
        <span className="font-mono text-[11px] tabular-nums text-slate-400">{count.toLocaleString()}</span>
      </button>
    </li>
  );
}

/**
 * /brain: the knowledge base as a graph, for showing Wizard to people, drawn the way graphify draws knowledge graphs
 * (owner, 30 Oct 2026). A page of its own beside the app: it changes nothing in the chat. Every point, link and number on
 * it was read from the knowledge base, the catalogs and the company database (brain.py); the communities are found from
 * the links (graph3d.ts). The news panel and the presenter tour stay. Keys: → or Space next step, ← back, Esc out,
 * F full screen, N a demo "new article came in", R frame the graph again, / search.
 *
 * `snapshot`: the page as published on the Pages site (site.py, owner 30 Oct 2026): the map and news as they were read
 * when the person published them, with no sign-in, no refresh and no way back into the app.
 */
export function BrainPage({snapshot}: {snapshot?: BrainSnapshot} = {}) {
  const [boot, setBoot] = useState<Bootstrap | null>(null);
  const [map, setMap] = useState<BrainMap | null>(snapshot?.map ?? null);
  const [live, setLive] = useState<BrainLive | null>(snapshot?.live ?? null);
  const [published, setPublished] = useState<{busy: boolean; message?: string; url?: string | null; failed?: boolean}>({busy: false});
  const [error, setError] = useState<string | null>(null);
  const [hover, setHover] = useState<GNode | null>(null);
  const [pinned, setPinned] = useState<string | null>(null);
  const [step, setStep] = useState<number | null>(null);
  const [group, setGroup] = useState<Pin>(null);
  const [category, setCategory] = useState<string | null>(null);
  const [layers, setLayers] = useState<ReadonlySet<LayerId>>(DEFAULT_LAYERS);
  const [colourBy, setColourBy] = useState<ColourBy>('community');
  const [hidden, setHidden] = useState<ReadonlySet<string>>(new Set());
  const [dims, setDims] = useState<2 | 3>(3);  // owner, 30 Oct 2026: "it needs to be 3D and rotate"
  const [rotate, setRotate] = useState(true);
  const [hubs, setHubs] = useState(false);
  const [query, setQuery] = useState('');
  const [settled, setSettled] = useState<{done: boolean; ticks: number}>({done: false, ticks: 0});
  const [fresh, setFresh] = useState<Set<string>>(new Set());
  const [incoming, setIncoming] = useState<NewsItem[]>([]);
  const shownDemo = useRef(new Set<string>());
  const freshTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const control = useRef<GraphControl | null>(null);
  const searchBox = useRef<HTMLInputElement>(null);
  const reduced = useReducedMotion();

  const loadBoot = useCallback(() => { api.bootstrap().then(setBoot).catch((e: unknown) => setError(e instanceof Error ? e.message : 'Wizard could not start.')); }, []);
  useEffect(() => { if (!snapshot) loadBoot(); }, [loadBoot, snapshot]);
  const signedIn = !!boot?.identity && !boot.auth.login_required;
  useEffect(() => {
    if (!signedIn || snapshot) return;
    const loadMap = () => api.brain().then(setMap).catch((e: unknown) => setError(e instanceof Error ? e.message : 'The knowledge graph could not be read.'));
    const loadLive = () => api.brainLive().then(setLive).catch(() => undefined);
    void loadMap(); void loadLive();
    const timer = setInterval(() => { void loadMap(); void loadLive(); }, REFRESH_MS);
    return () => { clearInterval(timer); if (freshTimer.current) clearTimeout(freshTimer.current); };
  }, [signedIn]);

  const news = live?.news ?? null;
  const showNews = news?.status === 'ok';
  const graph = useMemo(() => (map ? buildGraph(map, news) : null), [map, news]);
  const stats = useMemo(() => (graph ? networkStats(graph) : null), [graph]);
  const steps = useMemo(() => (map ? tourSteps(map, live) : []), [map, live]);
  const current = step !== null ? steps[Math.min(step, steps.length - 1)] : null;
  const focus: Focus | {kind: 'community'; id: number} = current ? current.focus : pinned ? {kind: 'note', id: pinned} : group ?? {kind: 'all'};
  const focusId = `${focus.kind}:${(focus as {id?: string | number}).id ?? ''}`;
  const lit = useMemo(() => (graph ? focusNodes(graph, !current && !pinned && hover ? {kind: 'note', id: hover.key} : focus) : null),
    [graph, current, pinned, hover, focusId]); // eslint-disable-line react-hooks/exhaustive-deps
  const frameOn = useMemo(() => {
    const set = graph ? focusNodes(graph, focus) : null;
    return set ? [...set] : null;
  }, [graph, focusId]); // eslint-disable-line react-hooks/exhaustive-deps
  const colors = useMemo(() => (graph ? graph.nodes.map(node => colourBy === 'community' ? graph.communities[node.community].color
    : node.area ? graph.areaColors.get(node.area) ?? OTHER : UNGROUPED) : []), [graph, colourBy]);
  const visible = useMemo(() => (graph ? Uint8Array.from(graph.nodes, node => (colourBy === 'community' ? !hidden.has(`c:${node.community}`)
    : !node.area || !hidden.has(`a:${node.area}`)) ? 1 : 0) : new Uint8Array()), [graph, colourBy, hidden]);
  // The notes a tour step names are labelled.
  const labelled = useMemo(() => {
    if (!graph || !current?.examples) return new Set<number>();
    return new Set(graph.nodes.filter(n => n.kind === 'note' && current.examples!.includes(n.label)).map(n => n.i));
  }, [graph, current]);
  const results = useMemo(() => (graph ? search(graph, query) : []), [graph, query]);

  /** The demo "a new article came in" (owner, 28 Oct 2026): one of the table's own articles slides in at the top
   *  marked NEW. Nothing is written and no count moves (brain.ts, demoArrival). */
  const arrive = useCallback(() => {
    if (news?.status !== 'ok') return;
    const item = demoArrival(news.latest ?? [], shownDemo.current, Date.now());
    if (!item) return;
    shownDemo.current.add(item.origin!);
    setIncoming(prev => [item, ...prev].slice(0, 5));
    setFresh(new Set([itemKey(item)]));
    if (freshTimer.current) clearTimeout(freshTimer.current);
    freshTimer.current = setTimeout(() => setFresh(new Set()), FRESH_MS);
  }, [news]);
  useEffect(() => {
    if (current?.id !== 'news') return;
    const timer = setTimeout(arrive, ARRIVE_AFTER_MS);
    return () => clearTimeout(timer);
  }, [current?.id]); // eslint-disable-line react-hooks/exhaustive-deps

  const open = useCallback((node: GNode | null) => { setPinned(node?.key ?? null); setGroup(null); setStep(null); }, []);
  const next = useCallback(() => setStep(s => (s === null ? 0 : Math.min(s + 1, steps.length - 1))), [steps.length]);
  const previous = useCallback(() => setStep(s => (s === null ? null : Math.max(0, s - 1))), []);
  useEffect(() => {
    const keydown = (e: KeyboardEvent) => {
      if (e.target instanceof HTMLElement && ['INPUT', 'TEXTAREA'].includes(e.target.tagName) && (e.target as HTMLInputElement).type !== 'checkbox') return;
      if (['ArrowRight', 'PageDown', ' '].includes(e.key)) { e.preventDefault(); next(); }
      else if (['ArrowLeft', 'PageUp'].includes(e.key)) { e.preventDefault(); previous(); }
      else if (e.key === 'Escape') { setStep(null); setPinned(null); setGroup(null); }
      else if (e.key === 'Home') setStep(0);
      else if (e.key.toLowerCase() === 'f') void document.documentElement.requestFullscreen?.().catch(() => undefined);
      else if (e.key.toLowerCase() === 'n') arrive();
      else if (e.key.toLowerCase() === 'r') control.current?.reset();
      else if (e.key === '/') { e.preventDefault(); searchBox.current?.focus(); }
    };
    window.addEventListener('keydown', keydown);
    return () => window.removeEventListener('keydown', keydown);
  }, [next, previous, arrive]);

  if (error) return <div className="grid min-h-dvh place-items-center bg-[#0f1117] p-6 text-sm text-rose-300" role="alert">{error}</div>;
  if (!snapshot && !boot) return <div className="grid min-h-dvh place-content-center bg-[#0f1117] text-sm text-slate-400">Loading Wizard…</div>;
  if (!snapshot && boot && !signedIn) return <LoginScreen mode={boot.auth.mode} onLogin={loadBoot} />;
  const publish = () => {
    setPublished({busy: true});
    api.publishBrain().then(r => setPublished({busy: false, message: r.message, url: r.url}))
      .catch((e: unknown) => setPublished({busy: false, failed: true, message: e instanceof Error ? e.message : 'Not published.'}));
  };

  const card = graph ? (pinned ? graph.byKey.get(pinned) : hover) ?? null : null;
  const database = live?.database.status === 'ok' ? live.database : null;
  const toggle = (id: LayerId) => setLayers(prev => { const out = new Set(prev); if (out.has(id)) out.delete(id); else out.add(id); return out; });
  const show = (key: string, on: boolean) => setHidden(prev => { const out = new Set(prev); if (on) out.delete(key); else out.add(key); return out; });
  const counts = stats ? {related: stats.byEdge.related, mention: stats.byEdge.mention, shared: stats.byEdge.shared, tags: stats.byKind.tag,
    terms: stats.byKind.term, systems: stats.byKind.system, reports: stats.byKind.report, news: stats.byKind.category} as Record<LayerId, number> : null;
  const groups = !graph ? [] : colourBy === 'community'
    ? graph.communities.map(c => ({key: `c:${c.id}`, name: c.name, count: c.size, color: c.color, pin: {kind: 'community', id: c.id} as Pin,
      testid: 'brain-community', data: {'data-community': String(c.id)}}))
    : graph.areas.map(a => ({key: `a:${a.id}`, name: a.name, count: a.size, color: a.color, pin: {kind: 'cluster', id: a.id} as Pin,
      testid: 'brain-cluster', data: {'data-cluster': a.id}}));
  const allShown = groups.every(g => !hidden.has(g.key));
  return (
    <div className="brain-page flex h-dvh w-screen flex-col overflow-hidden text-slate-100" data-testid="brain-page" data-dims={dims}>
      <header className="z-20 flex flex-wrap items-center gap-3 px-4 pb-2 pt-3">
        <img src={mark} alt="" className="size-7" />
        <div className="min-w-0">
          <h1 className="text-[18px] font-semibold leading-tight tracking-tight text-white">Knowledge graph</h1>
          <p className="text-[12px] text-slate-400">
            {map?.content === 'company' ? <>Company knowledge base{snapshot ? `, as published ${formatDate(snapshot.published_at, true)}`
              : map.knowledge_synced_at ? `, synced ${formatDate(map.knowledge_synced_at, true)}` : ''}</>
              : map?.content === 'none' ? 'The knowledge base has not synced yet' : map ? 'Example content: not company knowledge' : 'Reading what Wizard knows…'}
          </p>
        </div>
        {map && map.content !== 'company' && <span className="rounded-full border border-amber-300/40 bg-amber-300/10 px-2 py-0.5 text-[11px] font-semibold text-amber-200" data-testid="brain-examples">EXAMPLE CONTENT</span>}
        <div className="ml-auto flex items-center gap-1.5">
          <div className="relative">
            <Search className="pointer-events-none absolute left-2 top-1/2 size-3.5 -translate-y-1/2 text-slate-500" />
            <input ref={searchBox} value={query} onChange={e => setQuery(e.target.value)} placeholder="Find a note, term or tag  /"
              onKeyDown={e => { if (e.key === 'Enter' && results[0]) { open(results[0]); setQuery(''); e.currentTarget.blur(); } if (e.key === 'Escape') { setQuery(''); e.currentTarget.blur(); } }}
              className="h-8 w-[240px] rounded-lg border border-white/10 bg-white/[0.04] pl-7 pr-2 text-[12.5px] text-slate-100 placeholder:text-slate-500 focus:border-white/25 focus:outline-none"
              aria-label="Find in the knowledge graph" data-testid="brain-search" />
            {query && (
              <ul className="absolute right-0 top-9 z-40 w-[320px] rounded-lg border border-white/10 bg-[#161a23] p-1 shadow-2xl" data-testid="brain-results">
                {results.map(node => (
                  <li key={node.key}>
                    <button type="button" onClick={() => { open(node); setQuery(''); }} className="flex w-full items-center gap-2 rounded px-2 py-1 text-left text-[12.5px] hover:bg-white/5">
                      <i className="size-2 shrink-0 rounded-full" style={{background: colors[node.i]}} />
                      <span className="min-w-0 flex-1 truncate">{node.label}</span>
                      <span className="shrink-0 text-[10.5px] text-slate-500">{KIND_NAMES[node.kind]}</span>
                    </button>
                  </li>
                ))}
                {results.length === 0 && <li className="px-2 py-1 text-[12px] text-slate-400">Nothing by that name.</li>}
              </ul>
            )}
          </div>
          <button type="button" onClick={() => (step === null ? setStep(0) : setStep(null))} data-testid="brain-tour"
            className="inline-flex h-8 items-center gap-1.5 rounded-lg border border-white/10 bg-white/[0.04] px-3 text-[12.5px] font-medium hover:bg-white/10">
            {step === null ? <><Play className="size-3.5" />Tour</> : <><Pause className="size-3.5" />End tour</>}</button>
          <button type="button" onClick={() => void document.documentElement.requestFullscreen?.().catch(() => undefined)} aria-label="Full screen" title="Full screen (F)"
            className="grid size-8 place-items-center rounded-lg border border-white/10 bg-white/[0.04] hover:bg-white/10"><Maximize2 className="size-3.5" /></button>
          {!snapshot && boot?.site?.enabled && (
            <button type="button" onClick={publish} disabled={published.busy} data-testid="brain-publish" title="Publish this graph to the Pages site"
              className="inline-flex h-8 items-center gap-1.5 rounded-lg border border-white/10 bg-white/[0.04] px-3 text-[12.5px] font-medium hover:bg-white/10 disabled:opacity-60">
              <Upload className="size-3.5" />{published.busy ? 'Publishing…' : 'Publish'}</button>
          )}
          {!snapshot && <a href="/" className="inline-flex h-8 items-center gap-1.5 rounded-lg bg-[#1428a0] px-3 text-[12.5px] font-semibold text-white hover:bg-[#1c34c0]">
            <MessageSquareText className="size-3.5" />Ask Wizard</a>}
        </div>
        {published.message && (
          <p className={cn('basis-full text-right text-[12px]', published.failed ? 'text-rose-300' : 'text-emerald-300')} role="status" data-testid="brain-published">
            {published.message}{published.url && <> <a href={published.url} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1 underline">
              Open the published graph<ExternalLink className="size-3" /></a></>}
          </p>
        )}
      </header>

      <div className="flex min-h-0 flex-1 flex-col gap-3 px-3 pb-3 lg:flex-row">
        <div className="brain-stage relative min-h-[460px] flex-1 overflow-hidden rounded-2xl border border-white/[0.06]" data-testid="brain-stage">
          {graph && map && <>
            <Graph3D graph={graph} layers={layers} visible={visible} colors={colors} lit={lit} frameOn={frameOn} frameKey={`${focusId}|${dims}`}
              selected={pinned} hovered={hover?.key ?? null} labelled={labelled} hubs={hubs} dims={dims} reduced={reduced} rotate={rotate}
              inset={PANEL + 12} bottom={STRIP} control={control} onHover={node => setHover(node)} onPick={open}
              onProgress={(done, ticks) => setSettled(s => (s.done === done && (done || ticks - s.ticks < 25) ? s : {done, ticks}))} />

            {/* The panels on the left: communities (or areas), layers, sources. */}
            <div className="scroll-thin absolute left-3 top-3 z-10 flex flex-col gap-2 overflow-y-auto pr-0.5" style={{bottom: STRIP + 8, width: PANEL}}>
              <section className="brain-panel" aria-label={colourBy === 'community' ? 'Communities' : 'Areas'}>
                <div className="mb-1.5 flex items-center gap-2">
                  <p className="flex-1 text-[11px] font-semibold uppercase tracking-[0.08em] text-slate-400">{colourBy === 'community' ? 'Communities' : 'Areas'}</p>
                  <div className="flex rounded-md border border-white/10 p-px text-[10.5px]" role="group" aria-label="Colour by">
                    {(['community', 'area'] as const).map(by => (
                      <button key={by} type="button" onClick={() => { setColourBy(by); setHidden(new Set()); setGroup(null); }} aria-pressed={colourBy === by}
                        data-testid={`brain-colour-${by}`} className={cn('rounded px-1.5 py-px', colourBy === by ? 'bg-white/15 text-white' : 'text-slate-400 hover:text-white')}>
                        {by === 'community' ? 'Communities' : 'Areas'}</button>
                    ))}
                  </div>
                </div>
                <label className="flex items-center gap-1.5 px-0 py-[3px] text-[12px] text-slate-300">
                  <input type="checkbox" checked={allShown} onChange={e => setHidden(e.target.checked ? new Set() : new Set(groups.map(g => g.key)))}
                    className="size-3.5 cursor-pointer accent-[#3987e5]" data-testid="brain-select-all" />Select all</label>
                <ul className="mt-0.5">
                  {groups.map(g => (
                    <GroupRow key={g.key} color={g.color} name={g.name} count={g.count} shown={!hidden.has(g.key)} testid={g.testid} data={g.data}
                      focused={!!group && group.kind === g.pin!.kind && group.id === g.pin!.id} dimmed={!!group && !(group.kind === g.pin!.kind && group.id === g.pin!.id)}
                      onShow={on => show(g.key, on)} onFocus={() => { setGroup(group && group.kind === g.pin!.kind && group.id === g.pin!.id ? null : g.pin); setPinned(null); setStep(null); }} />
                  ))}
                </ul>
              </section>
              <section className="brain-panel" aria-label="Layers">
                <p className="mb-1 text-[11px] font-semibold uppercase tracking-[0.08em] text-slate-400">Layers</p>
                <ul>
                  {LAYERS.filter(layer => (counts?.[layer.id] ?? 0) > 0 || layer.id === 'shared').map(layer => (
                    <li key={layer.id}>
                      <label className={cn('flex cursor-pointer items-center gap-1.5 rounded px-0 py-[3px] text-[12px] hover:bg-white/5', !layers.has(layer.id) && 'opacity-60')}>
                        <input type="checkbox" checked={layers.has(layer.id)} onChange={() => toggle(layer.id)} className="size-3.5 cursor-pointer accent-[#3987e5]"
                          data-testid="brain-layer" data-layer={layer.id} />
                        <span className="min-w-0 flex-1 truncate text-slate-200">{layer.label}</span>
                        <span className="font-mono text-[11px] tabular-nums text-slate-400">{(counts?.[layer.id] ?? 0).toLocaleString()}</span>
                      </label>
                    </li>
                  ))}
                </ul>
                <p className="mt-1.5 text-[10.5px] leading-snug text-slate-500">Size: a point's links. An edge takes the colour of the hub it leaves.</p>
              </section>
              <section className="brain-panel" aria-label="Sources">
                <p className="mb-1 text-[11px] font-semibold uppercase tracking-[0.08em] text-slate-400">Sources</p>
                <ul className="space-y-0.5">
                  {ringSystems(map).filter(s => s.id !== 'knowledge').map(system => {
                    const detail = system.id === 'postgresql' && database ? `${plural(database.relations ?? 0, 'table')} & views`
                      : system.mapped?.mapped ? `${plural(system.mapped.mapped, 'report')} mapped`
                      : system.reports ? `${plural(system.reports, 'report')} catalogued` : system.kind === 'portal' ? 'read live'
                      : system.kind === 'schedules' ? 'recurring briefs' : '';
                    return (
                      <li key={system.id} className="flex items-baseline gap-2 px-1 text-[12px]" data-testid="brain-system" data-system={system.id}>
                        <span className="min-w-0 flex-1 truncate text-slate-200">{system.name}</span>
                        <span className="shrink-0 text-[11px] text-slate-400">{detail}</span>
                      </li>
                    );
                  })}
                </ul>
              </section>
            </div>

            {/* The statistics, the layout's state and the view controls, along the bottom. */}
            <div className="absolute inset-x-0 bottom-0 z-10 flex items-center gap-3 border-t border-white/[0.06] bg-[#0f1117]/85 px-4 backdrop-blur" style={{height: STRIP}}>
              {stats && <StatsStrip stats={stats} />}
              <span className="hidden shrink-0 font-mono text-[10.5px] tabular-nums text-slate-500 xl:inline" data-testid="brain-layout"
                title="Force-directed layout: springs along the edges, Barnes-Hut repulsion (θ = 0.9), a weak pull towards each community; seeded, so the same knowledge base settles the same way">
                {settled.done ? `layout settled · ${settled.ticks} it.` : `layout · it. ${settled.ticks}`}</span>
              <div className="flex shrink-0 rounded-md border border-white/10 p-px" role="group" aria-label="View">
                {([2, 3] as const).map(d => (
                  <button key={d} type="button" onClick={() => setDims(d)} aria-pressed={dims === d} data-testid={`brain-${d}d`}
                    className={cn('h-6 rounded px-2 text-[11.5px]', dims === d ? 'bg-white/15 text-white' : 'text-slate-400 hover:text-white')}>{d}D</button>
                ))}
              </div>
              <button type="button" onClick={() => setHubs(v => !v)} aria-pressed={hubs} title="Name each community's hub and the most linked points" data-testid="brain-labels"
                className={cn('h-7 shrink-0 rounded-md border border-white/10 px-2 text-[11.5px] hover:bg-white/10', hubs ? 'bg-white/10 text-white' : 'bg-white/[0.03] text-slate-400')}>Labels</button>
              {dims === 3 && !reduced && <button type="button" onClick={() => setRotate(r => !r)} aria-pressed={rotate} title="Turn slowly" data-testid="brain-rotate"
                className={cn('h-7 shrink-0 rounded-md border border-white/10 px-2 text-[11.5px] hover:bg-white/10', rotate ? 'bg-white/10 text-white' : 'bg-white/[0.03] text-slate-400')}>Rotate</button>}
              <div className="flex shrink-0 gap-1">
                <button type="button" onClick={() => control.current?.zoom(0.8)} aria-label="Zoom in" className="grid size-7 place-items-center rounded-md border border-white/10 bg-white/[0.03] hover:bg-white/10"><Plus className="size-3.5" /></button>
                <button type="button" onClick={() => control.current?.zoom(1.25)} aria-label="Zoom out" className="grid size-7 place-items-center rounded-md border border-white/10 bg-white/[0.03] hover:bg-white/10"><Minus className="size-3.5" /></button>
                <button type="button" onClick={() => control.current?.reset()} aria-label="Frame the graph again" title="Frame the graph again (R, or double click)" data-testid="brain-reset"
                  className="grid size-7 place-items-center rounded-md border border-white/10 bg-white/[0.03] hover:bg-white/10"><RotateCcw className="size-3.5" /></button>
              </div>
            </div>
          </>}
          {!map && <div className="absolute inset-0 grid place-content-center text-sm text-slate-400">Reading what Wizard knows…</div>}
          {map && map.notes.length === 0 && <p className="absolute left-1/2 top-6 -translate-x-1/2 rounded-lg bg-white/10 px-3 py-2 text-[13px] text-slate-200">No knowledge notes are loaded on this Wizard yet.</p>}

          {graph && card && !current && <NodeCard graph={graph} node={card} color={colors[card.i] ?? OTHER} pinned={!!pinned && card.key === pinned}
            onClose={() => setPinned(null)} onOpen={open} />}

          {/* The tour's caption, for presenting. */}
          {current && (
            <div className="pointer-events-none absolute right-3 z-30 flex justify-center" style={{left: PANEL + 24, bottom: STRIP + 12}}>
              <div key={current.id} className="brain-caption pointer-events-auto w-full max-w-[660px] rounded-xl border border-white/10 bg-[#161a23]/92 px-5 py-4 shadow-2xl backdrop-blur"
                data-testid="brain-caption" aria-live="polite">
                <p className="font-mono text-[11px] uppercase tracking-[0.12em] text-slate-400">Step {Math.min(step! + 1, steps.length)} of {steps.length}</p>
                <h2 className="mt-1 text-[22px] font-semibold leading-tight tracking-tight text-white">{current.title}</h2>
                <p className="mt-1.5 text-[15px] leading-snug text-slate-200">{current.body}</p>
                {current.examples && current.examples.length > 0 && <p className="mt-2 text-[12.5px] text-slate-400">Including {current.examples.map((e, i) => <span key={e}>{i ? (i === current.examples!.length - 1 ? ' and ' : ', ') : ''}<span className="text-slate-200">{e}</span></span>)}.</p>}
                <div className="mt-3 flex items-center gap-2">
                  <div className="flex gap-1">{steps.map((s, i) => <button key={s.id} type="button" onClick={() => setStep(i)} aria-label={`Step ${i + 1}: ${s.title}`}
                    className={cn('h-1.5 rounded-full transition-all', i === step ? 'w-6 bg-slate-200' : 'w-1.5 bg-white/25 hover:bg-white/50')} />)}</div>
                  <span className="ml-auto text-[11px] text-slate-500">← → to move · Esc to leave</span>
                  <button type="button" onClick={previous} disabled={step === 0} aria-label="Previous step" className="rounded-md border border-white/10 p-1.5 hover:bg-white/10 disabled:opacity-30"><ArrowLeft className="size-4" /></button>
                  {step! < steps.length - 1 ? <button type="button" onClick={next} aria-label="Next step" className="rounded-md bg-[#1428a0] p-1.5 hover:bg-[#1c34c0]"><ArrowRight className="size-4" /></button>
                    : <a href="/" className="rounded-md bg-[#1428a0] px-3 py-1.5 text-[12.5px] font-semibold hover:bg-[#1c34c0]">Ask Wizard</a>}
                </div>
              </div>
            </div>
          )}
          {step === null && graph && !card && <p className="pointer-events-none absolute right-4 top-3 z-0 hidden text-[11px] text-slate-500 lg:block">
            {dims === 2 ? 'Drag to move' : 'Drag to turn'} · scroll to zoom · → for the tour</p>}
        </div>
        {news && (
          <aside className={cn('flex min-h-0 shrink-0 flex-col lg:w-[400px] xl:w-[460px]', current?.focus.kind === 'cluster' && current.focus.id === NEWS && 'brain-spotlight')}>
            {showNews ? <NewsPanel news={news} fresh={fresh} incoming={incoming} category={category} onCategory={setCategory} name={live?.name ?? 'Company database'} still={reduced}
              snapshotAt={snapshot?.published_at} />
              : <NewsMissing news={news} />}
          </aside>
        )}
      </div>
    </div>
  );
}
