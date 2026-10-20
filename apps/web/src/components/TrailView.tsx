import {ChevronRight, ExternalLink, FileText, Lock} from 'lucide-react';
import {cn} from '@/lib/utils';
import type {Trail} from '@/types';

function Crumbs({path, last}: {path: string[]; last?: string | null}) {
  const parts = [...path, ...(last ? [last] : [])];
  if (!parts.length) return null;
  return (
    <span className="inline-flex min-w-0 flex-wrap items-center gap-0.5 text-[12px] text-ink-3" data-testid="trail-crumbs">
      {parts.map((part, i) => (
        <span key={`${i}-${part}`} className="inline-flex items-center gap-0.5">
          {i > 0 && <ChevronRight className="size-3 shrink-0" aria-hidden="true" />}
          <span className={cn(i === parts.length - 1 && last ? 'font-medium text-ink' : '')}>{part}</span>
        </span>
      ))}
    </span>
  );
}

function OpenLink({url, label = 'Open'}: {url?: string | null; label?: string}) {
  if (!url) return null;
  return (
    <a href={url} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1 text-[12px] font-medium text-accent hover:underline"
      data-testid="trail-open"><ExternalLink className="size-3" />{label}</a>
  );
}

const cell = (v: string | number | null) => v === null ? '—' : typeof v === 'number' ? v.toLocaleString() : v;

/** Where a step went, as a person would see it: the folders a search turned up, the report it opened and its prompts,
 *  the first rows it read. Only what the step returned; the evidence holds everything. */
export function TrailView({trail, className}: {trail: Trail; className?: string}) {
  if (trail.kind === 'search') {
    if (!trail.results.length) return null;
    return (
      <ul className={cn('space-y-0.5', className)} data-testid="trail" data-kind="search">
        {trail.results.map(r => (
          <li key={r.report_id} className="flex items-center gap-1.5">
            <FileText className="size-3 shrink-0 text-ink-3" />
            <Crumbs path={r.folder_path} last={r.name} />
            {r.row_access === 'NAVIGATION_ONLY' && <Lock className="size-3 shrink-0 text-ink-3" aria-label="navigation only" />}
          </li>
        ))}
      </ul>
    );
  }
  if (trail.kind === 'report') {
    return (
      <div className={cn('space-y-1 rounded-lg border border-line bg-canvas px-2.5 py-1.5', className)} data-testid="trail" data-kind="report">
        <div className="flex flex-wrap items-center gap-2"><Crumbs path={trail.folder_path} last={trail.name} /><OpenLink url={trail.open_url} /></div>
        {trail.prompts.length > 0 && (
          <div className="flex flex-wrap items-center gap-1 text-[11.5px] text-ink-3">Prompts:
            {trail.prompts.map(p => <span key={p} className="rounded-full bg-surface px-1.5 py-0.5 text-ink-2 ring-1 ring-line">{p}</span>)}
          </div>
        )}
      </div>
    );
  }
  return (
    <div className={cn('space-y-1', className)} data-testid="trail" data-kind="rows">
      <div className="overflow-x-auto rounded-lg border border-line">
        <table className="w-full text-[11.5px] tabular-nums">
          <thead><tr>{trail.columns.map((c, i) => <th key={`${i}-${c}`} className="whitespace-nowrap bg-surface px-2 py-1 text-left font-medium text-ink-3">{c}</th>)}</tr></thead>
          <tbody>
            {trail.rows.map((row, i) => (
              <tr key={i} className="border-t border-line">{row.map((v, j) => <td key={j} className="whitespace-nowrap px-2 py-0.5 text-ink-2">{cell(v)}</td>)}</tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="flex flex-wrap items-center gap-2 text-[11.5px] text-ink-3">
        {trail.total_rows !== null && trail.total_rows > trail.rows.length && <span>first {trail.rows.length} of {trail.total_rows.toLocaleString()} rows</span>}
        <OpenLink url={trail.open_url} label="Open the source" />
      </div>
    </div>
  );
}
