import {useEffect, useState} from 'react';
import {Loader2, Map as MapIcon, Square, Trash2, UploadCloud} from 'lucide-react';
import {api} from '@/api';
import {formatDate} from '@/format';
import {Button} from './ui/button';
import type {PortalMapStatus, PortalMapping, PortalStatus} from '@/types';

const POLL_MS = 15_000;

/** The map's counts in words: "37 reports mapped, 4 partial, 80 to do · 12 shortcuts". */
export function mapSummary(map: PortalMapStatus): string {
  if (!map.reports && !map.has_overview) return 'Not mapped yet.';
  const parts = [`${map.reports_mapped} report${map.reports_mapped === 1 ? '' : 's'} mapped`];
  if (map.reports_partial) parts.push(`${map.reports_partial} partial`);
  if (map.reports_failed) parts.push(`${map.reports_failed} failed`);
  if (map.reports_todo) parts.push(`${map.reports_todo} to do`);
  const topics = map.topics ? ` · ${map.topics} technical note${map.topics === 1 ? '' : 's'} and shortcuts` : '';
  const from = map.source === 'knowledge_base' ? ' · from the knowledge base' : '';
  return parts.join(', ') + topics + from + (map.updated ? ` · updated ${formatDate(map.updated, true)}` : '');
}

function published(map: PortalMapStatus): string | null {
  const last = map.published;
  if (!last) return map.can_publish ? 'Not published to the knowledge base yet.' : null;
  if (last.outcome === 'failed') return `Publishing failed: ${last.message}`;
  return `Published to the knowledge base ${formatDate(last.at, true)}.`;
}

/** Map a portal: Gemini explores it in rounds, in a conversation of its own, and keeps what it learns (menus, report
 * ids, filters, data requests, shortcuts) so a later question goes straight to the data. Published to the knowledge
 * base when this PC has its write token. */
export function PortalMaps({status, onChange}: {status: PortalStatus; onChange: (next: PortalStatus) => void}) {
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const mapping = status.mapping ?? null;
  const running = mapping?.state === 'running';

  useEffect(() => {
    if (!running) return undefined;
    const timer = window.setInterval(() => { api.portals().then(onChange).catch(() => undefined); }, POLL_MS);
    return () => window.clearInterval(timer);
  }, [running, onChange]);

  async function act(system: string, kind: 'map' | 'stop' | 'publish' | 'forget') {
    setBusy(`${kind}:${system}`); setError(null); setNote(null);
    try {
      const call = {map: api.mapPortal, stop: api.stopMapping, publish: api.publishMap, forget: api.forgetMap}[kind];
      const view = await call(system);
      if (view.message) setNote(view.message);
      onChange(await api.portals());
    } catch (e) {
      setError(e instanceof Error ? e.message : 'That did not work.');
    } finally {
      setBusy(null);
    }
  }

  if (!status.maps) return null;
  return (
    <div className="mt-3 space-y-3 rounded-lg bg-surface px-3 py-3" data-testid="portal-maps">
      <p className="text-xs text-ink-2">Map a portal: Gemini explores it on its own, in rounds, and writes down its menus, report
        ids, filters, data requests and shortcuts, so questions go straight to the data. You can keep asking questions meanwhile.</p>
      {status.portals.map(portal => {
        const map = status.maps?.[portal.id];
        if (!map) return null;
        const mine: PortalMapping | null = mapping && mapping.system === portal.id ? mapping : null;
        const here = mine?.state === 'running';
        const started = map.reports > 0 || map.has_overview;
        const line = published(map);
        return (
          <div key={portal.id} className="space-y-1.5" data-testid={`portal-map-${portal.id}`}>
            <p className="flex items-center gap-1.5 text-xs font-medium text-ink"><MapIcon className="size-3.5" />{portal.name}</p>
            <p className="text-xs text-ink-2" data-testid={`portal-map-summary-${portal.id}`}>{mapSummary(map)}</p>
            {mine && (
              <p className="text-xs text-ink-2" role="status" data-testid={`portal-mapping-${portal.id}`}>
                {here && <Loader2 className="mr-1 inline size-3 animate-spin" />}
                {here ? `Mapping now, round ${mine.round}. ` : ''}{mine.message}{' '}
                <a className="underline" href={`?c=${encodeURIComponent(mine.conversation_id)}`}>Watch it</a></p>
            )}
            {line && <p className="text-xs text-ink-3">{line}</p>}
            <div className="flex flex-wrap items-center gap-2">
              {here ? (
                <Button size="xs" variant="outline" onClick={() => void act(portal.id, 'stop')} disabled={busy !== null}
                  data-testid={`portal-map-stop-${portal.id}`}>
                  {busy === `stop:${portal.id}` ? <Loader2 className="animate-spin" /> : <Square />}Stop</Button>
              ) : (
                <Button size="xs" variant="outline" onClick={() => void act(portal.id, 'map')} disabled={busy !== null || running}
                  data-testid={`portal-map-start-${portal.id}`}>
                  {busy === `map:${portal.id}` ? <Loader2 className="animate-spin" /> : <MapIcon />}
                  {started ? 'Continue mapping' : `Map ${portal.name}`}</Button>
              )}
              {map.can_publish && map.source === 'this_pc' && !here && (
                <Button size="xs" variant="ghost" onClick={() => void act(portal.id, 'publish')} disabled={busy !== null}
                  data-testid={`portal-map-publish-${portal.id}`}>
                  {busy === `publish:${portal.id}` ? <Loader2 className="animate-spin" /> : <UploadCloud />}Publish now</Button>
              )}
              {map.source === 'this_pc' && !here && (
                <Button size="xs" variant="ghost" onClick={() => {
                  if (window.confirm(`Delete this PC's map of ${portal.name}? A copy published to the knowledge base stays.`)) {
                    void act(portal.id, 'forget');
                  }
                }} disabled={busy !== null} data-testid={`portal-map-forget-${portal.id}`}>
                  {busy === `forget:${portal.id}` ? <Loader2 className="animate-spin" /> : <Trash2 />}Start over</Button>
              )}
            </div>
          </div>
        );
      })}
      {note && <p className="text-xs text-ink-2" role="status">{note}</p>}
      {error && <p className="text-xs text-danger" role="alert">{error}</p>}
    </div>
  );
}
