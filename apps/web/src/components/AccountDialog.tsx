import {useState} from 'react';
import {ExternalLink, KeyRound, Unlink} from 'lucide-react';
import {api, ApiError} from '@/api';
import {formatDate} from '@/format';
import {Button} from './ui/button';
import {Dialog, DialogContent} from './ui/dialog';
import type {Bootstrap, GeminiAccount} from '@/types';

/** Link the user's own enterprise Gemini account (Gemini CLI's user-code OAuth flow). Wizard never sees the password. */
export function AccountDialog({open, boot, onClose, onChanged}: {open: boolean; boot: Bootstrap; onClose: () => void; onChanged: (a: GeminiAccount) => void}) {
  const [pending, setPending] = useState<{url: string; state: string} | null>(null);
  const [code, setCode] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [working, setWorking] = useState(false);
  const account = boot.gemini_account;
  const runtime = boot.runtime;
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
  return (
    <Dialog open={open} onOpenChange={value => { if (!value) onClose(); }}>
      <DialogContent title="Your account" description={`${boot.identity?.name} · ${boot.identity?.email} · ${boot.identity?.role}`}>
        <div className="space-y-4 text-sm" data-testid="account-dialog">
          <section className="rounded-xl border border-line p-4">
            <h3 className="font-semibold">Gemini</h3>
            <p className="mt-1 text-ink-2">Runtime: {runtime?.label}. {runtime?.reason}</p>
            {!account?.needs_link ? <p className="mt-2 text-ink-3">Replay mode does not call Gemini, so no account is needed.</p>
              : account.linked ? <div className="mt-3 space-y-2">
                  <p>Linked{account.google_email ? <> as <strong>{account.google_email}</strong></> : ' through a host sign-in'}{account.linked_at ? ` on ${formatDate(account.linked_at, true)}` : ''}.</p>
                  <p className="text-xs text-ink-3">Questions run under this account only. Token storage: {account.secret_store}.</p>
                  <Button variant="outline" size="sm" onClick={async () => onChanged(await api.unlink())}><Unlink />Unlink</Button>
                </div>
              : <div className="mt-3 space-y-3">
                  <p className="text-ink-2">Wizard runs your questions under your own enterprise Gemini entitlement, never someone else's.</p>
                  <ol className="list-decimal space-y-2 pl-5 text-[13.5px]">
                    <li><Button size="sm" variant="accent" onClick={() => void start()} data-testid="link-start"><ExternalLink />Sign in with Google</Button>
                      <span className="mt-1 block text-xs text-ink-3">Use your own enterprise account ({boot.identity?.email}). A new tab opens at Google.</span></li>
                    <li>After signing in, Google shows an authorization code. Paste it here:
                      <form className="mt-2 flex gap-2" onSubmit={e => { e.preventDefault(); void complete(); }}>
                        <input value={code} onChange={e => setCode(e.target.value)} disabled={!pending} placeholder={pending ? 'Authorization code' : 'Start the sign-in first'}
                          aria-label="Authorization code" className="h-9 flex-1 rounded-lg border border-line px-3 text-sm outline-none focus:border-line-2" />
                        <Button type="submit" size="sm" disabled={!pending || code.trim().length < 4 || working}><KeyRound />Link</Button>
                      </form>
                      {pending && <a className="mt-1 block text-xs text-accent underline" href={pending.url} target="_blank" rel="noopener noreferrer">Open the Google sign-in again</a>}
                    </li>
                  </ol>
                </div>}
            {error && <p className="mt-3 rounded-lg bg-danger-soft px-3 py-2 text-danger" role="alert">{error}</p>}
          </section>
          <p className="text-xs text-ink-3">Source access comes from each system's own entitlements. Wizard shows only reports and markets you may see.</p>
        </div>
      </DialogContent>
    </Dialog>
  );
}
