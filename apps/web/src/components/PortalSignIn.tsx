import {useCallback, useEffect, useState} from 'react';
import {CheckCircle2, Globe, Loader2, LogIn, XCircle} from 'lucide-react';
import {api, ApiError} from '@/api';
import {formatDate} from '@/format';
import {cn} from '@/lib/utils';
import {Button} from './ui/button';
import {AccessRequestForm} from './AccessRequestForm';
import {PortalMaps} from './PortalMaps';
import type {PortalCheck, PortalStatus} from '@/types';

/** A portal's name, with its applications when it has several: "Big Data Portal (Superset, information catalog)". */
export function portalLabel(portal: PortalStatus['portals'][number]): string {
  return portal.parts?.length ? `${portal.name} (${portal.parts.map(p => p.name).join(', ')})` : portal.name;
}

/** Where a check that found no sign-in ended up: the page's title and host say whether it is the sign-in page. */
function landed(p: PortalCheck['portals'][number]): string {
  const where = [p.title, p.host].filter(Boolean).join(' · ');
  return where ? ` (${where})` : '';
}

/** Signing in to the company portals in Wizard's own browser: a visible window opens on this PC with one tab per
 * portal; the person signs in and closes it, and Gemini then reads the portals in the background with that sign-in. */
export function PortalSignIn({compact = false}: {compact?: boolean}) {
  const [status, setStatus] = useState<PortalStatus | null | 'none'>(null);
  const [busy, setBusy] = useState<'sign-in' | 'done' | 'check' | null>(null);
  const [check, setCheck] = useState<PortalCheck | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    api.portals().then(setStatus).catch(e => setStatus(e instanceof ApiError && e.status === 404 ? 'none' : null));
  }, []);
  useEffect(load, [load]);

  async function act(kind: 'sign-in' | 'done' | 'check') {
    setBusy(kind); setError(null);
    try {
      if (kind === 'check') setCheck(await api.portalCheck());
      else setStatus(kind === 'sign-in' ? await api.portalSignIn() : await api.portalSignedIn());
    } catch (e) {
      setError(e instanceof Error ? e.message : 'That did not work.');
    } finally {
      setBusy(null);
    }
  }

  if (status === null) return null;
  if (status === 'none') {
    return compact ? null : <p className="mt-3 text-xs text-ink-3" data-testid="portals-none">Fill in a portal's address and save: Wizard restarts and the sign-in button appears here.</p>;
  }
  return (<>
    <div className={cn('space-y-2', compact ? '' : 'mt-3 rounded-lg bg-surface px-3 py-3')} data-testid="portal-sign-in">
      {!compact && (
        <p className="flex items-center gap-1.5 text-xs text-ink-2"><Globe className="size-3.5" />
          {status.browser} · {status.portals.map(portalLabel).join(', ')}
          {status.last_sign_in ? ` · last signed in ${formatDate(status.last_sign_in, true)}` : ' · not signed in yet'}</p>
      )}
      {status.signing_in ? (
        <div className="flex flex-wrap items-center gap-2">
          <p className="flex-1 text-xs text-ink-2" role="status">{status.window === 'access_request'
            ? `An access request form is open in Wizard's browser window on this PC${status.access_request?.filled.length
              ? `; Wizard filled ${status.access_request.filled.join(', ')}` : ''}. Check every field, submit it there yourself, then close the window or press Done.`
            : 'A Wizard browser window is open on this PC. Sign in to each portal there, then close the window or press Done.'}</p>
          <Button size="xs" variant="accent" onClick={() => void act('done')} disabled={busy !== null} data-testid="portal-done">
            {busy === 'done' ? <Loader2 className="animate-spin" /> : <CheckCircle2 />}Done</Button>
        </div>
      ) : (
        <div className="flex flex-wrap items-center gap-2">
          <Button size="xs" variant={compact ? 'accent' : 'outline'} onClick={() => void act('sign-in')} disabled={busy !== null} data-testid="portal-sign-in-open">
            {busy === 'sign-in' ? <Loader2 className="animate-spin" /> : <LogIn />}Sign in to the portals</Button>
          {!compact && (
            <Button size="xs" variant="ghost" onClick={() => void act('check')} disabled={busy !== null} data-testid="portal-check">
              {busy === 'check' ? <Loader2 className="animate-spin" /> : <CheckCircle2 />}Check sign-in</Button>
          )}
        </div>
      )}
      {check && (
        <ul className="space-y-1 text-xs" data-testid="portal-check-result">
          {check.portals.map(p => (
            <li key={p.id} className={cn('flex items-center gap-1.5', p.signed_in ? 'text-emerald-800' : 'text-danger')}>
              {p.signed_in ? <CheckCircle2 className="size-3.5" /> : <XCircle className="size-3.5" />}
              {p.name}: {p.signed_in ? 'signed in' : p.error ?? `asks for a sign-in${landed(p)}`}
            </li>
          ))}
        </ul>
      )}
      {error && <p className="text-xs text-danger" role="alert">{error}</p>}
    </div>
    {!compact && <PortalMaps status={status} onChange={setStatus} />}
    {!compact && status.portals.filter(p => p.access_requests).map(p => <AccessRequestForm key={p.id} system={p.id} name={p.name} />)}
  </>);
}
