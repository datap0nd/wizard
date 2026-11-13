import {cleanup, fireEvent, render, screen, waitFor, within} from '@testing-library/react';
import {afterEach, describe, expect, it, vi} from 'vitest';
import {prepareAnswer} from '@/citations';
import {applyEvent, emptyRun, shownDecks} from '@/runState';
import type {Deck, DesignTokens, Output, RunView} from '@/types';
import {VisualEnvContext, type VisualEnv} from '@/visualEnv';
import {Composer} from './Composer';
import {DeckCard} from './DeckCard';
import {SteerContext, StorylineQuestions, storylineReply, type SteerActions} from './Steering';
import {TooltipProvider} from './ui/menu';

afterEach(() => { cleanup(); vi.restoreAllMocks(); });

const TOKENS: DesignTokens = {
  name: 'Executive dense', slide: {width: 13.333, height: 7.5},
  fonts: {title: 'Arial', subtitle: 'Arial', body: 'Arial', labels: 'Arial', east_asian: 'Malgun Gothic'},
  colors: {brand: '#1428A0', title: '#000000', text: '#000000', secondary: '#404040', muted: '#7F7F7F', background: '#FFFFFF',
    card: '#E7ECF0', line: '#D9D9D9', good_fill: '#E2EFDA', good_text: '#375623', bad_fill: '#FFF2CC', bad_text: '#7F6000',
    positive: '#1F7A3A', negative: '#C00000', series: ['#1428A0']},
  sizes: {cover_title: 44, cover_subtitle: 20, cover_meta: 16, title: 32, subtitle: 14, section_title: 36, agenda: 22, heading: 12,
    body: 10, kpi: 28, table: 10, chart_label: 8, unit: 8, footnote: 6.5},
  cover: {background: 'brand'}, footer: {text: '', page_numbers: true}, rules: {max_highlights: 4, max_points: 6},
};

const DECK: Deck = {id: 'D2', run_id: 'r', title: 'Q3 review', storyline: 'Flagship carried Q3.', audience: null, revises: 'D1', family: 'D1',
  version: 2, created_at: '', evidence_ids: [], data_mode: 'SYNTHETIC', visuals: {}, sources: {},
  design: {tokens: TOKENS, source: 'knowledge', note: 'presentation-look', status: 'DRAFT_UNSIGNED', problems: [], about: 'The company design.'},
  slides: [{kind: 'cover', title: 'Q3 review'}, {kind: 'text', title: 'Flagship carried Q3', points: ['**Flagship:** +18%']}, {kind: 'closing', title: 'Thank you'}]};

function env(save = vi.fn(async () => ({id: 'x1', filename: 'Q3 review (v2).pptx', folder: 'Downloads'})), open = vi.fn(async () => undefined)): VisualEnv {
  return {dataMode: 'SYNTHETIC', rowsBehind: true, sources: async () => ({sources: [], rows: []}), save, open};
}

describe('a presentation under its answer', () => {
  it('shows every slide, moves between them, and saves the PowerPoint where Wizard runs on this PC', async () => {
    const value = env();
    render(<TooltipProvider><VisualEnvContext.Provider value={value}><DeckCard deck={DECK} /></VisualEnvContext.Provider></TooltipProvider>);
    expect(screen.getByTestId('deck-title').textContent).toBe('Q3 review');
    expect(screen.getByText(/3 slides · version 2/)).toBeTruthy();
    expect(screen.getByTestId('deck-storyline').textContent).toContain('Flagship carried Q3.');
    expect(within(screen.getByTestId('deck-strip')).getAllByTestId('slide')).toHaveLength(3);
    expect(screen.getByTestId('deck-position').textContent).toBe('1 / 3');
    fireEvent.keyDown(screen.getByTestId('deck-viewer'), {key: 'ArrowRight'});
    expect(screen.getByTestId('deck-position').textContent).toBe('2 / 3');
    expect(within(screen.getByTestId('deck-viewer')).getByText('Flagship carried Q3')).toBeTruthy();
    fireEvent.click(screen.getByRole('button', {name: 'Slide 3: Thank you'}));
    expect(screen.getByTestId('deck-position').textContent).toBe('3 / 3');
    expect(screen.getByTestId('deck-hint').textContent).toContain('In the company\'s design (Executive dense)');

    fireEvent.click(screen.getByTestId('deck-download'));
    await waitFor(() => expect(screen.getByTestId('deck-saved').textContent).toContain('Saved in Downloads as Q3 review (v2).pptx'));
    expect(value.save).toHaveBeenCalledWith(expect.any(Blob), 'Q3 review (v2).pptx');
    fireEvent.click(screen.getByTestId('deck-open'));
    await waitFor(() => expect(value.open).toHaveBeenCalled());
  });

  it('says when the deck is drawn in Wizard\'s neutral design', () => {
    render(<TooltipProvider><DeckCard deck={{...DECK, design: {...DECK.design, source: 'default'}}} /></TooltipProvider>);
    expect(screen.getByTestId('deck-hint').textContent).toContain("Drawn in Wizard's neutral design.");
  });

  it('shows the newest version of each deck an answer made, and drops the [D1] line from the answer text', () => {
    let run: RunView = emptyRun('r', 'c', 'deck');
    run = applyEvent(run, {seq: 1, type: 'deck_added', ts: '', payload: {deck: {...DECK, id: 'D1', revises: null, family: null, version: 1}}});
    run = applyEvent(run, {seq: 2, type: 'deck_added', ts: '', payload: {deck: DECK}});
    expect(shownDecks(run).map(d => d.id)).toEqual(['D2']);
    expect(prepareAnswer('Here it is.\n\n[D2]\n\nAsk for changes.')).toBe('Here it is.\n\n\nAsk for changes.');
    expect(prepareAnswer('See [D2] above.')).toBe('See [D2](#deck-D2) above.');
  });
});

describe('the storyline question', () => {
  const run = applyEvent({...emptyRun('r', 'c', 'Q3 deck'), status: 'succeeded'}, {seq: 1, type: 'storylines_proposed', ts: '', payload: {
    question: 'What story should the presentation tell?', why: null,
    storylines: [{title: 'Flagship carried Q3', arc: ['Q3 beat plan', 'Flagship drove it'], best_for: 'a board update'},
      {title: 'A segment review', arc: ['Flagship', 'Mass'], best_for: null}]}});

  it('shows each story with its arc and sends the one chosen as the next question, for a presentation', () => {
    const story = vi.fn();
    const actions: SteerActions = {live: true, notThis: vi.fn(), remember: vi.fn(), turnOn: vi.fn(), reply: vi.fn(), story};
    render(<SteerContext.Provider value={actions}><StorylineQuestions run={{...run, status: 'succeeded'}} /></SteerContext.Provider>);
    const options = screen.getAllByTestId('storyline');
    expect(options).toHaveLength(2);
    expect(options[0].textContent).toContain('Q3 beat plan');
    expect(options[0].textContent).toContain('For a board update');
    fireEvent.click(options[0]);
    expect(story).toHaveBeenCalledWith(expect.anything(), 'Storyline: Flagship carried Q3 (Q3 beat plan → Flagship drove it)');
    expect(screen.getAllByTestId('storyline').every(b => (b as HTMLButtonElement).disabled)).toBe(true);
    expect(storylineReply({title: 'X', arc: [], best_for: null})).toBe('Storyline: X');
  });

  it('takes no click on an earlier answer', () => {
    const actions: SteerActions = {live: true, notThis: vi.fn(), remember: vi.fn(), turnOn: vi.fn(), reply: vi.fn()};
    render(<SteerContext.Provider value={actions}><StorylineQuestions run={run} latest={false} /></SteerContext.Provider>);
    expect(screen.getAllByTestId('storyline').every(b => (b as HTMLButtonElement).disabled)).toBe(true);
  });
});

describe('the Output picker', () => {
  it('switches the question between an analysis and a PowerPoint', async () => {
    const onOutput = vi.fn();
    const {rerender} = render(<TooltipProvider><Composer busy={false} draft="" onDraftChange={vi.fn()} onSubmit={vi.fn()} output="analysis" onOutput={onOutput} /></TooltipProvider>);
    const picker = screen.getByTestId('output-picker');
    expect(picker.dataset.output).toBe('analysis');
    fireEvent.pointerDown(picker, {button: 0, ctrlKey: false});
    const options = await screen.findAllByTestId('output-option');
    expect(options.map(o => o.dataset.output)).toEqual(['analysis', 'presentation']);
    fireEvent.click(options[1]);
    expect(onOutput).toHaveBeenCalledWith('presentation' satisfies Output);
    rerender(<TooltipProvider><Composer busy={false} draft="" onDraftChange={vi.fn()} onSubmit={vi.fn()} output="presentation" onOutput={onOutput} /></TooltipProvider>);
    expect(screen.getByTestId('output-picker').dataset.output).toBe('presentation');
    expect(screen.getByLabelText('Your question').getAttribute('placeholder')).toContain('What should the presentation be about?');
  });
});
