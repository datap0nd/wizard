import {cleanup, fireEvent, render, screen, waitFor, within} from '@testing-library/react';
import type {ReactNode} from 'react';
import {afterEach, beforeEach, describe, expect, it, vi} from 'vitest';
import type {Case, CaseEntry, CaseTurn} from '@/cases';
import {digest, editsBody, feedbackIssue, jsonBlock, NO_EDITS, quizIssue, type Edits, type FeedbackConfig, type Quiz} from '@/feedback';
import {TooltipProvider} from '../ui/menu';
import {AdminPage} from './AdminPage';
import {CasePage, CasesGallery} from './CasePage';
import {QuizPage} from './QuizPage';
import {CasesSiteContext, type CasesSite} from './SiteChrome';

const CONFIG: FeedbackConfig = {format: 1, api: 'https://github.example.com/api/v3', web: 'https://github.example.com', repo: 'acme/wizard-feedback',
  token: 'github_pat_test', pin: '', edits_issue: 1};
const turn = (n: number): CaseTurn => ({n, kind: 'ask', prompt: `Prompt ${n}`, asked_at: '2026-11-12T10:00:00Z', answer: `Answer ${n}`,
  data_mode: 'SYNTHETIC', check: {status: 'NOT_CHECKED', summary: null}, visuals: [], sources: [], steps: []});
const CASE: Case = {format: 1, id: 'c0123456789abcd', title: 'Return by market', takeaway: 'Egypt leads.', author: null,
  published_at: '2026-11-12T10:00:00Z', systems: ['NERP'], data_modes: ['SYNTHETIC'], turns: [turn(1), turn(2)]};
const entry = (id: string, title: string): CaseEntry => ({id, title, takeaway: '', author: null, published_at: '2026-11-12T10:00:00Z',
  updated_at: '', prompts: 1, systems: ['NERP'], data_modes: ['SYNTHETIC'], first_prompt: 'Which market?'});
const QUIZ: Quiz = {format: 1, updated: '', sections: [
  {id: 'bi', title: 'Business intelligence', intro: 'Data questions.', prepared_at: '2026-11-12T10:00:00Z', questions: [
    {id: 'bi-1', topic: 'Share', question: 'Is share in units or value?', now: 'Two notes disagree.', choices: ['Units', 'Value'], notes: []},
    {id: 'bi-2', topic: 'Weeks', question: 'When does the fiscal week start?', now: 'UNKNOWN.', choices: [], notes: []}]},
  {id: 'business', title: 'Business', intro: '', prepared_at: '2026-11-12T10:00:00Z', questions: [
    {id: 'b-1', topic: 'Switchers', question: 'What counts as a switcher?', now: 'Draft.', choices: [], notes: []}]}]};

let sent: {method: string; url: string; body: Record<string, unknown> | null}[] = [];
function mockGitHub(issues: unknown[] = [], edits: Edits = NO_EDITS) {
  sent = [];
  vi.stubGlobal('fetch', vi.fn(async (url: RequestInfo | URL, init?: RequestInit) => {
    const method = init?.method ?? 'GET';
    sent.push({method, url: String(url), body: init?.body ? JSON.parse(init.body as string) as Record<string, unknown> : null});
    if (String(url).endsWith('.json')) return new Response(JSON.stringify(CASE), {status: 200});
    if (method === 'GET' && String(url).includes('/issues/1')) return new Response(JSON.stringify({number: 1, title: 'e', state: 'open', created_at: '', body: editsBody(edits)}));
    if (method === 'GET') return new Response(JSON.stringify(issues));
    return new Response(JSON.stringify({number: 99}), {status: method === 'POST' ? 201 : 200});
  }));
}

function site(extra: Partial<CasesSite> = {}): CasesSite {
  return {config: CONFIG, edits: NO_EDITS, setEdits: vi.fn(), quiz: QUIZ, admin: false, setAdmin: vi.fn(), ...extra};
}
const wrap = (value: CasesSite, child: ReactNode) => render(<TooltipProvider><CasesSiteContext.Provider value={value}>{child}</CasesSiteContext.Provider></TooltipProvider>);

beforeEach(() => { localStorage.clear(); sessionStorage.clear(); });
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

describe('rating an answer', () => {
  it('sends the stars and the comment anonymously, once, and remembers it on this browser', async () => {
    mockGitHub();
    wrap(site(), <CasePage item={CASE} home="./" />);
    const first = screen.getAllByTestId('case-rate')[0];
    fireEvent.click(within(first).getAllByTestId('case-star')[3]);
    fireEvent.change(within(first).getByTestId('case-comment'), {target: {value: 'Right market, wrong quarter'}});
    fireEvent.click(within(first).getByTestId('case-rate-send'));
    await screen.findByText(/You rated this answer 4 \/ 5/);
    expect(sent).toHaveLength(1);
    expect(sent[0].method).toBe('POST');
    expect(sent[0].url).toBe('https://github.example.com/api/v3/repos/acme/wizard-feedback/issues');
    expect(jsonBlock(sent[0].body!.body as string)).toMatchObject({kind: 'feedback', case: CASE.id, turn: 1, stars: 4, comment: 'Right market, wrong quarter'});
    expect(JSON.stringify(sent[0].body)).not.toMatch(/author|email|name/);
    cleanup();
    wrap(site(), <CasePage item={CASE} home="./" />);
    expect(screen.getAllByTestId('case-rated')).toHaveLength(1);  // answer 1 rated, answer 2 still open
    expect(screen.getAllByTestId('case-rate')).toHaveLength(1);
  });

  it('is not offered without feedback, nor in Wizard\'s preview', () => {
    wrap(site({config: null}), <CasePage item={CASE} home="./" />);
    expect(screen.queryByTestId('case-rate')).toBeNull();
    cleanup();
    wrap(site(), <CasePage item={CASE} home="/" preview />);
    expect(screen.queryByTestId('case-rate')).toBeNull();
  });

  it('shows the admin pane\'s title and notes from the editors over the published case', () => {
    wrap(site({edits: {format: 1, cases: {[CASE.id]: {title: 'Marketing return, Q3', notes: {2: 'Q3 only: Q4 was not in yet.'}}}}}), <CasePage item={CASE} home="./" />);
    expect(screen.getByTestId('case-title').textContent).toBe('Marketing return, Q3');
    expect(screen.getAllByTestId('case-editor-note').map(n => n.textContent)).toEqual(['Note from the editors: Q3 only: Q4 was not in yet.']);
  });
});

describe('the gallery', () => {
  it('leaves hidden cases out and leads to the quiz', () => {
    wrap(site({edits: {format: 1, cases: {c2: {hidden: true}}}}), <CasesGallery cases={[entry('c1', 'Shown'), entry('c2', 'Hidden')]} home="./" />);
    expect(screen.getAllByTestId('case-card').map(c => c.querySelector('h2')?.textContent)).toEqual(['Shown']);
    expect(screen.getByTestId('gallery-quiz').textContent).toContain('3 questions');
  });
});

describe('the quiz', () => {
  it('sends the answered questions of a section as one anonymous issue and marks them answered', async () => {
    mockGitHub();
    wrap(site(), <QuizPage home="./" section={null} />);
    expect(screen.getAllByTestId('quiz-tab').map(t => t.textContent)).toEqual(['Business intelligence · 2', 'Business · 1']);
    const [share, weeks] = screen.getAllByTestId('quiz-question');
    expect(screen.getByTestId('quiz-send').hasAttribute('disabled')).toBe(true);
    fireEvent.click(within(share).getByLabelText('Value'));
    fireEvent.change(within(weeks).getByTestId('quiz-answer'), {target: {value: 'Monday'}});
    fireEvent.click(screen.getByTestId('quiz-send'));
    await screen.findByTestId('quiz-sent');
    const data = jsonBlock(sent[0].body!.body as string) as {section: string; answers: {question_id: string; choice: string | null; answer: string}[]};
    expect(data.section).toBe('bi');
    expect(data.answers.map(a => [a.question_id, a.choice, a.answer])).toEqual([['bi-1', 'Value', ''], ['bi-2', null, 'Monday']]);
    expect(screen.getAllByTestId('quiz-question').map(q => q.dataset.sent)).toEqual(['true', 'true']);
    fireEvent.click(screen.getAllByTestId('quiz-tab')[1]);
    expect(screen.getAllByTestId('quiz-question').map(q => q.dataset.sent)).toEqual(['false']);
  });

  it('says when there is nothing to answer yet', () => {
    wrap(site({quiz: null}), <QuizPage home="./" section={null} />);
    expect(screen.getByTestId('quiz-empty')).toBeTruthy();
  });
});

describe('the admin pane', () => {
  it('opens only with the PIN', async () => {
    const config = {...CONFIG, pin: await digest('2323')};
    const setAdmin = vi.fn();
    const assign = vi.fn();
    vi.stubGlobal('location', {...location, get search() { return ''; }, set search(v: string) { assign(v); }});
    wrap(site({config, setAdmin}), <CasesGallery cases={[]} home="./" />);
    fireEvent.click(screen.getByTestId('admin-open'));
    fireEvent.change(screen.getByTestId('admin-pin'), {target: {value: '1111'}});
    fireEvent.click(screen.getByTestId('admin-pin-open'));
    await screen.findByTestId('admin-pin-wrong');
    expect(setAdmin).not.toHaveBeenCalled();
    fireEvent.change(screen.getByTestId('admin-pin'), {target: {value: '2323'}});
    fireEvent.click(screen.getByTestId('admin-pin-open'));
    await waitFor(() => expect(setAdmin).toHaveBeenCalledWith(true));
    expect(assign).toHaveBeenCalledWith('?admin');
  });

  it('shows each case\'s ratings and comments, marks one done, and saves an edit', async () => {
    const rated = (n: number, turnN: number, stars: number, comment: string) => ({number: n, state: 'open', created_at: `2026-11-12T10:0${n}:00Z`,
      ...feedbackIssue({kind: 'feedback', case: CASE.id, case_title: CASE.title, turn: turnN, prompt: 'p', stars, comment, at: `2026-11-12T10:0${n}:00Z`})});
    const quiz = {number: 5, state: 'open', created_at: '2026-11-12T11:00:00Z', ...quizIssue({kind: 'quiz', section: 'bi', section_title: 'Business intelligence',
      at: '2026-11-12T11:00:00Z', answers: [{question_id: 'bi-1', question: 'Is share in units or value?', topic: 'Share', choice: 'Units', answer: 'In ASAP', unsure: false}]})};
    mockGitHub([rated(2, 1, 5, 'Spot on'), rated(3, 2, 2, 'Wrong quarter'), quiz]);
    const setEdits = vi.fn();
    wrap(site({admin: true, setEdits}), <AdminPage cases={[entry(CASE.id, CASE.title)]} home="./" />);
    const card = await screen.findByTestId('admin-case-feedback');
    expect(card.textContent).toContain('3.5/ 5 · 2 ratings');
    expect(card.textContent).toContain('Spot on');
    fireEvent.click(within(card).getAllByText('Mark done')[0]);
    await waitFor(() => expect(sent.some(s => s.method === 'PATCH' && s.url.endsWith('/issues/3') && s.body?.state === 'closed')).toBe(true));
    fireEvent.click(screen.getByTestId('admin-tab-quiz'));
    expect(screen.getAllByTestId('admin-question')[0].textContent).toContain('1 answer · Units: 1');
    fireEvent.click(screen.getByTestId('admin-tab-edit'));
    fireEvent.click(screen.getByTestId('admin-edit-case'));
    fireEvent.change(screen.getByTestId('admin-edit-title'), {target: {value: 'Marketing return, Q3'}});
    fireEvent.click(screen.getByTestId('admin-edit-hidden'));
    fireEvent.click(screen.getByTestId('admin-edit-save'));
    await screen.findByText(/Saved: everyone sees it now/);
    const patch = sent.filter(s => s.method === 'PATCH' && s.url.endsWith('/issues/1')).at(-1)!;
    expect((jsonBlock(patch.body!.body as string) as Edits).cases[CASE.id]).toMatchObject({title: 'Marketing return, Q3', hidden: true});
    expect(setEdits).toHaveBeenLastCalledWith(expect.objectContaining({cases: {[CASE.id]: expect.objectContaining({hidden: true})}}));
  });

  it('stays closed without the PIN', () => {
    wrap(site({admin: false}), <AdminPage cases={[]} home="./" />);
    expect(screen.getByTestId('admin-closed').textContent).toContain('enter the PIN');
  });
});
