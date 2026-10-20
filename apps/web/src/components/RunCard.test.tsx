import {afterEach, describe, expect, it, vi} from 'vitest';
import {act, cleanup, fireEvent, render, screen} from '@testing-library/react';
import {RunCard} from './RunCard';
import {beam, layout, SystemsContext} from './SystemsStage';
import {TooltipProvider} from './ui/menu';
import {applyEvent, emptyRun} from '@/runState';
import type {RunEvent} from '@/types';

afterEach(() => { cleanup(); vi.useRealTimers(); });

const noop = () => {};
const card = (run: ReturnType<typeof emptyRun>) => (
  <TooltipProvider>
    <RunCard run={run} onEvidence={noop} onCheck={noop} onCancel={noop} onRetry={noop} onFeedback={noop} onEmail={noop} busy={false} />
  </TooltipProvider>
);

describe('run card timing', () => {
  it('counts up while Gemini works and shows when each step started and how long its tool took', () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date('2026-10-07T07:25:00Z'));
    let seq = 0;
    const ev = (type: string, ts: string, payload: Record<string, unknown>): RunEvent => ({seq: ++seq, type, ts, payload});
    let run = {...emptyRun('run_1', 'cnv_1', 'Market share by market in August 2026'), createdAt: '2026-10-07T07:25:00Z'};
    run = applyEvent(run, ev('run_started', '2026-10-07T07:25:00Z', {runtime: 'gemini-cli', runtime_label: 'x', model: 'm'}));
    run = applyEvent(run, ev('tool_started', '2026-10-07T07:27:35Z', {call_id: 'c1', name: 'wizard_query_postgresql', label: 'Queried PostgreSQL', category: 'source'}));
    run = applyEvent(run, ev('tool_finished', '2026-10-07T07:28:33Z', {call_id: 'c1', name: 'wizard_query_postgresql', ok: true, duration_ms: 58100, summary: '12 rows'}));
    render(card(run));
    expect(screen.getByTestId('elapsed').textContent).toBe('0:00');
    act(() => { vi.advanceTimersByTime(3 * 60_000 + 5_000); });
    expect(screen.getByTestId('elapsed').textContent).toBe('3:05');
    fireEvent.click(screen.getByRole('button', {name: /Step by step/}));
    expect(screen.getByTestId('step-timing').textContent).toBe('2:35 · 58.1 s');
  });
});

describe('systems stage', () => {
  it('lights up the system Gemini is reading and shows the query it sent', () => {
    let seq = 0;
    const ev = (type: string, payload: Record<string, unknown>): RunEvent => ({seq: ++seq, type, ts: '2026-10-07T07:25:00Z', payload});
    let run = applyEvent(emptyRun('run_1', 'cnv_1', 'Sell-in by market'), ev('run_started', {runtime: 'code-assist', runtime_label: 'x', model: 'm'}));
    run = applyEvent(run, ev('tool_started', {call_id: 'c1', name: 'wizard_read_knowledge', label: 'Read sell-in', category: 'knowledge', arguments: {ids: ['sell-in']}}));
    run = applyEvent(run, ev('tool_finished', {call_id: 'c1', name: 'wizard_read_knowledge', ok: true, duration_ms: 20, summary: 'Sell-in'}));
    run = applyEvent(run, ev('tool_started', {call_id: 'c2', name: 'wizard_query_postgresql', label: 'Queried the AI Team Database',
      category: 'source', arguments: {sql: 'SELECT market, sum(units) FROM bi_reporting.sell_in_amt_mv GROUP BY 1'}}));
    render(
      <SystemsContext.Provider value={[{id: 'postgresql', name: 'AI Team Database', kind: 'database'}, {id: 'knowledge', name: 'Knowledge base', kind: 'knowledge', notes: 12}]}>
        {card(run)}
      </SystemsContext.Provider>,
    );
    const nodes = screen.getAllByTestId('stage-node');
    expect(nodes.map(n => [n.dataset.system, n.dataset.state])).toEqual([['postgresql', 'active'], ['knowledge', 'done']]);
    expect(screen.getByTestId('stage-now').textContent).toContain('Querying AI Team Database');
    expect(screen.getByTestId('stage-now').textContent).toContain('SELECT market, sum(units) FROM bi_reporting.sell_in_amt_mv');
    fireEvent.click(nodes[1]);
    expect(screen.getByTestId('stage-calls').textContent).toContain('Read sell-in');
  });
});

describe('the wizard on the stage', () => {
  it('acts out the running step, hops when the answer lands live, then the stage folds', () => {
    vi.useFakeTimers();
    let seq = 0;
    const ev = (type: string, payload: Record<string, unknown>): RunEvent => ({seq: ++seq, type, ts: '2026-10-20T08:00:00Z', payload});
    let run = applyEvent(emptyRun('run_2', 'cnv_1', 'q'), ev('run_started', {runtime: 'replay', runtime_label: 'x', model: 'm'}));
    run = applyEvent(run, ev('tool_started', {call_id: 'c1', name: 'nerp_run_report', label: 'Read NERP · Spend', category: 'source'}));
    const view = render(<SystemsContext.Provider value={[{id: 'nerp', name: 'NERP', kind: 'reports'}]}>{card(run)}</SystemsContext.Provider>);
    expect(screen.getByTestId('wizard-sprite').dataset.animation).toBe('read');
    expect(screen.getByTestId('wizard-verb').textContent).toContain('Reading');
    run = applyEvent(run, ev('tool_finished', {call_id: 'c1', name: 'nerp_run_report', ok: true, duration_ms: 3, summary: '3 rows'}));
    run = applyEvent(run, ev('tool_started', {call_id: 'c2', name: 'wizard_render_visual', label: 'Prepared a bar: Spend', category: 'present'}));
    view.rerender(<SystemsContext.Provider value={[{id: 'nerp', name: 'NERP', kind: 'reports'}]}>{card(run)}</SystemsContext.Provider>);
    expect(screen.getByTestId('wizard-sprite').dataset.animation).toBe('chart');
    run = applyEvent(run, ev('tool_finished', {call_id: 'c2', name: 'wizard_render_visual', ok: true, duration_ms: 3, summary: 'bar'}));
    run = applyEvent(run, ev('text_delta', {text: 'NERP shows'}));
    view.rerender(<SystemsContext.Provider value={[{id: 'nerp', name: 'NERP', kind: 'reports'}]}>{card(run)}</SystemsContext.Provider>);
    act(() => { vi.advanceTimersByTime(2_500); });
    expect(screen.getByTestId('wizard-sprite').dataset.animation).toBe('write');
    run = applyEvent(run, ev('run_finished', {status: 'succeeded', report_id: 'r', answer: 'Done.', data_mode: 'SYNTHETIC', check_status: 'NOT_CHECKED', warnings: []}));
    view.rerender(<SystemsContext.Provider value={[{id: 'nerp', name: 'NERP', kind: 'reports'}]}>{card(run)}</SystemsContext.Provider>);
    expect(screen.getByTestId('wizard-sprite').dataset.animation).toBe('success');
    expect(screen.getByTestId('stage-orb').dataset.state).toBe('success');
    expect(screen.getByTestId('wizard-verb').textContent).toBe('Answer ready');
    act(() => { vi.advanceTimersByTime(2_500); });
    expect(screen.queryByTestId('stage')).toBeNull();
    expect(screen.getByTestId('journey')).toBeTruthy();
  });

  it('has no finale for a run loaded already finished', () => {
    let seq = 0;
    const ev = (type: string, payload: Record<string, unknown>): RunEvent => ({seq: ++seq, type, ts: '2026-10-20T08:00:00Z', payload});
    let run = applyEvent(emptyRun('run_3', 'cnv_1', 'q'), ev('run_started', {runtime: 'replay', runtime_label: 'x', model: 'm'}));
    run = applyEvent(run, ev('tool_started', {call_id: 'c1', name: 'nerp_run_report', label: 'Read NERP', category: 'source'}));
    run = applyEvent(run, ev('tool_finished', {call_id: 'c1', name: 'nerp_run_report', ok: true, duration_ms: 3, summary: '3 rows'}));
    run = applyEvent(run, ev('run_finished', {status: 'succeeded', report_id: 'r', answer: 'Done.', data_mode: 'SYNTHETIC', check_status: 'NOT_CHECKED', warnings: []}));
    render(card(run));
    expect(screen.queryByTestId('stage')).toBeNull();
    fireEvent.click(screen.getByTestId('show-journey'));
    expect(screen.getByTestId('wizard-sprite').dataset.animation).toBe('idle');
  });

  it('puts the modules in two arcs around the wizard, clear of his circle', () => {
    for (const count of [1, 2, 5, 6, 8]) {
      const l = layout(720, count);
      expect(l.mode).toBe('orbit');
      expect(l.nodes).toHaveLength(count);
      for (const node of l.nodes) {
        expect(Math.hypot(node.x - l.orb.x, node.y - l.orb.y)).toBeGreaterThan(l.radius + 58);
        expect(node.y).toBeGreaterThan(30);
        expect(node.y).toBeLessThan(l.height - 30);
        expect(beam(l, node)).toMatch(/^M [\d.]+ [\d.]+ Q [\d.]+ [\d.]+ [\d.]+ [\d.]+$/);
      }
      for (let i = 0; i < count; i++) for (let j = i + 1; j < count; j++)
        expect(Math.hypot(l.nodes[i].x - l.nodes[j].x, l.nodes[i].y - l.nodes[j].y)).toBeGreaterThan(100);
    }
    expect(layout(420, 6).mode).toBe('row');
  });
});
