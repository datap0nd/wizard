// Copies and downloads of a visual, built in the page from what it shows (loaded only when the person asks for one):
// - Copy table: the cells as HTML with their shading (PowerPoint and Word paste a native table, Excel paste cells with
//   numbers it can calculate) and as tab-separated text.
// - Copy picture / Picture (.png): the chart, heatmap or table drawn with its title and source line.
// - PowerPoint (.pptx): one slide with an editable PowerPoint chart (its data opens in Excel) or a native table.
// - Excel (.xlsx): the visual's values as numbers with Wizard's formats and shading, its sources (names, data labels,
//   queries) and, inside Wizard, the rows each cited source returned: the data behind the visual.
// Every copy and file carries the answer's data label and where its values came from.
import JSZip from 'jszip';
import * as echarts from 'echarts/core';
import {BarChart, LineChart, ScatterChart} from 'echarts/charts';
import {GridComponent, LegendComponent} from 'echarts/components';
import {CanvasRenderer} from 'echarts/renderers';
import {chartOption} from './chartOption';
import {formatDate, formatValue} from './format';
import type {Column, Visual} from './types';
import type {SavedExport, SourceRows, VisualEnv, VisualSource} from './visualEnv';
import {COLORS, HEAD, INK, INK_2, LINE, excelFormat, excelValue, fileName, grid, heatScale, sourceLine, type Cell, type Grid} from './visuals';

echarts.use([BarChart, LineChart, ScatterChart, GridComponent, LegendComponent, CanvasRenderer]);

const FONT = 'Inter, "Segoe UI", Arial, sans-serif';

// ----------------------------------------------------------------------------------------------- delivery

function browserDownload(file: Blob, filename: string): void {
  const url = URL.createObjectURL(file);
  const link = document.createElement('a');
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 60_000);
}

/** Saved in Downloads by Wizard where it runs on this PC (the answer says where), else the browser's own download. */
export async function deliver(env: VisualEnv, file: Blob, filename: string): Promise<SavedExport | null> {
  if (env.save) {
    const saved = await env.save(file, filename);
    if (saved) return saved;
  }
  browserDownload(file, filename);
  return null;
}

// ----------------------------------------------------------------------------------------------- clipboard

const escape = (text: string) => text.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');

/** The table as HTML for the clipboard. Excel reads each number from x:num and shows it with mso-number-format;
 *  PowerPoint and Word show the text, as Wizard does. */
export function tableHtml(visual: Visual, env: Pick<VisualEnv, 'dataMode'>): string {
  const g = grid(visual);
  const cell = 'border:1px solid #e0e4eb;padding:4px 8px;';
  const formats = g.types.map((t, j) => excelFormat(t, g.units[j], g.rows.map(r => r[j].value)));
  const head = g.header.map((h, j) => `<th style="${cell}background:${HEAD};color:${INK};font-weight:bold;text-align:${g.types[j] === 'string' ? 'left' : 'right'}">${escape(h)}</th>`).join('');
  const body = g.rows.map(row => '<tr>' + row.map((c, j) => {
    const value = excelValue(c);
    const number = typeof value === 'number';
    const style = `${cell}text-align:${c.numeric ? 'right' : 'left'};${c.fill ? `background:${c.fill};color:${c.color};` : `color:${INK};`}` +
      (number && formats[j] ? `mso-number-format:'${formats[j]!.replace(/"/g, '\\"')}';` : '');
    return `<td style="${style}"${number ? ` x:num="${value}"` : ''}>${escape(c.text)}</td>`;
  }).join('') + '</tr>').join('');
  const synthetic = env.dataMode === 'SYNTHETIC'
    ? `<tr><td colspan="${g.header.length}" style="padding:4px 8px;color:#9a5b00;font-style:italic">SYNTHETIC test data, not corporate figures</td></tr>` : '';
  return `<html xmlns:x="urn:schemas-microsoft-com:office:excel"><head><meta charset="utf-8"></head><body>` +
    `<table style="border-collapse:collapse;font-family:Calibri,Arial,sans-serif;font-size:11pt"><tr>${head}</tr>${body}${synthetic}</table></body></html>`;
}

/** The table as tab-separated text: numbers as numbers (a percent as 12.5%), for any program. */
export function tableText(visual: Visual): string {
  const g = grid(visual);
  const value = (c: Grid['rows'][number][number]) => typeof c.value === 'number' ? (c.type === 'percent' ? `${c.value}%` : String(c.value)) : c.value ?? '';
  return [g.header, ...g.rows.map(r => r.map(value))].map(r => r.map(v => String(v).replace(/[\t\r\n]+/g, ' ')).join('\t')).join('\r\n');
}

function legacyCopy(html: string): boolean {
  const holder = document.createElement('div');
  holder.contentEditable = 'true';
  holder.style.cssText = 'position:fixed;left:-10000px;top:0;opacity:0';
  holder.innerHTML = html;
  document.body.appendChild(holder);
  const range = document.createRange();
  range.selectNodeContents(holder);
  const selection = window.getSelection();
  selection?.removeAllRanges();
  selection?.addRange(range);
  let ok = false;
  try { ok = document.execCommand('copy'); } catch { ok = false; }
  selection?.removeAllRanges();
  holder.remove();
  return ok;
}

export async function copyTable(visual: Visual, env: VisualEnv): Promise<void> {
  const html = tableHtml(visual, env);
  const text = tableText(visual);
  if (typeof ClipboardItem !== 'undefined' && navigator.clipboard?.write) {
    try {
      await navigator.clipboard.write([new ClipboardItem({'text/html': new Blob([html], {type: 'text/html'}),
        'text/plain': new Blob([text], {type: 'text/plain'})})]);
      return;
    } catch { /* fall through to the older copy */ }
  }
  if (!legacyCopy(html)) throw new Error('This browser did not allow the copy. Download the Excel file instead.');
}

export async function copyPicture(visual: Visual, env: VisualEnv): Promise<void> {
  if (typeof ClipboardItem === 'undefined' || !navigator.clipboard?.write) {
    throw new Error('This browser cannot copy pictures. Download the picture (.png) instead.');
  }
  // The item is handed over at once, while the click still counts, and the picture follows.
  await navigator.clipboard.write([new ClipboardItem({'image/png': picture(visual, env)})]);
}

// ----------------------------------------------------------------------------------------------- pictures

function wrap(ctx: CanvasRenderingContext2D, text: string, width: number): string[] {
  const lines: string[] = [];
  let line = '';
  for (const word of text.split(/\s+/).filter(Boolean)) {
    const next = line ? `${line} ${word}` : word;
    if (ctx.measureText(next).width > width && line) { lines.push(line); line = word; } else line = next;
  }
  if (line) lines.push(line);
  return lines;
}

function canvasBlob(canvas: HTMLCanvasElement): Promise<Blob> {
  return new Promise((resolve, reject) => canvas.toBlob(b => b ? resolve(b) : reject(new Error('The picture could not be made.')), 'image/png'));
}

function loadImage(url: string): Promise<HTMLImageElement> {
  return new Promise((resolve, reject) => {
    const image = new Image();
    image.onload = () => resolve(image);
    image.onerror = () => reject(new Error('The chart could not be drawn.'));
    image.src = url;
  });
}

/** The chart drawn by ECharts on a canvas, at twice its size for a sharp picture. */
async function chartImage(visual: Visual, width: number): Promise<{image: HTMLImageElement; height: number}> {
  const height = visual.kind === 'bar' ? Math.max(240, 64 + visual.rows.length * 40) : 440;
  const host = document.createElement('div');
  host.style.cssText = `position:fixed;left:-10000px;top:0;width:${width}px;height:${height}px`;
  document.body.appendChild(host);
  try {
    const chart = echarts.init(host, undefined, {renderer: 'canvas', width, height});
    chart.setOption({...chartOption(visual), animation: false, tooltip: undefined});
    const url = chart.getDataURL({type: 'png', pixelRatio: 2, backgroundColor: '#ffffff'});
    chart.dispose();
    return {image: await loadImage(url), height};
  } finally {
    host.remove();
  }
}

/** The visual as a PNG: its title and subtitle, the chart or the (shaded) table, and its source line. */
export async function picture(visual: Visual, env: VisualEnv): Promise<Blob> {
  const scale = 2, pad = 28;
  const probe = document.createElement('canvas').getContext('2d');
  if (!probe) throw new Error('This browser cannot draw pictures.');
  const g = visual.kind === 'heatmap' || visual.kind === 'table' ? grid(visual) : null;
  // Table and heatmap columns as wide as their longest text.
  probe.font = `600 13px ${FONT}`;
  const widths = g ? g.header.map((h, j) => Math.min(320, Math.ceil(Math.max(probe.measureText(h).width,
    ...g.rows.map(r => { probe.font = `${j === 0 && visual.kind === 'heatmap' ? 600 : 400} 13px ${FONT}`; return probe.measureText(r[j].text).width; })) + 24))) : [];
  const body = g ? Math.max(480, widths.reduce((a, b) => a + b, 0)) : 1040;
  const width = body + pad * 2;
  probe.font = `400 12px ${FONT}`;
  const footer = wrap(probe, sourceLine(visual, env.dataMode), body);
  probe.font = `400 13px ${FONT}`;
  const subtitle = visual.subtitle ? wrap(probe, visual.subtitle, body) : [];
  probe.font = `600 18px ${FONT}`;
  const title = wrap(probe, visual.title, body);
  const chart = g ? null : await chartImage(visual, body);
  const rowH = 30;
  const legendH = visual.kind === 'heatmap' ? 34 : 0;
  const content = g ? rowH * (g.rows.length + 1) + legendH : chart!.height;
  const top = pad + title.length * 24 + subtitle.length * 18 + 14;
  const height = top + content + 16 + footer.length * 16 + pad;

  const canvas = document.createElement('canvas');
  canvas.width = width * scale;
  canvas.height = height * scale;
  const ctx = canvas.getContext('2d')!;
  ctx.scale(scale, scale);
  ctx.fillStyle = '#ffffff';
  ctx.fillRect(0, 0, width, height);
  ctx.textBaseline = 'top';
  let y = pad;
  ctx.fillStyle = INK; ctx.font = `600 18px ${FONT}`;
  for (const line of title) { ctx.fillText(line, pad, y); y += 24; }
  ctx.fillStyle = INK_2; ctx.font = `400 13px ${FONT}`;
  for (const line of subtitle) { ctx.fillText(line, pad, y); y += 18; }
  y = top;
  if (chart) ctx.drawImage(chart.image, pad, y, body, chart.height);
  if (g) {
    ctx.textBaseline = 'middle';
    const scaleFactor = body / widths.reduce((a, b) => a + b, 0);
    const cols = widths.map(w => w * Math.max(1, scaleFactor));
    const draw = (cells: {text: string; fill?: string; color?: string; numeric: boolean; bold: boolean}[], rowTop: number) => {
      let x = pad;
      cells.forEach((c, j) => {
        ctx.fillStyle = c.fill ?? '#ffffff';
        ctx.fillRect(x, rowTop, cols[j], rowH);
        ctx.strokeStyle = LINE; ctx.lineWidth = 1;
        ctx.strokeRect(x + 0.5, rowTop + 0.5, cols[j] - 1, rowH - 1);
        ctx.fillStyle = c.color ?? INK;
        ctx.font = `${c.bold ? 600 : 400} 13px ${FONT}`;
        ctx.textAlign = c.numeric ? 'right' : 'left';
        ctx.fillText(c.text, c.numeric ? x + cols[j] - 10 : x + 10, rowTop + rowH / 2, cols[j] - 16);
        x += cols[j];
      });
      ctx.textAlign = 'left';
    };
    draw(g.header.map((h, j) => ({text: h, fill: HEAD, color: INK, numeric: g.types[j] !== 'string', bold: true})), y);
    g.rows.forEach((row, i) => draw(row.map((c, j) => ({text: c.text, fill: c.fill, color: c.color, numeric: c.numeric,
      bold: visual.kind === 'heatmap' && j === 0})), y + rowH * (i + 1)));
    y += rowH * (g.rows.length + 1);
    if (visual.kind === 'heatmap') {
      const heat = heatScale(visual);
      const ramp = ctx.createLinearGradient(pad, 0, pad + 200, 0);
      heat.stops.forEach((color, i) => ramp.addColorStop(i / (heat.stops.length - 1), color));
      ctx.fillStyle = ramp; ctx.fillRect(pad, y + 12, 200, 10);
      ctx.fillStyle = INK_2; ctx.font = `400 12px ${FONT}`; ctx.textBaseline = 'middle';
      const column = visual.columns.find(c => c.key === visual.series[0]);
      const show = (v: number) => formatValue(v, column?.type, column?.unit);
      const reach = Math.max(Math.abs(heat.min), Math.abs(heat.max));
      const missing = g.rows.some(r => r.slice(1).some(c => c.value === null)) ? '; — no data' : '';
      ctx.fillText((heat.kind === 'diverging' ? `${show(-reach)} (red) to ${show(reach)} (blue); grey is 0`
        : `${show(heat.min)} (light) to ${show(heat.max)} (dark)`) + missing, pad + 212, y + 17);
      y += legendH;
    }
    ctx.textBaseline = 'top';
  } else {
    y += chart!.height;
  }
  y += 16;
  ctx.fillStyle = '#65728a'; ctx.font = `400 12px ${FONT}`;
  for (const line of footer) { ctx.fillText(line, pad, y); y += 16; }
  return canvasBlob(canvas);
}

// ----------------------------------------------------------------------------------------------- PowerPoint

const bare = (color: string) => color.replace('#', '').toUpperCase();

/** A PowerPoint number format for a column's values, as Wizard shows them (percent values are 0-100). */
function pptFormat(type: string, unit: string | null, values: Cell[]): string {
  const nums = values.filter((v): v is number => typeof v === 'number');
  const big = nums.length > 0 && Math.max(...nums.map(Math.abs)) >= 1e6;
  if (type === 'percent') return '0.0"%"';
  if (type === 'currency') {
    const sign = !unit || unit === 'USD' ? '"$"' : '';
    const tail = unit && unit !== 'USD' ? ` "${unit.replace(/"/g, '')}"` : '';
    return big ? `${sign}#,##0.0,,"M"${tail}` : `${sign}#,##0${tail}`;
  }
  const whole = nums.every(Number.isInteger);
  const tail = unit && !['units', 'devices', 'transfers'].includes(unit) ? ` "${unit.replace(/"/g, '')}"` : '';
  return (whole ? '#,##0' : '#,##0.0#') + tail;
}

function notesText(visual: Visual, env: VisualEnv, sources: VisualSource[]): string {
  return [sourceLine(visual, env.dataMode), ...sources.map(s => [`${s.id}: ${s.name}`, s.dataMode, s.asOf ? `as of ${formatDate(s.asOf)}` : '']
    .filter(Boolean).join(' · ') + (s.query ? `\n${s.query.slice(0, 2000)}` : ''))].join('\n\n');
}

export async function pptx(visual: Visual, env: VisualEnv): Promise<Blob> {
  const [{default: PptxGenJS}, {sources}] = await Promise.all([import('pptxgenjs'), env.sources(visual.evidence_ids)]);
  const deck = new PptxGenJS();
  deck.layout = 'LAYOUT_WIDE';  // 13.33 x 7.5 in, PowerPoint's default 16:9
  deck.author = 'Wizard';
  deck.title = visual.title;
  const face = 'Arial';
  const notes = notesText(visual, env, sources);
  /** A slide with the visual's title, subtitle and source line (every slide of a long table has them). */
  const framed = (part = 0) => {
    const s = deck.addSlide();
    s.addText(visual.title + (part ? ` (continued, ${part + 1})` : ''), {x: 0.5, y: 0.3, w: 12.33, h: 0.6, fontFace: face, fontSize: 24, bold: true, color: bare(INK), margin: 0});
    if (visual.subtitle) s.addText(visual.subtitle, {x: 0.5, y: 0.9, w: 12.33, h: 0.4, fontFace: face, fontSize: 14, color: bare(INK_2), margin: 0});
    s.addText(sourceLine(visual, env.dataMode), {x: 0.5, y: 6.75, w: 12.33, h: 0.5, fontFace: face, fontSize: 10, color: '65728A',
      margin: 0, valign: 'top', fit: 'shrink'});
    s.addNotes(notes);
    return s;
  };
  const area = {x: 0.5, y: visual.subtitle ? 1.45 : 1.15, w: 12.33, h: visual.subtitle ? 5.15 : 5.45};

  const keys = visual.columns.map(c => c.key);
  const col = (key: string) => visual.columns.find(c => c.key === key)!;
  const values = (key: string) => visual.rows.map(r => { const v = r[keys.indexOf(key)]; return typeof v === 'number' ? v : null; });
  const labels = visual.rows.map(r => String(r[keys.indexOf(visual.x ?? '')] ?? ''));
  const axis = {fontFace: face, catAxisLabelFontFace: face, valAxisLabelFontFace: face, catAxisLabelFontSize: 11, valAxisLabelFontSize: 10,
    catAxisLabelColor: bare(INK_2), valAxisLabelColor: bare(INK_2), valGridLine: {color: 'EEF0F5', size: 0.75}, catGridLine: {style: 'none' as const},
    chartColors: COLORS.slice(0, Math.max(1, visual.series.length)).map(bare), displayBlanksAs: 'gap', showLegend: visual.series.length > 1, legendPos: 't' as const, legendFontSize: 11, legendFontFace: face};

  if (visual.kind === 'bar' || visual.kind === 'line') {
    const first = col(visual.series[0]);
    const format = pptFormat(first.type, first.unit, values(first.key));
    // PowerPoint draws a bar chart's first category at the bottom: the rows go in last first, so the slide reads top
    // to bottom as the answer does (reversing the axis instead moves the value axis to the top).
    const order = <T,>(items: T[]) => visual.kind === 'bar' ? [...items].reverse() : items;
    const data = visual.series.map(key => ({name: col(key).label, labels: order(labels), values: order(values(key)) as number[]}));
    framed().addChart(visual.kind === 'bar' ? deck.ChartType.bar : deck.ChartType.line, data, {...area, ...axis,
      ...(visual.kind === 'bar'
        ? {barDir: 'bar', barGapWidthPct: 60, showValue: true, dataLabelPosition: 'outEnd' as const,
           dataLabelFontSize: 10, dataLabelColor: bare(INK_2), dataLabelFormatCode: format}
        : {lineSize: 2, lineDataSymbol: 'circle' as const, lineDataSymbolSize: 6}),
      valAxisLabelFormatCode: format});
  } else if (visual.kind === 'scatter') {
    const [xs, ys] = [values(visual.series[0]), values(visual.series[1])];
    const kept = xs.map((x, i) => x !== null && ys[i] !== null ? i : -1).filter(i => i >= 0);
    const [cx, cy] = [col(visual.series[0]), col(visual.series[1])];
    framed().addChart(deck.ChartType.scatter, [
      {name: cx.label, values: kept.map(i => xs[i]!)},
      {name: cy.label, values: kept.map(i => ys[i]!), labels: [kept.map(i => labels[i])]} as unknown as {name: string; values: number[]},
    ], {...area, ...axis, showLegend: false, lineSize: 0, lineDataSymbol: 'circle', lineDataSymbolSize: 9, showLabel: true,
      dataLabelFormatScatter: 'custom', dataLabelPosition: 'r', dataLabelFontSize: 10,
      showValAxisTitle: true, valAxisTitle: cy.label, showCatAxisTitle: true, catAxisTitle: cx.label, valAxisTitleFontSize: 11, catAxisTitleFontSize: 11,
      valAxisLabelFormatCode: pptFormat(cy.type, cy.unit, ys), catLabelFormatCode: pptFormat(cx.type, cx.unit, xs)});
  } else {
    const g = grid(visual);
    const size = g.rows.length <= 10 ? 12 : g.rows.length <= 16 ? 10 : 9;
    const rowH = size === 12 ? 0.36 : size === 10 ? 0.3 : 0.26;
    const head = g.header.map((h, j) => ({text: h, options: {bold: true, fill: {color: bare(HEAD)}, color: bare(INK), align: g.types[j] === 'string' ? 'left' as const : 'right' as const}}));
    const body = g.rows.map(row => row.map((c, j) => ({text: c.text, options: {
      align: c.numeric ? 'right' as const : 'left' as const, color: bare(c.color ?? INK), bold: visual.kind === 'heatmap' && j === 0,
      ...(c.fill ? {fill: {color: bare(c.fill)}} : {})}})));
    // Columns as wide as their longest text, so a label does not wrap and push the table past the slide.
    const weights = g.header.map((h, j) => Math.max(6, h.length, ...g.rows.map(r => r[j].text.length)));
    const colW = weights.map(w => area.w * w / weights.reduce((a, b) => a + b, 0));
    const legend = visual.kind === 'heatmap';
    const bottom = legend ? 6.25 : 6.6;
    const fits = Math.max(1, Math.floor((bottom - area.y) / rowH) - 1);
    for (let part = 0, start = 0; start < body.length; part++, start += fits) {
      const s = framed(part);
      const chunk = body.slice(start, start + fits);
      s.addTable([head, ...chunk], {x: area.x, y: area.y, w: area.w, colW, rowH, fontFace: face, fontSize: size, valign: 'middle',
        border: {type: 'solid', pt: 0.75, color: bare(LINE)}, margin: [0.03, 0.08, 0.03, 0.08]});
      if (legend) {
        const heat = heatScale(visual);
        const y = Math.min(6.35, area.y + rowH * (chunk.length + 1) + 0.2);
        heat.stops.forEach((color, i) => s.addShape(deck.ShapeType.rect, {x: area.x + i * 0.22, y, w: 0.22, h: 0.14,
          fill: {color: bare(color)}, line: {color: bare(color), width: 0}}));
        s.addText(heat.kind === 'diverging' ? 'Below zero (red) · zero (grey) · above zero (blue); — no data' : 'Low (light) to high (dark); — no data',
          {x: area.x + heat.stops.length * 0.22 + 0.15, y: y - 0.08, w: 7, h: 0.3, fontFace: face, fontSize: 10, color: bare(INK_2), margin: 0});
      }
    }
  }
  return withBlanks(await deck.write({outputType: 'arraybuffer'}) as ArrayBuffer);
}

/** A missing value written the way Office writes a blank: no point in the chart's cache, an empty cell in its
 *  workbook. pptxgenjs writes an empty value instead, which some readers take for an error. */
async function withBlanks(file: ArrayBuffer): Promise<Blob> {
  const zip = await JSZip.loadAsync(file);
  for (const name of Object.keys(zip.files)) {
    if (/^ppt\/charts\/chart\d*\.xml$/.test(name)) {
      zip.file(name, (await zip.file(name)!.async('string')).replace(/<c:pt idx="\d+"><c:v><\/c:v><\/c:pt>/g, ''));
    } else if (/^ppt\/embeddings\/.+\.xlsx$/.test(name)) {
      const inner = await JSZip.loadAsync(await zip.file(name)!.async('arraybuffer'));
      for (const sheet of Object.keys(inner.files).filter(n => /^xl\/worksheets\/sheet\d+\.xml$/.test(n))) {
        inner.file(sheet, (await inner.file(sheet)!.async('string')).replace(/<c r="([A-Z]+\d+)"><v><\/v><\/c>/g, '<c r="$1"/>'));
      }
      zip.file(name, await inner.generateAsync({type: 'uint8array', compression: 'DEFLATE'}));
    }
  }
  return zip.generateAsync({type: 'blob', mimeType: 'application/vnd.openxmlformats-officedocument.presentationml.presentation', compression: 'DEFLATE'});
}

// ----------------------------------------------------------------------------------------------- Excel

interface XStyle { bold?: boolean; size?: number; color?: string; fill?: string; format?: string | null; align?: 'left' | 'right'; wrap?: boolean; border?: boolean; italic?: boolean }
interface XCell { value: string | number | null; style?: XStyle }
interface XSheet { name: string; rows: XCell[][]; widths: number[]; freeze?: number }

const xml = (text: string) => text.replace(/[^\u0009\u000a\u000d -퟿-�]/g, '').replace(/&/g, '&amp;')
  .replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
const argb = (color: string) => 'FF' + bare(color);

function columnName(index: number): string {
  let name = '';
  for (let n = index + 1; n > 0; n = Math.floor((n - 1) / 26)) name = String.fromCharCode(65 + ((n - 1) % 26)) + name;
  return name;
}

class Styles {
  private fonts = ['<font><sz val="11"/><color rgb="FF18233B"/><name val="Calibri"/><family val="2"/></font>'];
  private fills = ['<fill><patternFill patternType="none"/></fill>', '<fill><patternFill patternType="gray125"/></fill>'];
  private formats: string[] = [];
  private xfs = ['<xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>'];
  private known = new Map<string, number>();

  id(style: XStyle | undefined): number {
    if (!style) return 0;
    const key = JSON.stringify(style);
    const found = this.known.get(key);
    if (found !== undefined) return found;
    const font = `<font>${style.bold ? '<b/>' : ''}${style.italic ? '<i/>' : ''}<sz val="${style.size ?? 11}"/><color rgb="${argb(style.color ?? INK)}"/><name val="Calibri"/><family val="2"/></font>`;
    let fontId = this.fonts.indexOf(font);
    if (fontId < 0) fontId = this.fonts.push(font) - 1;
    let fillId = 0;
    if (style.fill) {
      const fill = `<fill><patternFill patternType="solid"><fgColor rgb="${argb(style.fill)}"/><bgColor indexed="64"/></patternFill></fill>`;
      fillId = this.fills.indexOf(fill);
      if (fillId < 0) fillId = this.fills.push(fill) - 1;
    }
    let formatId = 0;
    if (style.format) {
      const at = this.formats.indexOf(style.format);
      formatId = 164 + (at < 0 ? this.formats.push(style.format) - 1 : at);
    }
    const align = style.align || style.wrap ? `<alignment${style.align ? ` horizontal="${style.align}"` : ''}${style.wrap ? ' wrapText="1"' : ''} vertical="top"/>` : '';
    const xf = `<xf numFmtId="${formatId}" fontId="${fontId}" fillId="${fillId}" borderId="${style.border ? 1 : 0}" xfId="0"` +
      ` applyNumberFormat="1" applyFont="1" applyFill="1" applyBorder="1"${align ? ' applyAlignment="1">' + align + '</xf>' : '/>'}`;
    const id = this.xfs.push(xf) - 1;
    this.known.set(key, id);
    return id;
  }

  xml(): string {
    const border = `<left style="thin"><color rgb="${argb(LINE)}"/></left><right style="thin"><color rgb="${argb(LINE)}"/></right>` +
      `<top style="thin"><color rgb="${argb(LINE)}"/></top><bottom style="thin"><color rgb="${argb(LINE)}"/></bottom><diagonal/>`;
    return '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">' +
      (this.formats.length ? `<numFmts count="${this.formats.length}">${this.formats.map((f, i) => `<numFmt numFmtId="${164 + i}" formatCode="${xml(f)}"/>`).join('')}</numFmts>` : '') +
      `<fonts count="${this.fonts.length}">${this.fonts.join('')}</fonts><fills count="${this.fills.length}">${this.fills.join('')}</fills>` +
      `<borders count="2"><border><left/><right/><top/><bottom/><diagonal/></border><border>${border}</border></borders>` +
      '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>' +
      `<cellXfs count="${this.xfs.length}">${this.xfs.join('')}</cellXfs>` +
      '<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles></styleSheet>';
  }
}

function sheetXml(sheet: XSheet, styles: Styles): string {
  const rows = sheet.rows.map((row, r) => {
    const cells = row.map((cell, c) => {
      const ref = `${columnName(c)}${r + 1}`;
      const s = styles.id(cell.style);
      const style = s ? ` s="${s}"` : '';
      if (typeof cell.value === 'number' && Number.isFinite(cell.value)) return `<c r="${ref}"${style}><v>${cell.value}</v></c>`;
      if (cell.value === null || cell.value === '') return s ? `<c r="${ref}"${style}/>` : '';
      return `<c r="${ref}"${style} t="inlineStr"><is><t xml:space="preserve">${xml(String(cell.value)).slice(0, 32_000)}</t></is></c>`;
    }).join('');
    return `<row r="${r + 1}">${cells}</row>`;
  }).join('');
  const pane = sheet.freeze ? `<sheetViews><sheetView workbookViewId="0"><pane ySplit="${sheet.freeze}" topLeftCell="A${sheet.freeze + 1}" activePane="bottomLeft" state="frozen"/></sheetView></sheetViews>`
    : '<sheetViews><sheetView workbookViewId="0"/></sheetViews>';
  const cols = sheet.widths.length ? `<cols>${sheet.widths.map((w, i) => `<col min="${i + 1}" max="${i + 1}" width="${w}" customWidth="1"/>`).join('')}</cols>` : '';
  return '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" ' +
    'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">' + pane + cols + `<sheetData>${rows}</sheetData></worksheet>`;
}

function sheetName(name: string, taken: Set<string>): string {
  const base = name.replace(/[[\]:*?/\\]/g, ' ').replace(/^'+|'+$/g, '').trim().slice(0, 31) || 'Sheet';
  let candidate = base;
  for (let n = 2; taken.has(candidate.toLowerCase()); n++) candidate = `${base.slice(0, 27)} (${n})`;
  taken.add(candidate.toLowerCase());
  return candidate;
}

/** A workbook from sheets: one worksheet each, inline strings, the styles they use. */
export async function workbook(sheets: XSheet[]): Promise<Blob> {
  const zip = new JSZip();
  const styles = new Styles();
  const parts = sheets.map(s => sheetXml(s, styles));
  zip.file('[Content_Types].xml', '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">' +
    '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/>' +
    '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>' +
    '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>' +
    '<Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>' +
    sheets.map((_, i) => `<Override PartName="/xl/worksheets/sheet${i + 1}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>`).join('') +
    '</Types>');
  zip.file('_rels/.rels', '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">' +
    '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>' +
    '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/></Relationships>');
  zip.file('docProps/core.xml', '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" ' +
    'xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:dcterms="http://purl.org/dc/terms/" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">' +
    `<dc:creator>Wizard</dc:creator><dcterms:created xsi:type="dcterms:W3CDTF">${new Date().toISOString().replace(/\.\d+Z$/, 'Z')}</dcterms:created></cp:coreProperties>`);
  zip.file('xl/workbook.xml', '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" ' +
    'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets>' +
    sheets.map((s, i) => `<sheet name="${xml(s.name)}" sheetId="${i + 1}" r:id="rId${i + 1}"/>`).join('') + '</sheets></workbook>');
  zip.file('xl/_rels/workbook.xml.rels', '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">' +
    sheets.map((_, i) => `<Relationship Id="rId${i + 1}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet${i + 1}.xml"/>`).join('') +
    `<Relationship Id="rId${sheets.length + 1}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/></Relationships>`);
  parts.forEach((part, i) => zip.file(`xl/worksheets/sheet${i + 1}.xml`, part));
  zip.file('xl/styles.xml', styles.xml());
  return zip.generateAsync({type: 'blob', mimeType: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', compression: 'DEFLATE'});
}

const NOTE: XStyle = {color: '#65728a', italic: true};
const HEADER: XStyle = {bold: true, fill: HEAD, border: true};

function width(texts: string[]): number {
  return Math.min(60, Math.max(8, ...texts.map(t => t.length + 2)));
}

/** A table of typed columns as sheet rows: the header, then each row with Excel's number formats. */
function typedRows(columns: {label: string; type: string; unit: string | null}[], rows: Cell[][], fills?: (string | undefined)[][], colors?: (string | undefined)[][]): XCell[][] {
  const formats = columns.map((c, j) => excelFormat(c.type, c.unit, rows.map(r => r[j] ?? null)));
  return [
    columns.map(c => ({value: c.label + (c.unit && c.type !== 'string' && !['%', 'USD'].includes(c.unit) ? ` (${c.unit})` : ''),
      style: {...HEADER, align: c.type === 'string' ? 'left' as const : 'right' as const}})),
    ...rows.map((row, i) => columns.map((c, j) => {
      const raw = row[j] ?? null;
      const value = c.type === 'string' ? (raw === null ? null : String(raw)) : excelValue({value: typeof raw === 'number' ? raw : null, type: c.type});
      return {value: c.type !== 'string' && typeof raw === 'string' ? raw : value,
        style: {border: true, format: formats[j], ...(fills?.[i]?.[j] ? {fill: fills[i][j], color: colors?.[i]?.[j]} : {})}};
    })),
  ];
}

function evidenceColumns(columns: Column[]): {label: string; type: string; unit: string | null}[] {
  return columns.map(c => ({label: c.label || c.key, type: ['integer', 'number', 'percent', 'currency'].includes(c.type) ? c.type : 'string', unit: c.unit ?? null}));
}

/** The visual's workbook: its values as on screen, its sources, and (in Wizard) each cited source's rows. */
export async function xlsx(visual: Visual, env: VisualEnv): Promise<Blob> {
  const {sources, rows} = await env.sources(visual.evidence_ids);
  const taken = new Set<string>();
  const g = grid(visual, true);
  const lead: XCell[][] = [[{value: visual.title, style: {bold: true, size: 14}}]];
  if (visual.subtitle) lead.push([{value: visual.subtitle, style: {color: INK_2}}]);
  lead.push([{value: sourceLine(visual, env.dataMode, sources.map(s => `${s.id} ${s.name}`)), style: NOTE}], []);
  const table = typedRows(visual.columns, visual.rows, g.rows.map(r => r.map(c => c.fill)), g.rows.map(r => r.map(c => c.color)));
  const data: XSheet = {name: sheetName(`${visual.id} ${visual.kind === 'table' ? 'table' : visual.kind}`, taken), rows: [...lead, ...table],
    widths: g.header.map((h, j) => width([h, ...g.rows.map(r => r[j].text)])), freeze: lead.length + 1};
  const sheets: XSheet[] = [data];
  if (sources.length || visual.evidence_ids.length) {
    const known = new Map(sources.map(s => [s.id, s]));
    const list = visual.evidence_ids.map(id => known.get(id) ?? {id, name: 'Not available here'});
    sheets.push({name: sheetName('Sources', taken), widths: [10, 44, 18, 16, 12, 90], rows: [
      [{value: `Where ${visual.id}'s values came from`, style: {bold: true, size: 14}}],
      [{value: env.rowsBehind ? 'Each source with rows has its own sheet: the rows it returned to Wizard.'
        : 'The rows are not published with a case; each source names the query that read them.', style: NOTE}],
      [],
      ['Evidence', 'Source', 'Data label', 'As of', 'Rows read', 'Query'].map(value => ({value, style: HEADER})),
      ...list.map(s => [s.id, s.name, s.dataMode ?? '', s.asOf ? formatDate(s.asOf) : '', s.totalRows ?? null, s.query ?? '']
        .map((value, j) => ({value, style: {border: true, wrap: j === 5, format: j === 4 ? '#,##0' : null}}))),
    ]});
  }
  for (const source of rows as SourceRows[]) {
    const meta = sources.find(s => s.id === source.id);
    const columns = evidenceColumns(source.columns);
    const kept = source.rows.length;
    sheets.push({name: sheetName(`${source.id} rows`, taken), freeze: 4,
      widths: columns.map((c, j) => width([c.label, ...source.rows.slice(0, 200).map(r => String(r[j] ?? ''))])),
      rows: [
        [{value: `${source.id} · ${meta?.name ?? source.id}`, style: {bold: true, size: 14}}],
        [{value: [meta?.dataMode, meta?.asOf ? `as of ${formatDate(meta.asOf)}` : '', `${kept.toLocaleString()} rows kept by Wizard` +
          (source.truncated || (meta?.totalRows ?? kept) > kept ? ` of ${(meta?.totalRows ?? kept).toLocaleString()} read` : '')].filter(Boolean).join(' · '), style: NOTE}],
        [],
        ...typedRows(columns, source.rows),
      ]});
  }
  return workbook(sheets);
}

export type ExportKind = 'pptx' | 'xlsx' | 'png';

/** Build one download and hand it over (Downloads on this PC, else the browser). */
export async function download(kind: ExportKind, visual: Visual, env: VisualEnv): Promise<{saved: SavedExport | null; filename: string}> {
  const file = kind === 'pptx' ? await pptx(visual, env) : kind === 'xlsx' ? await xlsx(visual, env) : await picture(visual, env);
  const filename = fileName(visual, kind);
  return {saved: await deliver(env, file, filename), filename};
}
