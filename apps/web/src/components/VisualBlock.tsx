import {useContext, useEffect, useMemo, useRef, useState} from 'react';
import {Check, Copy, FileSpreadsheet, FolderOpen, Image as ImageIcon, ImageDown, Loader2, Presentation, Table2} from 'lucide-react';
import * as echarts from 'echarts/core';
import {BarChart, LineChart, ScatterChart} from 'echarts/charts';
import {AriaComponent, GridComponent, LegendComponent, TooltipComponent} from 'echarts/components';
import {SVGRenderer} from 'echarts/renderers';
import {chartOption, describeVisual} from '@/chartOption';
import {formatValue} from '@/format';
import {cn} from '@/lib/utils';
import type {Visual} from '@/types';
import {VisualEnvContext, type SavedExport} from '@/visualEnv';
import {grid, heatScale} from '@/visuals';
import {DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuLabel, DropdownMenuSeparator, DropdownMenuTrigger} from './ui/menu';

echarts.use([BarChart, LineChart, ScatterChart, AriaComponent, GridComponent, LegendComponent, TooltipComponent, SVGRenderer]);

function Chart({visual}: {visual: Visual}) {
  const host = useRef<HTMLDivElement>(null);
  const option = useMemo(() => chartOption(visual), [visual]);
  useEffect(() => {
    if (!host.current) return;
    const chart = echarts.init(host.current, undefined, {renderer: 'svg'});
    chart.setOption(option);
    const observer = new ResizeObserver(() => chart.resize());
    observer.observe(host.current);
    return () => { observer.disconnect(); chart.dispose(); };
  }, [option]);
  const height = visual.kind === 'bar' ? Math.max(160, 56 + visual.rows.length * 34) : 300;
  return <div ref={host} role="img" aria-label={describeVisual(visual)} style={{height}} className="w-full" data-testid="visual-chart" />;
}

export function VisualTable({visual}: {visual: Visual}) {
  return (
    <div className="overflow-x-auto rounded-xl border border-line">
      <table className="w-full border-collapse text-[13px] tabular">
        <caption className="sr-only">{visual.title}</caption>
        <thead><tr>{visual.columns.map(c => <th key={c.key} scope="col" className={cn('whitespace-nowrap bg-surface px-3 py-2 font-medium text-ink-3', c.type === 'string' ? 'text-left' : 'text-right')}>{c.label}{c.unit && !['%', 'USD'].includes(c.unit) ? ` (${c.unit})` : ''}</th>)}</tr></thead>
        <tbody>{visual.rows.map((row, i) => <tr key={i} className="border-t border-line">{row.map((cell, j) => {
          const c = visual.columns[j];
          return <td key={j} className={cn('px-3 py-2', c.type === 'string' ? 'text-left' : 'text-right')}>{formatValue(cell, c.type, c.unit)}</td>;
        })}</tr>)}</tbody>
      </table>
    </div>
  );
}

/** A heatmap: one row per row label, one column per heatmap column, each cell shaded by its value with the value printed
 *  in it, so the colour is never the only way to read it. A real table, so it copies into PowerPoint as one. */
export function Heatmap({visual}: {visual: Visual}) {
  const g = useMemo(() => grid(visual), [visual]);
  const heat = useMemo(() => heatScale(visual), [visual]);
  const column = visual.columns.find(c => c.key === visual.series[0]);
  const show = (v: number) => formatValue(v, column?.type, column?.unit);
  const reach = Math.max(Math.abs(heat.min), Math.abs(heat.max));
  const missing = g.rows.some(r => r.slice(1).some(c => c.value === null));
  return (
    <div data-testid="visual-heatmap" data-scale={heat.kind}>
      <div className="overflow-x-auto rounded-xl border border-line">
        <table className="w-full border-collapse text-[13px] tabular">
          <caption className="sr-only">{visual.title}</caption>
          <thead><tr>{g.header.map((h, j) => <th key={j} scope="col" className={cn('whitespace-nowrap bg-surface px-3 py-2 font-medium text-ink-3', j === 0 ? 'text-left' : 'text-right')}>{h}</th>)}</tr></thead>
          <tbody>{g.rows.map((row, i) => <tr key={i}>{row.map((c, j) => j === 0
            ? <th key={j} scope="row" className="whitespace-nowrap border-t border-line px-3 py-2 text-left font-medium">{c.text}</th>
            : <td key={j} style={{background: c.fill, color: c.color}} data-testid="heat-cell" data-fill={c.fill}
                className={cn('border-2 border-canvas px-3 py-2 text-right', c.value === null && 'text-ink-3')}>{c.text}</td>)}</tr>)}</tbody>
        </table>
      </div>
      <p className="mt-2 flex flex-wrap items-center gap-2 text-xs text-ink-3" data-testid="heat-legend">
        <span aria-hidden="true" className="h-2 w-32 rounded-full" style={{background: `linear-gradient(to right, ${heat.stops.join(', ')})`}} />
        {heat.kind === 'diverging'
          ? <span>{show(-reach)} (red) to {show(reach)} (blue); grey is 0</span>
          : <span>{show(heat.min)} (light) to {show(heat.max)} (dark)</span>}
        {missing && <span>· — no data</span>}
      </p>
    </div>
  );
}

type ExportAction = 'copy-picture' | 'copy-table' | 'pptx' | 'xlsx' | 'png';
type ExportState = {step: 'idle'} | {step: 'busy'; action: ExportAction} | {step: 'done'; text: string; saved?: SavedExport} | {step: 'failed'; text: string};

const load = () => import('@/visualExport');

/** Copy and download a visual as it is: a picture or a table for the clipboard, an editable PowerPoint slide, an Excel
 *  workbook of its data (in Wizard, with the rows of the sources it cites) or a picture file. */
export function VisualExport({visual}: {visual: Visual}) {
  const env = useContext(VisualEnvContext);
  const [state, setState] = useState<ExportState>({step: 'idle'});
  const chart = visual.kind === 'bar' || visual.kind === 'line' || visual.kind === 'scatter';
  useEffect(() => {
    if (state.step !== 'done' || state.saved) return;
    const timer = setTimeout(() => setState({step: 'idle'}), 6000);
    return () => clearTimeout(timer);
  }, [state]);
  const act = async (action: ExportAction) => {
    setState({step: 'busy', action});
    try {
      const made = await load();
      if (action === 'copy-picture') {
        await made.copyPicture(visual, env);
        setState({step: 'done', text: 'Picture copied: paste it into PowerPoint, Word or an email.'});
      } else if (action === 'copy-table') {
        await made.copyTable(visual, env);
        setState({step: 'done', text: 'Table copied: paste it into Excel or PowerPoint.'});
      } else {
        const {saved, filename} = await made.download(action, visual, env);
        setState(saved ? {step: 'done', text: `Saved in ${saved.folder} as ${saved.filename}.`, saved} : {step: 'done', text: `Downloaded ${filename}.`});
      }
    } catch (e) {
      setState({step: 'failed', text: e instanceof Error ? e.message : 'That did not work.'});
    }
  };
  const open = async (saved: SavedExport) => {
    try { await env.open?.(saved); } catch (e) { setState({step: 'failed', text: e instanceof Error ? e.message : 'The file did not open.'}); }
  };
  const busy = state.step === 'busy';
  const item = (action: ExportAction, icon: React.ReactNode, label: string, hint: string) => (
    <DropdownMenuItem onSelect={() => void act(action)} data-testid={`visual-export-${action}`} className="items-start">
      <span className="mt-0.5 text-ink-3 [&_svg]:size-4">{icon}</span>
      <span className="flex flex-col"><span className="font-medium text-ink">{label}</span><span className="text-xs text-ink-3">{hint}</span></span>
    </DropdownMenuItem>
  );
  return (
    <>
      <DropdownMenu onOpenChange={opened => { if (opened) void load(); }}>
        <DropdownMenuTrigger asChild>
          <button type="button" disabled={busy} data-testid="visual-export" aria-label={`Copy or download ${visual.title}`}
            className="inline-flex h-8 items-center gap-1.5 rounded-lg border border-line px-2.5 text-[13px] font-medium text-ink-2 hover:bg-surface hover:text-ink disabled:opacity-60">
            {busy ? <Loader2 className="size-4 animate-spin" /> : <Copy className="size-4" />}Copy / download</button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end" className="w-72">
          <DropdownMenuLabel>Copy</DropdownMenuLabel>
          {item('copy-picture', <ImageIcon />, 'Copy picture', 'Paste into PowerPoint, Word or an email')}
          {item('copy-table', <Table2 />, 'Copy table', 'Paste as cells in Excel, or as a table in PowerPoint')}
          <DropdownMenuSeparator />
          <DropdownMenuLabel>Download</DropdownMenuLabel>
          {item('pptx', <Presentation />, 'PowerPoint slide (.pptx)', chart ? 'An editable PowerPoint chart, its data in Excel' : 'An editable PowerPoint table')}
          {item('xlsx', <FileSpreadsheet />, 'Excel workbook (.xlsx)', env.rowsBehind ? 'Its values, its sources and the rows behind it' : 'Its values and its sources (a case keeps no rows)')}
          {item('png', <ImageDown />, 'Picture (.png)', 'The visual with its title and source')}
        </DropdownMenuContent>
      </DropdownMenu>
      {(state.step === 'done' || state.step === 'failed') && (
        <p role={state.step === 'failed' ? 'alert' : 'status'} data-testid="visual-export-status"
          className={cn('basis-full text-xs', state.step === 'failed' ? 'text-danger' : 'text-ink-2')}>
          {state.step === 'done' && <Check className="mr-1 inline size-3.5 text-ok" />}{state.text}
          {state.step === 'done' && state.saved && env.open && <button type="button" onClick={() => void open(state.saved!)} data-testid="visual-export-open"
            className="ml-2 inline-flex items-center gap-1 font-medium text-accent hover:underline"><FolderOpen className="size-3.5" />Open</button>}
        </p>
      )}
    </>
  );
}

export function VisualBlock({visual, onEvidence}: {visual: Visual; onEvidence?: (id: string) => void}) {
  const [view, setView] = useState<'chart' | 'data'>(visual.kind === 'table' ? 'data' : 'chart');
  return (
    <figure id={`visual-${visual.id}`} className="my-4 rounded-xl border border-line bg-canvas p-4" data-testid="visual" data-visual-id={visual.id} data-kind={visual.kind}>
      <div className="flex flex-wrap items-start gap-3">
        <figcaption className="min-w-0 flex-1">
          <p className="text-[15px] font-semibold leading-tight">{visual.title}</p>
          {visual.subtitle && <p className="mt-1 text-xs text-ink-3">{visual.subtitle}</p>}
        </figcaption>
        {visual.kind !== 'table' && <div role="group" aria-label="Presentation" className="inline-flex rounded-lg bg-surface p-1">
          {(['chart', 'data'] as const).map(v => <button key={v} type="button" aria-pressed={view === v} onClick={() => setView(v)}
            className={cn('rounded-md px-3 py-1 text-[13px] font-medium', view === v ? 'bg-canvas text-accent shadow-sm' : 'text-ink-2 hover:text-ink')}>{v === 'chart' ? (visual.kind === 'heatmap' ? 'Heatmap' : 'Chart') : 'Data'}</button>)}
        </div>}
        <VisualExport visual={visual} />
      </div>
      <div className="mt-3">{view === 'data' ? <VisualTable visual={visual} /> : visual.kind === 'heatmap' ? <Heatmap visual={visual} /> : <Chart visual={visual} />}</div>
      <p className="mt-2 flex flex-wrap items-center gap-1.5 text-xs text-ink-3">
        <span>Prepared by Gemini from</span>
        {visual.evidence_ids.length ? visual.evidence_ids.map(id => <button key={id} type="button" onClick={() => onEvidence?.(id)} className="rounded bg-accent-soft px-1.5 font-medium text-accent hover:bg-accent-line/60">{id}</button>)
          : <span className="font-medium text-warn">no cited evidence</span>}
        {visual.note && <span>· {visual.note}</span>}
      </p>
    </figure>
  );
}
