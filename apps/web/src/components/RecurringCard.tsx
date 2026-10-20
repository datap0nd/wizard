import {AlertTriangle, CalendarClock, Check, FileSpreadsheet, Loader2, Mail, UserRound, X} from 'lucide-react';
import {Button} from './ui/button';
import {SystemLogo} from './SystemLogo';
import type {Schedule} from '@/types';

const STATUS: Record<Schedule['status'], {label: string; tone: string}> = {
  proposed: {label: 'Waiting for you', tone: 'bg-accent-soft text-accent'},
  creating: {label: 'Creating…', tone: 'bg-accent-soft text-accent'},
  created: {label: 'Scheduled', tone: 'bg-ok-soft text-ok'},
  failed: {label: 'Not created', tone: 'bg-danger-soft text-danger'},
  uncertain: {label: 'Check Metronome', tone: 'bg-warn-soft text-warn'},
  dismissed: {label: 'Dismissed', tone: 'bg-surface text-ink-3'},
};

function when(value: string | null | undefined): string | null {
  if (!value) return null;
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? null
    : date.toLocaleString(undefined, {weekday: 'short', day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit'});
}

function Row({icon: Icon, label, children}: {icon: typeof Mail; label: string; children: React.ReactNode}) {
  return (
    <div className="flex gap-2.5 text-[13px]">
      <Icon className="mt-0.5 size-4 shrink-0 text-ink-3" aria-hidden="true" />
      <span className="w-20 shrink-0 text-ink-3">{label}</span>
      <span className="min-w-0 flex-1 break-words text-ink">{children}</span>
    </div>
  );
}

interface Props {
  schedule: Schedule;
  onCreate: (schedule: Schedule) => void;
  onDismiss: (schedule: Schedule) => void;
}

/** A recurring extraction Gemini proposed. Nothing exists in Metronome until the person presses Create in Metronome;
 *  the Flow then belongs to Metronome's Wizard user and Metronome emails the file on the schedule. */
export function RecurringCard({schedule, onCreate, onDismiss}: Props) {
  const status = STATUS[schedule.status] ?? STATUS.proposed;
  const file = `${schedule.title} <date>.${schedule.file_format}`;
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
        <Row icon={FileSpreadsheet} label="File">
          {file} ({schedule.file_format === 'xlsx' ? 'Excel' : 'CSV'}){schedule.subject ? <>, subject “{schedule.subject}”</> : null}
        </Row>
        <Row icon={UserRound} label="Owner">Metronome user {schedule.metronome_user}, which sends it and receives failure alerts</Row>
        <details className="pt-1 text-[13px]">
          <summary className="cursor-pointer text-ink-2 hover:text-ink">
            Query and today's test run ({schedule.preview.rows_in_test}{schedule.preview.more ? '+' : ''} rows, cited as {schedule.evidence_id})
          </summary>
          <pre className="mt-2 max-h-56 overflow-auto whitespace-pre-wrap rounded-lg bg-surface p-3 font-mono text-xs text-ink-2" data-testid="recurring-sql">{schedule.sql}</pre>
          {schedule.preview.columns.length > 0 && <p className="mt-1.5 text-xs text-ink-3">Columns: {schedule.preview.columns.join(', ')}</p>}
        </details>
      </div>
      <footer className="flex flex-wrap items-center gap-2 border-t border-line px-4 py-2.5 text-[13px]" data-testid="recurring-actions">
        {schedule.status === 'created' && schedule.flow && <p className="flex items-start gap-1.5 text-ok">
          <Check className="mt-0.5 size-4 shrink-0" />
          <span>Created in Metronome as Flow #{schedule.flow.id} “{schedule.flow.name}”, owned by {schedule.flow.owner}.
            {next && <> First email {next}.</>} Pause or delete it in Metronome's Flows.</span>
        </p>}
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
