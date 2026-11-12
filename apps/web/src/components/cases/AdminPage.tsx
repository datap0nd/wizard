import {useCallback, useEffect, useMemo, useState} from 'react';
import {Download, ExternalLink, Loader2, RefreshCw, Star} from 'lucide-react';
import type {Case, CaseEntry} from '@/cases';
import {answersByQuestion, edited, FeedbackClient, parseIssues, ratings, stars, toCsv, type AnswerFeedback, type CaseEdit,
  type QuizSubmission, type Received} from '@/feedback';
import {formatDate} from '@/format';
import {cn} from '@/lib/utils';
import {SiteTop, useCasesSite} from './SiteChrome';

type Tab = 'feedback' | 'quiz' | 'edit';
const field = 'rounded-[10px] border border-line-2 bg-canvas px-3 py-2 text-[14px] text-ink outline-none focus:border-accent';
const small = 'inline-flex min-h-9 items-center gap-1.5 rounded-lg border border-line-2 bg-canvas px-3 text-[13px] font-medium text-ink hover:bg-surface disabled:opacity-50';

function download(name: string, rows: (string | number | null)[][]) {
  const url = URL.createObjectURL(new Blob(['﻿' + toCsv(rows)], {type: 'text/csv;charset=utf-8'}));
  const a = Object.assign(document.createElement('a'), {href: url, download: name});
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

function Average({value, count}: {value: number | null; count: number}) {
  if (value === null) return <span className="text-[13px] text-ink-3">No ratings yet</span>;
  return <span className="inline-flex items-center gap-1.5 text-[14px]"><Star className="size-4 fill-[#f5a524] text-[#f5a524]" />
    <b>{value.toFixed(1)}</b><span className="text-ink-3">/ 5 · {count} {count === 1 ? 'rating' : 'ratings'}</span></span>;
}

function FeedbackTab({cases, feedback, onState, busy}: {cases: CaseEntry[]; feedback: Received<AnswerFeedback>[];
  onState: (n: number, open: boolean) => void; busy: number | null}) {
  const [all, setAll] = useState(false);
  const byCase = useMemo(() => ratings(feedback), [feedback]);
  const titles = new Map(cases.map(c => [c.id, c.title]));
  const ids = [...new Set([...cases.map(c => c.id), ...feedback.map(f => f.data.case)])].filter(id => byCase.has(id) || titles.has(id));
  const shown = (id: string) => feedback.filter(f => f.data.case === id && (all || f.open));
  return (
    <div className="space-y-4" data-testid="admin-feedback">
      <div className="flex flex-wrap items-center gap-3">
        <label className="inline-flex items-center gap-2 text-[13.5px] text-ink-2"><input type="checkbox" checked={all} onChange={e => setAll(e.target.checked)} className="size-4" />Show the ones marked done</label>
        <button type="button" className={cn(small, 'ml-auto')} disabled={!feedback.length}
          onClick={() => download('wizard-cases-feedback.csv', [['Date', 'Case', 'Answer', 'Stars', 'Comment', 'Prompt', 'Done', 'Issue'],
            ...feedback.map(f => [f.data.at || f.created_at, f.data.case_title, f.data.turn, f.data.stars, f.data.comment, f.data.prompt, f.open ? '' : 'yes', f.number])])}>
          <Download className="size-4" />Download (CSV)</button>
      </div>
      {ids.length === 0 && <p className="text-[14px] text-ink-2">No feedback yet.</p>}
      {ids.map(id => {
        const stats = byCase.get(id);
        const items = shown(id);
        return (
          <section key={id} className="rounded-2xl border border-line bg-canvas" data-testid="admin-case-feedback">
            <div className="flex flex-wrap items-center gap-x-4 gap-y-1 border-b border-line px-5 py-3">
              <a href={`./?case=${encodeURIComponent(id)}`} className="text-[16px] font-semibold text-ink">{titles.get(id) ?? feedback.find(f => f.data.case === id)?.data.case_title ?? id}</a>
              <Average value={stats?.average ?? null} count={stats?.count ?? 0} />
              {stats && [...stats.turns].sort(([a], [b]) => a - b).map(([n, r]) => (
                <span key={n} className="text-[12.5px] text-ink-3">answer {n}: {r.average?.toFixed(1)} ({r.count})</span>))}
            </div>
            {items.length > 0 ? (
              <ul className="divide-y divide-line">
                {items.map(f => (
                  <li key={f.number} className={cn('flex flex-wrap items-start gap-x-4 gap-y-1.5 px-5 py-3', !f.open && 'opacity-60')}>
                    <span className="text-[15px] tracking-[0.05em] text-[#f5a524]" aria-label={`${f.data.stars} of 5 stars`}>{stars(f.data.stars)}</span>
                    <span className="min-w-0 flex-1 text-[14px]">
                      <span className="text-[12.5px] text-ink-3">Answer {f.data.turn} · {formatDate(f.data.at || f.created_at, true)}</span>
                      <span className="block whitespace-pre-wrap text-ink">{f.data.comment || <i className="text-ink-3">No comment.</i>}</span>
                    </span>
                    <span className="flex items-center gap-2">
                      {f.url && <a href={f.url} target="_blank" rel="noreferrer" className="text-ink-3 hover:text-accent" title="Open on GitHub"><ExternalLink className="size-4" /></a>}
                      <button type="button" className={small} disabled={busy === f.number} onClick={() => onState(f.number, !f.open)}>
                        {busy === f.number && <Loader2 className="size-3.5 animate-spin" />}{f.open ? 'Mark done' : 'Reopen'}</button>
                    </span>
                  </li>
                ))}
              </ul>
            ) : <p className="px-5 py-3 text-[13.5px] text-ink-3">{stats?.count ? 'Every comment here is marked done.' : 'No ratings yet.'}</p>}
          </section>
        );
      })}
    </div>
  );
}

function QuizTab({received}: {received: Received<QuizSubmission>[]}) {
  const site = useCasesSite();
  const questions = useMemo(() => answersByQuestion(site?.quiz ?? null, received), [site?.quiz, received]);
  const sections = site?.quiz?.sections ?? [];
  const titleOf = (id: string) => sections.find(s => s.id === id)?.title ?? id;
  const current = new Set(sections.flatMap(s => s.questions.map(q => q.id)));
  return (
    <div className="space-y-4" data-testid="admin-quiz">
      <div className="flex flex-wrap items-center gap-3">
        <p className="text-[13.5px] text-ink-2">{received.length} {received.length === 1 ? 'person sent' : 'sends'} answers. Answers to questions no longer on the site are kept at the end.</p>
        <button type="button" className={cn(small, 'ml-auto')} disabled={!received.length}
          onClick={() => download('wizard-quiz-answers.csv', [['Date', 'Section', 'Topic', 'Question', 'Choice', 'Answer', 'Not sure', 'Question id'],
            ...questions.flatMap(q => q.answers.map(a => [a.at, titleOf(q.section), q.topic, q.question, a.choice, a.answer, a.unsure ? 'yes' : '', q.question_id]))])}>
          <Download className="size-4" />Download (CSV)</button>
      </div>
      {questions.length === 0 && <p className="text-[14px] text-ink-2">No quiz yet: run a quiz task in Wizard (Settings → Tasks).</p>}
      {questions.map(q => {
        const known = q.answers.filter(a => !a.unsure);
        const tally = new Map<string, number>();
        for (const a of known) if (a.choice) tally.set(a.choice, (tally.get(a.choice) ?? 0) + 1);
        return (
          <section key={q.question_id} className={cn('space-y-2 rounded-2xl border border-line bg-canvas px-5 py-4', !current.has(q.question_id) && 'border-dashed')} data-testid="admin-question">
            <p className="text-[12.5px] text-ink-3">{titleOf(q.section)} · {q.topic}{current.has(q.question_id) ? '' : ' · no longer on the site'}</p>
            <h3 className="text-[15.5px] font-semibold">{q.question}</h3>
            <p className="text-[13px] text-ink-3">{known.length} {known.length === 1 ? 'answer' : 'answers'}{q.answers.length > known.length ? `, ${q.answers.length - known.length} not sure` : ''}
              {[...tally].map(([choice, n]) => ` · ${choice}: ${n}`).join('')}</p>
            {known.length > 0 && (
              <ul className="space-y-1.5">
                {known.map((a, i) => (
                  <li key={`${a.number}-${i}`} className="rounded-lg bg-surface px-3 py-2 text-[14px]">
                    {a.choice && <b className="mr-1.5">{a.choice}</b>}{a.answer && <span className="whitespace-pre-wrap">{a.answer}</span>}
                    <span className="ml-2 text-[12px] text-ink-3">{formatDate(a.at, true)}</span>
                  </li>
                ))}
              </ul>
            )}
          </section>
        );
      })}
    </div>
  );
}

function CaseEditor({entry, onSaved}: {entry: CaseEntry; onSaved: () => void}) {
  const site = useCasesSite()!;
  const current = site.edits.cases[entry.id] ?? {};
  const [draft, setDraft] = useState<CaseEdit>(current);
  const [turns, setTurns] = useState<Case['turns'] | null>(null);
  const [state, setState] = useState<'idle' | 'saving' | 'saved' | string>('idle');
  useEffect(() => {
    fetch(`./${entry.id}.json`, {cache: 'no-cache'}).then(r => r.ok ? r.json() as Promise<Case> : null).then(c => setTurns(c?.turns ?? [])).catch(() => setTurns([]));
  }, [entry.id]);
  const save = async (edit: CaseEdit) => {
    setState('saving');
    try {
      site.setEdits(await new FeedbackClient(site.config!).saveEdit(entry.id, edit));
      setDraft(edit);
      setState('saved');
      onSaved();
    } catch (e) { setState(e instanceof Error ? e.message : 'Not saved. Try again.'); }
  };
  return (
    <div className="space-y-3 border-t border-line px-5 py-4" data-testid="admin-case-editor">
      <label className="flex flex-col gap-1.5 text-[13px] text-ink-2">Title
        <input value={draft.title ?? ''} placeholder={entry.title} maxLength={120} onChange={e => setDraft({...draft, title: e.target.value})} className={field} data-testid="admin-edit-title" />
      </label>
      <label className="flex flex-col gap-1.5 text-[13px] text-ink-2">Takeaway
        <textarea value={draft.takeaway ?? entry.takeaway} rows={2} maxLength={400} onChange={e => setDraft({...draft, takeaway: e.target.value})} className={cn(field, 'resize-y')} />
      </label>
      <label className="inline-flex items-center gap-2 text-[13.5px] text-ink-2">
        <input type="checkbox" checked={!!draft.hidden} onChange={e => setDraft({...draft, hidden: e.target.checked})} className="size-4" data-testid="admin-edit-hidden" />
        Hide it from the gallery (its link still opens it)</label>
      <div className="space-y-2">
        <p className="text-[13px] text-ink-2">Notes from the editors, shown above an answer (a correction, a caveat). Wizard's answer itself is not changed.</p>
        {turns === null ? <p className="text-[13px] text-ink-3">Loading the answers…</p> : turns.map(t => (
          <label key={t.n} className="flex flex-col gap-1 text-[12.5px] text-ink-3">Answer {t.n}: {t.prompt.slice(0, 110)}{t.prompt.length > 110 ? '…' : ''}
            <textarea rows={2} maxLength={800} value={draft.notes?.[String(t.n)] ?? ''} className={cn(field, 'resize-y')} data-testid="admin-edit-note"
              onChange={e => setDraft({...draft, notes: {...draft.notes, [String(t.n)]: e.target.value}})} />
          </label>
        ))}
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <button type="button" onClick={() => void save(draft)} disabled={state === 'saving'} data-testid="admin-edit-save"
          className="inline-flex min-h-10 items-center gap-2 rounded-[10px] bg-[#1428a0] px-4 text-[14px] font-semibold text-white disabled:opacity-60">
          {state === 'saving' && <Loader2 className="size-4 animate-spin" />}Save</button>
        <button type="button" className={small} disabled={state === 'saving'} onClick={() => void save({})}>Undo every edit</button>
        {state === 'saved' && <span className="text-[13px] text-ok">Saved: everyone sees it now.</span>}
        {!['idle', 'saving', 'saved'].includes(state) && <span role="alert" className="text-[13px] text-danger">{state}</span>}
      </div>
    </div>
  );
}

function EditTab({cases}: {cases: CaseEntry[]}) {
  const site = useCasesSite()!;
  const [open, setOpen] = useState<string | null>(null);
  return (
    <div className="space-y-3" data-testid="admin-edit">
      <p className="text-[13.5px] text-ink-2">Edits show over what Wizard published, for everyone who opens the site. To take a case off the site, remove it in Wizard (Share as case → Remove from the site).</p>
      {cases.length === 0 && <p className="text-[14px] text-ink-2">No cases yet.</p>}
      {cases.map(c => {
        const edit = site.edits.cases[c.id];
        return (
          <section key={c.id} className="rounded-2xl border border-line bg-canvas">
            <button type="button" onClick={() => setOpen(open === c.id ? null : c.id)} aria-expanded={open === c.id} data-testid="admin-edit-case"
              className="flex w-full flex-wrap items-center gap-x-3 gap-y-1 px-5 py-3 text-left hover:bg-surface">
              <span className="text-[15.5px] font-semibold">{edit?.title || c.title}</span>
              {edit?.hidden && <span className="rounded-full bg-surface-2 px-2 py-0.5 text-[12px] text-ink-2">hidden</span>}
              {edit && !edit.hidden && <span className="rounded-full bg-warn-soft px-2 py-0.5 text-[12px] text-warn">edited</span>}
              <span className="ml-auto text-[12.5px] text-ink-3">{formatDate(c.published_at)}</span>
            </button>
            {open === c.id && <CaseEditor entry={c} onSaved={() => undefined} />}
          </section>
        );
      })}
    </div>
  );
}

/** The admin pane (owner, 12 Nov 2026), opened with the PIN: every rating and comment by case, every quiz answer by
 *  question, and edits to the cases. It reads the feedback repository's issues with the site's token. */
export function AdminPage({cases, home}: {cases: CaseEntry[]; home: string}) {
  const site = useCasesSite();
  const [tab, setTab] = useState<Tab>(() => (new URLSearchParams(location.search).get('admin') as Tab) || 'feedback');
  const [data, setData] = useState<ReturnType<typeof parseIssues> | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState<number | null>(null);
  const client = useMemo(() => site?.config ? new FeedbackClient(site.config) : null, [site?.config]);
  const load = useCallback(async () => {
    if (!client) return;
    setLoading(true);
    setError(null);
    try {
      const [issues, edits] = await Promise.all([client.issues(), client.edits()]);
      setData(parseIssues(issues));
      site?.setEdits(edits);
    } catch (e) { setError(e instanceof Error ? e.message : 'The feedback could not be read.'); }
    setLoading(false);
  }, [client]);
  useEffect(() => { void load(); }, [load]);
  if (!site?.config || !site.admin) {
    return (
      <div className="min-h-dvh bg-page text-ink">
        <SiteTop home={home} page="admin" />
        <p className="mx-auto max-w-[860px] px-4 pt-10 text-[15px] text-ink-2 md:px-8" data-testid="admin-closed">
          {site?.config ? 'The admin pane is closed: choose Admin at the top right and enter the PIN.' : 'This site takes no feedback yet.'}</p>
      </div>
    );
  }
  const setState = async (n: number, open: boolean) => {
    setBusy(n);
    try {
      await client!.setOpen(n, open);
      setData(d => d && {...d, feedback: d.feedback.map(f => f.number === n ? {...f, open} : f)});
    } catch (e) { setError(e instanceof Error ? e.message : 'Not changed.'); }
    setBusy(null);
  };
  const choose = (t: Tab) => { setTab(t); history.replaceState(null, '', `?admin=${t}`); };
  const counts: Record<Tab, number | null> = {feedback: data?.feedback.filter(f => f.open).length ?? null, quiz: data?.quiz.length ?? null, edit: null};
  const tabs: [Tab, string][] = [['feedback', 'Feedback'], ['quiz', 'Quiz answers'], ['edit', 'Edit cases']];
  return (
    <div className="min-h-dvh bg-page text-ink" data-testid="admin-page">
      <SiteTop home={home} page="admin" />
      <main className="mx-auto flex max-w-[1040px] flex-col gap-5 px-4 pb-20 pt-8 md:px-8">
        <div className="flex flex-wrap items-end gap-3">
          <div className="space-y-1">
            <h1 className="text-[30px] font-bold leading-tight">Admin pane</h1>
            <p className="text-[14px] text-ink-2">Everyone's feedback and quiz answers, sent anonymously, kept as issues in {site.config.repo}.</p>
          </div>
          <button type="button" onClick={() => void load()} disabled={loading} className={cn(small, 'ml-auto')} data-testid="admin-refresh">
            {loading ? <Loader2 className="size-4 animate-spin" /> : <RefreshCw className="size-4" />}Refresh</button>
        </div>
        <div role="tablist" aria-label="Admin" className="flex flex-wrap gap-2">
          {tabs.map(([id, label]) => (
            <button key={id} type="button" role="tab" aria-selected={tab === id} onClick={() => choose(id)} data-testid={`admin-tab-${id}`}
              className={cn('min-h-11 rounded-full border px-4 text-[14px]', tab === id ? 'border-[#1428a0] bg-[#1428a0] font-semibold text-white' : 'border-line-2 bg-canvas font-medium hover:bg-surface')}>
              {label}{counts[id] !== null ? ` · ${counts[id]}` : ''}</button>
          ))}
        </div>
        {error && <p role="alert" className="rounded-[10px] border border-danger-line bg-danger-soft px-4 py-2.5 text-[14px] text-danger">{error}</p>}
        {tab === 'edit' ? <EditTab cases={cases} /> : !data ? <p className="text-[14px] text-ink-3">{loading ? 'Reading the feedback…' : ''}</p>
          : tab === 'feedback' ? <FeedbackTab cases={cases.map(c => edited(c, site.edits))} feedback={data.feedback} onState={(n, o) => void setState(n, o)} busy={busy} />
          : <QuizTab received={data.quiz} />}
      </main>
    </div>
  );
}
