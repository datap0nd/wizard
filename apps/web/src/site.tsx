// The Pages site (services/api/wizard_api/site.py): Brain and Cases, two pages of their own on the company GitHub's
// Pages, built with relative paths (vite.site.config.ts) so they work wherever Pages serves the branch. Each folder's
// index.html says which page it is (data-page); the data sits beside it as JSON. Nothing here calls Wizard's API.
import {lazy, StrictMode, Suspense, useEffect, useState} from 'react';
import {createRoot} from 'react-dom/client';
import type {BrainSnapshot} from './brain';
import {CASE_ID, type Case, type CaseIndex} from './cases';
import {TooltipProvider} from './components/ui/menu';
import './styles.css';

const BrainPage = lazy(() => import('./components/brain/BrainPage').then(m => ({default: m.BrainPage})));
const CasePage = lazy(() => import('./components/cases/CasePage').then(m => ({default: m.CasePage})));
const CasesGallery = lazy(() => import('./components/cases/CasePage').then(m => ({default: m.CasesGallery})));

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

function Cases() {
  const id = new URLSearchParams(location.search).get('case');
  const [index, setIndex] = useState<CaseIndex | null>(null);
  const [item, setItem] = useState<Case | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    const fail = (e: unknown) => setError(e instanceof Error ? e.message : String(e));
    if (id === null) { read<CaseIndex>('./cases.json').then(setIndex).catch(fail); return; }
    if (!CASE_ID.test(id)) { setError('There is no case at this address.'); return; }
    read<Case>(`./${id}.json`).then(found => { setItem(found); document.title = `${found.title} · Cases`; })
      .catch(() => setError('This case is no longer on the site.'));
  }, [id]);
  if (error) return <Message text={error} />;
  if (id !== null && item) return <Suspense fallback={<Message text="Loading the case…" />}><CasePage item={item} home="./" /></Suspense>;
  if (id === null && index) return <Suspense fallback={<Message text="Loading the cases…" />}><CasesGallery cases={index.cases} home="./" /></Suspense>;
  return <Message text="Loading…" />;
}

const page = document.documentElement.dataset.page;
createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <TooltipProvider delayDuration={250}>{page === 'brain' ? <Brain /> : page === 'cases' ? <Cases /> : <Message text="Open a page of the site." />}</TooltipProvider>
  </StrictMode>,
);
