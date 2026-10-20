import {createContext, useContext, useEffect, useMemo, useRef, useState} from 'react';
import {CheckCircle2, ChevronDown, Loader2, MessageSquareText, Sparkles, Trophy, X, XCircle} from 'lucide-react';
import {spoken} from '@/format';
import {cn} from '@/lib/utils';
import {badges, detailOf, stageModel, WIZARD, type ModuleStats, type StageModel} from '@/stage';
import {brand, SystemLogo} from './SystemLogo';
import type {RunView, SystemInfo, TimelineItem} from '@/types';

/** The systems this person can use (from bootstrap), for every run card. */
export const SystemsContext = createContext<SystemInfo[]>([]);

type Point = {x: number; y: number};
interface Layout { width: number; height: number; orb: Point; nodes: Point[]; mode: 'sides' | 'row' }

/** Modules on both sides of the Wizard orb on a wide card; in a row under it on a narrow one (the desktop panel). */
export function layout(width: number, count: number): Layout {
  if (width >= 560) {
    const left = Math.ceil(count / 2), right = count - left;
    const height = Math.max(210, Math.max(left, right, 1) * 96 + 24);
    const column = (k: number, x: number) => Array.from({length: k}, (_, i) => ({x, y: ((i + 0.5) / k) * height}));
    const lefts = column(left, 76), rights = column(right, width - 76);
    const nodes = Array.from({length: count}, (_, i) => (i % 2 === 0 ? lefts[i / 2] : rights[(i - 1) / 2]));
    return {width, height, orb: {x: width / 2, y: height / 2}, nodes, mode: 'sides'};
  }
  const perRow = Math.min(4, Math.max(count, 1)), rows = Math.max(1, Math.ceil(count / perRow));
  const orb = {x: width / 2, y: 64};
  const nodes = Array.from({length: count}, (_, i) => {
    const row = Math.floor(i / perRow), inRow = Math.min(perRow, count - row * perRow);
    return {x: ((i % perRow) + 0.5) / inRow * width, y: 192 + row * 100};
  });
  return {width, height: 192 + (rows - 1) * 100 + 62, orb, nodes, mode: 'row'};
}

function beam(l: Layout, node: Point): string {
  if (l.mode === 'sides') {
    const fromLeft = node.x < l.orb.x;
    const sx = node.x + (fromLeft ? 34 : -34), ex = l.orb.x + (fromLeft ? -46 : 46), ey = l.orb.y + (node.y - l.orb.y) * 0.3;
    return `M ${sx} ${node.y} C ${(sx + ex) / 2} ${node.y}, ${(sx + ex) / 2} ${ey}, ${ex} ${ey}`;
  }
  const sy = node.y - 34, ex = l.orb.x + (node.x - l.orb.x) * 0.25, ey = l.orb.y + 46;
  return `M ${node.x} ${sy} C ${node.x} ${(sy + ey) / 2}, ${ex} ${(sy + ey) / 2}, ${ex} ${ey}`;
}

function useWidth(): [React.RefObject<HTMLDivElement | null>, number] {
  const ref = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(640);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    setWidth(el.clientWidth || 640);
    if (typeof ResizeObserver === 'undefined') return;
    const observer = new ResizeObserver(entries => setWidth(entries[0].contentRect.width || 640));
    observer.observe(el);
    return () => observer.disconnect();
  }, []);
  return [ref, width];
}

const LINGER_MS = 2200;

/** Most tool calls take milliseconds. A system stays lit for a moment after Wizard touched it, so every pull is seen;
 *  a long query stays lit for as long as it runs. Stored runs (opened later) never linger. */
function useLit(model: StageModel, live: boolean): {lit: Set<string>; recent: TimelineItem | null} {
  const seen = useRef(new Map<string, {signature: string; at: number}>());
  const latest = useRef<{item: TimelineItem; at: number} | null>(null);
  const first = useRef(true);
  const [now, setNow] = useState(() => Date.now());
  const stamp = Date.now();
  for (const m of [...model.modules, {id: WIZARD, stats: model.wizard}]) {
    const signature = m.stats.calls.map(c => `${c.key}:${c.state}`).join('|');
    const before = seen.current.get(m.id);
    if (before?.signature !== signature) {
      seen.current.set(m.id, {signature, at: first.current || !live ? 0 : stamp});
      const last = m.stats.calls[m.stats.calls.length - 1];
      if (last && live && !first.current) latest.current = {item: last, at: stamp};
    }
  }
  first.current = false;
  const lit = new Set<string>();
  for (const m of model.modules) {
    const at = seen.current.get(m.id)?.at ?? 0;
    if (m.stats.running || (live && now - at < LINGER_MS)) lit.add(m.id);
  }
  const recent = latest.current && live && now - latest.current.at < LINGER_MS ? latest.current.item : null;
  const lingering = live && Array.from(seen.current.values()).some(v => now - v.at < LINGER_MS);
  useEffect(() => {
    if (!lingering) return;
    const timer = setInterval(() => setNow(Date.now()), 200);
    return () => clearInterval(timer);
  }, [lingering]);
  return {lit, recent};
}

function useReducedMotion(): boolean {
  const [reduced] = useState(() => typeof matchMedia === 'function' && matchMedia('(prefers-reduced-motion: reduce)').matches);
  return reduced;
}

/** A number that counts up to its new value. */
function CountUp({value}: {value: number}) {
  const [shown, setShown] = useState(value);
  const from = useRef(value);
  useEffect(() => {
    const start = from.current, delta = value - start;
    if (!delta || typeof requestAnimationFrame !== 'function') { setShown(value); from.current = value; return; }
    const began = performance.now();
    let frame = 0;
    const tick = (now: number) => {
      const t = Math.min(1, (now - began) / 600);
      setShown(Math.round(start + delta * (1 - (1 - t) ** 3)));
      if (t < 1) frame = requestAnimationFrame(tick); else from.current = value;
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [value]);
  return <span className="tabular-nums">{shown.toLocaleString()}</span>;
}

function plural(n: number, word: string) { return `${n.toLocaleString()} ${word}${n === 1 ? '' : 's'}`; }

function statLine(m: SystemInfo & {stats: ModuleStats}): string {
  const s = m.stats;
  if (!s.calls.length) return m.kind === 'knowledge' && m.notes ? `${plural(m.notes, 'note')} ready` : 'ready';
  const parts = [plural(s.calls.length, m.kind === 'database' ? 'query' : m.kind === 'knowledge' ? 'lookup' : 'call')
    .replace('querys', 'queries')];
  if (s.rows) parts.push(plural(s.rows, 'row'));
  if (s.notes) parts.push(plural(s.notes, 'note'));
  if (s.errors) parts.push(`${s.errors} failed`);
  return parts.join(' · ');
}

const VERBS: Record<string, string> = {database: 'Querying', reports: 'Reading', knowledge: 'Searching', files: 'Reading'};

function Detail({item, className, onlyNew = false}: {item: TimelineItem; className?: string; onlyNew?: boolean}) {
  const detail = detailOf(item);
  // The label already names the report, the search words or the notes; the SQL is what it cannot show.
  if (!detail || (onlyNew && !detail.code)) return null;
  return detail.code
    ? <code className={cn('block overflow-hidden text-ellipsis whitespace-nowrap rounded-md bg-ink/[0.04] px-2 py-1 font-mono text-[11.5px] text-ink-2', className)}>{detail.text}</code>
    : <span className={cn('text-[12.5px] text-ink-2', className)}>{detail.text}</span>;
}

function Calls({module, onEvidence, onClose}: {module: SystemInfo & {stats: ModuleStats}; onEvidence: (id: string) => void; onClose: () => void}) {
  return (
    <div className="stage-pop rounded-xl border border-line bg-canvas p-3 shadow-sm" data-testid="stage-calls">
      <div className="mb-2 flex items-center gap-2">
        <SystemLogo id={module.id} name={module.name} size={22} />
        <p className="text-[13px] font-semibold">{module.name}</p>
        <span className="text-[12px] text-ink-3">{statLine(module)}</span>
        <button type="button" onClick={onClose} aria-label="Close" className="ml-auto rounded p-1 text-ink-3 hover:bg-surface"><X className="size-3.5" /></button>
      </div>
      {!module.stats.calls.length && <p className="text-[12.5px] text-ink-3">Not used for this answer.</p>}
      <ol className="space-y-2">
        {module.stats.calls.map(call => (
          <li key={call.key} className="text-[12.5px]">
            <div className="flex items-center gap-1.5">
              {call.state === 'running' ? <Loader2 className="size-3.5 animate-spin" style={{color: brand(module.id).color}} />
                : call.state === 'error' ? <XCircle className="size-3.5 text-danger" /> : <CheckCircle2 className="size-3.5 text-ok" />}
              <span className="font-medium text-ink">{call.label}</span>
              {call.durationMs !== undefined && <span className="text-[11px] text-ink-3">{spoken(call.durationMs)}</span>}
              {call.evidence && <button type="button" onClick={() => onEvidence(call.evidence!.id)}
                className="rounded bg-accent-soft px-1.5 text-[11px] font-semibold text-accent hover:bg-accent-line/60">{call.evidence.id}</button>}
            </div>
            <Detail item={call} className="mt-1" />
            {call.summary && <p className={cn('mt-0.5 text-[12px]', call.state === 'error' ? 'text-danger' : 'text-ink-3')}>→ {call.summary}</p>}
          </li>
        ))}
      </ol>
    </div>
  );
}

function Stage({run, model, onEvidence}: {run: RunView; model: StageModel; onEvidence: (id: string) => void}) {
  const [ref, width] = useWidth();
  const reduced = useReducedMotion();
  const [selected, setSelected] = useState<string | null>(null);
  const running = run.status === 'running' || run.status === 'queued';
  const l = useMemo(() => layout(width, model.modules.length), [width, model.modules.length]);
  const {lit, recent} = useLit(model, running);
  const active = model.active ?? recent;
  const activeModule = active ? model.modules.find(m => m.stats.calls.includes(active)) : null;
  const wizardBusy = running && model.wizard.running;
  const note = running ? [...run.timeline].reverse().find(t => t.kind === 'note') : undefined;
  const chosen = model.modules.find(m => m.id === selected);
  return (
    <div className="space-y-2.5" data-testid="systems-stage">
      <div ref={ref} className="relative w-full select-none" style={{height: l.height}}>
        <svg className="pointer-events-none absolute inset-0" width={l.width} height={l.height} aria-hidden="true">
          {model.modules.map((m, i) => {
            const node = l.nodes[i];
            if (!node) return null;
            const d = beam(l, node), color = brand(m.id, m.name).color, s = m.stats, on = lit.has(m.id);
            return (
              <g key={m.id}>
                <path d={d} fill="none" stroke={s.calls.length ? color : '#cbd3e1'} strokeWidth={s.calls.length ? 2 : 1.5}
                  strokeOpacity={s.calls.length ? 0.35 : 0.8} strokeDasharray={s.calls.length ? undefined : '3 6'} />
                {on && <path d={d} fill="none" stroke={color} strokeWidth={2.5} strokeLinecap="round" className="stage-flow" />}
                {on && !reduced && [0, 1, 2].map(k => (
                  <circle key={k} r={4} fill={color}>
                    <animateMotion dur="1.4s" begin={`${k * 0.46}s`} repeatCount="indefinite" path={d} />
                  </circle>
                ))}
              </g>
            );
          })}
        </svg>
        <div className="absolute flex -translate-x-1/2 -translate-y-1/2 flex-col items-center" style={{left: l.orb.x, top: l.orb.y}} data-testid="stage-orb"
          data-state={running ? (activeModule ? 'pulling' : 'thinking') : 'done'}>
          <div className="relative grid size-[88px] place-items-center">
            {running && <span className="stage-spin absolute inset-0 rounded-full"
              style={{background: `conic-gradient(from 0deg, transparent 0 60%, ${activeModule ? brand(activeModule.id).color : '#315bd6'} 100%)`}} />}
            <span className={cn('absolute inset-[5px] rounded-full bg-canvas', (activeModule || wizardBusy) && 'stage-glow')}
              style={{['--glow' as string]: activeModule ? brand(activeModule.id).color : '#315bd6'}} />
            <span className="relative grid size-[68px] place-items-center rounded-full text-[28px] font-bold text-white shadow-md"
              style={{background: 'radial-gradient(circle at 30% 25%, #6d8cf0, #315bd6 55%, #1e3a8a)'}}>W</span>
            {!running && run.status === 'succeeded' && <CheckCircle2 className="stage-pop absolute -right-0.5 bottom-1 size-6 rounded-full bg-canvas text-ok" />}
          </div>
          <span className="mt-1 text-[12px] font-semibold text-ink">Wizard</span>
        </div>
        {model.modules.map((m, i) => {
          const node = l.nodes[i];
          if (!node) return null;
          const s = m.stats, color = brand(m.id, m.name).color, on = lit.has(m.id);
          const state = on ? 'active' : s.state;
          return (
            <button key={m.id} type="button" onClick={() => setSelected(selected === m.id ? null : m.id)}
              aria-label={`${m.name}: ${statLine(m)}. Show what Wizard did here`} aria-pressed={selected === m.id}
              className={cn('absolute flex w-[124px] -translate-x-1/2 -translate-y-1/2 flex-col items-center gap-1 rounded-xl px-1 py-1.5 transition-all duration-300 hover:bg-surface/80',
                state === 'idle' && 'opacity-55 grayscale-[40%] hover:opacity-90', state === 'active' && 'scale-[1.06]', selected === m.id && 'bg-surface')}
              style={{left: node.x, top: node.y}} data-testid="stage-node" data-system={m.id} data-state={state}>
              <span className="relative">
                {state === 'active' && <span className="stage-ping absolute -inset-1.5 rounded-[32%]" style={{boxShadow: `0 0 0 2px ${color}`}} />}
                <SystemLogo id={m.id} name={m.name} size={46} className={cn(state === 'active' && 'stage-breathe')} />
                {state === 'done' && <CheckCircle2 className="stage-pop absolute -bottom-1 -right-1 size-[18px] rounded-full bg-canvas text-ok" />}
                {state === 'error' && <XCircle className="stage-pop absolute -bottom-1 -right-1 size-[18px] rounded-full bg-canvas text-danger" />}
                {s.calls.length > 0 && <span className="stage-pop absolute -right-2 -top-2 min-w-[20px] rounded-full px-1.5 text-center text-[11px] font-bold leading-[20px] text-white shadow"
                  style={{background: color}}><CountUp value={s.calls.length} /></span>}
              </span>
              <span className="max-w-full truncate text-[12px] font-medium leading-tight text-ink">{m.name}</span>
              <span className="max-w-full truncate text-[11px] leading-tight text-ink-3">{statLine(m)}</span>
            </button>
          );
        })}
      </div>
      {running && (
        <div className="rounded-xl border border-line bg-surface/60 px-3 py-2" aria-live="polite" data-testid="stage-now">
          {active ? (
            <div className="flex items-start gap-2.5">
              <SystemLogo id={activeModule?.id ?? WIZARD} name={activeModule?.name} size={26} className="stage-breathe mt-0.5" />
              <div className="min-w-0 flex-1">
                <p className="text-[13px] font-medium text-ink">
                  {activeModule ? <>{VERBS[activeModule.kind] ?? 'Reading'} <span style={{color: brand(activeModule.id).deep}}>{activeModule.name}</span></> : active.label}
                  <span className="stage-dots ml-0.5" aria-hidden="true" />
                </p>
                {activeModule && <p className="truncate text-[12.5px] text-ink-2">{active.label}</p>}
                <div className={cn('mt-1 overflow-hidden rounded-md', active.state === 'running' && 'stage-scan')}><Detail item={active} onlyNew /></div>
                {active.state !== 'running' && active.summary && (
                  <p className={cn('stage-pop mt-1 text-[12.5px] font-medium', active.state === 'error' ? 'text-danger' : 'text-ok')}>→ {active.summary}</p>
                )}
              </div>
            </div>
          ) : (
            <p className="flex items-center gap-2 text-[13px] text-ink-2">
              <Sparkles className="size-4 text-accent" />Gemini is deciding the next step<span className="stage-dots" aria-hidden="true" />
            </p>
          )}
          {note && <p className="mt-1.5 flex gap-1.5 border-t border-line pt-1.5 text-[12.5px] italic text-ink-2" data-testid="stage-note">
            <MessageSquareText className="mt-0.5 size-3.5 shrink-0 text-ink-3" /><span className="line-clamp-2">{note.label}</span></p>}
        </div>
      )}
      {chosen && <Calls module={chosen} onEvidence={onEvidence} onClose={() => setSelected(null)} />}
    </div>
  );
}

function Totals({model, running}: {model: StageModel; running: boolean}) {
  const items: [string, number, string][] = [
    ['systems', model.totals.systems, `of ${model.totals.available} system${model.totals.available === 1 ? '' : 's'} used`],
    ['calls', model.totals.calls, model.totals.calls === 1 ? 'call' : 'calls'],
    ['rows', model.totals.rows, model.totals.rows === 1 ? 'row read' : 'rows read'],
    ['notes', model.totals.notes, model.totals.notes === 1 ? 'note read' : 'notes read'],
  ];
  return (
    <div className="flex flex-wrap gap-1.5" data-testid="stage-totals">
      {items.filter(([key, value]) => value > 0 || key === 'systems' || (running && key === 'calls')).map(([key, value, label]) => (
        <span key={key} className="inline-flex items-baseline gap-1 rounded-full border border-line bg-canvas px-2.5 py-0.5 text-[12px] text-ink-2">
          <strong className="text-[13px] text-ink"><CountUp value={value} /></strong>{label}
        </span>
      ))}
    </div>
  );
}

/** What Wizard is doing, as a picture: the systems this person can use around the Wizard orb. A module lights up and
 *  streams into the orb while Gemini reads from it; the caption shows the actual SQL, search words or report. Only
 *  observed tool calls drive it. After the answer it folds into a strip of the systems used, with earned badges. */
export function SystemsStage({run, onEvidence}: {run: RunView; onEvidence: (id: string) => void}) {
  const systems = useContext(SystemsContext);
  const model = useMemo(() => stageModel(run, systems), [run, systems]);
  const running = run.status === 'running' || run.status === 'queued';
  const [open, setOpen] = useState(false);
  const earned = badges(run, model);
  if (!running && model.totals.calls === 0) return null;
  if (running || open) {
    return (
      <div className="rounded-xl border border-line bg-gradient-to-b from-accent-soft/40 to-canvas p-3" data-testid="stage">
        <Stage run={run} model={model} onEvidence={onEvidence} />
        <div className="mt-2 flex flex-wrap items-center gap-2">
          <Totals model={model} running={running} />
          {!running && <button type="button" onClick={() => setOpen(false)} className="ml-auto text-[12px] font-medium text-accent hover:underline">Fold</button>}
        </div>
      </div>
    );
  }
  const used = model.modules.filter(m => m.stats.calls.length);
  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-2 rounded-xl border border-line bg-surface/50 px-3 py-2" data-testid="journey">
      <div className="flex items-center gap-1.5">
        {used.map(m => (
          <span key={m.id} className="inline-flex items-center gap-1.5 rounded-full bg-canvas py-0.5 pl-0.5 pr-2.5 text-[12px] shadow-sm"
            data-testid="journey-system" data-system={m.id} title={`${m.name}: ${statLine(m)}`}>
            <SystemLogo id={m.id} name={m.name} size={20} /><span className="font-medium text-ink">{m.name}</span>
            <span className="text-ink-3">{m.stats.rows ? `${m.stats.rows.toLocaleString()} rows` : m.stats.notes ? plural(m.stats.notes, 'note') : plural(m.stats.calls.length, 'call')}</span>
          </span>
        ))}
        {!used.length && <span className="text-[12px] text-ink-3">{plural(model.totals.calls, 'step')} on Wizard's own tools</span>}
      </div>
      {earned.map(b => (
        <span key={b.id} title={b.detail} className="stage-pop inline-flex items-center gap-1 rounded-full border border-amber-200 bg-amber-50 px-2 py-0.5 text-[11.5px] font-semibold text-amber-800" data-testid="badge">
          <Trophy className="size-3" />{b.label}
        </span>
      ))}
      <button type="button" onClick={() => setOpen(true)} className="ml-auto inline-flex items-center gap-1 text-[12px] font-medium text-accent hover:underline" data-testid="show-journey">
        Show the journey<ChevronDown className="size-3.5" />
      </button>
    </div>
  );
}
