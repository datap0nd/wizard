import {useEffect, useMemo, useRef, useState} from 'react';
import * as echarts from 'echarts/core';
import {BarChart, LineChart, ScatterChart} from 'echarts/charts';
import {AriaComponent, GridComponent, LegendComponent, TooltipComponent} from 'echarts/components';
import {SVGRenderer} from 'echarts/renderers';
import type {EChartsOption, SeriesOption} from 'echarts';
import {compact, formatValue} from '@/format';
import {cn} from '@/lib/utils';
import type {Visual} from '@/types';

echarts.use([BarChart, LineChart, ScatterChart, AriaComponent, GridComponent, LegendComponent, TooltipComponent, SVGRenderer]);

const COLORS = ['#315bd6', '#0891b2', '#b45309', '#7c3aed', '#be123c', '#4b5871'];

export function chartOption(visual: Visual): EChartsOption {
  const keys = visual.columns.map(c => c.key);
  const xi = keys.indexOf(visual.x ?? '');
  const labels = visual.rows.map(r => String(r[xi] ?? ''));
  const col = (key: string) => visual.columns.find(c => c.key === key)!;
  const base: EChartsOption = {
    color: COLORS, animationDuration: 200, textStyle: {fontFamily: 'Inter, system-ui, sans-serif', color: '#4b5871'},
    grid: {left: 12, right: 28, top: visual.series.length > 1 ? 36 : 20, bottom: 24, containLabel: true},
    tooltip: {trigger: visual.kind === 'scatter' ? 'item' : 'axis', confine: true, borderColor: '#dde2ed', textStyle: {fontSize: 12}},
    legend: visual.series.length > 1 && visual.kind !== 'scatter' ? {top: 0, icon: 'roundRect', itemHeight: 8} : undefined,
    aria: {enabled: true, decal: {show: false}},
  };
  if (visual.kind === 'scatter') {
    const [xs, ys] = visual.series.map(s => keys.indexOf(s));
    return {...base, xAxis: {type: 'value', name: col(visual.series[0]).label, nameLocation: 'middle', nameGap: 28, axisLabel: {formatter: compact}},
      yAxis: {type: 'value', name: col(visual.series[1]).label, axisLabel: {formatter: compact}},
      series: [{type: 'scatter', symbolSize: 12, data: visual.rows.map(r => ({name: labels[visual.rows.indexOf(r)], value: [Number(r[xs]), Number(r[ys])]})),
        label: {show: true, position: 'right', formatter: '{b}', fontSize: 11}}]};
  }
  const horizontal = visual.kind === 'bar' && visual.rows.length > 0;
  const series = visual.series.map(key => {
    const index = keys.indexOf(key);
    const meta = col(key);
    return {name: meta.label, type: visual.kind === 'line' ? 'line' : 'bar', data: visual.rows.map(r => r[index] as number | null),
      barMaxWidth: 26, itemStyle: {borderRadius: horizontal ? [0, 3, 3, 0] : [3, 3, 0, 0]},
      label: {show: visual.kind === 'bar', position: horizontal ? 'right' : 'top', fontSize: 11, color: '#4b5871',
        formatter: (p: {value: unknown}) => formatValue(p.value, meta.type, meta.unit)}} as SeriesOption;
  });
  if (horizontal) return {...base, grid: {...(base.grid as object), right: 96},
    yAxis: {type: 'category', data: labels, inverse: true, axisTick: {show: false}, axisLine: {show: false}},
    xAxis: {type: 'value', splitLine: {lineStyle: {color: '#eef0f5'}}, axisLabel: {formatter: compact}}, series};
  return {...base, xAxis: {type: 'category', data: labels, axisLabel: {hideOverlap: true}},
    yAxis: {type: 'value', splitLine: {lineStyle: {color: '#eef0f5'}}, axisLabel: {formatter: compact}}, series};
}

export function describeVisual(visual: Visual): string {
  const series = visual.series.map(s => visual.columns.find(c => c.key === s)?.label ?? s).join(' and ');
  const x = visual.columns.find(c => c.key === visual.x)?.label ?? 'category';
  return `${visual.kind} chart of ${series} by ${x}, ${visual.rows.length} items. Exact values are in the Data view.`;
}

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

export function VisualBlock({visual, onEvidence}: {visual: Visual; onEvidence?: (id: string) => void}) {
  const [view, setView] = useState<'chart' | 'data'>(visual.kind === 'table' ? 'data' : 'chart');
  return (
    <figure id={`visual-${visual.id}`} className="my-4 rounded-xl border border-line bg-canvas p-4" data-testid="visual" data-visual-id={visual.id}>
      <div className="flex flex-wrap items-start gap-3">
        <figcaption className="min-w-0 flex-1">
          <p className="text-[15px] font-semibold leading-tight">{visual.title}</p>
          {visual.subtitle && <p className="mt-1 text-xs text-ink-3">{visual.subtitle}</p>}
        </figcaption>
        {visual.kind !== 'table' && <div role="group" aria-label="Presentation" className="inline-flex rounded-lg bg-surface p-1">
          {(['chart', 'data'] as const).map(v => <button key={v} type="button" aria-pressed={view === v} onClick={() => setView(v)}
            className={cn('rounded-md px-3 py-1 text-[13px] font-medium', view === v ? 'bg-canvas text-accent shadow-sm' : 'text-ink-2 hover:text-ink')}>{v === 'chart' ? 'Chart' : 'Data'}</button>)}
        </div>}
      </div>
      <div className="mt-3">{view === 'chart' ? <Chart visual={visual} /> : <VisualTable visual={visual} />}</div>
      <p className="mt-2 flex flex-wrap items-center gap-1.5 text-xs text-ink-3">
        <span>Prepared by Gemini from</span>
        {visual.evidence_ids.length ? visual.evidence_ids.map(id => <button key={id} type="button" onClick={() => onEvidence?.(id)} className="rounded bg-accent-soft px-1.5 font-medium text-accent hover:bg-accent-line/60">{id}</button>)
          : <span className="font-medium text-warn">no cited evidence</span>}
        {visual.note && <span>· {visual.note}</span>}
      </p>
    </figure>
  );
}
