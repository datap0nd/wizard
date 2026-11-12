// The Pages site (services/api/wizard_api/site.py): Brain and Cases, two pages of their own on the company GitHub's
// Pages, built with relative paths (vite.site.config.ts) so they work wherever Pages serves the branch. Each folder's
// index.html says which page it is (data-page); the data sits beside it as JSON. Nothing here calls Wizard's API.
import {lazy, StrictMode, Suspense, useEffect, useState} from 'react';
import {createRoot} from 'react-dom/client';
import type {BrainSnapshot} from './brain';
import {CASE_ID, type Case, type CaseIndex} from './cases';
import {CasesSiteContext, type CasesSite} from './components/cases/SiteChrome';
import {TooltipProvider} from './components/ui/menu';
import {FeedbackClient, memory, NO_EDITS, readConfig, type Edits, type FeedbackConfig, type Quiz} from './feedback';
import './styles.css';

const BrainPage = lazy(() => import('./components/brain/BrainPage').then(m => ({default: m.BrainPage})));
const CasePage = lazy(() => import('./components/cases/CasePage').then(m => ({default: m.CasePage})));
const CasesGallery = lazy(() => import('./components/cases/CasePage').then(m => ({default: m.CasesGallery})));
const QuizPage = lazy(() => import('./components/cases/QuizPage').then(m => ({default: m.QuizPage})));
const AdminPage = lazy(() => import('./components/cases/AdminPage').then(m => ({default: m.AdminPage})));

async function read<T>(path: string): Promise<T> {
  const response = await fetch(path, {cache: 'no-cache'});
  if (response.status === 404) throw new Error('Nothing has been published here yet.');
  if (!response.ok) throw new Error(`The page could not be read (HTTP ${response.status}).`);
  return await response.json() as T;
}

function Message({text, dark = false}: {text: string; dark?: boolean}) {
  return <div className={`grid min-h-dvh place-items-center p-6 text-sm ${dark ? 'bg-[#0f1117] text-slate-400' : 'bg-page text-ink-2'}`} role="status">{text}</div>;
}

function Brain() {
  const [snapshot, setSnapshot] = useState<BrainSnapshot | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => { read<BrainSnapshot>('./brain.json').then(setSnapshot).catch((e: unknown) => setError(e instanceof Error ? e.message : String(e))); }, []);
  if (error) return <Message text={error} dark />;
  if (!snapshot) return <Message text="Loading the knowledge graph…" dark />;
  return <Suspense fallback={<Message text="Loading the knowledge graph…" dark />}><BrainPage snapshot={snapshot} /></Suspense>;
}

/** The feedback set-up Wizard published beside the pages (null: feedback is off), the admin pane's edits read from
 *  GitHub with it, and the quiz. A page waits for them so a hidden case never flashes in the gallery. */
function useFeedback(): {config: FeedbackConfig | null; edits: Edits; quiz: Quiz | null; ready: boolean; setEdits: (e: Edits) => void} {
  const [config, setConfig] = useState<FeedbackConfig | null | undefined>(undefined);
  const [edits, setEdits] = useState<Edits | undefined>(undefined);
  const [quiz, setQuiz] = useState<Quiz | null | undefined>(undefined);
  useEffect(() => {
    void readConfig().then(found => {
      setConfig(found);
      if (!found) { setEdits(NO_EDITS); return; }
      new FeedbackClient(found).edits().then(setEdits).catch(() => setEdits(NO_EDITS));
    });
    read<Quiz>('./quiz.json').then(found => setQuiz(Array.isArray(found?.sections) ? found : null)).catch(() => setQuiz(null));
  }, []);
  return {config: config ?? null, edits: edits ?? NO_EDITS, quiz: quiz ?? null, setEdits,
    ready: config !== undefined && edits !== undefined && quiz !== undefined};
}

function Cases() {
  const params = new URLSearchParams(location.search);
  const id = params.get('case');
  const view = id !== null ? 'case' : params.has('admin') ? 'admin' : params.has('quiz') ? 'quiz' : 'gallery';
  const [index, setIndex] = useState<CaseIndex | null>(null);
  const [item, setItem] = useState<Case | null>(null);
  const [error, setError] = useState<string | null>(null);
  const feedback = useFeedback();
  const [admin, setAdmin] = useState(() => memory.admin());
  useEffect(() => {
    const fail = (e: unknown) => setError(e instanceof Error ? e.message : String(e));
    if (id === null) {
      read<CaseIndex>('./cases.json').then(setIndex).catch(view === 'gallery' ? fail : () => setIndex({format: 1, updated: '', cases: []}));
      return;
    }
    if (!CASE_ID.test(id)) { setError('There is no case at this address.'); return; }
    read<Case>(`./${id}.json`).then(found => { setItem(found); document.title = `${found.title} · Cases`; })
      .catch(() => setError('This case is no longer on the site.'));
  }, [id, view]);
  useEffect(() => { if (view === 'quiz') document.title = 'Quiz · Cases'; if (view === 'admin') document.title = 'Admin · Cases'; }, [view]);
  const site: CasesSite = {config: feedback.config, edits: feedback.edits, setEdits: feedback.setEdits, quiz: feedback.quiz,
    admin: admin && !!feedback.config, setAdmin: on => { memory.setAdmin(on); setAdmin(on); }};
  if (error) return <Message text={error} />;
  if (!feedback.ready) return <Message text="Loading…" />;
  const page = view === 'case' && item ? <CasePage item={item} home="./" />
    : view === 'quiz' ? <QuizPage home="./" section={params.get('quiz') || null} />
    : view === 'admin' && index ? <AdminPage cases={index.cases} home="./" />
    : view === 'gallery' && index ? <CasesGallery cases={index.cases} home="./" /> : null;
  if (!page) return <Message text="Loading…" />;
  return <CasesSiteContext.Provider value={site}><Suspense fallback={<Message text="Loading…" />}>{page}</Suspense></CasesSiteContext.Provider>;
}

const page = document.documentElement.dataset.page;
createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <TooltipProvider delayDuration={250}>{page === 'brain' ? <Brain /> : page === 'cases' ? <Cases /> : <Message text="Open a page of the site." />}</TooltipProvider>
  </StrictMode>,
);
