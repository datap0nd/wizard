// The visual environment inside Wizard: the cited evidence with its rows (read from the person's own conversation, as
// the evidence drawer reads it), and Download saving into the person's Downloads folder where Wizard runs on their PC.
import {api, ApiError} from './api';
import {evidenceSql} from './sources';
import type {DataMode, Evidence, EvidenceSummary} from './types';
import type {SavedExport, SourceRows, VisualEnv, VisualSource} from './visualEnv';

function sourceName(e: Evidence | EvidenceSummary): string {
  return [e.system_name ?? e.system, e.report_name].filter(Boolean).join(' · ') || e.id;
}

function queryOf(e: Evidence | EvidenceSummary): string | null {
  const sql = evidenceSql(e);
  if (sql) return sql;
  if (!('request' in e) || !e.request) return null;
  const {steps, filters, group_by, measures} = e.request;
  if (steps?.length) return steps.map((s, i) => `${i + 1}. ${[s.action, s.url, s.selector, s.name, s.text].filter(Boolean).join(' ')}`).join('\n');
  const parts = [filters?.length ? `filters: ${filters.map(f => `${f.field} in (${f.values.join(', ')})`).join('; ')}` : '',
    group_by?.length ? `grouped by ${group_by.join(', ')}` : '', measures?.length ? `measures: ${measures.join(', ')}` : ''];
  return parts.filter(Boolean).join('\n') || null;
}

export function wizardVisualEnv(conversationId: string | null, dataMode: DataMode | null, evidence: (Evidence | EvidenceSummary)[]): VisualEnv {
  const full = async (id: string): Promise<Evidence | EvidenceSummary | null> => {
    const known = evidence.find(e => e.id === id) ?? null;
    if (known && 'rows' in known) return known;
    if (!conversationId) return known;
    try { return (await api.evidence(conversationId, id)).evidence; } catch { return known; }
  };
  return {
    dataMode, rowsBehind: true,
    sources: async ids => {
      const found = (await Promise.all(ids.map(full))).filter((e): e is Evidence | EvidenceSummary => e !== null);
      const sources: VisualSource[] = found.map(e => ({id: e.id, name: sourceName(e), dataMode: e.data_mode, asOf: e.as_of,
        totalRows: e.total_rows, truncated: e.truncated, query: queryOf(e)}));
      const rows: SourceRows[] = found.filter((e): e is Evidence => 'rows' in e && Array.isArray(e.rows) && e.rows.length > 0 && Array.isArray(e.columns))
        .map(e => ({id: e.id, columns: e.columns, rows: e.rows, truncated: e.truncated}));
      return {sources, rows};
    },
    save: async (file, filename): Promise<SavedExport | null> => {
      try {
        return (await api.saveExport(file, filename)).saved;
      } catch (e) {
        if (e instanceof ApiError && e.code === 'not_on_this_pc') return null;  // a server: the browser downloads it
        throw e;
      }
    },
    open: async saved => { await api.openExport(saved.id); },
  };
}
