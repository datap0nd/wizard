import {describe, expect, it, vi} from 'vitest';
import type {CaseEntry} from './cases';
import {answersByQuestion, digest, editsBody, FeedbackClient, feedbackIssue, jsonBlock, parseIssues, pinMatches, quizIssue,
  ratings, shownCases, toCsv, withEdit, type AnswerFeedback, type FeedbackConfig, type Issue, type Quiz} from './feedback';

const CONFIG: FeedbackConfig = {format: 1, api: 'https://github.example.com/api/v3', web: 'https://github.example.com', repo: 'acme/wizard-feedback',
  token: 'github_pat_test', pin: '', edits_issue: 1};
const rated = (c: string, turn: number, s: number, comment = ''): AnswerFeedback => ({kind: 'feedback', case: c, case_title: `Case ${c}`, turn,
  prompt: 'Which market?', stars: s, comment, at: '2026-11-12T10:00:00Z'});
const issue = (number: number, made: {title: string; body: string}, extra: Partial<Issue> = {}): Issue => ({number, ...made, state: 'open',
  created_at: `2026-11-12T10:0${number}:00Z`, ...extra});
const entry = (id: string, title: string): CaseEntry => ({id, title, takeaway: 'T', author: null, published_at: '', updated_at: '', prompts: 1,
  systems: [], data_modes: [], first_prompt: ''});

describe('feedback as issues', () => {
  it('reads back what the site sent, a comment with backticks included, and nothing else', () => {
    const tricky = rated('c1', 2, 4, 'Use ```json``` here?\nSecond line');
    const issues = [issue(1, feedbackIssue(tricky)), issue(2, {title: 'Someone else', body: 'Hello'}),
      issue(3, feedbackIssue(rated('c1', 1, 2)), {pull_request: {}}),
      issue(4, quizIssue({kind: 'quiz', section: 'bi', section_title: 'Business intelligence', at: '2026-11-12T10:00:00Z',
        answers: [{question_id: 'bi-1', question: 'Units or value?', topic: 'Share', choice: 'Units', answer: '', unsure: false}]}))];
    const found = parseIssues(issues);
    expect(found.feedback.map(f => [f.number, f.data.comment])).toEqual([[1, tricky.comment]]);
    expect(found.quiz.map(q => q.data.answers[0].choice)).toEqual(['Units']);
    expect(feedbackIssue(tricky).title).toBe('★★★★☆ Case c1 · answer 2');
    expect(feedbackIssue(tricky).body).toContain('> Use ```json``` here?\n> Second line');
  });

  it('averages each case and each of its answers', () => {
    const received = [rated('c1', 1, 5, 'Great'), rated('c1', 1, 3), rated('c1', 2, 1, 'Wrong market'), rated('c2', 1, 4)]
      .map((data, i) => ({number: i, open: true, created_at: '', url: null, data}));
    const byCase = ratings(received);
    expect(byCase.get('c1')).toMatchObject({count: 3, average: 3, comments: 2});
    expect(byCase.get('c1')!.turns.get(1)).toMatchObject({count: 2, average: 4});
    expect(byCase.get('c2')!.average).toBe(4);
  });

  it('groups quiz answers by question, the quiz order first and questions no longer on the site after', () => {
    const quiz: Quiz = {format: 1, updated: '', sections: [{id: 'bi', title: 'Business intelligence', intro: '', prepared_at: '', questions: [
      {id: 'bi-1', topic: 'Share', question: 'Units or value?', now: '', choices: [], notes: []},
      {id: 'bi-2', topic: 'Weeks', question: 'When does the week start?', now: '', choices: [], notes: []}]}]};
    const sent = (answers: {question_id: string; question: string}[]) => ({number: 1, open: true, created_at: '', url: null,
      data: {kind: 'quiz' as const, section: 'bi', section_title: 'BI', at: '2026-11-12', answers: answers.map(a => ({...a, topic: 'x', choice: null, answer: 'A', unsure: false}))}});
    const grouped = answersByQuestion(quiz, [sent([{question_id: 'bi-old', question: 'Gone?'}, {question_id: 'bi-2', question: 'When does the week start?'}])]);
    expect(grouped.map(q => [q.question_id, q.answers.length])).toEqual([['bi-1', 0], ['bi-2', 1], ['bi-old', 1]]);
  });
});

describe('the admin pane\'s edits', () => {
  it('hide a case from the gallery and show its new title, and an empty edit removes the entry', () => {
    let edits = withEdit({format: 1, cases: {}}, 'c1', {title: '  Better title ', hidden: false, notes: {1: 'Check Q3', 2: ' '}});
    edits = withEdit(edits, 'c2', {hidden: true});
    expect(edits.cases).toEqual({c1: {title: 'Better title', notes: {1: 'Check Q3'}}, c2: {hidden: true}});
    expect(shownCases([entry('c1', 'Old'), entry('c2', 'Hidden'), entry('c3', 'Plain')], edits).map(c => [c.id, c.title]))
      .toEqual([['c1', 'Better title'], ['c3', 'Plain']]);
    expect(withEdit(edits, 'c2', {}).cases).not.toHaveProperty('c2');
    expect(jsonBlock(editsBody(edits))).toEqual(edits);
  });

  it('are saved on top of the edits as they are on GitHub now', async () => {
    const calls: {method: string; url: string; body?: string}[] = [];
    const send = vi.fn(async (url: RequestInfo | URL, init?: RequestInit) => {
      calls.push({method: init?.method ?? 'GET', url: String(url), body: init?.body as string | undefined});
      if ((init?.method ?? 'GET') === 'GET') return new Response(JSON.stringify({number: 1, title: 't', state: 'open', created_at: '',
        body: editsBody({format: 1, cases: {c9: {hidden: true}}})}), {status: 200});
      return new Response('{}', {status: 200});
    });
    const saved = await new FeedbackClient(CONFIG, send as typeof fetch).saveEdit('c1', {title: 'New'});
    expect(saved.cases).toEqual({c9: {hidden: true}, c1: {title: 'New'}});
    expect(calls.map(c => `${c.method} ${c.url}`)).toEqual(['GET https://github.example.com/api/v3/repos/acme/wizard-feedback/issues/1',
      'PATCH https://github.example.com/api/v3/repos/acme/wizard-feedback/issues/1']);
    expect(jsonBlock(JSON.parse(calls[1].body!).body)).toEqual(saved);
    expect((send.mock.calls[0][1]!.headers as Record<string, string>).Authorization).toBe('Bearer github_pat_test');
  });

  it('say in words what went wrong', async () => {
    const client = new FeedbackClient(CONFIG, (async () => new Response('{}', {status: 401})) as typeof fetch);
    await expect(client.open({title: 't', body: 'b'})).rejects.toThrow('no longer works');
    const offline = new FeedbackClient(CONFIG, (async () => { throw new TypeError('Failed to fetch'); }) as typeof fetch);
    await expect(offline.issues()).rejects.toThrow('could not be reached');
  });
});

describe('the PIN', () => {
  it('matches the digest Wizard publishes (sha256 of wizard-cases:<pin>), never the PIN itself', async () => {
    const config = {...CONFIG, pin: await digest('2323')};
    expect(config.pin).toBe('46a2ed4e9e7263ac4558b6b03a126d6a1683251dc6ae779c7128b08a0c5bd846');  // hashlib.sha256(b'wizard-cases:2323'), as feedback.py publishes it
    expect(await pinMatches('2323', config)).toBe(true);
    expect(await pinMatches('2324', config)).toBe(false);
    expect(await pinMatches('23', config)).toBe(false);
  });
});

it('writes CSV that Excel opens', () => {
  expect(toCsv([['a', 'b, c'], ['say "hi"', null]])).toBe('a,"b, c"\r\n"say ""hi""",');
});
