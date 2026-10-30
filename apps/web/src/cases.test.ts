import {describe, expect, it} from 'vitest';
import {chosenTurns, filterCases, flowRows, systemsOf, type CaseEntry, type CaseTurn} from './cases';

const entry = (id: string, title: string, systems: string[], extra: Partial<CaseEntry> = {}): CaseEntry => ({id, title, takeaway: '',
  author: null, published_at: '2026-10-30T10:00:00Z', updated_at: '2026-10-30T10:00:00Z', prompts: 1, systems, data_modes: ['SYNTHETIC'],
  first_prompt: '', ...extra});
const turn = (n: number, runId: string): CaseTurn => ({n, kind: 'ask', prompt: `Prompt ${n}`, asked_at: '2026-10-30T10:00:00Z', answer: 'A',
  data_mode: 'SYNTHETIC', check: {status: 'NOT_CHECKED', summary: null}, visuals: [], sources: [], steps: [], run_id: runId});

describe('the snake', () => {
  it('runs prompt → answer, drops on the side the answer ended, then runs ← the other way', () => {
    expect(flowRows(['a', 'b', 'c', 'd']).map(r => [r.turn, r.reversed, r.drop])).toEqual([
      ['a', false, 'right'], ['b', true, 'left'], ['c', false, 'right'], ['d', true, null]]);
    expect(flowRows(['only'])).toEqual([{turn: 'only', reversed: false, drop: null}]);
  });
});

describe('the gallery', () => {
  const cases = [entry('c1', 'Marketing return by market', ['NERP', 'GSCM'], {takeaway: 'Egypt leads'}),
    entry('c2', 'Switchers from Apple', ['ASAP'], {first_prompt: 'Where are we winning switchers?'})];
  it('finds a case by every word in its title, takeaway, first prompt or systems', () => {
    expect(filterCases(cases, 'egypt market', null).map(c => c.id)).toEqual(['c1']);
    expect(filterCases(cases, 'winning', null).map(c => c.id)).toEqual(['c2']);
    expect(filterCases(cases, '', 'ASAP').map(c => c.id)).toEqual(['c2']);
    expect(filterCases(cases, 'egypt', 'ASAP')).toEqual([]);
    expect(systemsOf(cases)).toEqual(['ASAP', 'GSCM', 'NERP']);
  });
  it('previews only the answers chosen to share, numbered again', () => {
    const turns = [turn(1, 'r1'), turn(2, 'r2'), turn(3, 'r3')];
    expect(chosenTurns(turns, ['r1', 'r3']).map(t => [t.n, t.run_id])).toEqual([[1, 'r1'], [2, 'r3']]);
    expect(chosenTurns(turns, null)).toHaveLength(3);
  });
});
