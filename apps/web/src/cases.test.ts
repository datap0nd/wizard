import {describe, expect, it} from 'vitest';
import {chosenTurns, decksLeftOut, defaultPicks, filterCases, flowRows, systemsOf, type CaseEntry, type CaseTurn, type PublishedCase} from './cases';
import type {Deck} from './types';

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

describe('Share as case', () => {
  const at = (t: CaseTurn, asked_at: string, decks?: Deck[]): CaseTurn => ({...t, asked_at, decks});
  const deck = {id: 'D1', title: 'Q3 review', slides: []} as unknown as Deck;
  const published: PublishedCase = {id: 'c1', title: 'T', takeaway: '', runs: ['r1'], published_at: '2026-11-13T10:00:00Z', url: null};

  it('ticks every answer of a chat not shared yet', () => {
    expect([...defaultPicks([turn(1, 'r1'), turn(2, 'r2')], null)]).toEqual(['r1', 'r2']);
  });

  it('ticks what was shared and every answer asked since, so a PowerPoint made later goes into the update', () => {
    const turns = [at(turn(1, 'r1'), '2026-11-13T09:00:00Z'), at(turn(2, 'r2'), '2026-11-13T09:30:00Z'),
      at(turn(3, 'r3'), '2026-11-13T11:00:00Z'), at(turn(4, 'r4'), '2026-11-13T11:05:00Z', [deck])];
    const picked = defaultPicks(turns, published);
    expect([...picked]).toEqual(['r1', 'r3', 'r4']);  // r2 was left out before, and stays out
    expect(decksLeftOut(turns, picked)).toEqual([]);
    expect(decksLeftOut(turns, new Set(['r1']))).toEqual(['Q3 review']);
  });
});
