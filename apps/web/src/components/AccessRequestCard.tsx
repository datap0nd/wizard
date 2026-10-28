import {useState} from 'react';
import {AlertTriangle, Check, ExternalLink, Globe, ListChecks, Loader2, Table2} from 'lucide-react';
import {api} from '@/api';
import {Button} from './ui/button';
import {Row} from './RecurringCard';
import {SystemLogo} from './SystemLogo';
import type {AccessRequest} from '@/types';

function shortAddress(address: string): string {
  try {
    const url = new URL(address);
    const rest = url.pathname + url.search;
    return url.host + (rest.length > 60 ? `${rest.slice(0, 59)}…` : rest === '/' ? '' : rest);
  } catch {
    return address;
  }
}

/** An access request Gemini prepared in a portal's information catalog. Nothing is sent: Open the request form opens
 *  the page in Wizard's browser window on this PC, with the person's saved answers and this request's filled into the
 *  form's empty fields; they check every field and submit the request there themselves. */
export function AccessRequestCard({request}: {request: AccessRequest}) {
  const [state, setState] = useState<'ready' | 'opening' | 'open'>('ready');
  const [error, setError] = useState<string | null>(null);
  const tables = request.tables.join(', ');

  async function open() {
    setState('opening'); setError(null);
    try {
      await api.openAccessRequest(request.system, {address: request.address, tables: request.tables, answers: request.answers});
      setState('open');
    } catch (e) {
      setError(e instanceof Error ? e.message : 'The request form could not be opened.');
      setState('ready');
    }
  }

  return (
    <section className="rounded-xl border border-line bg-canvas" aria-label={`Access request${tables ? ` for ${tables}` : ''}`}
      data-testid="access-request-card" data-state={state}>
      <header className="flex items-center gap-2.5 border-b border-line px-4 py-2.5">
        <SystemLogo id={request.system} name={request.portal} size={28} />
        <div className="min-w-0 flex-1">
          <p className="truncate text-sm font-semibold">Request access{tables ? ` to ${tables}` : ''}</p>
          <p className="text-xs text-ink-3">{request.portal} · information catalog</p>
        </div>
      </header>
      <div className="space-y-1.5 px-4 py-3">
        {tables && <Row icon={Table2} label="Tables">{tables}</Row>}
        <Row icon={Globe} label="Opens">{shortAddress(request.address)}</Row>
        <Row icon={ListChecks} label="Fills in">
          {request.saved.length > 0 ? <>Your saved answers ({request.saved.join(', ')})</> : <>No saved answers yet</>}
          {request.answers.length > 0 && <>; for this request: {request.answers.map(a => a.label).join(', ')}</>}
        </Row>
        {request.saved.length === 0 && (
          <p className="text-xs text-ink-3">Add the answers you give on every request in Settings → Portals → Access request form.</p>
        )}
      </div>
      <footer className="flex flex-wrap items-center gap-2 border-t border-line px-4 py-2.5 text-[13px]">
        {state === 'open' ? (
          <p className="flex items-start gap-1.5 text-ok" role="status" data-testid="access-request-open">
            <Check className="mt-0.5 size-4 shrink-0" />
            <span>Open in Wizard's browser window on this PC. Check every field Wizard filled (outlined), submit the request
              there, then close the window. Until then Wizard waits to read the portals.</span>
          </p>
        ) : (
          <>
            <Button size="sm" onClick={() => void open()} disabled={state === 'opening'} data-testid="access-request-open-form">
              {state === 'opening' ? <Loader2 className="animate-spin" /> : <ExternalLink />}Open the request form
            </Button>
            <span className="text-xs text-ink-3">Nothing is requested until you submit the form yourself.</span>
          </>
        )}
        {error && <p className="flex w-full items-start gap-1.5 text-danger" role="alert"><AlertTriangle className="mt-0.5 size-4 shrink-0" />{error}</p>}
      </footer>
    </section>
  );
}
