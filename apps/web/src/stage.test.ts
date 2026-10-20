import {describe, expect, it} from 'vitest';
import {emptyRun} from './runState';
import {badges, detailOf, moduleOf, stageModel} from './stage';
import type {RunView, SystemInfo, TimelineItem} from './types';

const SYSTEMS: SystemInfo[] = [
  {id: 'asap', name: 'ASAP', kind: 'reports'}, {id: 'nerp', name: 'NERP', kind: 'reports'},
  {id: 'postgresql', name: 'AI Team Database', kind: 'database'}, {id: 'knowledge', name: 'Knowledge base', kind: 'knowledge', notes: 40},
  {id: 'attachment', name: 'Attached files', kind: 'files'},
];

function tool(key: string, name: string, state: TimelineItem['state'], extra: Partial<TimelineItem> = {}): TimelineItem {
  return {key, kind: 'tool', label: name, name, state, ...extra};
}

function run(timeline: TimelineItem[], status: RunView['status'] = 'running'): RunView {
  return {...emptyRun('r1', 'c1', 'q'), status, timeline};
}

const evidence = (id: string, system: string, rows: number) => ({id, system, report_id: 'x', report_name: 'x', data_mode: 'LIVE' as const,
  as_of: null, total_rows: rows, truncated: false, warnings: [], access_note: null});

describe('the systems stage', () => {
  it('maps each tool to the system it reads', () => {
    expect(moduleOf('wizard_query_postgresql')).toBe('postgresql');
    expect(moduleOf('wizard_read_knowledge')).toBe('knowledge');
    expect(moduleOf('wizard_lookup_definitions')).toBe('knowledge');
    expect(moduleOf('nerp_run_report')).toBe('nerp');
    expect(moduleOf('bdp_search_reports')).toBe('bdp');
    expect(moduleOf('wizard_query_attachment')).toBe('attachment');
    expect(moduleOf('wizard_calculate')).toBe('wizard');
    expect(moduleOf('wizard_search_catalog')).toBe('wizard');
    expect(moduleOf('wizard_schedule_extraction')).toBe('metronome');
  });

  it('shows what each call looked for, from its own arguments', () => {
    expect(detailOf(tool('1', 'wizard_query_postgresql', 'running', {args: {sql: 'select  *\n from  sales'}}))).toEqual({text: 'select * from sales', code: true});
    expect(detailOf(tool('2', 'wizard_lookup_definitions', 'running', {args: {query: 'gross margin'}}))?.text).toBe('“gross margin”');
    expect(detailOf(tool('3', 'nerp_run_report', 'running', {args: {report_id: 'nerp-spend', filters: [{field: 'market', values: ['SA', 'EG']}]}}))?.text)
      .toBe('nerp-spend · market=SA/EG');
    expect(detailOf(tool('4', 'wizard_read_knowledge', 'ok', {args: {ids: ['a', 'b']}}))?.text).toBe('a, b');
    expect(detailOf(tool('5', 'wizard_list_sources', 'ok'))).toBeNull();
  });

  it('counts calls, rows and notes per system and knows which one is active', () => {
    const model = stageModel(run([
      tool('1', 'wizard_lookup_definitions', 'ok', {summary: 'Gross margin, Sell-out'}),
      tool('2', 'nerp_run_report', 'ok', {evidence: evidence('E1', 'nerp', 120)}),
      tool('3', 'wizard_query_postgresql', 'ok', {evidence: evidence('E2', 'postgresql', 900)}),
      tool('4', 'wizard_query_postgresql', 'running'),
      tool('5', 'wizard_calculate', 'ok'),
    ]), SYSTEMS);
    expect(model.modules.map(m => m.id)).toEqual(['postgresql', 'asap', 'nerp', 'knowledge']);  // files only once used
    const db = model.modules.find(m => m.id === 'postgresql')!;
    expect(db.stats).toMatchObject({state: 'active', rows: 900, running: true});
    expect(db.stats.calls).toHaveLength(2);
    expect(model.modules.find(m => m.id === 'asap')!.stats.state).toBe('idle');
    expect(model.modules.find(m => m.id === 'knowledge')!.stats.notes).toBe(2);
    expect(model.active?.key).toBe('4');
    expect(model.totals).toEqual({systems: 3, available: 4, calls: 5, rows: 1020, notes: 2});
    expect(model.wizard.calls).toHaveLength(1);
  });

  it('adds a system the run used even if it is not listed, and marks failed ones', () => {
    const model = stageModel(run([tool('1', 'gscm_run_report', 'error')], 'failed'), SYSTEMS);
    expect(model.modules.find(m => m.id === 'gscm')).toMatchObject({name: 'GSCM', kind: 'reports'});
    expect(model.modules.find(m => m.id === 'gscm')!.stats.state).toBe('error');
  });

  it('shows Metronome, by its own name, while Gemini prepares a recurring email', () => {
    const scheduled = tool('1', 'wizard_schedule_extraction', 'ok', {evidence: {...evidence('E1', 'postgresql', 20),
      system_name: 'AI Team Database'}});
    const model = stageModel(run([scheduled], 'succeeded'), SYSTEMS);
    const metronome = model.modules.find(m => m.id === 'metronome')!;
    expect(metronome).toMatchObject({name: 'Metronome', kind: 'schedules'});
    expect(metronome.stats.calls).toHaveLength(1);
    expect(model.modules.at(-1)!.id).toBe('metronome');
  });

  it('awards only badges the finished run earned', () => {
    const timeline = [tool('1', 'wizard_read_knowledge', 'ok', {args: {ids: ['n1']}}),
      tool('2', 'wizard_query_postgresql', 'ok', {evidence: evidence('E1', 'postgresql', 1500)})];
    const done = run(timeline, 'succeeded');
    expect(badges(done, stageModel(done, SYSTEMS)).map(b => b.id)).toEqual(['cross', 'grounded', 'deep']);
    const live = run(timeline, 'running');
    expect(badges(live, stageModel(live, SYSTEMS))).toEqual([]);
    const one = run([tool('1', 'nerp_run_report', 'ok', {evidence: evidence('E1', 'nerp', 5)})], 'succeeded');
    expect(badges(one, stageModel(one, SYSTEMS))).toEqual([]);
  });
});
