import type {DataMode, Evidence, EvidenceSummary} from './types';

/** The real sources behind an answer: a database table or view, a report in one of a system's modules, or a file the
 *  user attached. Gemini may query one table fourteen times; that is one source with fourteen pieces of evidence. */

// A parenthesis after one of these words opens a subquery or a list, not a function call such as EXTRACT(... FROM ...).
const NOT_CALLS = new Set(['as', 'in', 'exists', 'from', 'join', 'lateral', 'on', 'where', 'select', 'and', 'or', 'not',
  'union', 'all', 'any', 'some', 'with', 'using', 'values', 'then', 'else', 'when', 'case', 'by', 'having', 'except',
  'intersect', 'materialized', 'recursive']);
const AFTER_TABLE = new Set(['where', 'join', 'inner', 'left', 'right', 'full', 'cross', 'natural', 'on', 'using', 'group',
  'order', 'limit', 'offset', 'fetch', 'union', 'except', 'intersect', 'having', 'window', 'tablesample']);

/** Tables and views a SELECT reads, as schema.name, for "which tables did it use". Read only for display: the query
 *  itself is in the evidence. CTE names and set-returning functions are left out. */
export function sqlRelations(sql: string): string[] {
  const text = sql.replace(/--[^\n]*/g, ' ').replace(/\/\*[\s\S]*?\*\//g, ' ')
    .replace(/\$([A-Za-z_][A-Za-z0-9_]*)?\$[\s\S]*?\$\1\$/g, "''").replace(/'(?:[^']|'')*'/g, "''");
  const tokens = text.match(/"(?:[^"]|"")*"|[A-Za-z_][A-Za-z0-9_$]*|\S/g) ?? [];
  const isWord = (t?: string) => !!t && /^["A-Za-z_]/.test(t);
  const lower = (t?: string) => (t ?? '').toLowerCase();
  const plain = (t: string) => t.startsWith('"') ? t.slice(1, -1).replace(/""/g, '"') : t.toLowerCase();
  const nameAt = (i: number): [string, number] | null => {
    if (!isWord(tokens[i]) || NOT_CALLS.has(lower(tokens[i]))) return null;
    const parts = [plain(tokens[i])];
    let j = i + 1;
    while (tokens[j] === '.' && isWord(tokens[j + 1])) { parts.push(plain(tokens[j + 1])); j += 2; }
    return [parts.join('.'), j];
  };
  const closing = (open: number): number => {
    for (let depth = 0, j = open; j < tokens.length; j++) {
      depth += tokens[j] === '(' ? 1 : tokens[j] === ')' ? -1 : 0;
      if (depth === 0) return j;
    }
    return tokens.length;
  };
  const ctes = new Set<string>();
  tokens.forEach((t, i) => {
    if (lower(t) !== 'as') return;
    let j = i + 1;
    if (lower(tokens[j]) === 'not') j++;
    if (lower(tokens[j]) === 'materialized') j++;
    if (tokens[j] !== '(') return;
    let k = i - 1;
    if (tokens[k] === ')') { while (k > 0 && tokens[k] !== '(') k--; k--; }  // name(col, ...) AS (
    if (isWord(tokens[k])) ctes.add(plain(tokens[k]));
  });
  const found: string[] = [];
  const calls: boolean[] = [];
  for (let i = 0; i < tokens.length; i++) {
    const token = tokens[i];
    if (token === '(') { calls.push(isWord(tokens[i - 1]) && !NOT_CALLS.has(lower(tokens[i - 1]))); continue; }
    if (token === ')') { calls.pop(); continue; }
    const keyword = lower(token);
    if ((keyword !== 'from' && keyword !== 'join') || calls[calls.length - 1]) continue;
    let j = i + 1;
    for (;;) {  // one FROM item, then more after a comma
      while (['lateral', 'only'].includes(lower(tokens[j]))) j++;
      const ref = nameAt(j);
      if (ref) j = ref[1];
      if (tokens[j] === '(') j = closing(j) + 1;  // a subquery (the walk reaches its own FROM) or generate_series(...)
      else if (!ref) break;
      else if (!ctes.has(ref[0]) && !found.includes(ref[0])) found.push(ref[0]);
      if (lower(tokens[j]) === 'as') j++;
      if (isWord(tokens[j]) && !AFTER_TABLE.has(lower(tokens[j]))) j++;  // alias
      if (tokens[j] === '(') j = closing(j) + 1;  // alias column list
      if (tokens[j] !== ',') break;
      j++;
    }
  }
  return found;
}

export type SourceKind = 'table' | 'report' | 'file' | 'query' | 'catalog';

export interface Source {
  key: string;
  kind: SourceKind;
  /** The system: PostgreSQL, GSCM, Attached file. */
  system: string;
  /** schema.table, the report's name, or the file's name. */
  name: string;
  /** A report's folders in its system: the module it sits in. */
  path: string[];
  /** The evidence behind it (each query, report run or file read), in the order Wizard read them. */
  ids: string[];
  dataModes: DataMode[];
  /** The newest as-of among its evidence. */
  asOf: string | null;
  accessNotes: string[];
}

// PostgreSQL's own catalog: Gemini looks up columns there, which is not a source of figures.
const CATALOG = /^(information_schema|pg_catalog)\.|^pg_[a-z0-9_]+$/i;

export function evidenceSql(item: Evidence | EvidenceSummary): string | null {
  return item.sql ?? ('request' in item ? item.request?.sql : undefined) ?? null;
}

/** The sources a set of evidence read, in the order first read; catalog lookups last. A query that joins two tables
 *  counts under both. */
export function sourceGroups(evidence: (Evidence | EvidenceSummary)[]): Source[] {
  const groups = new Map<string, Source>();
  const add = (key: string, kind: SourceKind, system: string, name: string, path: string[], item: Evidence | EvidenceSummary) => {
    const group = groups.get(key) ?? {key, kind, system, name, path, ids: [], dataModes: [], asOf: null, accessNotes: []};
    if (!group.ids.includes(item.id)) group.ids.push(item.id);
    if (!group.dataModes.includes(item.data_mode)) group.dataModes.push(item.data_mode);
    if (item.as_of && (!group.asOf || Date.parse(item.as_of) > Date.parse(group.asOf))) group.asOf = item.as_of;
    if (item.access_note && !group.accessNotes.includes(item.access_note)) group.accessNotes.push(item.access_note);
    groups.set(key, group);
  };
  for (const item of evidence) {
    const system = item.system_name ?? item.system.toUpperCase();
    const sql = evidenceSql(item);
    if (item.system === 'attachment') {
      // One file, whichever sheet was read: query_attachment names it "file › sheet".
      add(`file\n${item.report_id}`, 'file', system, item.report_name.split(' › ')[0], [], item);
    } else if (sql) {
      const tables = sqlRelations(sql);
      for (const table of tables.filter(t => !CATALOG.test(t))) add(`table\n${system}\n${table}`, 'table', system, table, [], item);
      if (tables.some(t => CATALOG.test(t))) add(`catalog\n${system}`, 'catalog', system, 'Table and column definitions', [], item);
      if (!tables.length) add(`query\n${system}\n${item.report_name}`, 'query', system, item.report_name, [], item);
    } else {
      add(`report\n${item.system}\n${item.report_id}`, 'report', system, item.report_name, item.folder_path ?? [], item);
    }
  }
  const all = [...groups.values()];
  return [...all.filter(s => s.kind !== 'catalog'), ...all.filter(s => s.kind === 'catalog')];
}

/** How many sources to put on the "Show sources" button: catalog lookups are not counted. */
export function sourceCount(sources: Source[]): number {
  return sources.filter(s => s.kind !== 'catalog').length;
}

const USES: Record<SourceKind, [string, string]> = {table: ['query', 'queries'], report: ['run', 'runs'], file: ['read', 'reads'],
  query: ['query', 'queries'], catalog: ['lookup', 'lookups']};

/** "14 queries", "1 run": how often Wizard read a source. */
export function usesText(source: Source): string {
  return `${source.ids.length} ${USES[source.kind][source.ids.length === 1 ? 0 : 1]}`;
}

/** Lines that start alike (fourteen queries on one table) with their shared opening cut to "…", keeping three words
 *  before the first difference, so what tells them apart shows in a narrow row. One line, identical lines and lines
 *  with little in common stay whole. */
export function distinctLines(lines: string[]): string[] {
  if (lines.length < 2 || lines.every(line => line === lines[0])) return lines;
  const words = lines.map(line => line.split(' '));
  let shared = 0;
  while (words.every(w => shared < w.length && w[shared] === words[0][shared])) shared++;
  const cut = Math.max(0, shared - 3);
  if (words[0].slice(0, cut).join(' ').length < 20) return lines;
  return words.map(w => `… ${w.slice(cut).join(' ')}`);
}
