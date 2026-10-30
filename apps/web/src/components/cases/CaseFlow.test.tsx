import {render, screen} from '@testing-library/react';
import {describe, expect, it} from 'vitest';
import type {CaseTurn} from '@/cases';
import {TooltipProvider} from '../ui/menu';
import {CaseFlow} from './CaseFlow';

const turn = (n: number, prompt: string, answer: string): CaseTurn => ({n, kind: 'ask', prompt, asked_at: '2026-10-30T10:00:00Z', answer,
  data_mode: 'SYNTHETIC', check: {status: 'NOT_CHECKED', summary: null}, visuals: [],
  sources: [{id: 'E1', system_name: 'NERP', report_name: 'Marketing spend', data_mode: 'SYNTHETIC'}],
  steps: [{label: 'NERP marketing spend', summary: '6 rows', ok: true, evidence: 'E1'}]});

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
});
