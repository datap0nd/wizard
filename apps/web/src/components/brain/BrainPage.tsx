import {useCallback, useEffect, useMemo, useRef, useState} from 'react';
import {ArrowLeft, ArrowRight, BadgeCheck, Maximize2, MessageSquareText, Pause, Play, X} from 'lucide-react';
import {api} from '@/api';
import {areaColor, layoutBrain, NEWS, plural, ringSystems, tourSteps, type BrainLive, type BrainMap, type Focus, type LaidNode} from '@/brain';
import mark from '@/assets/wizard-mark.svg';
import {formatDate} from '@/format';
import {cn} from '@/lib/utils';
import type {Bootstrap} from '@/types';
import {LoginScreen} from '../LoginScreen';
import {SystemLogo} from '../SystemLogo';
import {WizardSprite} from '../WizardSprite';
import {BrainCanvas} from './BrainCanvas';
import {CountUp} from './CountUp';
import {itemKey, NewsMissing, NewsPanel} from './NewsPanel';

const LIVE_EVERY_MS = 60_000;
const MAP_EVERY_MS = 10 * 60_000;
const FRESH_MS = 5 * 60_000;
const STAGE_NAMES = {SIGNED: 'Signed by its owner', EXPERT_CHECKED: 'Checked by an expert', DRAFT: 'Draft'} as const;

/** The stage's size, measured once it is on the page (it appears only after sign-in) and whenever it changes. */
function useSize(): [(el: HTMLDivElement | null) => void, {width: number; height: number}] {
  const [el, setEl] = useState<HTMLDivElement | null>(null);
  const [size, setSize] = useState({width: 960, height: 640});
  useEffect(() => {
    if (!el) return;
    const measure = () => setSize({width: Math.max(320, el.clientWidth), height: Math.max(360, el.clientHeight)});
    measure();
    if (typeof ResizeObserver === 'undefined') return;
    const observer = new ResizeObserver(measure);
    observer.observe(el);
    return () => observer.disconnect();
  }, [el]);
  return [setEl, size];
}

function useReducedMotion(): boolean {
  const [reduced] = useState(() => typeof matchMedia === 'function' && matchMedia('(prefers-reduced-motion: reduce)').matches);
  return reduced;
}

function Stat({value, label, delay}: {value: number; label: string; delay: number}) {
  return (
    <div className="min-w-[96px] rounded-xl border border-white/10 bg-white/[0.04] px-3 py-2 backdrop-blur" data-testid="brain-stat">
      <p className="text-[24px] font-semibold leading-none tracking-tight text-white"><CountUp value={value} delay={delay} /></p>
      <p className="mt-1 text-[11.5px] leading-tight text-slate-400">{label}</p>
    </div>
  );
}

/**
 * /brain: what Wizard can draw on, as one living picture, for showing Wizard to people. A page of its own, beside the
 * app: it changes nothing in the chat. Every number and name on it was read from the knowledge base, the catalogs and
 * the company database (brain.py); the motion is decoration. Presenter keys: → or Space for the next step of the tour,
 * ← for the previous one, Esc to leave it, F for full screen.
 */
export function BrainPage() {
  const [boot, setBoot] = useState<Bootstrap | null>(null);
  const [map, setMap] = useState<BrainMap | null>(null);
  const [live, setLive] = useState<BrainLive | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [hover, setHover] = useState<LaidNode | null>(null);
  const [pinned, setPinned] = useState<LaidNode | null>(null);
  const [step, setStep] = useState<number | null>(null);
  const [cluster, setCluster] = useState<string | null>(null);
  const [category, setCategory] = useState<string | null>(null);
  const [fresh, setFresh] = useState<Set<string>>(new Set());
  const [burst, setBurst] = useState(0);
  const seen = useRef<Set<string> | null>(null);
  const freshTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [stageRef, size] = useSize();
  const reduced = useReducedMotion();

  const loadBoot = useCallback(() => { api.bootstrap().then(setBoot).catch((e: unknown) => setError(e instanceof Error ? e.message : 'Wizard could not start.')); }, []);
  useEffect(() => { loadBoot(); }, [loadBoot]);
  const signedIn = !!boot?.identity && !boot.auth.login_required;
  useEffect(() => {
    if (!signedIn) return;
    const loadMap = () => api.brain().then(setMap).catch((e: unknown) => setError(e instanceof Error ? e.message : 'The brain could not be read.'));
    const loadLive = () => api.brainLive().then(next => {
      setLive(next);
      const latest = next.news.latest ?? [];
      const keys = new Set(latest.map(itemKey));
      if (seen.current) {
        const arrived = latest.filter(item => !seen.current!.has(itemKey(item))).map(itemKey);
        if (arrived.length) {
          setFresh(new Set(arrived)); setBurst(b => b + 1);
          // "NEW" for a few minutes, not for as long as the page stays open.
          if (freshTimer.current) clearTimeout(freshTimer.current);
          freshTimer.current = setTimeout(() => setFresh(new Set()), FRESH_MS);
        }
      }
      seen.current = new Set([...(seen.current ?? []), ...keys]);
    }).catch(() => undefined);
    void loadMap(); void loadLive();
    const a = setInterval(loadLive, LIVE_EVERY_MS), b = setInterval(loadMap, MAP_EVERY_MS);
    return () => { clearInterval(a); clearInterval(b); if (freshTimer.current) clearTimeout(freshTimer.current); };
  }, [signedIn]);

  const news = live?.news ?? null;
  const showNews = news?.status === 'ok';
  const layout = useMemo(() => (map ? layoutBrain(map, news, size.width, size.height, 84) : null), [map, news, size.width, size.height]);
  const steps = useMemo(() => (map ? tourSteps(map, live) : []), [map, live]);
  const current = step !== null ? steps[Math.min(step, steps.length - 1)] : null;
  const focus: Focus = current ? current.focus : pinned ? {kind: 'note', id: pinned.key} : cluster ? {kind: 'cluster', id: cluster}
    : hover ? {kind: 'note', id: hover.key} : {kind: 'all'};

  const next = useCallback(() => setStep(s => (s === null ? 0 : Math.min(s + 1, steps.length - 1))), [steps.length]);
  const previous = useCallback(() => setStep(s => (s === null ? null : Math.max(0, s - 1))), []);
  useEffect(() => {
    const keydown = (e: KeyboardEvent) => {
      if (e.target instanceof HTMLElement && ['INPUT', 'TEXTAREA'].includes(e.target.tagName)) return;
      if (['ArrowRight', 'PageDown', ' '].includes(e.key)) { e.preventDefault(); next(); }
      else if (['ArrowLeft', 'PageUp'].includes(e.key)) { e.preventDefault(); previous(); }
      else if (e.key === 'Escape') { setStep(null); setPinned(null); setCluster(null); }
      else if (e.key === 'Home') setStep(0);
      else if (e.key.toLowerCase() === 'f') void document.documentElement.requestFullscreen?.().catch(() => undefined);
    };
    window.addEventListener('keydown', keydown);
    return () => window.removeEventListener('keydown', keydown);
  }, [next, previous]);

  if (error) return <div className="grid min-h-dvh place-items-center bg-[#050817] p-6 text-sm text-rose-300" role="alert">{error}</div>;
  if (!boot) return <div className="grid min-h-dvh place-content-center justify-items-center gap-2 bg-[#050817] text-sm text-slate-400"><WizardSprite animation="idle" scale={2} />Loading Wizard…</div>;
  if (!signedIn) return <LoginScreen mode={boot.auth.mode} onLogin={loadBoot} />;

  const counts = map?.counts;
  const card = pinned ?? hover;
  // The caption goes to the top while the cluster it talks about is in the lower part of the picture.
  const shown = current?.focus.kind === 'cluster' ? layout?.clusters.find(c => c.id === (current.focus as {id: string}).id) : null;
  const captionTop = !!shown && !!layout && shown.y > layout.height * 0.55;
  const database = live?.database.status === 'ok' ? live.database : null;
  const scale = layout && layout.core >= 78 ? 3 : 2;
  return (
    <div className="brain-page flex h-dvh w-screen flex-col overflow-hidden text-slate-100" data-testid="brain-page">
      <header className="z-20 flex flex-wrap items-center gap-3 px-5 pb-2 pt-4">
        <img src={mark} alt="" className="size-8" />
        <div className="min-w-0">
          <h1 className="text-[20px] font-semibold leading-tight tracking-tight text-white">Wizard's brain</h1>
          <p className="text-[12.5px] text-slate-400">
            {map?.content === 'company' ? <>Company knowledge base{map.knowledge_synced_at ? `, synced ${formatDate(map.knowledge_synced_at, true)}` : ''}</>
              : map?.content === 'none' ? 'The knowledge base has not synced yet' : map ? 'Example content: not company knowledge' : 'Reading what Wizard knows…'}
          </p>
        </div>
        {map && map.content !== 'company' && <span className="rounded-full border border-amber-300/40 bg-amber-300/10 px-2 py-0.5 text-[11.5px] font-semibold text-amber-200" data-testid="brain-examples">EXAMPLE CONTENT</span>}
        <div className="ml-auto flex items-center gap-1.5">
          <button type="button" onClick={() => (step === null ? setStep(0) : setStep(null))} data-testid="brain-tour"
            className="inline-flex items-center gap-1.5 rounded-lg border border-white/15 bg-white/5 px-3 py-1.5 text-[13px] font-medium hover:bg-white/10">
            {step === null ? <><Play className="size-3.5" />Tour</> : <><Pause className="size-3.5" />End tour</>}</button>
          <button type="button" onClick={() => void document.documentElement.requestFullscreen?.().catch(() => undefined)} aria-label="Full screen" title="Full screen (F)"
            className="rounded-lg border border-white/15 bg-white/5 p-2 hover:bg-white/10"><Maximize2 className="size-3.5" /></button>
          <a href="/" className="inline-flex items-center gap-1.5 rounded-lg bg-[#1428a0] px-3 py-1.5 text-[13px] font-semibold text-white shadow hover:bg-[#1c34c0]">
            <MessageSquareText className="size-3.5" />Ask Wizard</a>
        </div>
      </header>

      <div className="flex min-h-0 flex-1 flex-col gap-3 px-3 pb-3 lg:flex-row">
        <div ref={stageRef} className="relative min-h-[420px] flex-1 overflow-hidden rounded-3xl" data-testid="brain-stage">
          <div className="brain-stars pointer-events-none absolute inset-0" />
          {layout && map && <>
            <BrainCanvas layout={layout} focus={focus} hovered={card?.key ?? null} reduced={reduced} burst={burst}
              onHover={node => { if (!pinned) setHover(node); }} onPick={node => { setPinned(node); setCluster(null); }} />
            {/* The wizard at the centre, in his magic circle. */}
            <div className="pointer-events-none absolute -translate-x-1/2 -translate-y-1/2" style={{left: layout.center.x, top: layout.center.y}}>
              <svg width={layout.core * 2 + 40} height={layout.core * 2 + 40} viewBox="-1 -1 2 2" className="absolute left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2" aria-hidden="true">
                <defs><radialGradient id="brain-core"><stop offset="0" stopColor="#3b5bff" stopOpacity="0.55" /><stop offset="0.7" stopColor="#1428a0" stopOpacity="0.18" /><stop offset="1" stopColor="#1428a0" stopOpacity="0" /></radialGradient></defs>
                <circle r="1" fill="url(#brain-core)" />
                <circle r="0.86" fill="none" stroke="#8ea2ff" strokeOpacity="0.55" strokeWidth="0.012" strokeDasharray="0.05 0.035" className="stage-orbit" />
                <circle r="0.74" fill="none" stroke="#c7d2fe" strokeOpacity="0.35" strokeWidth="0.008" strokeDasharray="0.012 0.03" className="stage-orbit-rev" />
              </svg>
              <WizardSprite animation={current?.id === 'ask' ? 'wave' : 'cast'} scale={scale} label="Wizard" className="relative" />
            </div>
            {/* The systems around him. */}
            {layout.systems.map(({id, system, x, y}) => {
              const on = focus.kind === 'all' || focus.kind === 'systems' || (focus.kind === 'cluster' && focus.id === NEWS && id === 'postgresql');
              const detail = id === 'postgresql' && database ? `${plural(database.relations ?? 0, 'table')} & views`
                : system.reports ? plural(system.reports, 'report') : system.kind === 'knowledge' && system.notes ? plural(system.notes, 'note')
                : system.kind === 'portal' ? 'read live' : system.kind === 'schedules' ? 'recurring briefs' : '';
              return (
                <div key={id} className={cn('absolute flex w-[118px] -translate-x-1/2 -translate-y-1/2 flex-col items-center gap-1 text-center transition-opacity duration-500', on ? 'opacity-100' : 'opacity-30')}
                  style={{left: x, top: y}} data-testid="brain-system" data-system={id}>
                  <span className={cn('relative rounded-[30%]', focus.kind === 'systems' && 'brain-halo')}>
                    <SystemLogo id={id} name={system.name} size={42} />
                  </span>
                  <span className="max-w-full truncate text-[12px] font-semibold leading-tight text-white [text-shadow:0_1px_6px_#000]">{system.name}</span>
                  {detail && <span className="max-w-full truncate text-[11px] leading-tight text-slate-300 [text-shadow:0_1px_6px_#000]">{detail}</span>}
                </div>
              );
            })}
            {/* Each topic's name, outside its cluster. */}
            {layout.clusters.map(c => {
              const on = focus.kind === 'all' || (focus.kind === 'cluster' && focus.id === c.id) || (focus.kind === 'note' && layout.byKey.get(focus.id)?.cluster === c.id);
              return (
                <button key={c.id} type="button" onClick={() => { setCluster(cluster === c.id ? null : c.id); setPinned(null); setStep(null); }}
                  className={cn('absolute z-10 -translate-y-1/2 whitespace-nowrap rounded-lg px-2 py-1 text-left transition-opacity duration-500 hover:bg-white/10',
                    c.side === 'right' ? '' : c.side === 'left' ? '-translate-x-full text-right' : '-translate-x-1/2 text-center', on ? 'opacity-100' : 'opacity-35')}
                  style={{left: c.label.x, top: c.label.y}} aria-pressed={cluster === c.id} data-testid="brain-cluster" data-cluster={c.id}>
                  <span className="block text-[13.5px] font-semibold leading-tight [text-shadow:0_1px_8px_#000]" style={{color: c.color}}>{c.name}</span>
                  <span className="block text-[11.5px] leading-tight text-slate-300 [text-shadow:0_1px_8px_#000]">{c.id === NEWS ? plural(c.count, 'article') : plural(c.count, 'note')}</span>
                </button>
              );
            })}
          </>}
          {!map && <div className="absolute inset-0 grid place-content-center justify-items-center gap-2 text-sm text-slate-400"><WizardSprite animation="think" scale={3} />Reading what Wizard knows…</div>}
          {map && map.notes.length === 0 && <p className="absolute left-1/2 top-6 -translate-x-1/2 rounded-lg bg-white/10 px-3 py-2 text-[13px] text-slate-200">No knowledge notes are loaded on this Wizard yet.</p>}

          {/* A note under the pointer, or the one clicked. */}
          {card?.note && !current && (
            <div className="brain-pop absolute right-4 top-4 z-20 w-[min(340px,calc(100%-2rem))] rounded-xl border border-white/15 bg-[#0b1230]/95 p-3 shadow-2xl backdrop-blur" data-testid="brain-card">
              <div className="flex items-start gap-2">
                <i className="mt-1.5 size-2.5 shrink-0 rounded-full" style={{background: areaColor(card.note.area)}} />
                <div className="min-w-0 flex-1">
                  <p className="text-[14px] font-semibold leading-snug text-white">{card.note.title}</p>
                  <p className="mt-0.5 text-[11.5px] text-slate-400">{layout?.clusters.find(c => c.id === card.cluster)?.name}{card.note.type ? ` · ${card.note.type}` : ''}{card.note.terms ? ` · ${plural(card.note.terms, 'term')}` : ''}</p>
                </div>
                {pinned && <button type="button" onClick={() => setPinned(null)} aria-label="Close" className="rounded p-0.5 text-slate-400 hover:bg-white/10"><X className="size-3.5" /></button>}
              </div>
              {card.note.summary && <p className="mt-2 text-[12.5px] leading-snug text-slate-200">{card.note.summary}</p>}
              <p className={cn('mt-2 inline-flex items-center gap-1 text-[11.5px]', card.note.stage === 'DRAFT' ? 'text-slate-400' : 'text-emerald-300')}>
                {card.note.stage !== 'DRAFT' && <BadgeCheck className="size-3.5" />}{STAGE_NAMES[card.note.stage]}{card.note.updated ? ` · updated ${formatDate(card.note.updated)}` : ''}</p>
            </div>
          )}
          {card?.news && !current && (
            <div className="brain-pop absolute right-4 top-4 z-20 rounded-xl border border-white/15 bg-[#0b1230]/95 px-3 py-2 shadow-2xl" data-testid="brain-card">
              <p className="text-[14px] font-semibold text-white">{card.news.name}</p>
              <p className="text-[12px] text-slate-300">{plural(card.news.count, 'article')} in the news table</p>
            </div>
          )}

          {/* The tour's caption, for presenting. */}
          {current && (
            <div key={current.id} className={cn('brain-caption absolute left-1/2 z-30 w-[min(720px,calc(100%-2rem))] -translate-x-1/2 rounded-2xl border border-white/15 bg-[#081033]/90 px-6 py-4 shadow-2xl backdrop-blur',
              captionTop ? 'top-4' : 'bottom-4')} data-testid="brain-caption" data-place={captionTop ? 'top' : 'bottom'} aria-live="polite">
              <p className="text-[12px] font-medium uppercase tracking-[0.14em] text-[#8ea2ff]">Step {Math.min(step! + 1, steps.length)} of {steps.length}</p>
              <h2 className="mt-1 text-[26px] font-semibold leading-tight tracking-tight text-white">{current.title}</h2>
              <p className="mt-1.5 text-[16px] leading-snug text-slate-200">{current.body}</p>
              {current.examples && current.examples.length > 0 && <p className="mt-2 text-[13px] text-slate-400">Including {current.examples.map((e, i) => <span key={e}>{i ? (i === current.examples!.length - 1 ? ' and ' : ', ') : ''}<span className="text-slate-200">{e}</span></span>)}.</p>}
              <div className="mt-3 flex items-center gap-2">
                <div className="flex gap-1">{steps.map((s, i) => <button key={s.id} type="button" onClick={() => setStep(i)} aria-label={`Step ${i + 1}: ${s.title}`}
                  className={cn('h-1.5 rounded-full transition-all', i === step ? 'w-6 bg-[#8ea2ff]' : 'w-1.5 bg-white/25 hover:bg-white/50')} />)}</div>
                <span className="ml-auto text-[11.5px] text-slate-400">← → to move · Esc to leave</span>
                <button type="button" onClick={previous} disabled={step === 0} aria-label="Previous step" className="rounded-lg border border-white/15 p-1.5 hover:bg-white/10 disabled:opacity-30"><ArrowLeft className="size-4" /></button>
                {step! < steps.length - 1 ? <button type="button" onClick={next} aria-label="Next step" className="rounded-lg bg-[#1428a0] p-1.5 hover:bg-[#1c34c0]"><ArrowRight className="size-4" /></button>
                  : <a href="/" className="rounded-lg bg-[#1428a0] px-3 py-1.5 text-[13px] font-semibold hover:bg-[#1c34c0]">Ask Wizard</a>}
              </div>
            </div>
          )}
          {!current && counts && (
            <div className="pointer-events-none absolute bottom-3 left-3 right-3 z-10 flex gap-2 overflow-hidden" data-testid="brain-stats">
              {/* One row, most telling first: as many as the stage has room for. */}
              {([[counts.notes, 'notes'], [counts.areas, 'topics'], [counts.links, 'connections'], [showNews ? news.total ?? 0 : 0, 'news articles'],
                [ringSystems(map!).length, 'systems'], [counts.glossary_terms, 'terms & acronyms'], [counts.datasets, 'datasets documented'],
                [database?.relations ?? 0, 'tables & views readable'], [counts.reports, 'reports catalogued']] as [number, string][])
                .filter(([value], i) => value > 0 || i < 3).slice(0, Math.max(3, Math.floor((size.width - 24) / 128)))
                .map(([value, label], i) => <Stat key={label} value={value} label={label} delay={200 + i * 100} />)}
            </div>
          )}
          {step === null && map && !card && <p className="pointer-events-none absolute right-4 top-4 z-0 hidden text-[11.5px] text-slate-500 lg:block">Press → to start the tour</p>}
        </div>
        {news && (
          <aside className={cn('flex min-h-0 shrink-0 flex-col lg:w-[380px]', current?.focus.kind === 'cluster' && current.focus.id === NEWS && 'brain-spotlight')}>
            {showNews ? <NewsPanel news={news} fresh={fresh} category={category} onCategory={setCategory} name={live?.name ?? 'Company database'} />
              : <NewsMissing news={news} />}
          </aside>
        )}
      </div>
    </div>
  );
}
