import {useCallback, useEffect, useState} from 'react';
import {AlertTriangle, CalendarClock, Check, FileSpreadsheet, Loader2, Mail, RefreshCw, Trash2, UserRound, X} from 'lucide-react';
import {cn} from '@/lib/utils';
import {api} from '@/api';
import {Button} from './ui/button';
import {Dialog, DialogContent} from './ui/dialog';
import {PreviewDetails, Queries, Row, when} from './RecurringCard';
import type {RecurringItem, RecurringList} from '@/types';

/** Where a brief stands, read from Metronome when it could be reached. */
export function state(item: RecurringItem): {label: string; tone: string} {
  const flow = item.metronome;
  if (!flow) return {label: 'Scheduled', tone: 'bg-surface-2 text-ink-2'};
  if (flow.missing) return {label: 'Not in Metronome', tone: 'bg-warn-soft text-warn'};
  if (!flow.enabled) return {label: 'Off in Metronome', tone: 'bg-surface-2 text-ink-3'};
  if (flow.last_status === 'failed') return {label: 'Last run failed', tone: 'bg-danger-soft text-danger'};
  if (flow.last_run_at) return {label: `Sent ${when(flow.last_run_at)?.split(',')[0] ?? ''}`.trim(), tone: 'bg-ok-soft text-ok'};
  return {label: 'Active', tone: 'bg-ok-soft text-ok'};
}

const RUN: Record<string, string> = {succeeded: 'Sent', failed: 'Failed', queued: 'Queued', claimed: 'Starting', running: 'Running',
  cancelled: 'Stopped', interrupted: 'Interrupted'};

/** The sidebar's Recurring tab: the person's briefs in Metronome, kept in step with Metronome each time it opens. */
export function RecurringPanel() {
  const [list, setList] = useState<RecurringList | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [open, setOpen] = useState<RecurringItem | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setList(await api.recurringList());
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Wizard could not list your recurring briefs.');
    } finally {
      setLoading(false);
    }
  }, []);
  useEffect(() => { void load(); }, [load]);

  return (
    <div className="px-3 pb-3" data-testid="recurring-panel">
      <div className="flex items-center justify-between pb-1">
        <p className="text-[11px] font-medium uppercase tracking-wide text-ink-3">Sent by Metronome</p>
        <Button variant="ghost" size="icon-sm" onClick={() => void load()} aria-label="Refresh from Metronome" disabled={loading}>
          <RefreshCw className={cn(loading && 'animate-spin')} />
        </Button>
      </div>
      {error && <p className="flex items-start gap-1.5 py-2 text-[12.5px] text-danger" role="alert"><AlertTriangle className="mt-0.5 size-3.5 shrink-0" />{error}</p>}
      {list && !list.sync.ok && (
        <p className="mb-2 flex items-start gap-1.5 rounded-md bg-warn-soft px-2 py-1.5 text-[12px] text-warn" role="status">
          <AlertTriangle className="mt-0.5 size-3.5 shrink-0" /><span>Metronome could not be reached, so this is what Wizard last knew. {list.sync.message}</span>
        </p>
      )}
      {!list && !error && <p className="flex items-center gap-1.5 py-3 text-[13px] text-ink-3"><Loader2 className="size-3.5 animate-spin" />Asking Metronome…</p>}
      {list && list.items.length === 0 && (
        <p className="py-3 text-[13px] text-ink-3">No recurring briefs yet. Under an answer, choose <b className="font-medium text-ink-2">Make recurring</b> to have it emailed on a schedule.</p>
      )}
      <ul className="flex flex-col gap-1">
        {list?.items.map(item => {
          const badge = state(item);
          return (
            <li key={item.id}>
              <button type="button" onClick={() => setOpen(item)} data-testid="recurring-item"
                className="w-full rounded-lg px-2.5 py-2 text-left hover:bg-canvas focus-visible:bg-canvas">
                <span className="block truncate text-[13px] font-medium text-ink">{item.title}</span>
                <span className="block truncate text-[12px] text-ink-3">{item.schedule_text.replace(' (Dubai time)', '')}</span>
                <span className={cn('mt-1 inline-block rounded-full px-2 py-px text-[11px] font-medium', badge.tone)}>{badge.label}</span>
              </button>
            </li>
          );
        })}
      </ul>
      {open && <RecurringDialog item={open} onClose={() => setOpen(null)} onDeleted={() => { setOpen(null); void load(); }} />}
    </div>
  );
}

function RecurringDialog({item, onClose, onDeleted}: {item: RecurringItem; onClose: () => void; onDeleted: () => void}) {
  const [confirming, setConfirming] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [error, setError] = useState<string | null>(item.error);
  const flow = item.metronome;
  const badge = state(item);

  const remove = async () => {
    setDeleting(true);
    setError(null);
    try {
      await api.deleteRecurring(item.id);
      onDeleted();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Metronome could not turn the Flow off.');
      setDeleting(false);
      setConfirming(false);
    }
  };

  return (
    <Dialog open onOpenChange={next => { if (!next) onClose(); }}>
      <DialogContent side="right" title={item.title} description={`Recurring brief · Metronome Flow #${item.flow?.id ?? '?'} · owned by ${item.metronome_user}`}>
        <div className="space-y-4" data-testid="recurring-dialog">
          <div className="flex flex-wrap items-center gap-2">
            <span className={cn('rounded-full px-2 py-0.5 text-xs font-medium', badge.tone)}>{badge.label}</span>
            {flow?.enabled && flow.next_run_at && <span className="text-[13px] text-ink-2">Next email {when(flow.next_run_at)}</span>}
          </div>
          <div className="space-y-1.5">
            <Row icon={CalendarClock} label="When">{item.schedule_text}</Row>
            <Row icon={Mail} label="To">{item.recipients.join(', ')}</Row>
            <Row icon={FileSpreadsheet} label="Attached">{item.title} &lt;date&gt;.xlsx (Excel, every row)</Row>
            <Row icon={UserRound} label="Owner">Metronome user {item.metronome_user}, which sends it and receives failure alerts</Row>
          </div>
          {flow?.last_error && flow.last_status === 'failed' && (
            <p className="flex items-start gap-1.5 rounded-md bg-danger-soft px-3 py-2 text-[13px] text-danger"><AlertTriangle className="mt-0.5 size-4 shrink-0" />{flow.last_error}</p>
          )}
          {flow?.runs && flow.runs.length > 0 && (
            <div>
              <p className="pb-1 text-[11px] font-medium uppercase tracking-wide text-ink-3">Recent runs</p>
              <ul className="divide-y divide-line text-[13px]" data-testid="recurring-runs">
                {flow.runs.map(run => (
                  <li key={run.id} className="flex items-center justify-between gap-3 py-1.5">
                    <span className="text-ink-2">{when(run.at) ?? `Run #${run.id}`}</span>
                    <span className={cn('text-xs font-medium', run.status === 'failed' ? 'text-danger' : run.status === 'succeeded' ? 'text-ok' : 'text-ink-3')}>
                      {RUN[run.status] ?? run.status}{run.status === 'succeeded' && run.email === 'failed' ? ', email not sent' : ''}
                    </span>
                  </li>
                ))}
              </ul>
            </div>
          )}
          {item.kind === 'brief' && <PreviewDetails schedule={item} label="The email, as drawn from its test run" />}
          <Queries schedule={item} />
          {error && <p className="flex items-start gap-1.5 text-[13px] text-danger" role="alert"><AlertTriangle className="mt-0.5 size-4 shrink-0" />{error}</p>}
          <div className="flex flex-wrap items-center gap-2 border-t border-line pt-3">
            {!confirming ? (
              <Button variant="outline" size="sm" onClick={() => setConfirming(true)} data-testid="recurring-delete"><Trash2 />Delete</Button>
            ) : <>
              <span className="w-full text-[13px] text-ink-2">Stop these emails? Metronome turns the Flow off and keeps its run history.</span>
              <Button size="sm" onClick={() => void remove()} disabled={deleting} data-testid="recurring-delete-confirm" className="bg-danger hover:bg-danger/90">
                {deleting ? <Loader2 className="animate-spin" /> : <Check />}Delete
              </Button>
              <Button variant="ghost" size="sm" onClick={() => setConfirming(false)} disabled={deleting}><X />Keep it</Button>
            </>}
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}
