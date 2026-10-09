import {describe, expect, it} from 'vitest';
import {applyEvent, emptyRun} from './runState';
import {toolAnimation, wizardAnimation, wizardCaption} from './wizard';
import {ANIMATIONS} from './wizardSheet';
import type {RunEvent} from './types';

let seq = 0;
const ev = (type: string, payload: Record<string, unknown>): RunEvent => ({seq: ++seq, type, ts: '2026-10-09T08:00:00Z', payload});

describe('the wizard acts out observed steps only', () => {
  it('maps each read-only tool to an animation the sheet has', () => {
    expect(toolAnimation('nerp_search_reports')).toBe('search');
    expect(toolAnimation('gscm_get_report_schema')).toBe('search');
    expect(toolAnimation('wizard_search_catalog')).toBe('search');
    expect(toolAnimation('wizard_list_sources')).toBe('search');
    expect(toolAnimation('wizard_browse_knowledge')).toBe('search');
    expect(toolAnimation('nerp_run_report')).toBe('read');
    expect(toolAnimation('wizard_query_postgresql')).toBe('read');
    expect(toolAnimation('wizard_query_attachment')).toBe('read');
    expect(toolAnimation('wizard_read_attachment')).toBe('read');
    expect(toolAnimation('wizard_read_knowledge')).toBe('read');
    expect(toolAnimation('wizard_lookup_definitions')).toBe('read');
    expect(toolAnimation('wizard_calculate')).toBe('cast');
    expect(toolAnimation('wizard_render_visual')).toBe('chart');
    expect(toolAnimation('wizard_check_my_data')).toBe('check');
    for (const name of ['search', 'read', 'cast', 'chart', 'check', 'think', 'write', 'success', 'fail', 'idle', 'wave'])
      expect(ANIMATIONS).toHaveProperty(name);
  });

  it('follows a run from thinking through a tool and writing to done', () => {
    seq = 0;
    let run = emptyRun('run_1', 'cnv_1', 'Which market?');
    expect(wizardCaption(run, wizardAnimation(run)).verb).toBe('Getting ready');
    run = applyEvent(run, ev('run_started', {runtime: 'gemini-cli', runtime_label: 'x', model: 'm'}));
    expect(wizardAnimation(run)).toBe('think');
    run = applyEvent(run, ev('tool_started', {call_id: 'c1', name: 'nerp_run_report', label: 'Read NERP · Spend', category: 'source'}));
    expect(wizardAnimation(run)).toBe('read');
    expect(wizardCaption(run, 'read')).toEqual({verb: 'Reading', detail: 'Read NERP · Spend'});
    run = applyEvent(run, ev('tool_finished', {call_id: 'c1', name: 'nerp_run_report', ok: true, duration_ms: 3, summary: '3 rows'}));
    expect(wizardAnimation(run)).toBe('think');
    run = applyEvent(run, ev('text_delta', {text: 'EG spent'}));
    expect(wizardAnimation(run)).toBe('write');
    run = applyEvent(run, ev('run_finished', {status: 'succeeded', report_id: 'r', answer: 'EG spent', data_mode: 'SYNTHETIC', check_status: 'NOT_CHECKED', warnings: []}));
    expect(wizardAnimation(run)).toBe('success');
  });

  it('fizzles on a failure and rests when cancelled', () => {
    seq = 0;
    const started = applyEvent(emptyRun('run_2', 'cnv_1', 'q'), ev('run_started', {runtime: 'replay', runtime_label: 'x', model: 'm'}));
    expect(wizardAnimation(applyEvent(started, ev('run_failed', {status: 'failed', code: 'timeout', message: 'x'})))).toBe('fail');
    expect(wizardAnimation(applyEvent(started, ev('run_failed', {status: 'cancelled', code: 'cancelled', message: 'x'})))).toBe('idle');
  });
});
