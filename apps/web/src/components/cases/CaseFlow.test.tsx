import {cleanup, fireEvent, render, screen, within} from '@testing-library/react';
import {afterEach, describe, expect, it} from 'vitest';
import type {CaseTurn} from '@/cases';
import {TooltipProvider} from '../ui/menu';
import {CaseFlow} from './CaseFlow';

afterEach(cleanup);

const turn = (n: number, prompt: string, answer: string): CaseTurn => ({n, kind: 'ask', prompt, asked_at: '2026-10-30T10:00:00Z', answer,
  data_mode: 'SYNTHETIC', check: {status: 'NOT_CHECKED', summary: null}, visuals: [],
  sources: [{id: 'E1', system_name: 'NERP', report_name: 'Marketing spend', data_mode: 'SYNTHETIC'}],
  steps: [{label: 'NERP marketing spend', summary: '6 rows', ok: true, evidence: 'E1'}]});

const SQL = 'SELECT market, sum(spend_usd) AS spend\nFROM reporting.marketing_spend_mv\nGROUP BY 1';
const queried = (): CaseTurn => ({...turn(1, 'Spend by market?', 'Egypt spent most [E1]; GSCM shows the sell-out [E2].'),
  sources: [{id: 'E1', system_name: 'AI Team Database', report_name: 'SQL query on meto_db', data_mode: 'LIVE', total_rows: 4,
             query: {kind: 'sql', text: SQL, database: 'meto_db'}},
            {id: 'E2', system_name: 'GSCM', report_name: 'Daily sell-out', data_mode: 'LIVE',
             query: {kind: 'portal', steps: [{action: 'request', method: 'POST', url: '/gscm30/sellout/list.do', body: 'SSV:utf-8'},
                                             {action: 'evaluate', script: 'return W.nexacro.readGrid(P.grid);'}]}},
            {id: 'E3', system_name: 'Attached files', report_name: 'plan.xlsx', data_mode: 'USER_PROVIDED'}],
  steps: [{label: 'Queried the AI Team Database', summary: '4 rows', ok: true, evidence: 'E1'}]});

describe('a case', () => {
  it('shows each prompt and its answer window, alternating sides, with a drop between them', () => {
    render(<TooltipProvider><CaseFlow turns={[turn(1, 'Which market gave the best return?', 'Egypt [E1].'),
      turn(2, 'Why is Saudi Arabia not first?', 'Coverage differs.'), turn(3, 'And Morocco?', 'Spend is missing.')]} /></TooltipProvider>);
    expect(screen.getAllByTestId('case-prompt').map(p => p.textContent)).toEqual([
      expect.stringContaining('Which market gave the best return?'), expect.stringContaining('Why is Saudi Arabia not first?'),
      expect.stringContaining('And Morocco?')]);
    expect(screen.getAllByTestId('case-answer')).toHaveLength(3);
    expect(screen.getAllByTestId('case-row').map(r => r.dataset.reversed)).toEqual(['false', 'true', 'false']);
    expect(screen.getAllByTestId('case-drop').map(d => d.dataset.side)).toEqual(['right', 'left']);
    expect(screen.getAllByTestId('case-sources')[0].textContent).toContain('NERP · Marketing spend');
    expect(screen.getAllByText(/What Wizard did \(1 step\)/)).toHaveLength(3);
  });

  it('keeps a long prompt and a long answer in boxes that scroll, reachable by keyboard', () => {
    const {container} = render(<TooltipProvider><CaseFlow turns={[turn(1, 'A long question. '.repeat(200), 'A long answer. '.repeat(800))]} /></TooltipProvider>);
    const view = within(container);
    for (const box of [view.getByTestId('case-prompt-text'), view.getByTestId('case-answer-body')]) {
      expect(box.className).toContain('overflow-y-auto');
      expect(box.className).toMatch(/max-h-/);
      expect(box.tabIndex).toBe(0);
    }
  });

  it('opens the query behind a source from its chip in the answer, its source chip or a step', () => {
    render(<TooltipProvider><CaseFlow turns={[queried()]} /></TooltipProvider>);
    fireEvent.click(screen.getByRole('button', {name: 'Show evidence E1'}));
    expect(screen.getByTestId('case-query-text').textContent).toBe(SQL);
    expect(screen.getByText('SQL on meto_db')).toBeTruthy();
    expect(screen.getByText(/4 rows read \(not published\)/)).toBeTruthy();
    fireEvent.click(screen.getByRole('button', {name: 'Close'}));
    fireEvent.click(screen.getAllByTestId('case-source')[1]);
    const steps = screen.getByTestId('case-query-text').textContent ?? '';
    expect(steps).toContain('1. request POST /gscm30/sellout/list.do');
    expect(steps).toContain('W.nexacro.readGrid');
    fireEvent.click(screen.getByRole('button', {name: 'Close'}));
    fireEvent.click(screen.getByTestId('case-step-query'));
    expect(screen.getByTestId('case-query-text').textContent).toBe(SQL);
    fireEvent.click(screen.getByRole('button', {name: 'Close'}));
    fireEvent.click(screen.getAllByTestId('case-source')[2]);
    expect(screen.getByTestId('case-query-missing').textContent).toContain('stay on their PC');
  });
});
