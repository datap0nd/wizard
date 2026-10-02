import {useState} from 'react';
import {AlertTriangle, BookOpen, Calculator, ChartColumn, CheckCircle2, ChevronDown, Database, Loader2, MessageSquareText, Search, ShieldCheck, XCircle} from 'lucide-react';
import {cn} from '@/lib/utils';
import type {RunView, TimelineItem} from '@/types';

function icon(item: TimelineItem) {
  if (item.kind === 'note') return <MessageSquareText />;
  if (item.kind === 'warning') return <AlertTriangle className="text-warn" />;
  if (item.kind === 'status') return <Loader2 />;
  const name = item.name ?? '';
  if (name.endsWith('run_report')) return <Database />;
  if (name.includes('search') || name.includes('schema') || name.includes('list_sources')) return <Search />;
  if (name.includes('definitions')) return <BookOpen />;
  if (name.includes('calculate')) return <Calculator />;
  if (name.includes('render_visual')) return <ChartColumn />;
  if (name.includes('check_my_data')) return <ShieldCheck />;
  return <Search />;
}

function stateIcon(item: TimelineItem) {
  if (item.kind !== 'tool') return null;
  if (item.state === 'running') return <Loader2 className="size-3.5 animate-spin text-accent" aria-label="running" />;
  if (item.state === 'error') return <XCircle className="size-3.5 text-danger" aria-label="failed" />;
  return <CheckCircle2 className="size-3.5 text-ok" aria-label="done" />;
}

/** Observed actions only: tool calls Wizard executed (with their evidence), Gemini's interim notes, warnings.
 *  Not chain of thought, and nothing is invented to look busy. */
export function ActivityTimeline({run, onEvidence}: {run: RunView; onEvidence: (id: string) => void}) {
  const running = run.status === 'running' || run.status === 'queued';
  const [open, setOpen] = useState<boolean | null>(null);
  const expanded = open ?? running;
  const tools = run.timeline.filter(t => t.kind === 'tool');
  const systems = Array.from(new Set(tools.filter(t => t.evidence).map(t => t.evidence!.system.toUpperCase())));
  const summary = running ? (tools.length ? `Working · ${tools.length} step${tools.length === 1 ? '' : 's'} so far` : 'Starting')
    : `${tools.length} step${tools.length === 1 ? '' : 's'}${systems.length ? ` · consulted ${systems.join(', ')}` : ''}`;
  if (!run.timeline.length && !running) return null;
  return (
    <div className="rounded-xl border border-line bg-surface/60" data-testid="timeline">
      <button type="button" onClick={() => setOpen(!expanded)} aria-expanded={expanded}
        className="flex w-full items-center gap-2 px-3 py-2 text-left text-[13px] font-medium text-ink-2 hover:text-ink">
        {running ? <Loader2 className="size-4 animate-spin text-accent" /> : <ShieldCheck className="size-4 text-ink-3" />}
        <span>What Wizard did</span><span className="font-normal text-ink-3">· {summary}</span>
        <ChevronDown className={cn('ml-auto size-4 transition-transform', expanded && 'rotate-180')} />
      </button>
      {expanded && (
        <ol className="space-y-1 border-t border-line px-3 py-2" aria-live="polite">
          {run.timeline.map(item => (
            <li key={item.key} className="flex items-start gap-2 text-[13px]" data-testid="timeline-item" data-kind={item.kind} data-state={item.state}>
              <span className="mt-0.5 shrink-0 text-ink-3 [&_svg]:size-4">{icon(item)}</span>
              <div className="min-w-0 flex-1">
                <div className={cn('flex flex-wrap items-center gap-1.5', item.kind === 'note' ? 'italic text-ink-2' : 'text-ink')}>
                  <span className="break-words">{item.label}</span>{stateIcon(item)}
                  {item.evidence && <button type="button" onClick={() => onEvidence(item.evidence!.id)} className="rounded bg-accent-soft px-1.5 text-[11px] font-semibold text-accent hover:bg-accent-line/60">{item.evidence.id}</button>}
                </div>
                {item.summary && <p className={cn('text-xs', item.state === 'error' ? 'text-danger' : 'text-ink-3')}>{item.summary}</p>}
                {item.evidence?.access_note && <p className="text-xs text-warn">{item.evidence.access_note}</p>}
                {item.evidence?.warnings?.map(w => <p key={w} className="text-xs text-warn">{w}</p>)}
              </div>
            </li>
          ))}
          {running && <li className="flex items-center gap-2 text-[13px] text-ink-3"><span className="inline-flex gap-1" aria-hidden="true"><i className="size-1.5 animate-pulse rounded-full bg-ink-3" /><i className="size-1.5 animate-pulse rounded-full bg-ink-3 [animation-delay:150ms]" /><i className="size-1.5 animate-pulse rounded-full bg-ink-3 [animation-delay:300ms]" /></span>Gemini is deciding the next step</li>}
        </ol>
      )}
    </div>
  );
}
