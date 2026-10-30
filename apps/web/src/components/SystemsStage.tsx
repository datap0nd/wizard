import {createContext, useContext, useEffect, useMemo, useRef, useState} from 'react';
import {CheckCircle2, ChevronDown, Hourglass, Loader2, MessageSquareText, Sparkles, Trophy, X, XCircle} from 'lucide-react';
import {spoken} from '@/format';
import {cn} from '@/lib/utils';
import {badges, detailOf, stageModel, verbOf, WIZARD, type ModuleStats, type StageModel} from '@/stage';
import {toolAnimation, wizardAnimation, wizardCaption} from '@/wizard';
import type {WizardAnimation} from '@/wizardSheet';
import {NotThis} from './Steering';
import {brand, SystemLogo} from './SystemLogo';
import {WizardSprite} from './WizardSprite';
import type {RunView, SystemInfo, TimelineItem} from '@/types';

/** The systems this person can use (from bootstrap), for every run card. */
export const SystemsContext = createContext<SystemInfo[]>([]);

type Point = {x: number; y: number};
interface Layout { width: number; height: number; orb: Point; radius: number; scale: number; nodes: Point[]; nodeWidth: number; mode: 'orbit' | 'row' }

const TILE = 58;

/** Modules in two arcs around the wizard on a wide card (half on each side, an orbit); in rows under him on a narrow
 *  one. The wizard is pixel art, so he grows by whole numbers: 3x on a wide card, 2x otherwise. */
export function layout(width: number, count: number): Layout {
  if (width >= 560) {
    const left = Math.ceil(count / 2), right = count - left, side = Math.max(left, right, 1);
    const scale = width >= 640 ? 3 : 2, radius = 24 * scale + 22;
    const height = Math.max(scale === 3 ? 360 : 300, side * 124 + 48);
    const orb = {x: width / 2, y: height / 2};
    const rx = width / 2 - 82, ry = height / 2 - 62;
    const arc = (k: number, i: number, toLeft: boolean): Point => {
      const spread = Math.min(Math.PI * 0.75, (k - 1) * Math.PI * 0.42);
      const t = k === 1 ? 0 : (i / (k - 1) - 0.5) * spread;
      return {x: orb.x + (toLeft ? -1 : 1) * rx * Math.cos(t), y: orb.y + ry * Math.sin(t)};
    };
    const nodes = Array.from({length: count}, (_, i) => (i % 2 === 0 ? arc(left, i / 2, true) : arc(right, (i - 1) / 2, false)));
    return {width, height, orb, radius, scale, nodes, nodeWidth: 132, mode: 'orbit'};
  }
  const perRow = Math.max(1, Math.min(4, count, Math.floor(width / 116))), rows = Math.max(1, Math.ceil(count / perRow));
  const radius = 24 * 2 + 18, orb = {x: width / 2, y: radius + 12};
  const top = orb.y + radius + 78;
  const nodes = Array.from({length: count}, (_, i) => {
    const row = Math.floor(i / perRow), inRow = Math.min(perRow, count - row * perRow);
    return {x: ((i % perRow) + 0.5) / inRow * width, y: top + row * 112};
  });
  return {width, height: top + (rows - 1) * 112 + 66, orb, radius, scale: 2, nodes, nodeWidth: Math.min(132, Math.floor(width / perRow) - 4), mode: 'row'};
}

/** A stream from a module into the wizard's circle, bent a little the same way for every module, like a vortex. */
export function beam(l: Layout, node: Point): string {
  const dx = node.x - l.orb.x, dy = node.y - l.orb.y, dist = Math.hypot(dx, dy) || 1;
  const ux = dx / dist, uy = dy / dist;
  const sx = node.x - ux * (TILE / 2 + 6), sy = node.y - uy * (TILE / 2 + 6);
  const ex = l.orb.x + ux * (l.radius + 2), ey = l.orb.y + uy * (l.radius + 2);
  const bend = 0.16 * dist;
  const mx = (sx + ex) / 2 - uy * bend, my = (sy + ey) / 2 + ux * bend;
  return `M ${sx.toFixed(1)} ${sy.toFixed(1)} Q ${mx.toFixed(1)} ${my.toFixed(1)} ${ex.toFixed(1)} ${ey.toFixed(1)}`;
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

/** A system the person switched off for this answer (one it already read from stays shown as used). */
function switchedOff(run: RunView, m: SystemInfo & {stats: ModuleStats}): boolean {
  return !!run.systems && m.kind !== 'schedules' && !run.systems.includes(m.id) && !m.stats.calls.length;
}

function statLine(m: SystemInfo & {stats: ModuleStats}, off = false): string {
  const s = m.stats;
  if (off) return 'switched off';
  if (!s.calls.length) return m.kind === 'knowledge' && m.notes ? `${plural(m.notes, 'note')} ready` : 'ready';
  const parts = [plural(s.calls.length, m.kind === 'database' ? 'query' : m.kind === 'knowledge' ? 'lookup'
    : m.kind === 'schedules' ? 'schedule' : 'call')
    .replace('querys', 'queries')];
  if (s.rows) parts.push(plural(s.rows, 'row'));
  if (s.notes) parts.push(plural(s.notes, 'note'));
  if (s.errors) parts.push(`${s.errors} failed`);
  return parts.join(' · ');
}

function Detail({item, className, onlyNew = false}: {item: TimelineItem; className?: string; onlyNew?: boolean}) {
  const detail = detailOf(item);
  // The label already names the report, the search words or the notes; the SQL is what it cannot show.
  if (!detail || (onlyNew && !detail.code)) return null;
  return detail.code
    ? <code className={cn('block overflow-hidden text-ellipsis whitespace-nowrap rounded-md bg-ink/[0.04] px-2 py-1 font-mono text-[11.5px] text-ink-2', className)}>{detail.text}</code>
    : <span className={cn('text-[12.5px] text-ink-2', className)}>{detail.text}</span>;
}

function Calls({run, module, onEvidence, onClose}: {run: RunView; module: SystemInfo & {stats: ModuleStats}; onEvidence: (id: string) => void; onClose: () => void}) {
  return (
    <div className="stage-pop rounded-xl border border-line bg-canvas p-3 shadow-sm" data-testid="stage-calls">
      <div className="mb-2 flex items-center gap-2">
        <SystemLogo id={module.id} name={module.name} size={22} />
        <p className="text-[13px] font-semibold">{module.name}</p>
        <span className="text-[12px] text-ink-3">{statLine(module, switchedOff(run, module))}</span>
        <button type="button" onClick={onClose} aria-label="Close" className="ml-auto rounded p-1 text-ink-3 hover:bg-surface"><X className="size-3.5" /></button>
      </div>
      {!module.stats.calls.length && <p className="text-[12.5px] text-ink-3">{switchedOff(run, module) ? 'Switched off for this answer: pick it in Systems, next to the question box, to use it.' : 'Not used for this answer.'}</p>}
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
            <NotThis run={run} item={call} className="mt-0.5" />
          </li>
        ))}
      </ol>
    </div>
  );
}

/** Pixel stars that twinkle around the wizard while he works: decoration only, at fixed places. */
function Stars({width, height}: {width: number; height: number}) {
  const stars = useMemo(() => Array.from({length: 16}, (_, i) => {
    const a = Math.sin(i * 12.9898) * 43758.5453, b = Math.sin(i * 78.233) * 12345.6789;
    return {x: (a - Math.floor(a)) * width, y: (b - Math.floor(b)) * height, delay: (i % 8) * 0.31, big: i % 3 === 0};
  }), [width, height]);
  return (
    <>
      {stars.map((star, i) => (
        <i key={i} className="stage-twinkle pointer-events-none absolute bg-accent/60"
          style={{left: star.x, top: star.y, width: star.big ? 4 : 3, height: star.big ? 4 : 3, animationDelay: `${star.delay}s`}} />
      ))}
    </>
  );
}

/** The circle the wizard stands in: two rune rings that turn (faster while he pulls from a system) and a glowing floor. */
function MagicCircle({color, working, pulling}: {color: string; working: boolean; pulling: boolean}) {
  const ring = working ? color : '#cbd3e1';
  return (
    <svg className="pointer-events-none absolute inset-0 overflow-visible" viewBox="0 0 100 100" aria-hidden="true">
      <ellipse cx="50" cy="83" rx="31" ry="7" fill={ring} opacity={working ? 0.22 : 0.14} className={cn(working && 'stage-floor')} />
      <g className={cn(working && (pulling ? 'stage-orbit stage-orbit-fast' : 'stage-orbit'))}>
        <circle cx="50" cy="50" r="48" fill="none" stroke={ring} strokeWidth="1.3" strokeDasharray="1.5 4.2" strokeLinecap="square" />
        {[0, 90, 180, 270].map(a => (
          <rect key={a} x="48.4" y="0.4" width="3.2" height="3.2" fill={ring} transform={`rotate(${a} 50 50)`} />
        ))}
      </g>
      <g className={cn(working && 'stage-orbit-rev')} opacity={0.55}>
        <circle cx="50" cy="50" r="42" fill="none" stroke={ring} strokeWidth="0.8" strokeDasharray="6 3 1 3" />
        {[45, 135, 225, 315].map(a => (
          <rect key={a} x="49" y="6.8" width="2" height="2" fill={ring} transform={`rotate(${a} 50 50)`} />
        ))}
      </g>
    </svg>
  );
}

const BURST = 18;

/** Pixel confetti in the colours of the systems used, when an answer lands live. */
function Burst({colors}: {colors: string[]}) {
  const palette = colors.length ? colors : ['#1428a0', '#3a5cd6', '#6ebeff'];
  return (
    <span className="stage-burst pointer-events-none absolute inset-0" aria-hidden="true">
      {Array.from({length: BURST}, (_, i) => {
        const angle = (i / BURST) * Math.PI * 2, reach = 70 + (i % 3) * 22;
        return <i key={i} style={{background: palette[i % palette.length], ['--dx' as string]: `${Math.cos(angle) * reach}px`,
          ['--dy' as string]: `${Math.sin(angle) * reach}px`, ['--r' as string]: `${(i % 4) * 90}deg`, animationDelay: `${(i % 5) * 0.03}s`}} />;
      })}
    </span>
  );
}

function Stage({run, model, onEvidence, finale}: {run: RunView; model: StageModel; onEvidence: (id: string) => void; finale: Finale}) {
  const [ref, width] = useWidth();
  const reduced = useReducedMotion();
  const [selected, setSelected] = useState<string | null>(null);
  const running = run.status === 'running' || run.status === 'queued';
  const l = useMemo(() => layout(width, model.modules.length), [width, model.modules.length]);
  const {lit, recent} = useLit(model, running);
  const active = model.active ?? recent;
  const activeModule = active ? model.modules.find(m => m.stats.calls.includes(active)) : null;
  const note = running ? [...run.timeline].reverse().find(t => t.kind === 'note') : undefined;
  // Gemini's own limits (a wait, a switch of model) come as status lines and warnings: the latest one, while it is news.
  const last = run.timeline[run.timeline.length - 1];
  const waiting = running && !model.active && (last?.kind === 'status' || last?.kind === 'warning') ? last : undefined;
  const chosen = model.modules.find(m => m.id === selected);
  // The wizard acts out the step in progress, or the one that just finished while its module is still lit.
  const animation: WizardAnimation = finale ?? (!running ? 'idle' : active ? toolAnimation(active.name ?? '') : wizardAnimation(run));
  const verb = finale === 'success' ? 'Answer ready' : finale === 'fail' ? 'Could not finish' : wizardCaption(run, animation).verb;
  const color = activeModule ? brand(activeModule.id, activeModule.name).color : finale === 'fail' ? '#dc2626' : '#3a5cd6';
  const landed = recent && recent.state !== 'running' && recent.summary ? recent : null;
  const landedModule = landed ? model.modules.find(m => m.stats.calls.includes(landed)) : null;
  return (
    <div className="space-y-2.5" data-testid="systems-stage">
      <div ref={ref} className="relative w-full select-none" style={{height: l.height}}>
        {(running || finale) && !reduced && <Stars width={l.width} height={l.height} />}
        <svg className="pointer-events-none absolute inset-0" width={l.width} height={l.height} aria-hidden="true">
          {model.modules.map((m, i) => {
            const node = l.nodes[i];
            if (!node) return null;
            const d = beam(l, node), c = brand(m.id, m.name).color, s = m.stats, on = lit.has(m.id);
            return (
              <g key={m.id}>
                <path d={d} fill="none" stroke={s.calls.length ? c : '#cbd3e1'} strokeWidth={s.calls.length ? 2 : 1.5}
                  strokeOpacity={s.calls.length ? 0.35 : 0.8} strokeDasharray={s.calls.length ? undefined : '3 6'} />
                {on && <path d={d} fill="none" stroke={c} strokeWidth={7} strokeLinecap="round" strokeOpacity={0.14} />}
                {on && <path d={d} fill="none" stroke={c} strokeWidth={2.5} strokeLinecap="round" className="stage-flow" />}
                {on && !reduced && [0, 1, 2, 3].map(k => (
                  <rect key={k} x={-3.5} y={-3.5} width={7} height={7} fill={c} opacity={0}>
                    <animateMotion dur="1.3s" begin={`${k * 0.32}s`} repeatCount="indefinite" path={d} rotate="auto" />
                    <animate attributeName="opacity" values="0;1;1;0" keyTimes="0;0.12;0.8;1" dur="1.3s" begin={`${k * 0.32}s`} repeatCount="indefinite" />
                  </rect>
                ))}
              </g>
            );
          })}
        </svg>
        <div className="absolute flex -translate-x-1/2 -translate-y-1/2 flex-col items-center" style={{left: l.orb.x, top: l.orb.y}} data-testid="stage-orb"
          data-state={finale ?? (running ? (activeModule ? 'pulling' : 'thinking') : 'done')}>
          <div className="relative grid place-items-center" style={{width: 2 * l.radius, height: 2 * l.radius}}>
            <MagicCircle color={color} working={running || !!finale} pulling={!!activeModule} />
            {(running || finale) && <span className="stage-glow absolute rounded-full" style={{inset: '22%', ['--glow' as string]: color}} />}
            <WizardSprite animation={animation} scale={l.scale} label={`Wizard: ${verb}`} className="relative" />
            {finale === 'success' && !reduced && <Burst colors={model.modules.filter(m => m.stats.calls.length).map(m => brand(m.id, m.name).color)} />}
            {!running && !finale && run.status === 'succeeded' && <CheckCircle2 className="stage-pop absolute bottom-[14%] right-[14%] size-6 rounded-full bg-canvas text-ok" />}
          </div>
          <span className="-mt-1 text-[13px] font-semibold text-ink">Wizard</span>
          <span className="text-[11.5px] text-ink-3" data-testid="wizard-verb">{verb}{running && <span className="stage-dots" aria-hidden="true" />}</span>
        </div>
        {landed && (
          <span key={landed.key} className="stage-float pointer-events-none absolute inline-flex max-w-[260px] items-center gap-1 whitespace-nowrap rounded-full bg-canvas px-2 py-0.5 text-[12px] font-semibold shadow-md ring-1 ring-line"
            style={{left: l.orb.x, top: l.orb.y - l.radius - 20, color: landedModule ? brand(landedModule.id).deep : '#1428a0'}} data-testid="stage-landed">
            {landedModule && <SystemLogo id={landedModule.id} name={landedModule.name} size={16} />}
            <span className="truncate">{landed.state === 'error' ? 'failed' : `+ ${landed.summary}`}</span>
          </span>
        )}
        {model.modules.map((m, i) => {
          const node = l.nodes[i];
          if (!node) return null;
          const s = m.stats, c = brand(m.id, m.name).color, on = lit.has(m.id), off = switchedOff(run, m);
          const state = on ? 'active' : off ? 'off' : s.state;
          const last = s.calls[s.calls.length - 1];
          return (
            <button key={m.id} type="button" onClick={() => setSelected(selected === m.id ? null : m.id)}
              aria-label={`${m.name}: ${statLine(m, off)}. Show what Wizard did here`} aria-pressed={selected === m.id}
              className={cn('absolute flex -translate-x-1/2 -translate-y-1/2 flex-col items-center gap-1 rounded-xl px-1 py-1.5 transition-all duration-300 hover:-translate-y-[calc(50%+2px)] hover:bg-surface/80',
                state === 'idle' && 'opacity-55 grayscale-[40%] hover:opacity-90', state === 'off' && 'opacity-30 grayscale hover:opacity-60',
                state === 'active' && 'scale-[1.08]', selected === m.id && 'bg-surface')}
              style={{left: node.x, top: node.y, width: l.nodeWidth}} data-testid="stage-node" data-system={m.id} data-state={state}>
              <span key={on && last ? last.key : 'rest'} className={cn('relative', on && 'stage-hop')}>
                {state === 'active' && <span className="stage-ping absolute -inset-1.5 rounded-[32%]" style={{boxShadow: `0 0 0 2px ${c}`}} />}
                {state === 'active' && <span className="stage-glow absolute inset-0 rounded-[28%]" style={{['--glow' as string]: c}} />}
                <SystemLogo id={m.id} name={m.name} size={TILE} className={cn(state === 'active' && 'stage-breathe')} />
                {state === 'done' && <CheckCircle2 className="stage-pop absolute -bottom-1 -right-1 size-5 rounded-full bg-canvas text-ok" />}
                {state === 'error' && <XCircle className="stage-pop absolute -bottom-1 -right-1 size-5 rounded-full bg-canvas text-danger" />}
                {s.calls.length > 0 && <span className="stage-pop absolute -right-2 -top-2 min-w-[22px] rounded-full px-1.5 text-center text-[11.5px] font-bold leading-[22px] text-white shadow"
                  style={{background: c}}><CountUp value={s.calls.length} /></span>}
              </span>
              <span className="max-w-full truncate text-[12.5px] font-medium leading-tight text-ink">{m.name}</span>
              <span className="max-w-full truncate text-[11px] leading-tight text-ink-3">{statLine(m, off)}</span>
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
                  {activeModule ? (() => {
                    const {verb, suffix} = verbOf(active, activeModule.kind);
                    return <>{verb} <span style={{color: brand(activeModule.id).deep}}>{activeModule.name}</span>{suffix}</>;
                  })() : active.label}
                  <span className="stage-dots ml-0.5" aria-hidden="true" />
                </p>
                {activeModule && <p className="truncate text-[12.5px] text-ink-2">{active.label}</p>}
                <div className={cn('mt-1 overflow-hidden rounded-md', active.state === 'running' && 'stage-scan')}><Detail item={active} onlyNew /></div>
                {active.state !== 'running' && active.summary && (
                  <p className={cn('stage-pop mt-1 text-[12.5px] font-medium', active.state === 'error' ? 'text-danger' : 'text-ok')}>→ {active.summary}</p>
                )}
                <NotThis key={active.key} run={run} item={active} className="mt-1" />
              </div>
            </div>
          ) : waiting ? (
            <p className={cn('flex items-center gap-2 text-[13px]', waiting.kind === 'warning' ? 'text-warn' : 'text-ink-2')} data-testid="stage-waiting">
              <Hourglass className="size-4 shrink-0" />{waiting.label}
            </p>
          ) : (
            <p className="flex items-center gap-2 text-[13px] text-ink-2">
              <Sparkles className="size-4 text-accent" />{run.streamText ? 'Writing the answer' : 'Gemini is deciding the next step'}<span className="stage-dots" aria-hidden="true" />
            </p>
          )}
          {note && <p className="mt-1.5 flex gap-1.5 border-t border-line pt-1.5 text-[12.5px] italic text-ink-2" data-testid="stage-note">
            <MessageSquareText className="mt-0.5 size-3.5 shrink-0 text-ink-3" /><span className="line-clamp-2">{note.label}</span></p>}
        </div>
      )}
      {chosen && <Calls run={run} module={chosen} onEvidence={onEvidence} onClose={() => setSelected(null)} />}
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

/** True while the element is (mostly) scrolled out of view. */
function useOutOfView(ref: React.RefObject<HTMLElement | null>): boolean {
  const [out, setOut] = useState(false);
  useEffect(() => {
    const el = ref.current;
    if (!el || typeof IntersectionObserver === 'undefined') return;
    const observer = new IntersectionObserver(([entry]) => setOut(entry.intersectionRatio < 0.2), {threshold: [0, 0.2, 0.5]});
    observer.observe(el);
    return () => observer.disconnect();
  }, [ref]);
  return out;
}

/** While the view follows the answer down and the stage has scrolled away, the wizard comes along in a slim bar pinned
 *  to the top: what he is doing, the systems he drew on, and his hop when the answer lands. It takes no room. */
function StageBar({run, model, finale, stage}: {run: RunView; model: StageModel; finale: Finale; stage: React.RefObject<HTMLDivElement | null>}) {
  const out = useOutOfView(stage);
  if (!out) return null;
  const animation: WizardAnimation = finale ?? (model.active ? toolAnimation(model.active.name ?? '') : wizardAnimation(run));
  const verb = finale === 'success' ? 'Answer ready' : finale === 'fail' ? 'Could not finish' : wizardCaption(run, animation).verb;
  const used = model.modules.filter(m => m.stats.calls.length);
  return (
    <div className="sticky top-2 z-10 h-0">
      <div className="stage-enter flex items-center gap-3 rounded-2xl border border-accent-line bg-canvas/95 py-1 pl-1 pr-3 shadow-card backdrop-blur"
        data-testid="stage-bar" aria-hidden="true">
        <span className="relative">
          <WizardSprite animation={animation} scale={2} className="-my-3" />
          {finale === 'success' && <Burst colors={used.map(m => brand(m.id, m.name).color)} />}
        </span>
        <div className="min-w-0 flex-1">
          <p className="text-[14px] font-semibold text-ink">{verb}{!finale && <span className="stage-dots" />}</p>
          <div className="mt-1 flex flex-wrap items-center gap-1.5">
            {used.map(m => (
              <span key={m.id} className={cn('inline-flex items-center gap-1 rounded-full bg-surface py-0.5 pl-0.5 pr-2 text-[11.5px] text-ink-2',
                model.active && m.stats.calls.includes(model.active) && 'stage-breathe ring-1 ring-accent-line')}>
                <SystemLogo id={m.id} name={m.name} size={16} />{m.name}
              </span>
            ))}
            <span className="text-[11.5px] text-ink-3">{plural(model.totals.calls, 'call')}{model.totals.rows ? ` · ${plural(model.totals.rows, 'row')}` : ''}</span>
          </div>
        </div>
      </div>
    </div>
  );
}

type Finale = 'success' | 'fail' | null;
const FINALE_MS = 2400;

/** A moment after a run ends live: the wizard hops (an answer) or fizzles (a failure) before the stage folds. A run
 *  loaded already finished has no finale. */
function useFinale(run: RunView): Finale {
  const running = run.status === 'running' || run.status === 'queued';
  const was = useRef(running);
  const [finale, setFinale] = useState<Finale>(null);
  useEffect(() => {
    const ended = was.current && !running;
    was.current = running;
    if (!ended || (run.status !== 'succeeded' && run.status !== 'failed')) return;
    setFinale(run.status === 'succeeded' ? 'success' : 'fail');
    const timer = setTimeout(() => setFinale(null), FINALE_MS);
    return () => clearTimeout(timer);
  }, [running, run.status]);
  return finale;
}

/** What Wizard is doing, as a picture: the pixel wizard in his circle with the systems this person can use around him.
 *  A module lights up and streams into the circle while Gemini reads from it, and the wizard acts out the step; the
 *  caption shows the actual SQL, search words or report. Only observed tool calls drive it. When the answer lands he
 *  hops, then the stage folds into a strip of the systems used, with earned badges. */
export function SystemsStage({run, onEvidence}: {run: RunView; onEvidence: (id: string) => void}) {
  const systems = useContext(SystemsContext);
  const model = useMemo(() => stageModel(run, systems), [run, systems]);
  const running = run.status === 'running' || run.status === 'queued';
  const finale = useFinale(run);
  const [open, setOpen] = useState(false);
  const stage = useRef<HTMLDivElement>(null);
  const earned = badges(run, model);
  if (!running && !finale && model.totals.calls === 0) return null;
  if (running || open || finale) {
    return (
      <>
        {(running || finale) && <StageBar run={run} model={model} finale={finale} stage={stage} />}
        <div ref={stage} className="stage-enter overflow-hidden rounded-2xl border border-accent-line/70 bg-[radial-gradient(ellipse_at_center,rgb(58_92_214/0.10),transparent_70%),linear-gradient(to_bottom,var(--color-accent-soft),var(--color-canvas))] p-3"
          data-testid="stage">
          <Stage run={run} model={model} onEvidence={onEvidence} finale={finale} />
          <div className="mt-2 flex flex-wrap items-center gap-2">
            <Totals model={model} running={running} />
            {!running && !finale && <button type="button" onClick={() => setOpen(false)} className="ml-auto text-[12px] font-medium text-accent hover:underline">Fold</button>}
          </div>
        </div>
      </>
    );
  }
  const used = model.modules.filter(m => m.stats.calls.length);
  return (
    <div className="stage-enter flex flex-wrap items-center gap-x-3 gap-y-2 rounded-xl border border-line bg-surface/50 px-3 py-2" data-testid="journey">
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
