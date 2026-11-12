// Feedback on the Cases site (owner, 12 Nov 2026; services/api/wizard_api/feedback.py): people rate each answer from 1 to
// 5 stars, leave a comment and answer the quiz, without signing in. The site is static, so its pages send each one as
// an issue in the feedback repository, with the token Wizard published beside them (cases/feedback.json) after checking
// it can only open and read issues there. Every issue is signed by that token's account, so a submission names no one.
// The admin pane (a PIN, top right) reads them back and keeps its edits to the cases in one issue of its own. The PIN
// only hides the pane. This file holds the shapes, the pure helpers (tested without a browser) and the GitHub calls.
import type {Case, CaseEntry} from './cases';

export interface FeedbackConfig { format: number; api: string; web: string; repo: string; token: string; pin: string; edits_issue: number }

export interface AnswerFeedback {
  kind: 'feedback'; case: string; case_title: string; turn: number; prompt: string; stars: number; comment: string; at: string;
}
export interface QuizAnswer { question_id: string; question: string; topic: string; choice: string | null; answer: string; unsure: boolean }
export interface QuizSubmission { kind: 'quiz'; section: string; section_title: string; answers: QuizAnswer[]; at: string }

/** What the admin pane changed in a case: shown over what Wizard published, never written into the case itself. */
export interface CaseEdit { title?: string; takeaway?: string; hidden?: boolean; notes?: Record<string, string> }
export interface Edits { format: number; cases: Record<string, CaseEdit>; updated?: string }

/** The quiz a quiz task's Gemini prepared (cases/quiz.json, services/connectors/wizard_connectors/tools/quiz_tools.py). */
export interface QuizQuestion { id: string; topic: string; question: string; now: string; choices: string[]; notes: {id: string; title: string}[] }
export interface QuizSection { id: string; title: string; intro: string; prepared_at: string; questions: QuizQuestion[] }
export interface Quiz { format: number; updated: string; sections: QuizSection[] }

export interface Issue { number: number; title: string; body: string | null; state: 'open' | 'closed'; created_at: string; html_url?: string; pull_request?: unknown }
export interface Received<T> { number: number; open: boolean; created_at: string; url: string | null; data: T }

export const MARKER = {feedback: '<!-- wizard:feedback -->', quiz: '<!-- wizard:quiz -->', edits: '<!-- wizard:edits -->'} as const;
export const MAX_COMMENT = 2000;
export const MAX_ANSWER = 1500;
const MAX_PAGES = 30;  // 3,000 issues: the admin pane reads them all at once
export const NO_EDITS: Edits = {format: 1, cases: {}};

/** The data of an issue Wizard's site opened: its last ```json block (backticks inside it are escaped). */
export function jsonBlock(body: string | null | undefined): unknown {
  const text = body ?? '';
  const start = text.lastIndexOf('```json');
  if (start < 0) return null;
  const end = text.indexOf('```', start + 7);
  try { return JSON.parse(text.slice(start + 7, end > 0 ? end : undefined)); } catch { return null; }
}

function block(data: unknown): string {
  return '```json\n' + JSON.stringify(data, null, 1).replace(/`/g, '\\u0060') + '\n```\n';
}

function quote(text: string): string {
  return text.trim() ? text.trim().split('\n').map(line => `> ${line}`).join('\n') : '_No comment._';
}

const clip = (text: string, n: number) => text.length > n ? `${text.slice(0, n - 1)}…` : text;

export function stars(n: number): string {
  return '★'.repeat(n) + '☆'.repeat(5 - n);
}

export function feedbackIssue(f: AnswerFeedback): {title: string; body: string} {
  return {title: clip(`${stars(f.stars)} ${f.case_title} · answer ${f.turn}`, 200),
    body: `${MARKER.feedback}\n**${f.stars} / 5** for answer ${f.turn} of “${f.case_title}”.\n\n${quote(f.comment)}\n\n`
      + `Sent anonymously from the Cases site.\n\n${block(f)}`};
}

export function quizIssue(s: QuizSubmission): {title: string; body: string} {
  const lines = s.answers.map((a, i) => `${i + 1}. **${a.question}**\n   ${a.unsure ? '_Not sure._' : [a.choice, a.answer].filter(Boolean).join(' — ')}`);
  return {title: clip(`Quiz · ${s.section_title} · ${s.answers.length} ${s.answers.length === 1 ? 'answer' : 'answers'}`, 200),
    body: `${MARKER.quiz}\n${lines.join('\n')}\n\nSent anonymously from the Cases site.\n\n${block(s)}`};
}

export function editsBody(edits: Edits): string {
  return `${MARKER.edits}\nThe Cases site's admin pane keeps its edits to the cases here (titles, takeaways, notes from the editors, `
    + `hidden cases). The site reads this issue: change it from the admin pane, not by hand.\n\n${block(edits)}`;
}

function isFeedback(d: unknown): d is AnswerFeedback {
  const f = d as AnswerFeedback;
  return !!f && f.kind === 'feedback' && typeof f.case === 'string' && Number.isInteger(f.turn) && Number.isInteger(f.stars)
    && f.stars >= 1 && f.stars <= 5 && typeof f.comment === 'string';
}

function isQuiz(d: unknown): d is QuizSubmission {
  const s = d as QuizSubmission;
  return !!s && s.kind === 'quiz' && typeof s.section === 'string' && Array.isArray(s.answers)
    && s.answers.every(a => a && typeof a.question_id === 'string' && typeof a.question === 'string');
}

/** The ratings and quiz answers among a repository's issues, newest first; anything else is left out. */
export function parseIssues(issues: Issue[]): {feedback: Received<AnswerFeedback>[]; quiz: Received<QuizSubmission>[]} {
  const feedback: Received<AnswerFeedback>[] = [];
  const quiz: Received<QuizSubmission>[] = [];
  for (const issue of issues) {
    if (issue.pull_request || !issue.body) continue;
    const base = {number: issue.number, open: issue.state === 'open', created_at: issue.created_at, url: issue.html_url ?? null};
    const data = jsonBlock(issue.body);
    if (issue.body.startsWith(MARKER.feedback) && isFeedback(data)) feedback.push({...base, data});
    else if (issue.body.startsWith(MARKER.quiz) && isQuiz(data)) quiz.push({...base, data});
  }
  const newest = (a: {created_at: string}, b: {created_at: string}) => b.created_at.localeCompare(a.created_at);
  return {feedback: feedback.sort(newest), quiz: quiz.sort(newest)};
}

export interface Rating { count: number; average: number | null; comments: number }

function rating(items: AnswerFeedback[]): Rating {
  return {count: items.length, average: items.length ? items.reduce((sum, f) => sum + f.stars, 0) / items.length : null,
    comments: items.filter(f => f.comment.trim()).length};
}

/** Each case's ratings, and each answer's within it. */
export function ratings(feedback: Received<AnswerFeedback>[]): Map<string, Rating & {turns: Map<number, Rating>}> {
  const byCase = new Map<string, AnswerFeedback[]>();
  for (const f of feedback) byCase.set(f.data.case, [...(byCase.get(f.data.case) ?? []), f.data]);
  return new Map([...byCase].map(([id, items]) => {
    const turns = new Map<number, AnswerFeedback[]>();
    for (const f of items) turns.set(f.turn, [...(turns.get(f.turn) ?? []), f]);
    return [id, {...rating(items), turns: new Map([...turns].map(([n, t]) => [n, rating(t)]))}];
  }));
}

export interface QuestionAnswers { question_id: string; question: string; topic: string; section: string; answers: (QuizAnswer & {at: string; number: number})[] }

/** Every answer to each question, the quiz's own order first, then questions no longer on the site. */
export function answersByQuestion(quiz: Quiz | null, received: Received<QuizSubmission>[]): QuestionAnswers[] {
  const out = new Map<string, QuestionAnswers>();
  for (const section of quiz?.sections ?? []) for (const q of section.questions)
    out.set(q.id, {question_id: q.id, question: q.question, topic: q.topic, section: section.id, answers: []});
  for (const r of received) for (const a of r.data.answers) {
    const found = out.get(a.question_id) ?? {question_id: a.question_id, question: a.question, topic: a.topic, section: r.data.section, answers: []};
    found.answers.push({...a, at: r.data.at, number: r.number});
    out.set(a.question_id, found);
  }
  return [...out.values()];
}

/** A case as the site shows it: the admin pane's title and takeaway over Wizard's. */
export function edited<T extends Pick<Case, 'id' | 'title' | 'takeaway'> | CaseEntry>(item: T, edits: Edits): T {
  const edit = edits.cases[item.id];
  if (!edit) return item;
  return {...item, title: edit.title?.trim() || item.title, takeaway: edit.takeaway !== undefined ? edit.takeaway : item.takeaway};
}

/** The gallery: hidden cases left out, edits applied. */
export function shownCases(cases: CaseEntry[], edits: Edits): CaseEntry[] {
  return cases.filter(c => !edits.cases[c.id]?.hidden).map(c => edited(c, edits));
}

/** One case's edit merged into the latest edits; an empty edit removes the case's entry. */
export function withEdit(edits: Edits, id: string, edit: CaseEdit): Edits {
  const notes = Object.fromEntries(Object.entries(edit.notes ?? {}).filter(([, v]) => v.trim()));
  const clean: CaseEdit = {...(edit.title?.trim() ? {title: edit.title.trim()} : {}), ...(edit.takeaway !== undefined ? {takeaway: edit.takeaway.trim()} : {}),
    ...(edit.hidden ? {hidden: true} : {}), ...(Object.keys(notes).length ? {notes} : {})};
  const cases = {...edits.cases};
  if (Object.keys(clean).length) cases[id] = clean; else delete cases[id];
  return {format: 1, cases, updated: new Date().toISOString()};
}

export async function digest(pin: string): Promise<string> {
  const bytes = new TextEncoder().encode(`wizard-cases:${pin}`);
  const hash = await crypto.subtle.digest('SHA-256', bytes);
  return [...new Uint8Array(hash)].map(b => b.toString(16).padStart(2, '0')).join('');
}

export async function pinMatches(pin: string, config: FeedbackConfig): Promise<boolean> {
  return /^[0-9]{4,12}$/.test(pin) && await digest(pin) === config.pin;
}

export function toCsv(rows: (string | number | null)[][]): string {
  return rows.map(r => r.map(v => {
    const text = v === null ? '' : String(v);
    return /[",\n;]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
  }).join(',')).join('\r\n');
}

// This browser's own memory: what it already sent, so a page shows "sent" again. Never sent anywhere.
const KEY = 'wizard-cases';
function stored<T>(name: string, fallback: T): T {
  try { return JSON.parse(localStorage.getItem(`${KEY}:${name}`) ?? 'null') as T ?? fallback; } catch { return fallback; }
}
function store(name: string, value: unknown): void {
  try { localStorage.setItem(`${KEY}:${name}`, JSON.stringify(value)); } catch { /* private window: nothing kept */ }
}
export const memory = {
  rated: (caseId: string, n: number): number | null => stored<Record<string, number>>('rated', {})[`${caseId}:${n}`] ?? null,
  rate: (caseId: string, n: number, value: number) => store('rated', {...stored<Record<string, number>>('rated', {}), [`${caseId}:${n}`]: value}),
  answered: (): string[] => stored<string[]>('answered', []),
  answer: (ids: string[]) => store('answered', [...new Set([...stored<string[]>('answered', []), ...ids])]),
  admin: (): boolean => { try { return sessionStorage.getItem(`${KEY}:admin`) === '1'; } catch { return false; } },
  setAdmin: (on: boolean) => { try { if (on) sessionStorage.setItem(`${KEY}:admin`, '1'); else sessionStorage.removeItem(`${KEY}:admin`); } catch { /* */ } },
};

export class FeedbackError extends Error {}

/** The feedback repository's issues, with the published token. */
export class FeedbackClient {
  constructor(private config: FeedbackConfig, private send: typeof fetch = (...args) => fetch(...args)) {}

  private async call<T>(method: string, path: string, body?: unknown): Promise<T> {
    let response: Response;
    try {
      response = await this.send(`${this.config.api}/repos/${this.config.repo}${path}`, {method, cache: 'no-store',
        headers: {Authorization: `Bearer ${this.config.token}`, Accept: 'application/vnd.github+json',
          ...(body === undefined ? {} : {'Content-Type': 'application/json'})},
        body: body === undefined ? undefined : JSON.stringify(body)});
    } catch {
      throw new FeedbackError('GitHub could not be reached from this browser. Check the connection and try again.');
    }
    if (response.ok) return await response.json() as T;
    if (response.status === 401) throw new FeedbackError('The site\'s feedback key no longer works: tell the person who publishes the site.');
    if (response.status === 403 || response.status === 429) throw new FeedbackError('GitHub is busy (too many requests): try again in a few minutes.');
    if (response.status === 404) throw new FeedbackError('The feedback repository is not there any more: tell the person who publishes the site.');
    if (response.status === 410) throw new FeedbackError('Issues are turned off in the feedback repository: tell the person who publishes the site.');
    throw new FeedbackError(`GitHub answered HTTP ${response.status}. Try again.`);
  }

  async open(issue: {title: string; body: string}): Promise<number> {
    return (await this.call<Issue>('POST', '/issues', issue)).number;
  }

  async issues(): Promise<Issue[]> {
    const all: Issue[] = [];
    for (let page = 1; page <= MAX_PAGES; page++) {
      const found = await this.call<Issue[]>('GET', `/issues?state=all&sort=created&direction=desc&per_page=100&page=${page}`);
      all.push(...found);
      if (found.length < 100) break;
    }
    return all;
  }

  async setOpen(number: number, open: boolean): Promise<void> {
    await this.call('PATCH', `/issues/${number}`, {state: open ? 'open' : 'closed'});
  }

  async edits(): Promise<Edits> {
    const data = jsonBlock((await this.call<Issue>('GET', `/issues/${this.config.edits_issue}`)).body) as Edits | null;
    return data && typeof data.cases === 'object' && data.cases ? {format: 1, cases: data.cases, updated: data.updated} : NO_EDITS;
  }

  /** One case's edit, merged into the edits as they are now on GitHub (someone else may have saved since). */
  async saveEdit(id: string, edit: CaseEdit): Promise<Edits> {
    const next = withEdit(await this.edits(), id, edit);
    await this.call('PATCH', `/issues/${this.config.edits_issue}`, {body: editsBody(next)});
    return next;
  }
}

export async function readConfig(path = './feedback.json'): Promise<FeedbackConfig | null> {
  try {
    const response = await fetch(path, {cache: 'no-cache'});
    if (!response.ok) return null;
    const config = await response.json() as FeedbackConfig;
    return config && config.api && config.repo && config.token && config.pin ? config : null;
  } catch {
    return null;
  }
}
