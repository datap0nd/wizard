import {cleanup, fireEvent, render, screen, waitFor, within} from '@testing-library/react';
import {afterEach, describe, expect, it, vi} from 'vitest';
import type {CaseTurn} from '@/cases';
import type {Deck, DesignTokens} from '@/types';
import {TooltipProvider} from '../ui/menu';
import {CaseFlow} from './CaseFlow';

afterEach(() => { cleanup(); vi.restoreAllMocks(); });

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
    expect(screen.getAllByTestId('case-behind-toggle').map(t => t.textContent)).toEqual(Array(3).fill('How Wizard got this answer (1 source, 1 step)'));
  });

  it('folds the sources and steps behind each answer away until opened', () => {
    render(<TooltipProvider><CaseFlow turns={[queried()]} /></TooltipProvider>);
    const behind = screen.getByTestId('case-behind') as HTMLDetailsElement;
    expect(behind.open).toBe(false);
    expect(screen.getByTestId('case-behind-toggle').textContent).toBe('How Wizard got this answer (3 sources, 1 step)');
    expect(within(behind).getByTestId('case-steps').textContent).toContain('Queried the AI Team Database');
    fireEvent.click(screen.getByTestId('case-behind-toggle'));
    expect(behind.open).toBe(true);
  });

  it('opens the fold when the answer cites a source the case does not list', () => {
    const turnWithGap = {...queried(), answer: 'An older figure [E9].'};
    render(<TooltipProvider><CaseFlow turns={[turnWithGap]} /></TooltipProvider>);
    fireEvent.click(screen.getByRole('button', {name: 'Show evidence E9'}));
    expect((screen.getByTestId('case-behind') as HTMLDetailsElement).open).toBe(true);
    expect(screen.queryByTestId('case-query')).toBeNull();
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

  it('shows the PowerPoint an answer made and downloads it from the page', async () => {
    const tokens: DesignTokens = {
      name: 'Company look', slide: {width: 13.333, height: 7.5},
      fonts: {title: 'Arial', subtitle: 'Arial', body: 'Arial', labels: 'Arial', east_asian: 'Malgun Gothic'},
      colors: {brand: '#1428A0', title: '#000000', text: '#000000', secondary: '#404040', muted: '#7F7F7F', background: '#FFFFFF',
        card: '#E7ECF0', line: '#D9D9D9', good_fill: '#E2EFDA', good_text: '#375623', bad_fill: '#FFF2CC', bad_text: '#7F6000',
        positive: '#1F7A3A', negative: '#C00000', series: ['#1428A0']},
      sizes: {cover_title: 44, cover_subtitle: 20, cover_meta: 16, title: 32, subtitle: 14, section_title: 36, agenda: 22, heading: 12,
        body: 10, kpi: 28, table: 10, chart_label: 8, unit: 8, footnote: 6.5},
      cover: {background: 'brand'}, footer: {text: '', page_numbers: true}, rules: {max_highlights: 4, max_points: 6}};
    const deck: Deck = {id: 'D2', run_id: '', title: 'Q3 review', storyline: 'Flagship carried Q3.', audience: null, revises: 'D1',
      family: 'D1', version: 2, created_at: '', evidence_ids: [], data_mode: 'SYNTHETIC', visuals: {}, sources: {},
      design: {tokens, source: 'knowledge', note: null, status: null, problems: [], about: ''},
      slides: [{kind: 'cover', title: 'Q3 review'}, {kind: 'text', title: 'Flagship carried Q3', points: ['**Flagship:** +18%']}]};
    const made = vi.spyOn(URL, 'createObjectURL').mockReturnValue('blob:deck');
    const clicked = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => undefined);
    render(<TooltipProvider><CaseFlow turns={[{...turn(1, 'Make it a PowerPoint', 'Here it is.\n\n[D2]\n\nIt argues Q3.'), decks: [deck]}]} /></TooltipProvider>);
    const shown = within(screen.getByTestId('case-decks'));
    expect(shown.getByTestId('deck-title').textContent).toBe('Q3 review');
    expect(shown.getAllByTestId('slide').length).toBeGreaterThan(1);
    expect(shown.getByTestId('deck-hint').textContent).toContain('Shared from Wizard: download it to edit it in PowerPoint.');
    expect(shown.getByTestId('deck-hint').textContent).not.toContain('Ask for any change');
    fireEvent.click(shown.getByTestId('deck-download'));
    await waitFor(() => expect(shown.getByTestId('deck-saved').textContent).toBe('Downloaded Q3 review (v2).pptx.'), {timeout: 10_000});
    expect(made).toHaveBeenCalledWith(expect.any(Blob));
    expect(clicked).toHaveBeenCalled();
  });

  it('shows no presentation for an answer without one, or a case published before they were shared', () => {
    render(<TooltipProvider><CaseFlow turns={[turn(1, 'Spend?', 'Egypt [E1].')]} /></TooltipProvider>);
    expect(screen.queryByTestId('case-decks')).toBeNull();
  });
});
