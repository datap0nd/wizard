import {useState} from 'react';
import {CheckCircle2, ExternalLink, KeyRound, Unlink} from 'lucide-react';
import {api, ApiError} from '@/api';
import {formatDate} from '@/format';
import {Button} from './ui/button';
import type {Bootstrap, GeminiAccount} from '@/types';

/** Link the person's own enterprise Gemini account (Gemini CLI's user-code OAuth flow): in Account, and in Quick setup.
 *  Wizard never sees the password. `tone="setup"` shows the linked state as a confirmation, without Unlink. */
export function GeminiLink({boot, onChanged, tone = 'account'}: {boot: Bootstrap; onChanged: (a: GeminiAccount) => void;
  tone?: 'account' | 'setup'}) {
  const [pending, setPending] = useState<{url: string; state: string} | null>(null);
  const [code, setCode] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [working, setWorking] = useState(false);
  const account = boot.gemini_account;
  async function start() {
    setError(null);
    try { const r = await api.linkStart(); setPending({url: r.authorize_url, state: r.state}); window.open(r.authorize_url, '_blank', 'noopener'); }
    catch (e) { setError(e instanceof ApiError ? e.message : 'Could not start the sign-in.'); }
  }
  async function complete() {
    if (!pending) return;
    setWorking(true); setError(null);
    try { onChanged(await api.linkComplete(pending.state, code.trim())); setPending(null); setCode(''); }
    catch (e) { setError(e instanceof ApiError ? e.message : 'The code was not accepted.'); }
    finally { setWorking(false); }
  }
  const body = !account?.needs_link ? <p className="mt-2 text-ink-3" data-testid="gemini-no-link">Replay mode does not call Gemini, so no account is needed.</p>
    : account.link_note && !account.linked ? <p className="mt-3 rounded-lg bg-warn-soft px-3 py-2 text-ink" data-testid="link-note">{account.link_note}</p>
    : account.linked ? <div className="mt-3 space-y-2" data-testid="gemini-linked">
        <p className="flex items-center gap-1.5">{tone === 'setup' && <CheckCircle2 className="size-4 shrink-0 text-emerald-700" />}
          <span>Linked{account.google_email ? <> as <strong>{account.google_email}</strong></> : ' through a host sign-in'}{account.linked_at ? ` on ${formatDate(account.linked_at, true)}` : ''}.</span></p>
        <p className="text-xs text-ink-3">Questions run under this account only. Token storage: {account.secret_store}.</p>
        {tone === 'account' && <Button variant="outline" size="sm" onClick={async () => onChanged(await api.unlink())}><Unlink />Unlink</Button>}
      </div>
    : <div className="mt-3 space-y-3">
        {tone === 'account' && <p className="text-ink-2">Wizard runs your questions under your own enterprise Gemini entitlement, never someone else's.</p>}
        <ol className="list-decimal space-y-2 pl-5 text-[13.5px]">
          <li><Button size="sm" variant="accent" onClick={() => void start()} data-testid="link-start"><ExternalLink />Sign in with Google</Button>
            <span className="mt-1 block text-xs text-ink-3">{account.adopts_google_email || !boot.identity?.email ? 'Use your own enterprise Google account' : `Use your own enterprise account (${boot.identity.email})`}. A new tab opens at Google.</span></li>
          <li>After signing in, Google shows an authorization code. Paste it here:
            <form className="mt-2 flex gap-2" onSubmit={e => { e.preventDefault(); void complete(); }}>
              <input value={code} onChange={e => setCode(e.target.value)} disabled={!pending} placeholder={pending ? 'Authorization code' : 'Start the sign-in first'}
                aria-label="Authorization code" className="h-9 flex-1 rounded-lg border border-line px-3 text-sm outline-none focus:border-line-2" />
              <Button type="submit" size="sm" disabled={!pending || code.trim().length < 4 || working}><KeyRound />Link</Button>
            </form>
            {pending && <a className="mt-1 block text-xs text-accent underline" href={pending.url} target="_blank" rel="noopener noreferrer">Open the Google sign-in again</a>}
          </li>
        </ol>
      </div>;
  return <>{body}{error && <p className="mt-3 rounded-lg bg-danger-soft px-3 py-2 text-danger" role="alert">{error}</p>}</>;
}
