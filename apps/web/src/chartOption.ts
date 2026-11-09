// The ECharts option for a bar, line or scatter visual: drawn on screen by VisualBlock (SVG) and into pictures by
// visualExport.ts (canvas), so a copied picture looks like the chart in the answer.
import type {EChartsOption, SeriesOption} from 'echarts';
import {compact, formatValue} from './format';
import type {Visual} from './types';
import {COLORS} from './visuals';

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
  if (visual.kind === 'heatmap') return `Heatmap of ${visual.rows.length} rows by ${x}, with columns ${series}; each cell shows its value.`;
  return `${visual.kind} chart of ${series} by ${x}, ${visual.rows.length} items. Exact values are in the Data view.`;
}
