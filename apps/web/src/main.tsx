import {StrictMode} from 'react';
import {createRoot} from 'react-dom/client';
import {App} from './App';
import {BrainPage} from './components/brain/BrainPage';
import {ReportPage} from './components/ReportPage';
import {TooltipProvider} from './components/ui/menu';
import './styles.css';

const report = location.pathname.match(/^\/r\/([A-Za-z0-9_-]{4,64})\/?$/);
// /brain: a page of its own for showing Wizard to people; the app itself is unchanged.
const brain = /^\/brain\/?$/.test(location.pathname);

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <TooltipProvider delayDuration={250}>{brain ? <BrainPage /> : report ? <ReportPage id={report[1]} /> : <App compact={/^\/quick\/?$/.test(location.pathname)} />}</TooltipProvider>
  </StrictMode>,
);
