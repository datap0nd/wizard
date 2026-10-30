import {memo, useContext, useEffect, useState} from 'react';
import {AlertTriangle, CalendarClock, ChevronDown, Copy, ExternalLink, Flag, Info, Layers, Link2, ListTree, Mail, RotateCcw, ShieldCheck, Square} from 'lucide-react';
import {placedVisuals} from '@/citations';
import {sourceCount, sourceGroups} from '@/sources';
import {clock, duration} from '@/format';
import {errorDetails} from '@/runState';
import {Button} from './ui/button';
import {DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuLabel, DropdownMenuTrigger, Hint} from './ui/menu';
import {ActivityTimeline} from './ActivityTimeline';
import {AnswerMarkdown} from './AnswerMarkdown';
import {CheckBadge, DataModeBadge, RuntimeBadge} from './Badges';
import {Diagnostics} from './Diagnostics';
import {MadeFiles} from './Attachments';
import {RecurringCard} from './RecurringCard';
import {AccessRequestCard} from './AccessRequestCard';
import {SteerNotes, SystemRequests} from './Steering';
import {SystemsContext, SystemsStage} from './SystemsStage';
import {onlyNames} from '@/systems';
import {VisualBlock} from './VisualBlock';
import mark from '@/assets/wizard-mark.svg';
import type {Cadence, RunView, Schedule} from '@/types';

const FEEDBACK = [
  ['wrong_source', 'Wrong source'], ['mismatched_period', 'Mismatched period'], ['wrong_arithmetic', 'Wrong arithmetic'],
  ['omitted_contrary_signal', 'Missed a contrary signal'], ['unsupported_certainty', 'Too certain'], ['poor_chart', 'Unhelpful chart'],
  ['helpful', 'This was helpful'],
] as const;

interface Props {
  run: RunView;
  onEvidence: (run: RunView, id: string | null) => void;
  onCheck: (run: RunView) => void;
  onCancel: (run: RunView) => void;
  onRetry: (run: RunView) => void;
  onFeedback: (run: RunView, category: string) => void;
  onEmail: (run: RunView) => void;
  /** Make recurring: a follow-up in which Gemini proposes the schedule (asking how often only without a cadence). */
  onRecurring?: (run: RunView, cadence: Cadence | null) => void;
  /** The person's answer on a recurring-extraction card. */
  onSchedule?: (run: RunView, schedule: Schedule, action: 'create' | 'dismiss') => void;
  /** Metronome is connected and this person may schedule queries. */
  canRecur?: boolean;
  busy: boolean;
}

const CADENCES: [Cadence | null, string][] = [['daily', 'Every day'], ['weekly', 'Every Monday'], ['monthly', 'On the 1st of every month'],
  [null, 'Something else…']];

const KIND_LABEL: Record<RunView['kind'], string> = {ask: 'Wizard', check: 'Check my data', recurring: 'Make recurring'};

/** A running answer's time so far, so a long run reads as working rather than stuck (Stop is in the footer). */
function Elapsed({since}: {since: string}) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, []);
  return <span className="ml-auto text-xs tabular-nums text-ink-3" role="timer" aria-label="Time so far" data-testid="elapsed">
    {clock(now - new Date(since).getTime())}
  </span>;
}

function CheckPanel({run}: {run: RunView}) {
  if (!run.check) return null;
  const tone = run.check.overall === 'CHECKED' ? 'border-ok-line bg-ok-soft/50' : run.check.overall === 'DISCREPANCY' ? 'border-danger-line bg-danger-soft/60' : 'border-line bg-surface';
  return (
    <div className={`rounded-xl border px-4 py-3 text-sm ${tone}`} data-testid="check-panel">
      <p className="font-medium">Check my data · {run.check.overall.replace('_', ' ').toLowerCase()}</p>
      <ul className="mt-2 space-y-1 text-[13px]">
        {run.check.claims.map(claim => <li key={claim.label} className="flex flex-wrap gap-x-2">
          <span className={claim.status === 'MATCH' ? 'text-ok' : claim.status === 'NOT_VERIFIABLE' ? 'text-ink-3' : 'text-danger'}>{claim.status.replace('_', ' ')}</span>
          <span>{claim.label}</span>{claim.notes.length > 0 && <span className="text-ink-3">— {claim.notes.join('; ')}</span>}
        </li>)}
        {run.check.replays.map(replay => <li key={replay.evidence_id} className="text-ink-2">Replay {replay.evidence_id}: {replay.status.toLowerCase()} — {replay.detail}</li>)}
      </ul>
    </div>
  );
}

/** The systems the person chose for this answer (Auto shows nothing). */
function OnlySystems({ids}: {ids: string[]}) {
  const names = onlyNames(ids, useContext(SystemsContext));
  return <Hint text="You chose the systems for this question; the others were switched off.">
    <span className="inline-flex max-w-full items-center gap-1 truncate rounded-full border border-accent-line bg-accent-soft px-2 py-0.5 text-[11.5px] font-medium text-accent" data-testid="only-systems">
      <Layers className="size-3 shrink-0" /><span className="truncate">Only: {names.join(', ')}</span>
    </span>
  </Hint>;
}

/** Why the answer failed, in full: Google's own reason and words, what Gemini sent back, the last tool call and where
 * the run had got to. Copy puts it all on the clipboard with the question, to send to whoever helps. */
function ErrorDetails({run}: {run: RunView}) {
  const [open, setOpen] = useState(false);
  const [copied, setCopied] = useState(false);
  const rows = Object.entries(errorDetails(run));
  const text = [`Question: ${run.question}`, `Wizard could not finish this answer: ${run.error?.message ?? ''}`, '',
    ...rows.map(([label, value]) => `${label}: ${value}`)].join('\n');
  return <>
    <Button variant="ghost" size="sm" className="text-danger hover:bg-canvas/70 hover:text-danger" onClick={() => setOpen(o => !o)}
      aria-expanded={open} data-testid="error-details"><Info />Error details<ChevronDown className={open ? 'rotate-180' : ''} /></Button>
    {open && (
      <div className="min-w-0 basis-full rounded-lg border border-danger-line bg-canvas px-3 py-2.5 text-ink-2" data-testid="error-details-panel">
        <dl className="grid gap-y-1.5 text-[12.5px] sm:grid-cols-[minmax(0,11rem)_minmax(0,1fr)] sm:gap-x-3 sm:gap-y-1">
          {rows.map(([label, value]) => <div key={label} className="sm:contents">
            <dt className="text-[11.5px] text-ink-3 sm:text-[12.5px]">{label}</dt>
            <dd className="whitespace-pre-wrap font-mono text-[12px] text-ink [overflow-wrap:anywhere]">{value}</dd>
          </div>)}
        </dl>
        <Button variant="outline" size="xs" className="mt-2.5" onClick={() => void navigator.clipboard?.writeText(text).then(() => setCopied(true))}>
          <Copy />{copied ? 'Copied' : 'Copy details'}
        </Button>
      </div>
    )}
  </>;
}

export const RunCard = memo(function RunCard({run, onEvidence, onCheck, onCancel, onRetry, onFeedback, onEmail, onRecurring, onSchedule,
  canRecur = false, busy}: Props) {
  const running = run.status === 'running' || run.status === 'queued';
  const text = run.answer ?? run.streamText;
  const placed = placedVisuals(text);
  const loose = run.visuals.filter(v => !placed.has(v.id));
  const took = duration(run.createdAt, run.finishedAt);
  const queried = run.evidence.some(e => e.system === 'postgresql');
  const sources = sourceCount(sourceGroups(run.evidence));  // tables, reports and files, not each query
  return (
    <section className="rounded-card border border-line border-t-[3px] border-t-accent bg-canvas shadow-card" aria-label={run.kind === 'check' ? 'Check my data result' : 'Wizard answer'}
      data-testid="run-card" data-status={run.status} data-run-id={run.id}>
      <header className="flex flex-wrap items-center gap-2 px-5 pt-4 sm:px-6">
        <span className="inline-flex items-center gap-1.5 text-[13px] font-semibold text-accent"><img src={mark} alt="" className="size-4" />{KIND_LABEL[run.kind] ?? 'Wizard'}</span>
        {run.runtime === 'replay' && <RuntimeBadge kind={run.runtime} label={run.runtimeLabel} />}
        {(run.dataMode || run.status === 'succeeded') && <DataModeBadge mode={run.dataMode} />}
        {run.status === 'succeeded' && run.kind === 'ask' && <CheckBadge status={run.checkStatus} />}
        {run.systems && <OnlySystems ids={run.systems} />}
        {running ? <Elapsed since={run.createdAt} /> : took && <span className="ml-auto text-xs text-ink-3">{took}</span>}
      </header>
      <div className="space-y-4 px-5 py-4 sm:px-6">
        <SystemsStage run={run} onEvidence={id => onEvidence(run, id)} />
        <SteerNotes run={run} />
        <ActivityTimeline run={run} onEvidence={id => onEvidence(run, id)} />
        {text && <AnswerMarkdown text={text} visuals={run.visuals} streaming={running} onEvidence={id => onEvidence(run, id)} />}
        {loose.map(v => <VisualBlock key={v.id} visual={v} onEvidence={id => onEvidence(run, id)} />)}
        <MadeFiles files={run.attachments} />
        {run.schedules.map(schedule => <RecurringCard key={schedule.id} schedule={schedule}
          onCreate={s => onSchedule?.(run, s, 'create')} onDismiss={s => onSchedule?.(run, s, 'dismiss')} />)}
        {run.accessRequests.map(request => <AccessRequestCard key={request.id} request={request} />)}
        <SystemRequests run={run} />
        <CheckPanel run={run} />
        {run.warnings.length > 0 && run.status !== 'running' && (
          <ul className="space-y-1 rounded-xl border border-warn-line bg-warn-soft px-4 py-2 text-[13px] text-warn" data-testid="warnings">
            {run.warnings.map(w => <li key={w} className="flex gap-2"><AlertTriangle className="mt-0.5 size-3.5 shrink-0" />{w}</li>)}
          </ul>
        )}
        {run.error && (
          <div className="rounded-xl border border-danger-line bg-danger-soft px-4 py-3 text-sm text-danger" role="alert" data-testid="run-error" data-code={run.error.code}>
            <p className="font-medium">{run.status === 'cancelled' ? 'Cancelled' : 'Wizard could not finish this answer'}</p>
            <p className="mt-1">{run.error.message}{run.diagnostics.length > 0 && ' Details are under Diagnostics below.'}</p>
            {run.status !== 'cancelled' && <div className="mt-2 flex flex-wrap items-center gap-1.5">
              <Button variant="outline" size="sm" onClick={() => onRetry(run)} disabled={busy}><RotateCcw />Ask again</Button>
              <ErrorDetails run={run} />
            </div>}
          </div>
        )}
      </div>
      {run.diagnostics.length > 0 && <Diagnostics items={run.diagnostics} open={run.status === 'failed'} />}
      <footer className="no-print flex flex-wrap items-center gap-1.5 border-t border-line px-5 py-2.5 sm:px-6" data-testid="run-actions">
        {running && <Button variant="outline" size="sm" onClick={() => onCancel(run)}><Square />Stop</Button>}
        {run.status === 'succeeded' && run.kind === 'ask' && run.evidence.length > 0 && (
          <Hint text="Ask Gemini to recompute the figures in this answer from the cited evidence and correct or qualify anything that does not match.">
            <Button variant="outline" size="sm" onClick={() => onCheck(run)} disabled={busy} data-testid="check-my-data"><ShieldCheck />Check my data</Button>
          </Hint>
        )}
        {run.evidence.length > 0 && <Button variant="ghost" size="sm" onClick={() => onEvidence(run, null)} data-testid="show-sources"><ListTree />{sources ? `Show sources (${sources})` : 'Show sources'}</Button>}
        {run.reportId && <>
          <a href={`/r/${run.reportId}`} target="_blank" rel="noopener" className="inline-flex h-8 items-center gap-1.5 rounded-lg px-3 text-[13px] font-medium text-ink-2 hover:bg-surface hover:text-ink [&_svg]:size-4" data-testid="open-report"><ExternalLink />Report</a>
          <Hint text="Copy a link to this dated report. It opens only for you while your source rights still allow it.">
            <Button variant="ghost" size="sm" aria-label="Copy report link" onClick={() => void navigator.clipboard?.writeText(`${location.origin}/r/${run.reportId}`)}><Link2 /></Button>
          </Hint>
        </>}
        {run.status === 'succeeded' && run.kind === 'ask' && run.answer && (
          <Hint text="Open an Outlook draft with the question, this answer, how long it took and the sources it used. You add the recipient and send it.">
            <Button variant="ghost" size="sm" onClick={() => onEmail(run)} data-testid="email-answer"><Mail />Email</Button>
          </Hint>
        )}
        {run.status === 'succeeded' && run.kind === 'ask' && canRecur && queried && !run.schedules.length && onRecurring && (
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button variant="ghost" size="sm" disabled={busy} data-testid="make-recurring"><CalendarClock />Make recurring</Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="start">
              <DropdownMenuLabel>Emailed to you at 08:00 (Dubai), Excel attached</DropdownMenuLabel>
              {CADENCES.map(([cadence, label]) => (
                <DropdownMenuItem key={label} onSelect={() => onRecurring(run, cadence)} data-testid={`recurring-${cadence ?? 'other'}`}>{label}</DropdownMenuItem>
              ))}
            </DropdownMenuContent>
          </DropdownMenu>
        )}
        {run.status === 'succeeded' && (
          <DropdownMenu>
            <DropdownMenuTrigger asChild><Button variant="ghost" size="sm" className="ml-auto" aria-label="Flag a problem with this answer"><Flag />Feedback</Button></DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              <DropdownMenuLabel>Recorded in the evaluation log</DropdownMenuLabel>
              {FEEDBACK.map(([key, label]) => <DropdownMenuItem key={key} onSelect={() => onFeedback(run, key)}>{label}</DropdownMenuItem>)}
            </DropdownMenuContent>
          </DropdownMenu>
        )}
      </footer>
    </section>
  );
});
