import {createContext, useContext, useState} from 'react';
import {Ban, BookmarkPlus, Check, CheckCircle2, Clock3, Layers, UserRound} from 'lucide-react';
import {cn} from '@/lib/utils';
import {steerLabel} from '@/runState';
import {Button} from './ui/button';
import {SystemLogo} from './SystemLogo';
import type {RunView, Steer, SteerReason, SystemRequest, TimelineItem} from '@/types';

/** What the person can do to steer an answer, provided by the app to every card. */
export interface SteerActions {
  /** Notes reach Gemini while it works (otherwise a note stops the run and asks again). */
  live: boolean;
  notThis: (run: RunView, step: TimelineItem, reason: SteerReason, text: string) => Promise<void>;
  remember: (text: string, runId: string | null) => Promise<boolean>;
  turnOn: (run: RunView, request: SystemRequest) => void;
}

export const SteerContext = createContext<SteerActions | null>(null);

const REASONS: [SteerReason, string][] = [['table', 'Wrong table'], ['filter', 'Wrong filter'], ['period', 'Wrong period'], ['other', 'Something else']];

/** Steps a note can be about: the ones that read data (a query, a report, a search, a portal), not Wizard's own work. */
export function correctable(item: TimelineItem): boolean {
  return item.kind === 'tool' && (item.category === 'source' || item.category === 'knowledge');
}

/** Not this on one step: what was wrong with it and, if the person knows, what to use instead. While the answer runs,
 * Wizard reads it before its next step and leaves that step's evidence out; after, it redoes the answer. */
export function NotThis({run, item, className}: {run: RunView; item: TimelineItem; className?: string}) {
  const actions = useContext(SteerContext);
  const [open, setOpen] = useState(false);
  const [reason, setReason] = useState<SteerReason>('table');
  const [text, setText] = useState('');
  const [sending, setSending] = useState(false);
  if (!actions || !correctable(item)) return null;
  const running = run.status === 'running' || run.status === 'queued';
  const how = !running ? 'Wizard redoes the answer without this step.'
    : actions.live ? 'Wizard reads this before its next step and leaves this step out.'
      : 'Wizard stops and asks again with this note.';
  if (!open) return (
    <button type="button" onClick={() => setOpen(true)} data-testid="not-this"
      className={cn('inline-flex items-center gap-1 rounded px-1 text-[11.5px] font-medium text-ink-3 hover:bg-danger-soft hover:text-danger', className)}>
      <Ban className="size-3" />Not this
    </button>
  );
  async function send() {
    setSending(true);
    try { await actions!.notThis(run, item, reason, text.trim()); setOpen(false); setText(''); } finally { setSending(false); }
  }
  return (
    <form className="mt-1.5 basis-full rounded-lg border border-line bg-canvas p-2" data-testid="not-this-form"
      onSubmit={e => { e.preventDefault(); void send(); }}>
      <div className="flex flex-wrap gap-1" role="radiogroup" aria-label="What was wrong">
        {REASONS.map(([key, label]) => (
          <button key={key} type="button" role="radio" aria-checked={reason === key} onClick={() => setReason(key)}
            className={cn('rounded-full border px-2 py-0.5 text-[12px]', reason === key ? 'border-accent bg-accent-soft text-accent' : 'border-line text-ink-2 hover:bg-surface')}>{label}</button>
        ))}
      </div>
      <input autoFocus value={text} onChange={e => setText(e.target.value)} maxLength={2000} aria-label="What should Wizard use instead"
        placeholder="What should it use instead? (optional)"
        className="mt-1.5 h-8 w-full rounded-md border border-line px-2 text-[13px] outline-none placeholder:text-ink-3 focus:border-line-2" />
      <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
        <Button type="submit" size="xs" variant="accent" disabled={sending} data-testid="not-this-send">{running ? 'Send to Wizard' : 'Ask again'}</Button>
        <Button size="xs" variant="ghost" onClick={() => setOpen(false)}>Cancel</Button>
        <span className="text-[11.5px] text-ink-3">{how}</span>
      </div>
    </form>
  );
}

/** Remember this: the person's own words, edited if they like, go into every question they ask from now on. */
export function RememberButton({text, runId, className, label = 'Remember'}: {text: string; runId: string | null; className?: string; label?: string}) {
  const actions = useContext(SteerContext);
  const [editing, setEditing] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  if (!actions) return null;
  if (saved) return <span className={cn('inline-flex items-center gap-1 text-[11.5px] text-ok', className)} data-testid="remembered"><Check className="size-3" />Remembered</span>;
  if (editing === null) return (
    <button type="button" onClick={() => setEditing(text.slice(0, 500))} data-testid="remember"
      className={cn('inline-flex items-center gap-1 rounded px-1 text-[11.5px] font-medium text-ink-3 hover:bg-surface hover:text-ink', className)}>
      <BookmarkPlus className="size-3" />{label}
    </button>
  );
  return (
    <form className="flex w-full max-w-[560px] items-center gap-1.5" data-testid="remember-form"
      onSubmit={async e => { e.preventDefault(); if (editing.trim() && await actions.remember(editing.trim(), runId)) { setSaved(true); setEditing(null); } }}>
      <input autoFocus value={editing} onChange={e => setEditing(e.target.value)} maxLength={500} aria-label="What Wizard should remember"
        className="h-7 min-w-0 flex-1 rounded-md border border-line bg-canvas px-2 text-[12.5px] outline-none focus:border-line-2" />
      <Button type="submit" size="xs" variant="accent" disabled={!editing.trim()}>Remember</Button>
      <Button size="xs" variant="ghost" onClick={() => setEditing(null)}>Cancel</Button>
    </form>
  );
}

function rememberText(steer: Steer): string {
  return steer.text || steerLabel(steer);
}

/** The notes the person sent while this answer was worked on: waiting for Gemini's next step, then read. */
export function SteerNotes({run}: {run: RunView}) {
  if (!run.steers.length) return null;
  return (
    <ul className="space-y-1.5 rounded-xl border border-accent-line bg-accent-soft/40 px-3 py-2" data-testid="steer-notes" aria-live="polite">
      {run.steers.map(steer => (
        <li key={steer.id} className="flex flex-wrap items-center gap-x-2 gap-y-1 text-[13px]" data-testid="steer-note" data-state={steer.state}>
          <UserRound className="size-3.5 shrink-0 text-accent" />
          <span className="min-w-0 break-words text-ink"><span className="font-medium">You:</span> {steerLabel(steer)}</span>
          {steer.state === 'read'
            ? <span className="inline-flex items-center gap-1 text-[11.5px] text-ok"><CheckCircle2 className="size-3" />Read by Wizard</span>
            : <span className="inline-flex items-center gap-1 text-[11.5px] text-ink-3"><Clock3 className="size-3" />Wizard reads it after the current step</span>}
          <RememberButton text={rememberText(steer)} runId={run.id} className="ml-auto" />
        </li>
      ))}
    </ul>
  );
}

/** Gemini asked for a system the person switched off for this question: one click switches it on and goes on. */
export function SystemRequests({run}: {run: RunView}) {
  const actions = useContext(SteerContext);
  const [done, setDone] = useState<string[]>([]);
  const waiting = run.systemRequests.filter(r => !done.includes(r.system) && !run.systems?.includes(r.system));
  if (!waiting.length || !actions || run.systems === null) return null;
  const running = run.status === 'running' || run.status === 'queued';
  return <>
    {waiting.map(request => (
      <div key={request.system} className="flex flex-wrap items-center gap-2 rounded-xl border border-line bg-surface/60 px-3 py-2.5 text-[13px]" data-testid="system-request">
        <SystemLogo id={request.system} name={request.name} size={26} />
        <p className="min-w-0 flex-1"><span className="font-medium">This answer could use {request.name}</span>, which is switched off for this
          question. <span className="text-ink-2">{request.reason}</span></p>
        <Button size="sm" variant="outline" data-testid="turn-on-system" onClick={() => { setDone(d => [...d, request.system]); actions.turnOn(run, request); }}>
          <Layers />{running ? `Switch on ${request.name}` : `Switch on ${request.name} and continue`}
        </Button>
      </div>
    ))}
  </>;
}
