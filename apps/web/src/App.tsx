import {useCallback, useEffect, useMemo, useRef, useState} from 'react';
import {AlertTriangle} from 'lucide-react';
import {api, ApiError, eventsUrl} from './api';
import {applyEvent, emptyRun, fromRecord, TERMINAL} from './runState';
import {AccountDialog} from './components/AccountDialog';
import {RuntimeBadge} from './components/Badges';
import {Composer} from './components/Composer';
import {Conversation} from './components/Conversation';
import {EmptyState} from './components/EmptyState';
import {EvidenceDrawer} from './components/EvidenceDrawer';
import {LoginScreen} from './components/LoginScreen';
import {Sidebar} from './components/Sidebar';
import {Button} from './components/ui/button';
import type {Bootstrap, ConversationSummary, EvidenceSummary, RunEvent, RunView} from './types';

const LAST = 'wizard-conversation';

export function App() {
  const [boot, setBoot] = useState<Bootstrap | null>(null);
  const [fatal, setFatal] = useState<string | null>(null);
  const [conversations, setConversations] = useState<ConversationSummary[]>([]);
  const [currentId, setCurrentId] = useState<string | null>(null);
  const [runs, setRuns] = useState<RunView[]>([]);
  const [draft, setDraft] = useState('');
  const [notice, setNotice] = useState<string | null>(null);
  const [drawer, setDrawer] = useState<{items: EvidenceSummary[]; focus: string | null} | null>(null);
  const [accountOpen, setAccountOpen] = useState(false);
  const streams = useRef(new Map<string, EventSource>());

  const refreshConversations = useCallback(async () => { try { setConversations((await api.conversations()).conversations); } catch { /* keep list */ } }, []);
  const loadBoot = useCallback(async () => {
    try { setBoot(await api.bootstrap()); } catch (e) { setFatal(e instanceof Error ? e.message : 'Wizard could not start.'); }
  }, []);

  const follow = useCallback((runId: string, after: number, parentId: string | null) => {
    streams.current.get(runId)?.close();
    const source = new EventSource(eventsUrl(runId, after));
    streams.current.set(runId, source);
    source.onmessage = message => {
      const event = JSON.parse(message.data) as RunEvent;
      setRuns(prev => prev.map(r => (r.id === runId ? applyEvent(r, event) : r)));
      if (TERMINAL.has(event.type)) {
        source.close(); streams.current.delete(runId);
        void refreshConversations();
        if (parentId) void api.run(parentId).then(record => setRuns(prev => prev.map(r => (r.id === parentId ? {...fromRecord(record), timeline: r.timeline, check: r.check} : r)))).catch(() => undefined);
      }
    };
    source.onerror = () => {
      if (source.readyState === EventSource.CLOSED) {
        streams.current.delete(runId);
        void api.run(runId).then(record => setRuns(prev => prev.map(r => (r.id === runId ? fromRecord(record) : r)))).catch(() => undefined);
      }
    };
  }, [refreshConversations]);

  const loadConversation = useCallback(async (id: string) => {
    const data = await api.conversation(id);
    streams.current.forEach(s => s.close()); streams.current.clear();
    setCurrentId(id); localStorage.setItem(LAST, id);
    const views = data.runs.map(fromRecord);
    setRuns(views);
    for (const record of data.runs) if (record.active) follow(record.id, Math.max(0, ...record.events.map(e => e.seq)), record.parent_run_id);
  }, [follow]);

  useEffect(() => { void loadBoot(); }, [loadBoot]);
  useEffect(() => {
    if (!boot?.identity) return;
    void refreshConversations();
    const last = localStorage.getItem(LAST);
    if (last) void loadConversation(last).catch(() => localStorage.removeItem(LAST));
  }, [boot?.identity?.id]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => () => { streams.current.forEach(s => s.close()); }, []);

  const busy = runs.some(r => r.status === 'running' || r.status === 'queued');
  const ask = useCallback(async (question: string) => {
    setNotice(null);
    try {
      const started = await api.ask(question, currentId);
      if (started.conversation_id !== currentId) { setCurrentId(started.conversation_id); localStorage.setItem(LAST, started.conversation_id); }
      setRuns(prev => [...(started.conversation_id === currentId ? prev : []), emptyRun(started.run_id, started.conversation_id, question)]);
      setDraft('');
      follow(started.run_id, 0, null);
      void refreshConversations();
    } catch (e) {
      setNotice(e instanceof ApiError && e.loginRequired ? 'Your session expired. Reload the page to sign in again.' : e instanceof Error ? e.message : 'The question could not be sent.');
    }
  }, [currentId, follow, refreshConversations]);

  const check = useCallback(async (run: RunView) => {
    try {
      const started = await api.check(run.id);
      setRuns(prev => [...prev, {...emptyRun(started.run_id, started.conversation_id, 'Check my data', 'check'), parentRunId: run.id}]);
      follow(started.run_id, 0, run.id);
    } catch (e) { setNotice(e instanceof Error ? e.message : 'The check could not start.'); }
  }, [follow]);

  const allEvidence = useMemo(() => {
    const seen = new Map<string, EvidenceSummary>();
    runs.forEach(r => r.evidence.forEach(e => seen.set(e.id, e)));
    return Array.from(seen.values());
  }, [runs]);

  const newChat = useCallback(() => { streams.current.forEach(s => s.close()); streams.current.clear(); setCurrentId(null); setRuns([]); setDraft(''); localStorage.removeItem(LAST); }, []);

  if (fatal) return <div className="grid min-h-dvh place-items-center p-6 text-sm text-danger" role="alert">{fatal}</div>;
  if (!boot) return <div className="grid min-h-dvh place-items-center text-sm text-ink-3">Loading Wizard…</div>;
  if (boot.auth.login_required || !boot.identity) return <LoginScreen mode={boot.auth.mode} onLogin={() => void loadBoot()} />;

  const runtime = boot.runtime!;
  const synthetic = (boot.data_modes ?? []).includes('SYNTHETIC');
  const blocked = runtime.ready ? null : runtime.reason ?? 'Gemini is not available.';
  const title = conversations.find(c => c.id === currentId)?.title ?? 'New analysis';

  return (
    <div className="flex h-dvh w-screen overflow-hidden bg-page">
      <Sidebar boot={boot} conversations={conversations} currentId={currentId} onNew={newChat}
        onSelect={id => void loadConversation(id)} onRename={(id, t) => void api.rename(id, t).then(refreshConversations)}
        onDelete={id => void api.remove(id).then(async () => { if (id === currentId) newChat(); await refreshConversations(); })}
        onAccount={() => setAccountOpen(true)} onLogout={() => void api.logout().then(() => { localStorage.removeItem(LAST); void loadBoot(); })}
        onAsk={text => setDraft(text)} />
      <main className="flex min-w-0 flex-1 flex-col">
        <div className="flex flex-wrap items-center gap-2 border-b border-line bg-canvas px-4 py-2.5 md:px-6">
          <h2 className="mr-2 truncate text-[14px] font-semibold" data-testid="conversation-title">{title}</h2>
          <RuntimeBadge kind={runtime.kind} label={runtime.label} />
          {synthetic && <span className="inline-flex items-center gap-1 rounded-full border border-warn-line bg-warn-soft px-2 py-0.5 text-[11.5px] font-semibold text-warn" data-testid="synthetic-banner">SYNTHETIC DATA · not corporate figures</span>}
          {blocked && <Button size="xs" variant="outline" className="ml-auto border-warn-line text-warn" onClick={() => setAccountOpen(true)}><AlertTriangle />{blocked}</Button>}
        </div>
        <Conversation runs={runs} busy={busy}
          empty={<EmptyState suggestions={boot.suggestions} synthetic={synthetic} onPick={q => { if (!blocked) void ask(q); else setDraft(q); }} />}
          onEvidence={(run, id) => setDrawer({items: id ? allEvidence : run.evidence, focus: id})}
          onCheck={run => void check(run)} onCancel={run => void api.cancel(run.id)} onRetry={run => void ask(run.question)}
          onFeedback={(run, category) => void api.feedback(run.id, category).then(() => setNotice('Thanks — recorded in the evaluation log.'))} />
        <div className="border-t border-line bg-canvas px-4 pb-3 pt-3 md:px-6">
          {notice && <p className="mx-auto mb-2 max-w-[820px] rounded-lg bg-surface px-3 py-2 text-[13px] text-ink-2" role="status">{notice}</p>}
          <Composer busy={busy} draft={draft} onDraftChange={setDraft} onSubmit={ask} disabledReason={blocked} />
        </div>
      </main>
      <EvidenceDrawer conversationId={currentId} open={!!drawer} focus={drawer?.focus ?? null} items={drawer?.items ?? []} onClose={() => setDrawer(null)} />
      <AccountDialog open={accountOpen} boot={boot} onClose={() => setAccountOpen(false)}
        onChanged={account => { setBoot(b => (b ? {...b, gemini_account: account} : b)); void loadBoot(); }} />
    </div>
  );
}
