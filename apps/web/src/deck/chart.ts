// A deck chart in the preview, drawn with ECharts the way pptx.ts writes it to PowerPoint: the deck's chart style
// (columns, stacked, 100% stacked, bars, lines), the company's series colors, label sizes and gridlines.
import type {EChartsOption, SeriesOption} from 'echarts';
import {compact, formatValue} from '../format';
import type {DesignTokens, Visual} from '../types';
import {lineAxisMin, lineLabels, unitLabel, type DrawnChart} from './layout';

export function deckChartOption(visual: Visual, chart: DrawnChart, t: DesignTokens, pxPerInch: number): EChartsOption {
  const px = (pt: number) => Math.max(5, pt / 72 * pxPerInch);
  const keys = visual.columns.map(c => c.key);
  const labels = visual.rows.map(r => String(r[keys.indexOf(visual.x ?? '')] ?? ''));
  const col = (key: string) => visual.columns.find(c => c.key === key)!;
  const text = {fontFamily: `"${t.fonts.labels}", Arial, sans-serif`, color: t.colors.secondary, fontSize: px(t.sizes.chart_label)};
  const base: EChartsOption = {
    animation: false, color: t.colors.series.length ? t.colors.series : [t.colors.brand], textStyle: text,
    grid: {left: 4, right: 12, top: visual.series.length > 1 ? px(t.sizes.chart_label) * 2.6 : 8, bottom: 4, containLabel: true},
    legend: visual.series.length > 1 && chart !== 'scatter' ? {top: 0, icon: 'rect', itemWidth: px(8), itemHeight: px(8), textStyle: text} : undefined,
  };
  const axisLine = {lineStyle: {color: t.colors.line}};
  const axisLabel = {fontSize: text.fontSize, color: text.color, fontFamily: text.fontFamily};
  // The unit is in the chart's corner (layout.ts): the values on the bars are bare numbers.
  const unitShown = unitLabel(visual) !== '';
  const split = {lineStyle: {color: t.colors.line, width: 0.5}};
  if (chart === 'scatter') {
    const [xs, ys] = visual.series.map(s => keys.indexOf(s));
    return {...base, xAxis: {type: 'value', name: col(visual.series[0]).label, nameLocation: 'middle', nameGap: px(14), nameTextStyle: text, axisLabel: {...axisLabel, formatter: compact}, splitLine: split},
      yAxis: {type: 'value', name: col(visual.series[1]).label, nameTextStyle: text, axisLabel: {...axisLabel, formatter: compact}, splitLine: split},
      series: [{type: 'scatter', symbolSize: px(7), data: visual.rows.map((r, i) => ({name: labels[i], value: [Number(r[xs]), Number(r[ys])]})),
        label: {show: true, position: 'right', formatter: '{b}', ...text}}]};
  }
  const horizontal = chart === 'bar' || chart === 'stacked_bar';
  const stacked = chart === 'stacked' || chart === 'stacked_bar' || chart === 'percent';
  const totals = visual.rows.map(r => visual.series.reduce((sum, key) => sum + Math.abs(Number(r[keys.indexOf(key)]) || 0), 0));
  const labelled = stacked ? visual.rows.length * visual.series.length <= 40 : visual.rows.length * visual.series.length <= 24;
  const series = visual.series.map(key => {
    const index = keys.indexOf(key);
    const meta = col(key);
    const values = visual.rows.map((r, i) => {
      const v = r[index];
      if (typeof v !== 'number') return null;
      return chart === 'percent' ? (totals[i] ? {value: v / totals[i] * 100, raw: v} : null) : v;
    });
    return {name: meta.label, type: chart === 'line' ? 'line' : 'bar', data: values, stack: stacked ? 'total' : undefined,
      symbol: 'circle', symbolSize: px(5), barMaxWidth: px(40), connectNulls: false,
      label: {show: chart === 'line' ? lineLabels(visual) : labelled,
        position: stacked ? 'inside' : chart === 'line' ? 'top' : horizontal ? 'right' : 'top', ...text,
        color: stacked ? '#FFFFFF' : t.colors.secondary,
        // A 100% stacked segment is labelled with its own value, as PowerPoint labels it in the file.
        formatter: (p: {value: unknown; data?: unknown}) => formatValue(chart === 'percent' ? (p.data as {raw?: number} | null)?.raw ?? p.value : p.value,
          meta.type, unitShown ? null : meta.unit)}} as SeriesOption;
  });
  const value = {type: 'value' as const, splitLine: split, axisLabel: {...axisLabel, formatter: chart === 'percent' ? '{value}%' : compact},
    max: chart === 'percent' ? 100 : undefined, min: chart === 'line' ? lineAxisMin(visual) : undefined};
  const category = {type: 'category' as const, data: labels, axisTick: {show: false}, axisLine, axisLabel: {...axisLabel, hideOverlap: true}};
  return horizontal ? {...base, yAxis: {...category, inverse: true}, xAxis: value, series} : {...base, xAxis: category, yAxis: value, series};
}
