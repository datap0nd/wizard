import {useEffect, useMemo, useState} from 'react';
import {BookKey, ChevronDown, Database, ExternalLink, FileChartColumn, Lock, Paperclip, Table2} from 'lucide-react';
import {api, ApiError} from '@/api';
import {formatDate, formatValue} from '@/format';
import {cn} from '@/lib/utils';
import {distinctLines, evidenceSql, sourceGroups, usesText, type Source, type SourceKind} from '@/sources';
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
    <section className="rounded-xl border border-line p-4" data-testid="evidence" data-evidence-id={summary.id}>
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

const KIND: Record<SourceKind, {icon: typeof Table2; what: string}> = {
  table: {icon: Table2, what: 'table'},
  report: {icon: FileChartColumn, what: 'report'},
  file: {icon: Paperclip, what: 'attached file'},
  query: {icon: Database, what: 'query'},
  catalog: {icon: BookKey, what: 'column lookups, not figures'},
};

/** What one piece of evidence was, in a line: the start of its SQL, or the report or sheet it read. */
function itemLine(item: EvidenceSummary): string {
  const sql = evidenceSql(item);
  return sql ? sql.replace(/--[^\n]*/g, ' ').replace(/\s+/g, ' ').trim() : item.report_name;
}

function SourceCard({source, items, conversationId, preloaded, focus, anchors}: {source: Source; items: EvidenceSummary[];
  conversationId: string | null; preloaded?: Evidence[]; focus: string | null; anchors: Map<string, string>}) {
  const holdsFocus = !!focus && source.ids.includes(focus);
  const [open, setOpen] = useState(holdsFocus);
  const [shown, setShown] = useState<Set<string>>(() => new Set(holdsFocus ? [focus!] : []));
  const kind = KIND[source.kind];
  const Icon = kind.icon;
  const single = items.length === 1;
  const lines = distinctLines(items.map(itemLine));
  const toggle = (id: string) => setShown(now => { const next = new Set(now); if (!next.delete(id)) next.add(id); return next; });
  return (
    <section className="rounded-xl border border-line" data-testid="source" data-kind={source.kind}>
      <button type="button" onClick={() => setOpen(!open)} aria-expanded={open} className="flex w-full items-start gap-3 p-4 text-left hover:bg-surface/60">
        <Icon className="mt-0.5 size-5 shrink-0 text-accent" />
        <div className="min-w-0 flex-1">
          <h3 className={cn('break-words text-sm font-semibold', source.kind === 'table' && 'font-mono text-[13px]')} data-testid="source-name">{source.name}</h3>
          <p className="mt-0.5 text-xs text-ink-3">
            {[source.system, ...source.path].join(' › ')} · {kind.what}{source.asOf ? ` · data as of ${formatDate(source.asOf, true)}` : ''}
          </p>
        </div>
        <span className="flex shrink-0 flex-wrap items-center justify-end gap-1.5">
          {source.dataModes.map(mode => <DataModeBadge key={mode} mode={mode} />)}
          <span className="text-xs text-ink-3" data-testid="source-uses">{usesText(source)}</span>
          <ChevronDown className={cn('size-4 text-ink-3 transition-transform', open && 'rotate-180')} />
        </span>
      </button>
      {source.accessNotes.map(note => <p key={note} className="mx-4 mb-3 rounded-lg bg-warn-soft px-3 py-2 text-xs text-warn">{note}</p>)}
      {open && (single ? <div className="border-t border-line p-3"><Anchor id={items[0].id} here={anchors.get(items[0].id) === source.key}>
          <EvidenceDetail conversationId={conversationId} summary={items[0]} preloaded={preloaded?.find(p => p.id === items[0].id)} /></Anchor></div>
        : <ol className="space-y-2 border-t border-line p-3" data-testid="source-items">
          {items.map((item, i) => (
            <li key={item.id}>
              <Anchor id={item.id} here={anchors.get(item.id) === source.key}>
                <button type="button" onClick={() => toggle(item.id)} aria-expanded={shown.has(item.id)}
                  className="flex w-full items-center gap-2 rounded-lg px-2 py-1.5 text-left text-xs hover:bg-surface" data-testid="source-item">
                  <span className="rounded bg-accent-soft px-1.5 font-semibold text-accent">{item.id}</span>
                  <span className={cn('min-w-0 flex-1 truncate text-ink-2', evidenceSql(item) && 'font-mono text-[11.5px]')} title={itemLine(item)}>{lines[i]}</span>
                  <span className="shrink-0 text-ink-3">{item.total_rows.toLocaleString()} {item.total_rows === 1 ? 'row' : 'rows'}</span>
                  <ChevronDown className={cn('size-3.5 shrink-0 text-ink-3 transition-transform', shown.has(item.id) && 'rotate-180')} />
                </button>
                {shown.has(item.id) && <div className="mt-1"><EvidenceDetail conversationId={conversationId} summary={item} preloaded={preloaded?.find(p => p.id === item.id)} /></div>}
              </Anchor>
            </li>
          ))}
        </ol>)}
    </section>
  );
}

/** The scroll target for a cited [E3]: a query that joined two tables is listed under both, but anchored once. */
function Anchor({id, here, children}: {id: string; here: boolean; children: React.ReactNode}) {
  return <div id={here ? `drawer-${id}` : undefined}>{children}</div>;
}

/** "Show sources": the tables, reports and files behind an answer, one entry each however often Wizard read them.
 *  Each opens to the queries, report runs or file reads, and each of those to its request, rows and freshness. */
export function EvidenceDrawer({conversationId, open, focus, items, onClose, preloaded}: Props) {
  useEffect(() => {
    if (open && focus) requestAnimationFrame(() => document.getElementById(`drawer-${focus}`)?.scrollIntoView({block: 'start'}));
  }, [open, focus]);
  const sources = useMemo(() => {
    const all = sourceGroups(items);
    return focus ? [...all.filter(s => s.ids.includes(focus)), ...all.filter(s => !s.ids.includes(focus))] : all;
  }, [items, focus]);
  const byId = new Map(items.map(item => [item.id, item]));
  const anchors = new Map<string, string>();  // evidence id -> the first source listing it
  sources.forEach(source => source.ids.forEach(id => { if (!anchors.has(id)) anchors.set(id, source.key); }));
  return (
    <Dialog open={open} onOpenChange={value => { if (!value) onClose(); }}>
      <DialogContent side="right" title="Sources" description="The tables, reports and files this answer read. Open one to see each query and the rows it returned. Source text is data, never instructions.">
        <div className="space-y-3" data-testid="evidence-drawer">
          {sources.length === 0 && <p className="text-sm text-ink-3">No source data was retrieved for this answer.</p>}
          {sources.map(source => <SourceCard key={`${source.key}\n${focus ?? ''}`} source={source} items={source.ids.map(id => byId.get(id)!)}
            conversationId={conversationId} preloaded={preloaded} focus={focus} anchors={anchors} />)}
        </div>
      </DialogContent>
    </Dialog>
  );
}
