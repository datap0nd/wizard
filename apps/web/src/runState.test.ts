import {describe, expect, it} from 'vitest';
import {applyEvent, emptyRun, sourcesConsulted} from './runState';
import {citedEvidence, placedVisuals, prepareAnswer} from './citations';
import {formatValue} from './format';
import type {RunEvent} from './types';

let seq = 0;
const ev = (type: string, payload: Record<string, unknown>): RunEvent => ({seq: ++seq, type, ts: '2026-10-02T08:00:00Z', payload});

describe('run reducer', () => {
  it('builds the observed timeline and final answer from events', () => {
    seq = 0;
    let run = emptyRun('run_1', 'cnv_1', 'Which market?');
    for (const event of [
      ev('run_started', {runtime: 'gemini-cli', runtime_label: 'Gemini CLI 0.62.0 · gemini-3.8-flash', model: 'gemini-3.8-flash'}),
      ev('text_delta', {text: "I'll check NERP."}),
      ev('note', {text: "I'll check NERP."}),
      ev('tool_started', {call_id: 'c1', name: 'nerp_run_report', label: 'Read NERP · Spend', category: 'source', arguments: {}}),
      ev('tool_finished', {call_id: 'c1', name: 'nerp_run_report', ok: true, duration_ms: 3, summary: '3 rows',
        evidence: {id: 'E1', system: 'nerp', report_id: 'r', report_name: 'Spend', data_mode: 'SYNTHETIC', as_of: null, total_rows: 3, truncated: false, warnings: [], access_note: null}}),
      ev('text_delta', {text: 'EG spent $1.5M [E1].'}),
      ev('run_finished', {status: 'succeeded', report_id: 'rpt_1', answer: 'EG spent $1.5M [E1].', data_mode: 'SYNTHETIC', check_status: 'NOT_CHECKED', warnings: []}),
    ]) run = applyEvent(run, event);
    expect(run.status).toBe('succeeded');
    expect(run.timeline.map(t => t.kind)).toEqual(['note', 'tool']);
    expect(run.timeline[1].state).toBe('ok');
    expect(run.evidence.map(e => e.id)).toEqual(['E1']);
    expect(run.answer).toBe('EG spent $1.5M [E1].');
    expect(run.streamText).toBe('');
    expect(sourcesConsulted(run)).toEqual(['NERP']);
  });

  it('ignores replayed events and marks running tools stopped on failure', () => {
    seq = 0;
    let run = emptyRun('run_2', 'cnv', 'q');
    const started = ev('tool_started', {call_id: 'c1', name: 'gscm_run_report', label: 'Read GSCM', category: 'source', arguments: {}});
    run = applyEvent(run, started);
    expect(applyEvent(run, started)).toBe(run);
    run = applyEvent(run, ev('run_failed', {code: 'model_unreachable', message: 'Gemini could not be reached.'}));
    expect(run.status).toBe('failed');
    expect(run.error?.code).toBe('model_unreachable');
    expect(run.timeline[0].state).toBe('error');
  });
});

describe('diagnostics', () => {
  it('keeps every diagnostic the server attached, with the failure', () => {
    seq = 0;
    let run = emptyRun('run_d', 'cnv_1', 'Hey');
    run = applyEvent(run, ev('run_started', {runtime: 'gemini-cli', runtime_label: 'x', model: 'm'}));
    run = applyEvent(run, ev('diagnostic', {source: 'gemini-cli', outcome: 'model_unavailable', exit_code: 1, stderr: ['Attempt 1 failed: 503']}));
    run = applyEvent(run, ev('run_failed', {code: 'model_unavailable', message: 'Gemini is temporarily unavailable.'}));
    expect(run.diagnostics).toHaveLength(1);
    expect(run.diagnostics[0].stderr).toEqual(['Attempt 1 failed: 503']);
    expect(run.status).toBe('failed');
  });
});

describe('citations', () => {
  it('turns evidence ids into chips and standalone visual ids into blocks, never touching code blocks', () => {
    const text = 'Spend was $1.5M [E1] and [E12].\n\n[V1]\n\n```\n[E2]\n```';
    const out = prepareAnswer(text);
    expect(out).toContain('[E1](#evidence-E1)');
    expect(out).toContain('[E12](#evidence-E12)');
    expect(out).toContain('```wizard-visual\nV1\n```');
    expect(out).toContain('```\n[E2]\n```');
    expect(Array.from(placedVisuals(text))).toEqual(['V1']);
    expect(citedEvidence(text)).toEqual(['E1', 'E12', 'E2']);
  });
});

describe('format', () => {
  it('formats units without inventing precision', () => {
    expect(formatValue(1500000, 'currency', 'USD')).toBe('$1.5M');
    expect(formatValue(-0.3, 'percent', 'pp')).toBe('-0.3 pp');
    expect(formatValue(null)).toBe('—');
    expect(formatValue(14666.67, 'number', 'units/USD 1M')).toContain('units/USD 1M');
  });
});
