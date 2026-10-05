import {useEffect, useState} from 'react';
import {ArrowRight} from 'lucide-react';
import {api} from '@/api';

/** Development sign-in with SYNTHETIC test identities. Pilot and production use corporate SSO in front of Wizard. */
export function LoginScreen({mode, onLogin}: {mode: 'fixture' | 'trusted-header'; onLogin: () => void}) {
  const [identities, setIdentities] = useState<{id: string; name: string; role: string; email: string}[]>([]);
  const [notice, setNotice] = useState('');
  useEffect(() => { if (mode === 'fixture') api.identities().then(r => { setIdentities(r.identities); setNotice(r.notice); }).catch(() => undefined); }, [mode]);
  return (
    <div className="grid min-h-dvh place-items-center bg-page p-6">
      <div className="w-[min(520px,100%)] rounded-card border border-line bg-canvas p-8 shadow-card" data-testid="login">
        <p className="text-xs font-semibold uppercase tracking-[0.18em] text-accent">Wizard</p>
        <h1 className="mt-2 text-2xl font-semibold tracking-tight">Sign in</h1>
        {mode === 'trusted-header' ? <p className="mt-3 text-sm text-ink-2">Sign in through your company's single sign-on, then reload this page.</p> : <>
          <p className="mt-3 text-sm text-ink-2">{identities[0]?.id === 'local-owner'
            ? 'Choose yourself (Owner) to ask questions with your own Gemini account. The SYNTHETIC test identities only show how source rights change answers; no real Google account can be linked to them.'
            : 'Choose a test identity. Each one has different source rights, so answers and visible reports differ.'}</p>
          <ul className="mt-5 space-y-2">
            {identities.map(identity => (
              <li key={identity.id}>
                <button type="button" onClick={async () => { await api.login(identity.id); onLogin(); }} data-testid={`login-${identity.id}`}
                  className="group flex w-full items-center gap-3 rounded-xl border border-line px-4 py-3 text-left hover:border-accent-line hover:bg-accent-soft/40">
                  <span className="min-w-0 flex-1"><span className="block text-sm font-medium">{identity.name}</span><span className="block text-xs text-ink-3">{identity.id === 'local-owner' ? `${identity.role} · you, with your own Google account` : `${identity.role} · ${identity.email}`}</span></span>
                  <ArrowRight className="size-4 text-ink-3 group-hover:text-accent" />
                </button>
              </li>
            ))}
          </ul>
          {notice && <p className="mt-4 rounded-lg bg-warn-soft px-3 py-2 text-xs text-warn">{notice}</p>}
        </>}
      </div>
    </div>
  );
}
