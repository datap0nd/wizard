import {useEffect, useState} from 'react';
import {ExternalLink, Eye, Trash2, Upload} from 'lucide-react';
import {api} from '@/api';
import type {Case, CasePreview} from '@/cases';
import {DataModeBadge} from '../Badges';
import {Button} from '../ui/button';
import {Dialog, DialogContent} from '../ui/dialog';

type Result = {message: string; url?: string | null; failed?: boolean};

/** Share as case: this chat's answers on the Pages site's Cases page, at the person's click. They choose the answers,
 *  the title (Gemini's name for the chat to start with) and an optional takeaway, can preview it in Wizard, and publish,
 *  update or remove it. What is published is said before the click: prompts, answers, charts, tables and source names,
 *  never rows (services/api/wizard_api/site.py). */
export function ShareCaseDialog({conversationId, open, onClose}: {conversationId: string | null; open: boolean; onClose: () => void}) {
  const [preview, setPreview] = useState<CasePreview | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [title, setTitle] = useState('');
  const [takeaway, setTakeaway] = useState('');
  const [picked, setPicked] = useState<Set<string>>(new Set());
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<Result | null>(null);

  useEffect(() => {
    if (!open || !conversationId) return;
    setPreview(null); setError(null); setResult(null);
    api.casePreview(conversationId).then(found => {
      setPreview(found);
      const made = found.case && !('problem' in found.case && found.case.problem) ? found.case as Case : null;
      setTitle(found.published?.title ?? made?.title ?? '');
      setTakeaway(found.published?.takeaway ?? '');
      const runs = (made?.turns ?? []).map(t => t.run_id!).filter(Boolean);
      const before = found.published?.runs.filter(id => runs.includes(id)) ?? [];
      setPicked(new Set(before.length ? before : runs));
    }).catch((e: unknown) => setError(e instanceof Error ? e.message : 'The chat could not be read.'));
  }, [open, conversationId]);

  const made = preview?.case && !('problem' in preview.case && preview.case.problem) ? preview.case as Case : null;
  const problem = preview?.case && 'problem' in preview.case ? preview.case.problem : null;
  const site = preview?.site;
  const chosen = made ? made.turns.filter(t => t.run_id && picked.has(t.run_id)).map(t => t.run_id!) : [];
  const toggle = (id: string) => setPicked(prev => { const out = new Set(prev); if (out.has(id)) out.delete(id); else out.add(id); return out; });
  const previewHref = conversationId ? `/case/${encodeURIComponent(conversationId)}?${new URLSearchParams({runs: chosen.join(','), title, takeaway})}` : '#';

  const publish = () => {
    if (!conversationId) return;
    setBusy(true); setResult(null);
    api.publishCase(conversationId, {title, takeaway, run_ids: chosen})
      .then(r => { setResult({message: r.message, url: r.url}); setPreview(p => (p ? {...p, published: r.published} : p)); })
      .catch((e: unknown) => setResult({failed: true, message: e instanceof Error ? e.message : 'Not published.'}))
      .finally(() => setBusy(false));
  };
  const remove = () => {
    if (!conversationId) return;
    setBusy(true); setResult(null);
    api.removeCase(conversationId)
      .then(r => { setResult({message: r.message}); setPreview(p => (p ? {...p, published: null} : p)); })
      .catch((e: unknown) => setResult({failed: true, message: e instanceof Error ? e.message : 'Not removed.'}))
      .finally(() => setBusy(false));
  };

  return (
    <Dialog open={open} onOpenChange={value => { if (!value) onClose(); }}>
      <DialogContent side="right" title="Share as case" description="This chat on the Cases page of the Pages site, for people to see the analysis.">
        <div className="space-y-5" data-testid="share-case">
          {error && <p className="text-sm text-danger" role="alert">{error}</p>}
          {!preview && !error && <p className="text-sm text-ink-3">Reading the chat…</p>}
          {site && !site.allowed && <p className="text-sm text-ink-2">Only the person at this PC publishes to the site, with their own write token.</p>}
          {site && site.allowed && !site.enabled && <p className="rounded-lg border border-warn-line bg-warn-soft p-3 text-sm text-warn">{site.problem}</p>}
          {problem && <p className="text-sm text-danger">{problem}</p>}
          {preview && !preview.case && <p className="text-sm text-ink-2">This chat has no finished answer to share yet.</p>}
          {made && (
            <>
              <label className="block space-y-1.5 text-[13px] font-medium text-ink-2">Title
                <input value={title} onChange={e => setTitle(e.target.value)} maxLength={120} data-testid="case-title-input"
                  className="block h-10 w-full rounded-lg border border-line-2 bg-canvas px-3 text-[14px] font-normal text-ink outline-none focus:border-accent" />
              </label>
              <label className="block space-y-1.5 text-[13px] font-medium text-ink-2">Takeaway <span className="font-normal text-ink-3">(optional: the line people read first)</span>
                <textarea value={takeaway} onChange={e => setTakeaway(e.target.value)} maxLength={400} rows={2} data-testid="case-takeaway-input"
                  className="block w-full rounded-lg border border-line-2 bg-canvas px-3 py-2 text-[14px] font-normal text-ink outline-none focus:border-accent" />
              </label>
              <fieldset className="space-y-2">
                <legend className="mb-1 text-[13px] font-medium text-ink-2">Answers to share</legend>
                {made.turns.map(turn => (
                  <label key={turn.run_id} className="flex cursor-pointer items-start gap-2.5 rounded-lg border border-line p-2.5 hover:bg-surface" data-testid="case-turn">
                    <input type="checkbox" checked={picked.has(turn.run_id!)} onChange={() => toggle(turn.run_id!)} className="mt-1 size-4 accent-[#1428a0]" />
                    <span className="min-w-0 flex-1">
                      <span className="block text-[13.5px] text-ink">{turn.n}. {turn.kind === 'check' ? 'Check my data' : turn.prompt}</span>
                      <span className="mt-1 flex flex-wrap items-center gap-1.5 text-[12px] text-ink-3">
                        <DataModeBadge mode={turn.data_mode} />
                        {turn.sources.length} {turn.sources.length === 1 ? 'source' : 'sources'}{turn.visuals.length ? ` · ${turn.visuals.length} ${turn.visuals.length === 1 ? 'chart or table' : 'charts and tables'}` : ''}
                      </span>
                    </span>
                  </label>
                ))}
              </fieldset>
              <p className="rounded-lg border border-line bg-surface p-3 text-[13px] leading-relaxed text-ink-2">
                Everyone who can open the Pages site will see these prompts and answers, with their charts, tables, data labels and the
                names of their sources. The sources' rows are never published. Figures read with your own rights are shown as you saw
                them: share only what they may see.</p>
              <div className="flex flex-wrap items-center gap-2">
                <Button variant="accent" onClick={publish} disabled={busy || !site?.enabled || !chosen.length} data-testid="case-publish">
                  <Upload />{busy ? 'Publishing…' : preview?.published ? 'Update the case' : 'Publish'}</Button>
                <a href={previewHref} target="_blank" rel="noopener noreferrer"
                  className="inline-flex h-9 items-center gap-1.5 rounded-lg border border-line bg-canvas px-3.5 text-sm font-medium text-ink hover:bg-surface"><Eye className="size-4" />Preview</a>
                {preview?.published && <Button variant="ghost" onClick={remove} disabled={busy} data-testid="case-remove"><Trash2 />Remove from the site</Button>}
              </div>
            </>
          )}
          {result && (
            <p className={result.failed ? 'text-sm text-danger' : 'text-sm text-ok'} role="status" data-testid="case-result">
              {result.message}{result.url && <> <a href={result.url} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1 underline">Open the case<ExternalLink className="size-3.5" /></a></>}
            </p>
          )}
          {site?.enabled && (site.pages.cases
            ? <p className="text-[12.5px] text-ink-3">Cases on the site: <a href={site.pages.cases} target="_blank" rel="noopener noreferrer" className="underline">{site.pages.cases}</a></p>
            : site.setup && <p className="text-[12.5px] text-ink-3">{site.setup}</p>)}
        </div>
      </DialogContent>
    </Dialog>
  );
}
