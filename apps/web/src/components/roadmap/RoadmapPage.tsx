import {useCallback, useEffect, useMemo, useState} from 'react';
import type {ComponentType, CSSProperties} from 'react';
import {ArrowLeft, ArrowRight, BookOpen, BrainCircuit, CalendarDays, ChartLine, Database, FileSpreadsheet, Globe, KeyRound, ListChecks,
  Mail, Maximize2, MessageSquareText, MousePointerClick, Network, Presentation, Target} from 'lucide-react';
import mark from '@/assets/wizard-mark.svg';
import {cn} from '@/lib/utils';
import {CAPABILITIES, calendarDay, dayLabel, MILESTONES, placeMilestones, SYSTEMS_TODAY, type Icon, type PlacedMilestone} from '@/roadmap';
import {SystemLogo} from '../SystemLogo';
import {WizardSprite} from '../WizardSprite';

const ICONS: Record<Icon, {glyph: ComponentType<{className?: string; style?: CSSProperties}>; color: string}> = {
  ask: {glyph: MessageSquareText, color: '#8ea2ff'}, database: {glyph: Database, color: '#a78bfa'},
  portal: {glyph: Globe, color: '#38bdf8'}, knowledge: {glyph: BookOpen, color: '#34d399'},
  files: {glyph: FileSpreadsheet, color: '#4ade80'}, brief: {glyph: Mail, color: '#2dd4bf'},
  access: {glyph: KeyRound, color: '#fbbf24'}, evidence: {glyph: ListChecks, color: '#f472b6'}, desktop: {glyph: MousePointerClick, color: '#818cf8'},
  slides: {glyph: Presentation, color: '#fb923c'}, growth: {glyph: BrainCircuit, color: '#34d399'},
  metrics: {glyph: ChartLine, color: '#a78bfa'}, strategy: {glyph: Target, color: '#f472b6'},
};

const STATE_STYLE: Record<PlacedMilestone['state'], string> = {
  next: 'border-[#8ea2ff]/50 bg-[#8ea2ff]/15 text-[#c7d2fe]',
  planned: 'border-white/15 bg-white/5 text-slate-300',
  late: 'border-amber-300/40 bg-amber-300/10 text-amber-200',
  done: 'border-emerald-300/40 bg-emerald-300/10 text-emerald-200',
};

function IconTile({icon, size = 34}: {icon: Icon; size?: number}) {
  const {glyph: Glyph, color} = ICONS[icon];
  return (
    <span className="grid shrink-0 place-items-center rounded-xl border" aria-hidden="true"
      style={{width: size, height: size, color, borderColor: `${color}55`, background: `linear-gradient(145deg, ${color}33, ${color}0d)`}}>
      <Glyph className="size-[55%]" />
    </span>
  );
}

/** Today, then each Friday on a line; a Friday lights up once it is shown. */
function WeekRuler({milestones, shown, now}: {milestones: PlacedMilestone[]; shown: number; now: Date}) {
  const span = Math.max(1, milestones[milestones.length - 1].days);
  const at = (days: number) => `${Math.min(100, Math.max(0, (days / span) * 100))}%`;
  return (
    <div className="relative mx-2 mt-3 h-14" data-testid="roadmap-ruler" aria-hidden="true">
      <span className="absolute left-0 top-0 -translate-x-2 whitespace-nowrap text-[12px] font-semibold text-white">Today · {dayLabel(now)}</span>
      <div className="absolute inset-x-0 top-[25px] h-[3px] rounded-full bg-white/10" />
      <div className="absolute left-0 top-[25px] h-[3px] rounded-full bg-gradient-to-r from-[#8ea2ff] to-[#8ea2ff]/60 transition-[width] duration-700"
        style={{width: shown ? at(milestones[shown - 1].days) : '0%'}} />
      <span className="absolute left-0 top-[18px] size-[17px] -translate-x-1/2 rounded-full border-2 border-white bg-[#1428a0] shadow-[0_0_14px_#8ea2ff]" />
      {milestones.map((m, i) => (
        <span key={m.id} className="absolute top-[19px] -translate-x-1/2" style={{left: at(m.days)}}>
          <span className={cn('block size-[15px] rounded-full border-2 transition-colors duration-500',
            i < shown ? 'border-[#c7d2fe] bg-[#8ea2ff] shadow-[0_0_12px_#8ea2ff]' : 'border-white/30 bg-[#0b1230]')} />
          <span className={cn('absolute top-[21px] whitespace-nowrap text-[12px] transition-colors duration-500', i < shown ? 'text-white' : 'text-slate-500',
            i === milestones.length - 1 ? 'right-0 translate-x-2' : 'left-1/2 -translate-x-1/2')}>{dayLabel(calendarDay(m.due))}</span>
        </span>
      ))}
    </div>
  );
}

function MilestoneCard({m, index}: {m: PlacedMilestone; index: number}) {
  const {color} = ICONS[m.icon];
  return (
    <li className="roadmap-rise relative pl-16" data-testid="roadmap-milestone" data-state={m.state}>
      {/* The node on the timeline: the week's number. */}
      <span className={cn('absolute left-0 top-3 grid size-11 place-items-center rounded-full border-2 text-[15px] font-bold',
        m.state === 'next' ? 'roadmap-pulse border-[#c7d2fe] bg-[#1428a0] text-white' : m.state === 'done' ? 'border-emerald-200 bg-emerald-600 text-white' : 'border-white/25 bg-[#0b1230] text-slate-200')}>
        {index + 1}
      </span>
      <article className={cn('rounded-2xl border p-4 backdrop-blur', m.state === 'next' ? 'border-[#8ea2ff]/45 bg-[#101a4a]/80 shadow-[0_0_40px_rgb(91_124_255/0.22)]' : 'border-white/10 bg-white/[0.04]')}>
        <div className="flex flex-wrap items-center gap-2">
          <span className="inline-flex items-center gap-1.5 rounded-lg bg-white/10 px-2.5 py-1 text-[13px] font-semibold text-white" data-testid="roadmap-due">
            <CalendarDays className="size-3.5" />{dayLabel(calendarDay(m.due))}</span>
          <span className="text-[12px] font-medium uppercase tracking-[0.12em] text-slate-400">{m.week}</span>
          <span className={cn('ml-auto rounded-full border px-2.5 py-0.5 text-[12px] font-semibold', STATE_STYLE[m.state])} data-testid="roadmap-when">
            {m.state === 'next' ? `Next · ${m.when}` : m.when}</span>
        </div>
        <div className="mt-3 flex items-start gap-3">
          {m.logo ? <SystemLogo id={m.logo} size={40} /> : <IconTile icon={m.icon} size={40} />}
          <div className="min-w-0 flex-1">
            <h3 className="text-[19px] font-semibold leading-tight tracking-tight text-white">{m.title}</h3>
            <p className="mt-1 text-[14px] leading-snug text-slate-300">{m.body}</p>
          </div>
        </div>
        <ul className={cn('mt-3 grid gap-2', m.items.length > 2 ? 'sm:grid-cols-3' : 'sm:grid-cols-[repeat(2,max-content)]')}>
          {m.items.map(item => (
            <li key={item.name} className="flex items-center gap-2.5 rounded-xl border border-white/10 bg-white/[0.05] py-2 pl-2 pr-3" data-testid="roadmap-item">
              {item.logo ? <SystemLogo id={item.logo} name={item.name} size={30} /> : item.icon ? <IconTile icon={item.icon} size={30} />
                : <i className="size-1.5 shrink-0 rounded-full" style={{background: color}} />}
              <span className="min-w-0">
                <span className="block text-[13.5px] font-semibold leading-tight text-white">{item.name}</span>
                {item.detail && <span className="mt-0.5 block text-[12px] leading-snug text-slate-400">{item.detail}</span>}
              </span>
            </li>
          ))}
        </ul>
      </article>
    </li>
  );
}

/**
 * /roadmap: what Wizard does today (left) and what comes next, one Friday at a time (right), for showing Wizard to
 * people. A page of its own like /brain; nothing in the app changes, and it reads no data (its content is roadmap.ts).
 * → (or Space, Page Down) shows the next Friday, ← takes it back, End shows them all, Home none; F for full screen.
 */
export function RoadmapPage() {
  const [now, setNow] = useState(() => new Date());
  const [shown, setShown] = useState(0);
  const milestones = useMemo(() => placeMilestones(MILESTONES, now), [now]);
  const total = milestones.length;
  const next = useCallback(() => setShown(s => Math.min(total, s + 1)), [total]);
  const previous = useCallback(() => setShown(s => Math.max(0, s - 1)), []);

  useEffect(() => {
    const timer = setInterval(() => setNow(new Date()), 60 * 60_000);  // the countdown moves on after midnight
    const keydown = (e: KeyboardEvent) => {
      if (e.target instanceof HTMLElement && ['INPUT', 'TEXTAREA'].includes(e.target.tagName)) return;
      if (['ArrowRight', 'PageDown', ' '].includes(e.key)) { e.preventDefault(); next(); }
      else if (['ArrowLeft', 'PageUp'].includes(e.key)) { e.preventDefault(); previous(); }
      else if (e.key === 'End') setShown(total);
      else if (e.key === 'Home') setShown(0);
      else if (e.key.toLowerCase() === 'f') void document.documentElement.requestFullscreen?.().catch(() => undefined);
    };
    window.addEventListener('keydown', keydown);
    return () => { clearInterval(timer); window.removeEventListener('keydown', keydown); };
  }, [next, previous, total]);

  return (
    <div className="brain-page relative min-h-dvh w-full overflow-x-hidden text-slate-100" data-testid="roadmap-page">
      <div className="brain-stars pointer-events-none fixed inset-0" />
      <header className="relative z-10 flex flex-wrap items-center gap-3 px-5 pb-3 pt-4">
        <img src={mark} alt="" className="size-8" />
        <div className="min-w-0">
          <h1 className="text-[20px] font-semibold leading-tight tracking-tight text-white">Wizard roadmap</h1>
          <p className="text-[12.5px] text-slate-400">What Wizard does today, and what comes next: one Friday at a time.</p>
        </div>
        <div className="ml-auto flex items-center gap-1.5">
          <a href="/brain" className="inline-flex items-center gap-1.5 rounded-lg border border-white/15 bg-white/5 px-3 py-1.5 text-[13px] font-medium hover:bg-white/10">
            <Network className="size-3.5" />Brain</a>
          <button type="button" onClick={() => void document.documentElement.requestFullscreen?.().catch(() => undefined)} aria-label="Full screen" title="Full screen (F)"
            className="rounded-lg border border-white/15 bg-white/5 p-2 hover:bg-white/10"><Maximize2 className="size-3.5" /></button>
          <a href="/" className="inline-flex items-center gap-1.5 rounded-lg bg-[#1428a0] px-3 py-1.5 text-[13px] font-semibold text-white shadow hover:bg-[#1c34c0]">
            <MessageSquareText className="size-3.5" />Ask Wizard</a>
        </div>
      </header>

      <main className="relative z-10 grid gap-4 px-3 pb-5 sm:px-5 lg:grid-cols-[minmax(0,5fr)_minmax(0,7fr)]">
        {/* Today: what Wizard already does. */}
        <section className="rounded-3xl border border-white/10 bg-white/[0.03] p-5" data-testid="roadmap-today" aria-labelledby="roadmap-today-title">
          <div className="flex items-center gap-3">
            <div className="min-w-0 flex-1">
              <p className="flex items-center gap-2 text-[12px] font-semibold uppercase tracking-[0.16em] text-emerald-300">
                <i className="brain-live size-2 rounded-full bg-emerald-400 shadow-[0_0_10px_#34d399]" />Today</p>
              <h2 id="roadmap-today-title" className="mt-1 text-[26px] font-semibold leading-tight tracking-tight text-white">What Wizard already does</h2>
            </div>
            <WizardSprite animation="cast" scale={2} label="Wizard" />
          </div>
          <ul className="mt-4 grid gap-2.5 sm:grid-cols-2">
            {CAPABILITIES.map((c, i) => (
              <li key={c.title} className={cn('roadmap-rise flex gap-3 rounded-2xl border border-white/10 bg-white/[0.04] p-3',
                CAPABILITIES.length % 2 === 1 && i === CAPABILITIES.length - 1 && 'sm:col-span-2')} style={{animationDelay: `${0.05 + i * 0.05}s`}} data-testid="roadmap-capability">
                <IconTile icon={c.icon} />
                <div className="min-w-0">
                  <h3 className="text-[14.5px] font-semibold leading-tight text-white">{c.title}</h3>
                  <p className="mt-1 text-[12.5px] leading-snug text-slate-300">{c.body}</p>
                </div>
              </li>
            ))}
          </ul>
          <div className="mt-5 border-t border-white/10 pt-4">
            <p className="text-[12px] font-semibold uppercase tracking-[0.14em] text-slate-400">Reads today</p>
            <ul className="mt-2.5 grid grid-cols-4 gap-x-2 gap-y-3 sm:grid-cols-7">
              {SYSTEMS_TODAY.map(s => (
                <li key={s.id} className="flex flex-col items-center gap-1 text-center" data-testid="roadmap-system">
                  <SystemLogo id={s.id} name={s.name} size={36} />
                  <span className="text-[11.5px] leading-tight text-slate-300">{s.name}</span>
                </li>
              ))}
            </ul>
          </div>
        </section>

        {/* Next: the roadmap, one Friday at a time, shown with the arrow keys. */}
        <section className="flex flex-col rounded-3xl border border-white/10 bg-white/[0.03] p-5" data-testid="roadmap-next" aria-labelledby="roadmap-next-title">
          <p className="text-[12px] font-semibold uppercase tracking-[0.16em] text-[#8ea2ff]">Next</p>
          <h2 id="roadmap-next-title" className="mt-1 text-[26px] font-semibold leading-tight tracking-tight text-white">The roadmap</h2>
          <WeekRuler milestones={milestones} shown={shown} now={now} />
          <ol className="relative mt-5 flex-1 space-y-4" aria-live="polite">
            {shown > 0 && <span className="roadmap-line absolute bottom-6 left-[21px] top-6 w-[3px] rounded-full bg-gradient-to-b from-[#8ea2ff] via-[#8ea2ff]/40 to-white/5" aria-hidden="true" />}
            {milestones.slice(0, shown).map((m, i) => <MilestoneCard key={m.id} m={m} index={i} />)}
            {shown === total && (
              <li className="roadmap-rise relative pl-16">
                <span className="absolute left-[7px] top-0 size-[31px] rounded-full border-2 border-dashed border-white/25" aria-hidden="true" />
                <p className="pt-1.5 text-[14px] text-slate-400">Then the next step, one Friday later, and so on, week by week.</p>
              </li>
            )}
          </ol>
          {shown === 0 && (
            <button type="button" onClick={next} className="roadmap-rise mx-auto my-8 grid place-items-center gap-2 rounded-2xl px-6 py-4 text-slate-300 hover:bg-white/5" data-testid="roadmap-start">
              <span className="roadmap-pulse grid size-12 place-items-center rounded-full border-2 border-[#c7d2fe] bg-[#1428a0] text-white"><ArrowRight className="size-5" /></span>
              <span className="text-[14px]">Press → to see what's next</span>
            </button>
          )}
          <div className="mt-4 flex items-center gap-2 border-t border-white/10 pt-3">
            <div className="flex gap-1">{milestones.map((m, i) => (
              <button key={m.id} type="button" onClick={() => setShown(i + 1)} aria-label={`Show up to ${dayLabel(calendarDay(m.due))}`}
                className={cn('h-1.5 rounded-full transition-all', i < shown ? 'w-6 bg-[#8ea2ff]' : 'w-1.5 bg-white/25 hover:bg-white/50')} />))}</div>
            <span className="ml-auto hidden text-[11.5px] text-slate-500 sm:inline">← → to move</span>
            <button type="button" onClick={previous} disabled={shown === 0} aria-label="Previous" data-testid="roadmap-previous"
              className="rounded-lg border border-white/15 p-1.5 hover:bg-white/10 disabled:opacity-30"><ArrowLeft className="size-4" /></button>
            <button type="button" onClick={next} disabled={shown === total} aria-label="Next" data-testid="roadmap-forward"
              className="rounded-lg bg-[#1428a0] p-1.5 hover:bg-[#1c34c0] disabled:opacity-30"><ArrowRight className="size-4" /></button>
          </div>
        </section>
      </main>
    </div>
  );
}
