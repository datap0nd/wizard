import {StrictMode} from 'react';
import {createRoot} from 'react-dom/client';
import {App} from './App';
import {ReportPage} from './components/ReportPage';
import {TooltipProvider} from './components/ui/menu';
import './styles.css';

const report = location.pathname.match(/^\/r\/([A-Za-z0-9_-]{4,64})\/?$/);

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <TooltipProvider delayDuration={250}>{report ? <ReportPage id={report[1]} /> : <App />}</TooltipProvider>
  </StrictMode>,
);
