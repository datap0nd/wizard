import {memo, useEffect, useState} from 'react';
import {AlertTriangle, ExternalLink, Flag, Link2, ListTree, Mail, RotateCcw, ShieldCheck, Square} from 'lucide-react';
import {placedVisuals} from '@/citations';
import {clock, duration} from '@/format';
import {Button} from './ui/button';
import {DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuLabel, DropdownMenuTrigger, Hint} from './ui/menu';
import {ActivityTimeline} from './ActivityTimeline';
import {AnswerMarkdown} from './AnswerMarkdown';
import {CheckBadge, DataModeBadge, RuntimeBadge} from './Badges';
import {Diagnostics} from './Diagnostics';
import {VisualBlock} from './VisualBlock';
import {WizardStage} from './WizardSprite';
import mark from '@/assets/wizard-mark.svg';
import type {RunView} from '@/types';

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
  busy: boolean;
}

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

export const RunCard = memo(function RunCard({run, onEvidence, onCheck, onCancel, onRetry, onFeedback, onEmail, busy}: Props) {
  const running = run.status === 'running' || run.status === 'queued';
  const text = run.answer ?? run.streamText;
  const placed = placedVisuals(text);
  const loose = run.visuals.filter(v => !placed.has(v.id));
  const took = duration(run.createdAt, run.finishedAt);
  return (
    <section className="rounded-card border border-line border-t-[3px] border-t-accent bg-canvas shadow-card" aria-label={run.kind === 'check' ? 'Check my data result' : 'Wizard answer'}
      data-testid="run-card" data-status={run.status} data-run-id={run.id}>
      <header className="flex flex-wrap items-center gap-2 px-5 pt-4 sm:px-6">
        <span className="inline-flex items-center gap-1.5 text-[13px] font-semibold text-accent"><img src={mark} alt="" className="size-4" />{run.kind === 'check' ? 'Check my data' : 'Wizard'}</span>
        {run.runtime === 'replay' && <RuntimeBadge kind={run.runtime} label={run.runtimeLabel} />}
        {(run.dataMode || run.status === 'succeeded') && <DataModeBadge mode={run.dataMode} />}
        {run.status === 'succeeded' && run.kind === 'ask' && <CheckBadge status={run.checkStatus} />}
        {running ? <Elapsed since={run.createdAt} /> : took && <span className="ml-auto text-xs text-ink-3">{took}</span>}
      </header>
      <div className="space-y-4 px-5 py-4 sm:px-6">
        <WizardStage run={run} />
        <ActivityTimeline run={run} onEvidence={id => onEvidence(run, id)} />
        {text && <AnswerMarkdown text={text} visuals={run.visuals} streaming={running} onEvidence={id => onEvidence(run, id)} />}
        {!text && running && <p className="text-sm text-ink-3" role="status">Working on it…</p>}
        {loose.map(v => <VisualBlock key={v.id} visual={v} onEvidence={id => onEvidence(run, id)} />)}
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
            {run.status !== 'cancelled' && <Button variant="outline" size="sm" className="mt-2" onClick={() => onRetry(run)} disabled={busy}><RotateCcw />Ask again</Button>}
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
        {run.evidence.length > 0 && <Button variant="ghost" size="sm" onClick={() => onEvidence(run, null)} data-testid="show-sources"><ListTree />Show sources ({run.evidence.length})</Button>}
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
