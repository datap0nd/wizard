import {afterEach, describe, expect, it, vi} from 'vitest';
import {cleanup, fireEvent, render, screen, waitFor} from '@testing-library/react';
import {RunCard} from './RunCard';
import {Composer} from './Composer';
import {SteerContext, type SteerActions} from './Steering';
import {SystemsContext} from './SystemsStage';
import {TooltipProvider} from './ui/menu';
import {applyEvent, emptyRun} from '@/runState';
import {choiceLabel, choosable, conversationChoice, onlyNames, toggleSystem, withFiles} from '@/systems';
import type {RunEvent, RunView, SystemInfo} from '@/types';

afterEach(cleanup);

const SYSTEMS: SystemInfo[] = [
  {id: 'postgresql', name: 'AI Team Database', kind: 'database'}, {id: 'gscm', name: 'GSCM', kind: 'portal'},
  {id: 'knowledge', name: 'Knowledge base', kind: 'knowledge'}, {id: 'attachment', name: 'Attached files', kind: 'files'},
  {id: 'metronome', name: 'Metronome', kind: 'schedules'},
];
const AVAILABLE = choosable(SYSTEMS);
const SQL = 'SELECT market, SUM(units) FROM sales.raw_sellout GROUP BY 1';

let seq = 0;
const ev = (type: string, payload: Record<string, unknown>): RunEvent => ({seq: ++seq, type, ts: '2026-10-30T08:00:00Z', payload});

function queried(status: 'running' | 'succeeded' = 'running'): RunView {
  seq = 0;
  let run = applyEvent(emptyRun('run_1', 'cnv_1', 'Units by market?'), ev('run_started', {runtime: 'code-assist', runtime_label: 'x', model: 'm'}));
  run = applyEvent(run, ev('tool_started', {call_id: 'c1', name: 'wizard_query_postgresql', label: 'Queried the AI Team Database',
    category: 'source', arguments: {sql: SQL}}));
  run = applyEvent(run, ev('tool_finished', {call_id: 'c1', name: 'wizard_query_postgresql', ok: true, duration_ms: 5, summary: '12 rows'}));
  if (status === 'succeeded') run = applyEvent(run, ev('run_finished', {status: 'succeeded', report_id: 'r', answer: 'EG leads.', data_mode: 'LIVE', check_status: 'NOT_CHECKED'}));
  return run;
}

function actions(overrides: Partial<SteerActions> = {}): SteerActions {
  return {live: true, notThis: vi.fn(async () => {}), remember: vi.fn(async () => true), turnOn: vi.fn(), ...overrides};
}

const card = (run: RunView, steer: SteerActions) => (
  <TooltipProvider><SystemsContext.Provider value={SYSTEMS}><SteerContext.Provider value={steer}>
    <RunCard run={run} onEvidence={() => {}} onCheck={() => {}} onCancel={() => {}} onRetry={() => {}} onFeedback={() => {}} onEmail={() => {}} busy={false} />
  </SteerContext.Provider></SystemsContext.Provider></TooltipProvider>
);

describe('systems picker choices', () => {
  it('starts on Auto, brings the knowledge base with the first system, and goes back to Auto when emptied', () => {
    expect(AVAILABLE.map(s => s.id)).toEqual(['postgresql', 'gscm', 'knowledge', 'attachment']);
    const first = toggleSystem(null, 'gscm', AVAILABLE);
    expect(first).toEqual(['gscm', 'knowledge']);
    expect(toggleSystem(first, 'postgresql', AVAILABLE)).toEqual(['postgresql', 'gscm', 'knowledge']);
    expect(toggleSystem(['gscm'], 'gscm', AVAILABLE)).toBeNull();
    expect(toggleSystem(null, 'knowledge', AVAILABLE)).toEqual(['knowledge']);
    expect(withFiles(['gscm'], AVAILABLE)).toEqual(['gscm', 'attachment']);
    expect(withFiles(null, AVAILABLE)).toBeNull();
    expect([choiceLabel(null, AVAILABLE), choiceLabel(['gscm'], AVAILABLE), choiceLabel(['gscm', 'knowledge'], AVAILABLE)])
      .toEqual(['Auto', 'GSCM', '2 systems']);
    expect(onlyNames(['postgresql', 'nerp'], AVAILABLE)).toEqual(['AI Team Database', 'NERP']);
  });

  it('a conversation keeps the choice its latest question left', () => {
    const asked = {...emptyRun('a', 'c', 'q'), systems: ['gscm']};
    const checked = {...emptyRun('b', 'c', 'Check my data', 'check'), systems: null};
    expect(conversationChoice([asked, checked])).toEqual(['gscm']);
    expect(conversationChoice([])).toBeNull();
  });
});

describe('run reducer: notes and systems', () => {
  it('follows a note from waiting to read, a change of systems and a request for one', () => {
    let run = queried();
    run = applyEvent(run, ev('steer', {steer: {id: 's1', text: 'use the weekly view', reason: 'table', at: 'x', state: 'waiting',
      about: {call_id: 'c1', name: 'wizard_query_postgresql', label: 'Queried the AI Team Database', detail: SQL, evidence_id: 'E1'}}}));
    expect(run.steers[0].state).toBe('waiting');
    expect(run.timeline.at(-1)).toMatchObject({kind: 'steer', label: 'Wrong table: Queried the AI Team Database · use the weekly view', state: 'running'});
    run = applyEvent(run, ev('steer_read', {steer_id: 's1'}));
    expect(run.steers[0].state).toBe('read');
    expect(run.timeline.at(-1)?.state).toBe('ok');
    run = applyEvent(run, ev('systems_changed', {systems: ['gscm', 'knowledge'], on: ['GSCM', 'Knowledge base'], off: []}));
    expect(run.systems).toEqual(['gscm', 'knowledge']);
    run = applyEvent(run, ev('system_requested', {system: 'postgresql', name: 'AI Team Database', reason: 'Units live there.'}));
    expect(run.systemRequests).toEqual([{system: 'postgresql', name: 'AI Team Database', reason: 'Units live there.'}]);
    run = applyEvent(run, ev('run_failed', {code: 'cancelled', message: 'x', status: 'cancelled'}));
    expect(run.timeline.find(t => t.kind === 'steer')?.state).toBe('ok');  // a read note stays read when the run stops
  });
});

describe('steering on the card', () => {
  it('Not this on a step sends what was wrong and what to use instead', async () => {
    const steer = actions();
    const run = queried();
    render(card(run, steer));
    fireEvent.click(screen.getByRole('button', {name: /Step by step/}));
    fireEvent.click(screen.getAllByTestId('not-this')[0]);
    expect(screen.getByText('Wizard reads this before its next step and leaves this step out.')).toBeTruthy();
    fireEvent.click(screen.getByRole('radio', {name: 'Wrong period'}));
    fireEvent.change(screen.getByLabelText('What should Wizard use instead'), {target: {value: 'use W43'}});
    fireEvent.click(screen.getByTestId('not-this-send'));
    await waitFor(() => expect(steer.notThis).toHaveBeenCalledTimes(1));
    const [sentRun, step, reason, text] = (steer.notThis as ReturnType<typeof vi.fn>).mock.calls[0];
    expect([sentRun.id, step.key, reason, text]).toEqual(['run_1', 'c1', 'period', 'use W43']);
  });

  it('after the answer, Not this asks again; without live notes it says the run stops', () => {
    render(card(queried('succeeded'), actions()));
    fireEvent.click(screen.getByRole('button', {name: /Step by step/}));
    fireEvent.click(screen.getAllByTestId('not-this')[0]);
    expect(screen.getByTestId('not-this-send').textContent).toBe('Ask again');
    cleanup();
    render(card(queried(), actions({live: false})));
    fireEvent.click(screen.getByRole('button', {name: /Step by step/}));
    fireEvent.click(screen.getAllByTestId('not-this')[0]);
    expect(screen.getByText('Wizard stops and asks again with this note.')).toBeTruthy();
  });

  it('shows the notes sent, their state, and keeps one with Remember', async () => {
    const steer = actions();
    let run = queried();
    run = applyEvent(run, ev('steer', {steer: {id: 's1', text: 'only Gulf markets', reason: null, about: null, at: 'x', state: 'waiting'}}));
    const {rerender} = render(card(run, steer));
    expect(screen.getByTestId('steer-note').dataset.state).toBe('waiting');
    expect(screen.getByText('Wizard reads it after the current step')).toBeTruthy();
    rerender(card(applyEvent(run, ev('steer_read', {steer_id: 's1'})), steer));
    expect(screen.getByText('Read by Wizard')).toBeTruthy();
    fireEvent.click(screen.getByTestId('remember'));
    expect((screen.getByLabelText('What Wizard should remember') as HTMLInputElement).value).toBe('only Gulf markets');
    fireEvent.submit(screen.getByTestId('remember-form'));
    await waitFor(() => expect(screen.getByTestId('remembered')).toBeTruthy());
    expect(steer.remember).toHaveBeenCalledWith('only Gulf markets', 'run_1');
  });

  it('names the chosen systems, dims the ones switched off, and offers a requested one', () => {
    const steer = actions();
    let run: RunView = {...queried(), systems: ['postgresql', 'knowledge']};
    run = applyEvent(run, ev('system_requested', {system: 'gscm', name: 'GSCM', reason: 'Stock lives in GSCM.'}));
    render(card(run, steer));
    expect(screen.getByTestId('only-systems').textContent).toBe('Only: AI Team Database, Knowledge base');
    const states = Object.fromEntries(screen.getAllByTestId('stage-node').map(n => [n.dataset.system, n.dataset.state]));
    expect(states.gscm).toBe('off');
    expect(states.knowledge).toBe('idle');
    expect(screen.getByTestId('turn-on-system').textContent).toBe('Switch on GSCM');
    fireEvent.click(screen.getByTestId('turn-on-system'));
    expect(steer.turnOn).toHaveBeenCalledWith(run, {system: 'gscm', name: 'GSCM', reason: 'Stock lives in GSCM.'});
    expect(screen.queryByTestId('system-request')).toBeNull();
    cleanup();
    render(card(applyEvent(run, ev('run_finished', {status: 'succeeded', report_id: 'r', answer: 'ok', data_mode: 'LIVE', check_status: 'NOT_CHECKED'})), steer));
    expect(screen.getByTestId('turn-on-system').textContent).toBe('Switch on GSCM and continue');
  });
});

describe('composer while an answer runs', () => {
  it('sends what is typed as a note to Wizard', async () => {
    const onSteer = vi.fn(async () => {});
    const onSubmit = vi.fn();
    render(<TooltipProvider><Composer busy draft="use the weekly view" onDraftChange={() => {}} onSubmit={onSubmit}
      systems={AVAILABLE} chosen={['gscm', 'knowledge']} onChoose={() => {}} steer={{live: true, onSteer}} /></TooltipProvider>);
    expect(screen.getByLabelText('A note to Wizard while it works')).toBeTruthy();
    expect(screen.getByTestId('systems-picker').textContent).toContain('2 systems');
    fireEvent.click(screen.getByTestId('send'));
    await waitFor(() => expect(onSteer).toHaveBeenCalledWith('use the weekly view'));
    expect(onSubmit).not.toHaveBeenCalled();
    expect(screen.getByText('Wizard reads your note before its next step, without starting over.')).toBeTruthy();
  });

  it('without a running answer it asks as before, on Auto', () => {
    const onSubmit = vi.fn();
    render(<TooltipProvider><Composer busy={false} draft="Units?" onDraftChange={() => {}} onSubmit={onSubmit}
      systems={AVAILABLE} chosen={null} onChoose={() => {}} steer={null} /></TooltipProvider>);
    expect(screen.getByTestId('systems-picker').dataset.choice).toBe('auto');
    fireEvent.click(screen.getByTestId('send'));
    expect(onSubmit).toHaveBeenCalledWith('Units?');
  });
});
