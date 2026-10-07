import {afterEach, describe, expect, it, vi} from 'vitest';
import {act, cleanup, render, screen} from '@testing-library/react';
import {RunCard} from './RunCard';
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
    expect(screen.getByTestId('step-timing').textContent).toBe('2:35 · 58.1 s');
  });
});
