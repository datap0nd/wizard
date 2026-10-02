import {useEffect, useState} from 'react';
import {ChevronRight, Database, FileText, Folder, LayoutDashboard, Lock} from 'lucide-react';
import {api} from '@/api';
import {formatDate} from '@/format';
import {cn} from '@/lib/utils';
import {Button} from './ui/button';
import {Dialog, DialogContent} from './ui/dialog';
import {DataModeBadge, StatusPill} from './Badges';
import type {CatalogReport, SourceCatalog, SourceSummary} from '@/types';

function StatusChip({status}: {status: string}) {
  if (status === 'NAVIGATION_ONLY') return <StatusPill tone="muted"><Lock />Navigation only</StatusPill>;
  if (status === 'ROWS_VERIFIED') return <StatusPill tone="ok">Rows verified</StatusPill>;
  return <StatusPill tone="warn">Rows · synthetic</StatusPill>;
}

function Tree({catalog, parent, depth, onPick}: {catalog: SourceCatalog; parent: string | null; depth: number; onPick: (r: CatalogReport) => void}) {
  const folders = catalog.folders.filter(f => f.parent === parent);
  const reports = catalog.reports.filter(r => r.folder === parent);
  return (
    <ul className="space-y-0.5" role="group">
      {folders.map(folder => <FolderNode key={folder.id} catalog={catalog} id={folder.id} name={folder.name} depth={depth} onPick={onPick} />)}
      {reports.map(report => (
        <li key={report.id}>
          <button type="button" onClick={() => onPick(report)} style={{paddingLeft: 8 + depth * 12}} data-testid="catalog-report"
            className="flex w-full items-center gap-1.5 rounded-md py-1 pr-2 text-left text-[13px] text-ink-2 hover:bg-canvas hover:text-ink">
            {report.type === 'dossier' ? <LayoutDashboard className="size-3.5 shrink-0" /> : <FileText className="size-3.5 shrink-0" />}
            <span className="truncate">{report.name}</span>
            {report.row_access === 'NAVIGATION_ONLY' && <Lock className="ml-auto size-3 shrink-0 text-ink-3" aria-label="navigation only" />}
          </button>
        </li>
      ))}
    </ul>
  );
}

function FolderNode({catalog, id, name, depth, onPick}: {catalog: SourceCatalog; id: string; name: string; depth: number; onPick: (r: CatalogReport) => void}) {
  const [open, setOpen] = useState(depth < 1);
  return (
    <li>
      <button type="button" onClick={() => setOpen(!open)} aria-expanded={open} style={{paddingLeft: 8 + depth * 12}}
        className="flex w-full items-center gap-1.5 rounded-md py-1 pr-2 text-left text-[13px] font-medium text-ink hover:bg-canvas">
        <ChevronRight className={cn('size-3.5 shrink-0 transition-transform', open && 'rotate-90')} /><Folder className="size-3.5 shrink-0 text-ink-3" />{name}
      </button>
      {open && <Tree catalog={catalog} parent={id} depth={depth + 1} onPick={onPick} />}
    </li>
  );
}

/** Browse what you may see: system → folder → report → prompts. Browsing a report and reading its rows are separate states. */
export function SourceExplorer({onAsk}: {onAsk: (text: string) => void}) {
  const [sources, setSources] = useState<SourceSummary[] | null>(null);
  const [catalogs, setCatalogs] = useState<Record<string, SourceCatalog>>({});
  const [open, setOpen] = useState<string | null>(null);
  const [picked, setPicked] = useState<{system: SourceSummary; report: CatalogReport} | null>(null);
  useEffect(() => { api.sources().then(r => setSources(r.sources)).catch(() => setSources([])); }, []);
  async function toggle(system: SourceSummary) {
    if (open === system.id) { setOpen(null); return; }
    setOpen(system.id);
    if (!catalogs[system.id]) { const catalog = await api.catalog(system.id); setCatalogs(c => ({...c, [system.id]: catalog})); }
  }
  if (sources === null) return <p className="px-3 py-3 text-[13px] text-ink-3">Loading sources…</p>;
  if (sources.length === 0) return <p className="px-3 py-3 text-[13px] text-ink-3">No sources are available to you yet. Ask the source owner for access.</p>;
  return (
    <div className="space-y-1 px-2 pb-3" data-testid="source-explorer">
      {sources.map(system => (
        <div key={system.id} className="rounded-lg">
          <button type="button" onClick={() => void toggle(system)} aria-expanded={open === system.id} data-testid="source-system"
            className={cn('flex w-full items-start gap-2 rounded-lg px-2 py-2 text-left hover:bg-canvas', open === system.id && 'bg-canvas shadow-card')}>
            <Database className="mt-0.5 size-4 shrink-0 text-accent" />
            <span className="min-w-0 flex-1">
              <span className="block text-[13px] font-semibold">{system.name}</span>
              <span className="block truncate text-[11.5px] text-ink-3">{system.families.join(', ').replaceAll('_', ' ')}</span>
              <span className="mt-1 flex flex-wrap gap-1"><DataModeBadge mode={system.data_mode} /><span className="text-[11px] text-ink-3">{system.reports_with_rows}/{system.reports} readable</span></span>
            </span>
          </button>
          {open === system.id && catalogs[system.id] && <div className="mt-1"><Tree catalog={catalogs[system.id]} parent={null} depth={0} onPick={report => setPicked({system, report})} /></div>}
        </div>
      ))}
      <Dialog open={!!picked} onOpenChange={value => { if (!value) setPicked(null); }}>
        {picked && <DialogContent title={picked.report.name} description={`${picked.system.name} · ${picked.report.id}`}>
          <div className="space-y-3 text-sm" data-testid="report-details">
            <div className="flex flex-wrap gap-1.5"><StatusChip status={picked.report.status} /><DataModeBadge mode={picked.system.data_mode} />
              {picked.report.sensitivity === 'restricted' && <StatusPill tone="danger"><Lock />Restricted</StatusPill>}</div>
            <p className="text-ink-2">{picked.report.description}</p>
            <dl className="grid grid-cols-[auto,1fr] gap-x-3 gap-y-1 text-xs">
              <dt className="text-ink-3">Data as of</dt><dd>{formatDate(picked.report.as_of, true)}</dd>
              <dt className="text-ink-3">Refresh</dt><dd>{picked.report.refresh}</dd>
              {picked.report.measures.length > 0 && <><dt className="text-ink-3">Measures</dt><dd>{picked.report.measures.join(', ')}</dd></>}
              {picked.report.prompts.length > 0 && <><dt className="text-ink-3">Prompts</dt><dd>{picked.report.prompts.map(p => p.label).join(', ')}</dd></>}
            </dl>
            <div className="flex flex-wrap gap-2 pt-1">
              <Button size="sm" variant="accent" disabled={picked.report.row_access !== 'ROWS'} onClick={() => { onAsk(`Using the "${picked.report.name}" report in ${picked.system.name}, `); setPicked(null); }}>Ask about this report</Button>
              <Button size="sm" variant="outline" disabled title="Synthetic fixture: there is no live source link in this build">Open in {picked.system.name}</Button>
            </div>
            {picked.report.row_access !== 'ROWS' && <p className="text-xs text-ink-3">Navigation only: Wizard can list this report but cannot read its numbers until a visualization is approved and parity-tested.</p>}
          </div>
        </DialogContent>}
      </Dialog>
    </div>
  );
}
