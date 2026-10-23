import type {RunView, SystemInfo, TimelineItem} from './types';

/** Wizard's own work (calculating, charts, checks, searching every catalog): shown on the Wizard orb itself. */
export const WIZARD = 'wizard';

/** Which system module a tool call belongs to, from the tool's name. */
export function moduleOf(name: string | undefined): string {
  const tool = name ?? '';
  if (tool === 'wizard_query_postgresql') return 'postgresql';
  if (tool === 'wizard_schedule_brief') return 'metronome';
  if (/^wizard_(lookup_definitions|browse_knowledge|read_knowledge)$/.test(tool)) return 'knowledge';
  if (/^wizard_(read|query)_attachment$/.test(tool)) return 'attachment';
  const system = tool.match(/^([a-z0-9]+)_(search_reports|get_report_schema|run_report)$/);
  if (system) return system[1];
  return WIZARD;
}

const squash = (text: string, limit: number) => {
  const flat = text.replace(/\s+/g, ' ').trim();
  return flat.length > limit ? `${flat.slice(0, limit - 1)}…` : flat;
};

/** What the call was looking for, from Gemini's own arguments: the SQL, the search words, the notes, the filters. */
export function detailOf(item: TimelineItem): {text: string; code: boolean} | null {
  const args = item.args ?? {};
  if (typeof args.sql === 'string') return {text: squash(args.sql, 220), code: true};
  if (typeof args.query === 'string' && args.query) return {text: `“${squash(args.query, 120)}”`, code: false};
  if (Array.isArray(args.ids) && args.ids.length) return {text: args.ids.map(String).join(', '), code: false};
  const filters = Array.isArray(args.filters)
    ? args.filters.filter((f): f is {field: unknown; values?: unknown[]} => !!f && typeof f === 'object')
      .map(f => `${String(f.field)}=${(f.values ?? []).map(String).join('/')}`) : [];
  if (typeof args.report_id === 'string') return {text: [args.report_id, ...filters].join(' · '), code: false};
  if (typeof args.expression === 'string') return {text: squash(args.expression, 160), code: true};
  if (typeof args.area === 'string') return {text: `area ${args.area}`, code: false};
  if (typeof args.title === 'string') return {text: squash(args.title, 120), code: false};
  if (filters.length) return {text: filters.join(' · '), code: false};
  return null;
}

export interface ModuleStats {
  id: string;
  calls: TimelineItem[];
  running: boolean;
  errors: number;
  rows: number;
  /** Knowledge notes read or definitions found. */
  notes: number;
  state: 'idle' | 'active' | 'done' | 'error';
}

export interface StageModel {
  modules: (SystemInfo & {stats: ModuleStats})[];
  wizard: ModuleStats;
  active: TimelineItem | null;
  totals: {systems: number; available: number; calls: number; rows: number; notes: number};
}

function countNotes(item: TimelineItem): number {
  if (item.state !== 'ok') return 0;
  if (Array.isArray(item.args?.ids)) return item.args!.ids.length;
  if (item.name === 'wizard_lookup_definitions' && item.summary && item.summary !== 'no definition found') {
    return item.summary.split(', ').length;
  }
  return 0;
}

function stats(id: string, calls: TimelineItem[]): ModuleStats {
  const running = calls.some(c => c.state === 'running');
  const errors = calls.filter(c => c.state === 'error').length;
  const rows = calls.reduce((sum, c) => sum + (c.state === 'ok' && c.evidence ? c.evidence.total_rows || 0 : 0), 0);
  const notes = calls.reduce((sum, c) => sum + countNotes(c), 0);
  const state = running ? 'active' : !calls.length ? 'idle' : errors === calls.length ? 'error' : 'done';
  return {id, calls, running, errors, rows, notes, state};
}

const NAMES: Record<string, string> = {postgresql: 'AI Team Database', knowledge: 'Knowledge base', attachment: 'Attached files',
  metronome: 'Metronome'};

/** Everything the stage shows, derived only from what the run actually did. */
export function stageModel(run: RunView, systems: SystemInfo[]): StageModel {
  const tools = run.timeline.filter(t => t.kind === 'tool');
  const byModule = new Map<string, TimelineItem[]>();
  for (const tool of tools) {
    const id = moduleOf(tool.name);
    byModule.set(id, [...(byModule.get(id) ?? []), tool]);
  }
  const listed = systems.filter(s => s.kind !== 'files' || byModule.has(s.id));
  const extra = Array.from(byModule.keys()).filter(id => id !== WIZARD && !listed.some(s => s.id === id))
    .map(id => {
      const calls = byModule.get(id)!;
      const named = id === 'metronome' ? undefined : calls.find(c => c.evidence?.system_name)?.evidence?.system_name;
      return {id, name: named ?? NAMES[id] ?? id.toUpperCase(), kind: id === 'postgresql' ? 'database' : id === 'knowledge'
        ? 'knowledge' : id === 'attachment' ? 'files' : id === 'metronome' ? 'schedules' : 'reports'} as SystemInfo;
    });
  const order = (s: SystemInfo) => ({database: 0, reports: 1, knowledge: 2, files: 3, schedules: 4})[s.kind] ?? 5;
  const modules = [...listed, ...extra].sort((a, b) => order(a) - order(b))
    .map(s => ({...s, stats: stats(s.id, byModule.get(s.id) ?? [])}));
  const active = [...tools].reverse().find(t => t.state === 'running') ?? null;
  const used = modules.filter(m => m.stats.calls.length > 0);
  return {
    modules, wizard: stats(WIZARD, byModule.get(WIZARD) ?? []), active,
    totals: {systems: used.length, available: modules.length, calls: tools.length,
      rows: modules.reduce((sum, m) => sum + m.stats.rows, 0), notes: modules.reduce((sum, m) => sum + m.stats.notes, 0)},
  };
}

export interface Badge { id: string; label: string; detail: string }

/** Earned, never invented: each badge is a plain fact about the finished run. */
export function badges(run: RunView, model: StageModel): Badge[] {
  if (run.status !== 'succeeded') return [];
  const earned: Badge[] = [];
  const data = model.modules.filter(m => m.kind !== 'knowledge' && m.stats.rows > 0);
  const knowledge = model.modules.find(m => m.kind === 'knowledge' && m.stats.calls.some(c => c.state === 'ok'));
  if (model.totals.systems >= 2) earned.push({id: 'cross', label: `Cross-checked ${model.totals.systems} systems`,
    detail: 'The answer draws on more than one system.'});
  if (knowledge && data.length) earned.push({id: 'grounded', label: 'Data + definitions',
    detail: 'Numbers from the data, read against the knowledge base.'});
  if (model.totals.rows >= 1000) earned.push({id: 'deep', label: `Deep dive: ${model.totals.rows.toLocaleString()} rows`,
    detail: 'Read over a thousand rows to get here.'});
  if (run.check?.overall === 'CHECKED' || run.checkStatus === 'CHECKED') earned.push({id: 'checked', label: 'Checked',
    detail: 'The figures were recomputed from the evidence.'});
  return earned;
}
