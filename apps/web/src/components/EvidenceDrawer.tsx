import {useEffect, useState} from 'react';
import {ExternalLink, Lock} from 'lucide-react';
import {api, ApiError} from '@/api';
import {formatDate, formatValue} from '@/format';
import {Dialog, DialogContent} from './ui/dialog';
import {DataModeBadge, StatusPill} from './Badges';
import type {Evidence, EvidenceSummary} from '@/types';

interface Props {
  conversationId: string | null;
  open: boolean;
  focus: string | null;
  items: EvidenceSummary[];
  onClose: () => void;
  preloaded?: Evidence[];
}

function EvidenceDetail({conversationId, summary, preloaded}: {conversationId: string | null; summary: EvidenceSummary; preloaded?: Evidence}) {
  const [evidence, setEvidence] = useState<Evidence | null>(preloaded ?? null);
  const [error, setError] = useState<string | null>(null);
  const attached = summary.system === 'attachment';
  const sql = evidence?.request.sql;
  useEffect(() => {
    if (preloaded || !conversationId) return;
    api.evidence(conversationId, summary.id).then(r => setEvidence(r.evidence)).catch((e: unknown) => setError(e instanceof ApiError ? e.message : 'The evidence could not be loaded.'));
  }, [conversationId, summary.id, preloaded]);
  return (
    <section id={`drawer-${summary.id}`} className="rounded-xl border border-line p-4" data-testid="evidence" data-evidence-id={summary.id}>
      <header className="flex flex-wrap items-center gap-2">
        <span className="rounded bg-accent-soft px-1.5 text-xs font-semibold text-accent">{summary.id}</span>
        <h3 className="text-sm font-semibold">{summary.report_name}</h3>
        <DataModeBadge mode={summary.data_mode} />
      </header>
      <dl className="mt-2 grid grid-cols-[auto,1fr] gap-x-3 gap-y-1 text-xs text-ink-2">
        <dt className="text-ink-3">Source</dt><dd>{(summary.system_name ?? summary.system).toUpperCase()}{evidence?.folder_path?.length ? ` › ${evidence.folder_path.join(' › ')}` : ''} · <code>{summary.report_id}</code></dd>
        <dt className="text-ink-3">Data as of</dt><dd>{formatDate(summary.as_of, true)}</dd>
        {evidence && attached && <><dt className="text-ink-3">Read</dt><dd>{formatDate(evidence.retrieved_at, true)}{evidence.truncated ? ' · part of the file (Gemini can read on)' : ''}</dd></>}
        {evidence && !attached && <><dt className="text-ink-3">Retrieved</dt><dd>{formatDate(evidence.retrieved_at, true)} · connector {evidence.connector_status}</dd>
          {sql ? <><dt className="text-ink-3">Database</dt><dd>{evidence.request.database}</dd></>
            : <><dt className="text-ink-3">Request</dt><dd>{evidence.request.filters?.length ? evidence.request.filters.map(f => `${f.field} = ${f.values.join(', ')}`).join(' · ') : 'no filters'}
              {evidence.request.group_by ? ` · grouped by ${evidence.request.group_by.join(', ')}` : ''}</dd></>}
          <dt className="text-ink-3">Rows</dt><dd>{evidence.rows.length.toLocaleString()} shown of {evidence.total_rows.toLocaleString()}{evidence.truncated ? ' (truncated)' : ''} · digest {evidence.digest.slice(0, 12)}</dd></>}
      </dl>
      {sql && <pre className="mt-3 max-h-60 overflow-auto whitespace-pre rounded-lg border border-line bg-surface px-3 py-2 font-mono text-[12px] leading-5 text-ink-2 scroll-thin" data-testid="evidence-sql">{sql}</pre>}
      {summary.access_note && <p className="mt-2 rounded-lg bg-warn-soft px-3 py-2 text-xs text-warn">{summary.access_note}</p>}
      {summary.warnings?.map(w => <p key={w} className="mt-2 rounded-lg bg-warn-soft px-3 py-2 text-xs text-warn">{w}</p>)}
      {evidence?.caveats?.map(c => <p key={c} className="mt-2 text-xs text-ink-3">Caveat: {c}</p>)}
      {error && <p className="mt-2 flex items-center gap-1.5 text-xs text-danger"><Lock className="size-3.5" />{error}</p>}
      {evidence && evidence.rows.length > 0 && (
        <div className="mt-3 max-h-80 overflow-auto rounded-lg border border-line scroll-thin">
          <table className="w-full border-collapse text-[12.5px] tabular">
            <caption className="sr-only">Rows returned for {summary.id}</caption>
            <thead className="sticky top-0"><tr>{evidence.columns.map(c => <th key={c.key} scope="col" className="whitespace-nowrap bg-surface px-2.5 py-1.5 text-left font-medium text-ink-3">{c.label}</th>)}</tr></thead>
            <tbody>{evidence.rows.map((row, i) => <tr key={i} className="border-t border-line">{row.map((cell, j) =>
              <td key={j} className="whitespace-nowrap px-2.5 py-1.5 align-top">{formatValue(cell, evidence.columns[j]?.type, evidence.columns[j]?.unit)}</td>)}</tr>)}</tbody>
          </table>
        </div>
      )}
      {evidence?.excerpt && (
        <pre className="mt-3 max-h-80 overflow-auto whitespace-pre-wrap rounded-lg border border-line bg-surface px-3 py-2 text-[12px] leading-5 text-ink-2 scroll-thin" data-testid="evidence-excerpt">{evidence.excerpt}</pre>
      )}
      {evidence && !attached && evidence.rows.length === 0 && <p className="mt-3 rounded-lg border border-dashed border-line px-3 py-4 text-center text-xs text-ink-3">The source returned no rows for this request. Missing rows mean no data, not zero.</p>}
      <div className="mt-3 flex items-center gap-2 text-xs text-ink-3">
        {evidence?.locator.open_url ? <a href={evidence.locator.open_url} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1 text-accent"><ExternalLink className="size-3.5" />Open in {summary.system.toUpperCase()}</a>
          : <StatusPill tone="muted">{attached ? 'A file attached to the question' : sql ? 'A live query Gemini wrote' : 'No source link: synthetic fixture'}</StatusPill>}
      </div>
    </section>
  );
}

/** "Show sources": the evidence behind an answer, with rows, filters, freshness and data mode. */
export function EvidenceDrawer({conversationId, open, focus, items, onClose, preloaded}: Props) {
  useEffect(() => {
    if (open && focus) requestAnimationFrame(() => document.getElementById(`drawer-${focus}`)?.scrollIntoView({block: 'start'}));
  }, [open, focus]);
  const shown = focus ? [...items.filter(i => i.id === focus), ...items.filter(i => i.id !== focus)] : items;
  return (
    <Dialog open={open} onOpenChange={value => { if (!value) onClose(); }}>
      <DialogContent side="right" title="Sources and evidence" description="Every number Wizard cites comes from one of these retrievals. Source text is data, never instructions.">
        <div className="space-y-3" data-testid="evidence-drawer">
          {shown.length === 0 && <p className="text-sm text-ink-3">No source data was retrieved for this answer.</p>}
          {shown.map(item => <EvidenceDetail key={item.id} conversationId={conversationId} summary={item} preloaded={preloaded?.find(p => p.id === item.id)} />)}
        </div>
      </DialogContent>
    </Dialog>
  );
}
