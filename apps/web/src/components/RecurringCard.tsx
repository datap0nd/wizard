import {useState} from 'react';
import {AlertTriangle, CalendarClock, Check, FileSpreadsheet, Loader2, Mail, UserRound, X} from 'lucide-react';
import {Button} from './ui/button';
import {SystemLogo} from './SystemLogo';
import {EmailPreview} from './EmailPreview';
import type {Schedule} from '@/types';

export const STATUS: Record<Schedule['status'], {label: string; tone: string}> = {
  proposed: {label: 'Waiting for you', tone: 'bg-accent-soft text-accent'},
  creating: {label: 'Creating…', tone: 'bg-accent-soft text-accent'},
  created: {label: 'Scheduled', tone: 'bg-ok-soft text-ok'},
  failed: {label: 'Not created', tone: 'bg-danger-soft text-danger'},
  uncertain: {label: 'Check Metronome', tone: 'bg-warn-soft text-warn'},
  dismissed: {label: 'Dismissed', tone: 'bg-surface text-ink-3'},
  deleting: {label: 'Deleting…', tone: 'bg-surface text-ink-3'},
  deleted: {label: 'Deleted', tone: 'bg-surface text-ink-3'},
};

export function when(value: string | null | undefined): string | null {
  if (!value) return null;
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? null
    : date.toLocaleString(undefined, {weekday: 'short', day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit'});
}

export function Row({icon: Icon, label, children}: {icon: typeof Mail; label: string; children: React.ReactNode}) {
  return (
    <div className="flex gap-2.5 text-[13px]">
      <Icon className="mt-0.5 size-4 shrink-0 text-ink-3" aria-hidden="true" />
      <span className="w-20 shrink-0 text-ink-3">{label}</span>
      <span className="min-w-0 flex-1 break-words text-ink">{children}</span>
    </div>
  );
}

/** The brief's email, loaded only once someone opens it. */
export function PreviewDetails({schedule, label, initiallyOpen = false}: {schedule: Schedule; label: string; initiallyOpen?: boolean}) {
  const [open, setOpen] = useState(initiallyOpen);
  return (
    <details className="text-[13px]" open={open} onToggle={e => setOpen(e.currentTarget.open)}>
      <summary className="cursor-pointer text-ink-2 hover:text-ink">{label}</summary>
      {open && <div className="mt-2"><EmailPreview scheduleId={schedule.id} title={schedule.title} /></div>}
    </details>
  );
}

/** The queries behind a brief, one per section (or the one query of a proposal made before briefs). */
export function Queries({schedule}: {schedule: Schedule}) {
  const sections = schedule.brief?.sections ?? (schedule.sql ? [{kind: 'table' as const, title: schedule.title, subtitle: null, sql: schedule.sql, chart: null}] : []);
  const cited = schedule.evidence_ids?.join(', ') ?? schedule.evidence_id;
  return (
    <details className="text-[13px]">
      <summary className="cursor-pointer text-ink-2 hover:text-ink">
        {sections.length === 1 ? 'The query' : `The ${sections.length} queries`} it runs each time{cited ? ` (test run cited as ${cited})` : ''}
      </summary>
      <ol className="mt-2 space-y-2" data-testid="recurring-sql">
        {sections.map((section, i) => (
          <li key={i}>
            <p className="text-xs text-ink-3">{section.title ?? `Section ${i + 1}`} · {section.kind === 'chart' ? `${section.chart} chart` : section.kind === 'numbers' ? 'key numbers' : 'table'}</p>
            <pre className="mt-1 max-h-56 overflow-auto whitespace-pre-wrap rounded-lg bg-surface p-3 font-mono text-xs text-ink-2">{section.sql}</pre>
          </li>
        ))}
      </ol>
    </details>
  );
}

interface Props {
  schedule: Schedule;
  onCreate: (schedule: Schedule) => void;
  onDismiss: (schedule: Schedule) => void;
}

/** A recurring brief Gemini proposed: the email it will send, on a schedule. Nothing exists in Metronome until the
 *  person presses Create in Metronome; the Flow then belongs to Metronome's Wizard user and Metronome sends the email
 *  with the Excel file attached. */
export function RecurringCard({schedule, onCreate, onDismiss}: Props) {
  const status = STATUS[schedule.status] ?? STATUS.proposed;
  const file = `${schedule.title} <date>.xlsx`;
  const next = when(schedule.flow?.next_run_at);
  const open = schedule.status === 'proposed' || schedule.status === 'failed';
  return (
    <section className="rounded-xl border border-line bg-canvas" aria-label={`Recurring email ${schedule.label}`} data-testid="recurring-card"
      data-status={schedule.status}>
      <header className="flex items-center gap-2.5 border-b border-line px-4 py-2.5">
        <SystemLogo id="metronome" name="Metronome" size={28} />
        <div className="min-w-0 flex-1">
          <p className="truncate text-sm font-semibold">{schedule.title}</p>
          <p className="text-xs text-ink-3">Recurring email {schedule.label} · Metronome</p>
        </div>
        <span className={`shrink-0 rounded-full px-2 py-0.5 text-xs font-medium ${status.tone}`} data-testid="recurring-status">{status.label}</span>
      </header>
      <div className="space-y-1.5 px-4 py-3">
        <Row icon={CalendarClock} label="When">{schedule.schedule_text}</Row>
        <Row icon={Mail} label="To">{schedule.recipients.join(', ')}</Row>
        <Row icon={FileSpreadsheet} label="Attached">
          {file} (Excel, every row){schedule.subject ? <>, subject “{schedule.subject}”</> : null}
        </Row>
        <Row icon={UserRound} label="Owner">Metronome user {schedule.metronome_user}, which sends it and receives failure alerts</Row>
        {schedule.kind === 'brief' && schedule.status !== 'dismissed' && (
          <div className="pt-1"><PreviewDetails schedule={schedule} label="The email, drawn from today's test run"
            initiallyOpen={schedule.status === 'proposed'} /></div>
        )}
        <div className="pt-1"><Queries schedule={schedule} /></div>
      </div>
      <footer className="flex flex-wrap items-center gap-2 border-t border-line px-4 py-2.5 text-[13px]" data-testid="recurring-actions">
        {schedule.status === 'created' && schedule.flow && <p className="flex items-start gap-1.5 text-ok">
          <Check className="mt-0.5 size-4 shrink-0" />
          <span>Created in Metronome as Flow #{schedule.flow.id} “{schedule.flow.name}”, owned by {schedule.flow.owner}.
            {next && <> First email {next}.</>} Find it under Recurring in the sidebar.</span>
        </p>}
        {schedule.status === 'deleted' && <p className="text-ink-3">Deleted: the Flow is turned off in Metronome.</p>}
        {schedule.status === 'creating' && <p className="flex items-center gap-1.5 text-ink-2"><Loader2 className="size-4 animate-spin" />Creating the Flow in Metronome…</p>}
        {schedule.error && schedule.status !== 'created' && (
          <p className={`flex w-full items-start gap-1.5 ${schedule.status === 'uncertain' ? 'text-warn' : 'text-danger'}`} role="alert">
            <AlertTriangle className="mt-0.5 size-4 shrink-0" />{schedule.error}
          </p>
        )}
        {schedule.status === 'dismissed' && <p className="text-ink-3">Not scheduled.</p>}
        {open && <>
          <Button size="sm" onClick={() => onCreate(schedule)} data-testid="recurring-create">
            <CalendarClock />{schedule.status === 'failed' ? 'Try again' : 'Create in Metronome'}
          </Button>
          <Button size="sm" variant="ghost" onClick={() => onDismiss(schedule)} data-testid="recurring-dismiss"><X />Not now</Button>
          {schedule.status === 'proposed' && <span className="text-xs text-ink-3">Nothing is scheduled until you create it.</span>}
        </>}
      </footer>
    </section>
  );
}
