import {afterEach, describe, expect, it, vi} from 'vitest';
import {act, cleanup, fireEvent, render, screen, waitFor} from '@testing-library/react';
import {RunCard} from './RunCard';
import {beam, layout, SystemsContext} from './SystemsStage';
import {TooltipProvider} from './ui/menu';
import {api, ApiError} from '@/api';
import {applyEvent, emptyRun} from '@/runState';
import type {RunEvent, RunView, Schedule} from '@/types';
import {brand, SystemLogo} from './SystemLogo';

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

describe('show sources', () => {
  it('counts the tables, reports and files read, not each query', () => {
    let seq = 0;
    const ev = (type: string, payload: Record<string, unknown>): RunEvent => ({seq: ++seq, type, ts: '2026-10-07T07:25:00Z', payload});
    let run = applyEvent(emptyRun('run_5', 'cnv_1', 'Sell-in by market'), ev('run_started', {runtime: 'code-assist', runtime_label: 'x', model: 'm'}));
    const summary = (id: string, sql: string | null, extra: Record<string, unknown> = {}) => ({id, system: 'postgresql', system_name: 'PostgreSQL',
      report_id: `sql-${id}`, report_name: 'SQL query on meto_db', data_mode: 'LIVE', as_of: null, total_rows: 3, truncated: false, warnings: [],
      access_note: null, sql, ...extra});
    for (let i = 1; i <= 14; i++) {
      run = applyEvent(run, ev('tool_started', {call_id: `c${i}`, name: 'wizard_query_postgresql', label: 'Queried', category: 'source'}));
      run = applyEvent(run, ev('tool_finished', {call_id: `c${i}`, name: 'wizard_query_postgresql', ok: true, duration_ms: 5, summary: '3 rows',
        evidence: summary(`E${i}`, `SELECT * FROM bi_reporting.sell_in_amt_mv WHERE week = ${i}`)}));
    }
    run = applyEvent(run, ev('tool_started', {call_id: 'g1', name: 'gscm_run_report', label: 'Read GSCM', category: 'source'}));
    run = applyEvent(run, ev('tool_finished', {call_id: 'g1', name: 'gscm_run_report', ok: true, duration_ms: 5, summary: '3 rows',
      evidence: summary('E15', null, {system: 'gscm', system_name: 'GSCM', report_id: 'gscm-sell-in', report_name: 'Sell in', folder_path: ['Biz Plan']})}));
    render(card(run));
    expect(screen.getByTestId('show-sources').textContent).toBe('Show sources (2)');
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

  it('keeps Wizard at work while Wizard waits for Gemini: no "Gemini is busy" (owner, 23 Oct)', () => {
    let seq = 0;
    const ev = (type: string, payload: Record<string, unknown>): RunEvent => ({seq: ++seq, type, ts: '2026-10-20T08:00:00Z', payload});
    let run = applyEvent(emptyRun('run_4', 'cnv_1', 'q'), ev('run_started', {runtime: 'code-assist', runtime_label: 'x', model: 'gemini-3.1-pro'}));
    run = applyEvent(run, ev('tool_started', {call_id: 'c1', name: 'nerp_run_report', label: 'Read NERP', category: 'source'}));
    run = applyEvent(run, ev('tool_finished', {call_id: 'c1', name: 'nerp_run_report', ok: true, duration_ms: 3, summary: '3 rows'}));
    run = applyEvent(run, ev('model_wait', {seconds: 10, reason: 'capacity', models: ['gemini-3.8-flash', 'gemini-3.1-pro'], round: 2}));
    render(card(run));
    expect(screen.queryByTestId('stage-waiting')).toBeNull();
    expect(screen.getByTestId('systems-stage').textContent).not.toMatch(/busy|waiting/i);
    expect(run.timeline.map(t => t.kind)).toEqual(['tool']);
  });

  it('still says when a used-up quota moved the answer to the other model', () => {
    let seq = 0;
    const ev = (type: string, payload: Record<string, unknown>): RunEvent => ({seq: ++seq, type, ts: '2026-10-20T08:00:00Z', payload});
    let run = applyEvent(emptyRun('run_4', 'cnv_1', 'q'), ev('run_started', {runtime: 'code-assist', runtime_label: 'x', model: 'gemini-3.8-flash'}));
    run = applyEvent(run, ev('status', {message: 'Your Gemini quota for gemini-3.8-flash is used up. Wizard continues with gemini-3.1-pro.'}));
    render(card(run));
    expect(screen.getByTestId('stage-waiting').textContent).toContain('quota for gemini-3.8-flash is used up');
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
    for (const [width, count] of [[380, 4], [460, 6], [540, 3]]) {
      const l = layout(width, count);
      expect(l.mode).toBe('row');
      for (let i = 0; i < count; i++) for (let j = i + 1; j < count; j++) {
        const [a, b] = [l.nodes[i], l.nodes[j]];
        expect(Math.abs(a.y - b.y) >= 100 || Math.abs(a.x - b.x) >= l.nodeWidth).toBe(true);
      }
    }
  });
});

const SCHEDULE: Schedule = {
  id: 'sch_1', label: 'R1', run_id: 'run_1', status: 'proposed', title: 'Weekly sell-out by market',
  sql: 'SELECT market, sum(units) FROM bi_reporting.sell_out GROUP BY 1', database: null,
  recipients: ['rafael@corp.test', 'cfo@corp.test'], frequency: 'weekly', time: '08:00', days: ['monday'], day_of_month: null,
  file_format: 'xlsx', subject: null, schedule_text: 'Every Monday at 08:00 (Dubai time)', evidence_id: 'E2',
  metronome_user: 'Wizard', requested_by: {name: 'Rafael'}, created_at: '2026-10-20T09:00:00Z',
  preview: {columns: ['market', 'units'], rows: [['EG', 12]], rows_in_test: 1, more: false}, flow: null, error: null,
};

function answered(extra: Partial<RunView> = {}): RunView {
  return {...emptyRun('run_1', 'cnv_1', 'Sell-out by market last week'), status: 'succeeded', answer: 'EG led [E1].',
    evidence: [{id: 'E1', system: 'postgresql', report_id: 'sql-1', report_name: 'SQL', data_mode: 'LIVE', as_of: null,
      total_rows: 3, truncated: false, warnings: [], access_note: null}], ...extra};
}

function withHandlers(run: RunView, props: Partial<Parameters<typeof RunCard>[0]> = {}) {
  return (
    <TooltipProvider>
      <RunCard run={run} onEvidence={noop} onCheck={noop} onCancel={noop} onRetry={noop} onFeedback={noop} onEmail={noop}
        busy={false} {...props} />
    </TooltipProvider>
  );
}

describe('recurring emails', () => {
  it('offers Make recurring under a database answer only when Metronome is connected', () => {
    const onRecurring = vi.fn();
    const run = answered();
    const {rerender} = render(withHandlers(run, {onRecurring, canRecur: true}));
    fireEvent.keyDown(screen.getByTestId('make-recurring'), {key: 'Enter'});
    expect(screen.getByRole('menu').textContent).toContain('Emailed to you at 08:00 (Dubai), Excel attached');
    fireEvent.click(screen.getByTestId('recurring-weekly'));
    expect(onRecurring).toHaveBeenCalledWith(run, 'weekly');
    fireEvent.keyDown(screen.getByTestId('make-recurring'), {key: 'Enter'});
    fireEvent.click(screen.getByTestId('recurring-other'));
    expect(onRecurring).toHaveBeenLastCalledWith(run, null);
    rerender(withHandlers(answered(), {onRecurring, canRecur: false}));
    expect(screen.queryByTestId('make-recurring')).toBeNull();
    rerender(withHandlers(answered({evidence: []}), {onRecurring, canRecur: true}));
    expect(screen.queryByTestId('make-recurring')).toBeNull();
    rerender(withHandlers(answered({schedules: [SCHEDULE]}), {onRecurring, canRecur: true}));
    expect(screen.queryByTestId('make-recurring')).toBeNull();
  });

  it('shows the proposed schedule and leaves creating it to the person', () => {
    const onSchedule = vi.fn();
    let seq = 0;
    const run = applyEvent(answered(), {seq: ++seq, type: 'schedule_proposed', ts: '2026-10-20T09:00:00Z', payload: {schedule: SCHEDULE}});
    render(withHandlers(run, {onSchedule}));
    const shown = screen.getByTestId('recurring-card');
    expect(shown.dataset.status).toBe('proposed');
    expect(shown.textContent).toContain('Every Monday at 08:00 (Dubai time)');
    expect(shown.textContent).toContain('rafael@corp.test, cfo@corp.test');
    expect(shown.textContent).toContain('Weekly sell-out by market <date>.xlsx (Excel, every row)');
    expect(shown.textContent).toContain('Metronome user Wizard');
    expect(shown.textContent).toContain('Nothing is scheduled until you create it.');
    expect(screen.getByTestId('recurring-sql').textContent).toContain(SCHEDULE.sql!);
    expect(screen.queryByTestId('email-preview')).toBeNull();
    fireEvent.click(screen.getByTestId('recurring-create'));
    expect(onSchedule).toHaveBeenCalledWith(run, SCHEDULE, 'create');
    fireEvent.click(screen.getByTestId('recurring-dismiss'));
    expect(onSchedule).toHaveBeenLastCalledWith(run, SCHEDULE, 'dismiss');
  });

  it('says where the Flow is once created, and never offers to resend an uncertain one', () => {
    const created: Schedule = {...SCHEDULE, status: 'created', flow: {id: 41, name: 'Wizard · Weekly sell-out by market · for Rafael · a1',
      owner: 'Wizard', enabled: true, next_run_at: '2026-10-26T04:00:00Z', url: 'http://metronome.corp:8000/'}};
    const {rerender} = render(withHandlers(answered({schedules: [created]})));
    expect(screen.getByTestId('recurring-status').textContent).toBe('Scheduled');
    expect(screen.getByTestId('recurring-actions').textContent).toContain('Created in Metronome as Flow #41');
    expect(screen.getByTestId('recurring-actions').textContent).toContain('owned by Wizard');
    expect(screen.getByTestId('recurring-actions').textContent).toContain('Find it under Recurring in the sidebar.');
    expect(screen.queryByTestId('recurring-create')).toBeNull();
    rerender(withHandlers(answered({schedules: [{...SCHEDULE, status: 'uncertain', error: 'Metronome did not answer.'}]})));
    expect(screen.getByRole('alert').textContent).toContain('Metronome did not answer.');
    expect(screen.queryByTestId('recurring-create')).toBeNull();
    rerender(withHandlers(answered({schedules: [{...SCHEDULE, status: 'failed', error: 'A flow with that name already exists.'}]})));
    expect(screen.getByTestId('recurring-create').textContent).toBe('Try again');
  });
});

describe('system logos', () => {
  it('draws Metronome with its own logo and Orchestra with its wave, by id or by name', () => {
    expect(brand('metronome').color).toBe('#0d7377');
    expect(brand('orchestra')).toMatchObject({color: '#0125c4', deep: '#561ad4'});
    expect(brand('orch', 'Orchestra')).toBe(brand('orchestra'));
    expect(brand('wizard-ish', 'Wizard').icon).toBeNull();
    const {container} = render(<><SystemLogo id="metronome" /><SystemLogo id="orchestra" /></>);
    const [metronome, orchestra] = Array.from(container.querySelectorAll('svg'));
    expect(metronome.querySelector('circle')).not.toBeNull();
    expect(orchestra.querySelector('path')!.getAttribute('d')).toContain('M11.1 4.1v14.6');
  });
});

describe('error details', () => {
  let seq = 0;
  const ev = (type: string, payload: Record<string, unknown>): RunEvent => ({seq: ++seq, type, ts: '2026-10-23T08:00:00Z', payload});
  const failed = (payload: Record<string, unknown>) => applyEvent(
    applyEvent(emptyRun('run_9', 'cnv_1', 'Analyze S26 launch'), ev('run_started', {runtime: 'code-assist', runtime_label: 'Gemini Code Assist API · m', model: 'gemini-3.8-flash'})),
    ev('run_failed', {code: 'empty_answer', status: 'failed', message: 'Gemini sent back an empty turn 4 times in a row.', ...payload}));

  it('shows exactly why an answer failed, as the server recorded it, and copies it with the question', async () => {
    const writeText = vi.fn(() => Promise.resolve());
    Object.assign(navigator, {clipboard: {writeText}});
    render(card(failed({details: {'Error code': 'empty_answer', "Google's finish reason": 'Gemini wrote a tool call that could not be read (MALFORMED_FUNCTION_CALL)',
      'Tries': 'gemini-3.8-flash ×2, gemini-3.1-pro-preview ×2'}})));
    expect(screen.getByTestId('run-error').textContent).toContain('Gemini sent back an empty turn 4 times in a row.');
    expect(screen.queryByTestId('error-details-panel')).toBeNull();
    fireEvent.click(screen.getByTestId('error-details'));
    const panel = screen.getByTestId('error-details-panel');
    expect(panel.textContent).toContain("Google's finish reason");
    expect(panel.textContent).toContain('(MALFORMED_FUNCTION_CALL)');
    expect(panel.textContent).toContain('gemini-3.8-flash ×2, gemini-3.1-pro-preview ×2');
    await act(async () => { fireEvent.click(screen.getByRole('button', {name: /Copy details/})); });
    expect(writeText).toHaveBeenCalledWith(expect.stringContaining('Question: Analyze S26 launch\nWizard could not finish this answer: Gemini sent back'));
    expect(writeText).toHaveBeenCalledWith(expect.stringContaining("Google's finish reason: Gemini wrote a tool call that could not be read"));
    expect(screen.getByRole('button', {name: /Copied/})).toBeTruthy();
  });

  it('still says what it knows for a run that failed before details were recorded', () => {
    render(card(failed({})));
    fireEvent.click(screen.getByTestId('error-details'));
    const panel = screen.getByTestId('error-details-panel').textContent ?? '';
    expect(panel).toContain('Error code');
    expect(panel).toContain('empty_answer');
    expect(panel).toContain('gemini-3.8-flash');
    expect(panel).toContain('run_9');
  });

  it('is not offered for a cancelled run', () => {
    render(card(failed({status: 'cancelled', code: 'cancelled', message: 'The run was cancelled.'})));
    expect(screen.queryByTestId('error-details')).toBeNull();
  });
});

describe('files Wizard made', () => {
  afterEach(() => { vi.restoreAllMocks(); });

  function madeRun() {
    let run = emptyRun('run_e', 'cnv_e', 'Delete the closed rows and give me the file');
    run = applyEvent(run, {seq: 1, type: 'file_made', ts: '2026-10-23T12:00:00Z', payload: {attachment: {
      id: 'att_9', label: 'F2', filename: 'Sales (edited).xlsx', kind: 'spreadsheet', bytes: 9000, origin: 'edited', status: 'ok',
      method: 'openpyxl', chars: 120, note: 'Edited copy of F1 (Sales.xlsx): Sales: deleted 2 row(s)', parts: 1,
      created_at: '2026-10-23T12:00:00Z', run_id: 'run_e'}}});
    return run;
  }

  it('on this PC, Download has Wizard save the copy in Downloads (not the browser), then Open opens it', async () => {
    const save = vi.spyOn(api, 'saveFile').mockResolvedValue({saved: {filename: 'Sales (edited) (1).xlsx',
      folder: 'C:\\Users\\exec\\Downloads', method: 'excel', warnings: []}});
    const opened = vi.spyOn(api, 'openFile').mockResolvedValue({ok: true});
    const clicked = vi.spyOn(HTMLAnchorElement.prototype, 'click');
    render(card(madeRun()));
    expect(screen.getByTestId('made-files').textContent).toContain('deleted 2 row(s)');
    fireEvent.click(screen.getByTestId('made-file-download'));
    await waitFor(() => expect(screen.getByTestId('made-file-saved').textContent)
      .toBe('Saved in C:\\Users\\exec\\Downloads as Sales (edited) (1).xlsx.'));
    expect(save).toHaveBeenCalledWith('att_9');
    expect(clicked).not.toHaveBeenCalled();
    fireEvent.click(screen.getByTestId('made-file-open'));
    await waitFor(() => expect(opened).toHaveBeenCalledWith('att_9'));
  });

  it('where Wizard runs elsewhere, the browser downloads the copy', async () => {
    vi.spyOn(api, 'saveFile').mockRejectedValue(new ApiError('Wizard saves files only on your own PC.', 409, 'not_on_this_pc'));
    const links: HTMLAnchorElement[] = [];
    vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(function (this: HTMLAnchorElement) { links.push(this); });
    render(card(madeRun()));
    fireEvent.click(screen.getByTestId('made-file-download'));
    await waitFor(() => expect(links).toHaveLength(1));
    expect(links[0].getAttribute('href')).toBe('/api/v1/attachments/att_9/file');
    expect(links[0].getAttribute('download')).toBe('Sales (edited).xlsx');
    expect(screen.queryByTestId('made-file-error')).toBeNull();
  });

  it('says why the copy was not saved', async () => {
    vi.spyOn(api, 'saveFile').mockRejectedValue(new ApiError('Sales (edited).xlsx was not saved: Access is denied.', 422));
    render(card(madeRun()));
    fireEvent.click(screen.getByTestId('made-file-download'));
    await waitFor(() => expect(screen.getByTestId('made-file-error').textContent).toContain('Access is denied'));
    expect((screen.getByTestId('made-file-download') as HTMLButtonElement).disabled).toBe(false);
  });
});
