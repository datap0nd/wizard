import {useEffect, useState} from 'react';
import {ArrowLeft, Printer} from 'lucide-react';
import {api, ApiError} from '@/api';
import {placedVisuals} from '@/citations';
import {formatDate} from '@/format';
import {AnswerMarkdown} from './AnswerMarkdown';
import {CheckBadge, DataModeBadge, RuntimeBadge} from './Badges';
import {EvidenceDrawer} from './EvidenceDrawer';
import {Button} from './ui/button';
import {VisualBlock} from './VisualBlock';
import type {Report} from '@/types';

/** The dated web report behind a stable link. Reopening re-checks the viewer's current source rights. */
export function ReportPage({id}: {id: string}) {
  const [report, setReport] = useState<Report | null>(null);
  const [error, setError] = useState<{status: number; message: string} | null>(null);
  const [focus, setFocus] = useState<string | null>(null);
  const [drawer, setDrawer] = useState(false);
  useEffect(() => {
    api.report(id).then(r => setReport(r.report)).catch((e: unknown) => setError(e instanceof ApiError ? {status: e.status, message: e.message} : {status: 0, message: 'The report could not be loaded.'}));
  }, [id]);
  if (error) return (
    <div className="grid min-h-dvh place-items-center bg-page p-6">
      <div className="max-w-md rounded-card border border-line bg-canvas p-8 text-center shadow-card" role="alert" data-testid="report-error" data-status={error.status}>
        <h1 className="text-lg font-semibold">{error.status === 401 ? 'Sign in to open this report' : error.status === 403 ? 'Access has changed' : error.status === 410 ? 'Report expired' : 'Report not available'}</h1>
        <p className="mt-2 text-sm text-ink-2">{error.message}</p>
        <a href="/" className="mt-4 inline-block text-sm text-accent underline">Go to Wizard</a>
      </div>
    </div>
  );
  if (!report) return <div className="grid min-h-dvh place-items-center text-sm text-ink-3">Loading report…</div>;
  const placed = placedVisuals(report.answer);
  const open = (evidenceId: string | null) => { setFocus(evidenceId); setDrawer(true); };
  return (
    <div className="min-h-dvh bg-page px-4 py-8" data-testid="report-page">
      <article className="mx-auto max-w-[920px] rounded-card border border-line border-t-[3px] border-t-accent bg-canvas shadow-card">
        <header className="border-b border-line px-6 py-6 sm:px-8">
          <div className="no-print mb-4 flex items-center gap-2">
            <a href="/" className="inline-flex items-center gap-1 text-[13px] text-ink-3 hover:text-ink"><ArrowLeft className="size-4" />Wizard</a>
            <Button variant="ghost" size="sm" className="ml-auto" onClick={() => window.print()}><Printer />Print</Button>
          </div>
          <p className="text-xs font-semibold uppercase tracking-[0.16em] text-accent">Wizard report · {formatDate(report.created_at, true)}</p>
          <h1 className="mt-2 text-[22px] font-semibold leading-snug tracking-tight">{report.question}</h1>
          <div className="mt-3 flex flex-wrap items-center gap-2">
            <DataModeBadge mode={report.data_mode} /><CheckBadge status={report.check.status} /><RuntimeBadge kind={report.runtime.kind} label={report.runtime.label} />
          </div>
          <p className="mt-2 text-xs text-ink-3">Prepared for {report.user.name} ({report.user.role}) · model {report.runtime.model} · kept until {formatDate(report.expires_at)}</p>
          {report.check.summary && <p className="mt-2 text-xs text-ink-2">Check: {report.check.summary}</p>}
        </header>
        <div className="px-6 py-6 sm:px-8">
          <AnswerMarkdown text={report.answer} visuals={report.visuals} onEvidence={open} />
          {report.visuals.filter(v => !placed.has(v.id)).map(v => <VisualBlock key={v.id} visual={v} onEvidence={open} />)}
          {report.warnings.length > 0 && <ul className="mt-4 space-y-1 rounded-xl border border-warn-line bg-warn-soft px-4 py-2 text-[13px] text-warn">{report.warnings.map(w => <li key={w}>{w}</li>)}</ul>}
        </div>
        <section className="border-t border-line px-6 py-5 sm:px-8">
          <h2 className="text-sm font-semibold">Sources consulted</h2>
          <ul className="mt-2 space-y-1.5 text-[13px]">
            {report.evidence.map(e => <li key={e.id} className="flex flex-wrap items-center gap-2">
              <button type="button" onClick={() => open(e.id)} className="rounded bg-accent-soft px-1.5 text-[11px] font-semibold text-accent">{e.id}</button>
              <span>{e.system.toUpperCase()} · {e.report_name}</span><span className="text-ink-3">as of {formatDate(e.as_of, true)} · {e.total_rows} rows</span>
            </li>)}
            {report.evidence.length === 0 && <li className="text-ink-3">No source data was retrieved.</li>}
          </ul>
        </section>
        <footer className="border-t border-line px-6 py-4 text-[11.5px] text-ink-3 sm:px-8">Report {report.id} · run {report.run_id}{report.runtime.session_id ? ` · session ${report.runtime.session_id}` : ''}. Data mode describes where the data came from; it does not certify the interpretation.</footer>
      </article>
      <EvidenceDrawer conversationId={null} open={drawer} focus={focus} items={report.evidence} preloaded={report.evidence} onClose={() => setDrawer(false)} />
    </div>
  );
}
