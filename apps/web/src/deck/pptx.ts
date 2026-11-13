// The presentation as a PowerPoint file, written in the page from the same layout the preview draws (layout.ts): native
// text boxes, tables with their shading, and charts PowerPoint can edit (their data opens in Excel), in the company's
// fonts and colors; speaker notes carry what to say and the sources. Loaded only when the person downloads a deck.
import JSZip from 'jszip';
import type PptxGenJS from 'pptxgenjs';
import {formatValue} from '../format';
import type {Deck, Visual} from '../types';
import {layoutDeck, lineAxisMin, lineLabels, type DrawnChart, type Element, type Para} from './layout';

const bare = (color: string) => color.replace('#', '').toUpperCase();

/** A PowerPoint number format for a column's values, as Wizard shows them (percent values are 0-100). */
function numberFormat(type: string, unit: string | null, values: (number | null)[]): string {
  const nums = values.filter((v): v is number => typeof v === 'number');
  if (type === 'percent') return '0.0"%"';
  const big = nums.length > 0 && Math.max(...nums.map(Math.abs)) >= 1e6;
  if (type === 'currency') {
    const sign = !unit || unit === 'USD' ? '"$"' : '';
    return big ? `${sign}#,##0.0,,"M"` : `${sign}#,##0`;
  }
  return nums.every(Number.isInteger) ? (big ? '#,##0.0,,"M"' : '#,##0') : '#,##0.0';
}

function textRuns(paras: Para[]): PptxGenJS.TextProps[] {
  const out: PptxGenJS.TextProps[] = [];
  paras.forEach((p, i) => {
    p.runs.forEach((r, j) => {
      const first = j === 0;
      out.push({text: r.text, options: {
        fontFace: p.font, fontSize: p.size, color: bare(r.color ?? p.color), bold: !!(r.bold ?? p.bold),
        // Paragraph settings go on a paragraph's first run (pptx.ts tidies the rest away: tidyParagraphs).
        ...(first ? {align: p.align ?? 'left', paraSpaceBefore: i ? p.gap ?? 0 : 0,
          ...(p.bullet ? {bullet: {indent: p.level ? 12 : 14}, indentLevel: p.level ?? 0} : {})} : {}),
        breakLine: j === p.runs.length - 1 && i < paras.length - 1,
      }});
    });
  });
  return out;
}

function chartData(visual: Visual, chart: DrawnChart) {
  const keys = visual.columns.map(c => c.key);
  const col = (key: string) => visual.columns.find(c => c.key === key)!;
  const values = (key: string) => visual.rows.map(r => { const v = r[keys.indexOf(key)]; return typeof v === 'number' ? v : null; });
  const labels = visual.rows.map(r => String(r[keys.indexOf(visual.x ?? '')] ?? ''));
  // PowerPoint draws a horizontal bar chart's first category at the bottom: the rows go in last first, so the slide
  // reads top to bottom as the answer does.
  const order = <T,>(items: T[]) => chart === 'bar' || chart === 'stacked_bar' ? [...items].reverse() : items;
  return {col, values, labels, data: visual.series.map(key => ({name: col(key).label, labels: order(labels), values: order(values(key)) as number[]}))};
}

function addChart(pres: PptxGenJS, slide: PptxGenJS.Slide, el: Extract<Element, {type: 'chart'}>) {
  const {visual, chart, tokens: t} = el;
  const box = {x: el.x, y: el.y, w: el.w, h: el.h};
  const series = visual.series.length;
  const axis = {
    catAxisLabelFontFace: t.fonts.labels, valAxisLabelFontFace: t.fonts.labels, catAxisLabelFontSize: t.sizes.chart_label,
    valAxisLabelFontSize: t.sizes.chart_label, catAxisLabelColor: bare(t.colors.secondary), valAxisLabelColor: bare(t.colors.muted),
    valGridLine: {color: bare(t.colors.line), size: 0.5}, catGridLine: {style: 'none' as const}, catAxisLineShow: true,
    valAxisLineShow: false, chartColors: (t.colors.series.length ? t.colors.series : [t.colors.brand]).slice(0, Math.max(1, series)).map(bare),
    displayBlanksAs: 'gap', showLegend: series > 1, legendPos: 't' as const, legendFontSize: t.sizes.chart_label, legendFontFace: t.fonts.labels,
    legendColor: bare(t.colors.secondary),
  };
  if (chart === 'scatter') {
    const {values, labels, col} = chartData(visual, chart);
    const [xs, ys] = [values(visual.series[0]), values(visual.series[1])];
    const kept = xs.map((x, i) => x !== null && ys[i] !== null ? i : -1).filter(i => i >= 0);
    const [cx, cy] = [col(visual.series[0]), col(visual.series[1])];
    slide.addChart(pres.ChartType.scatter, [
      {name: cx.label, values: kept.map(i => xs[i]!)},
      {name: cy.label, values: kept.map(i => ys[i]!), labels: [kept.map(i => labels[i])]} as unknown as {name: string; values: number[]},
    ], {...box, ...axis, showLegend: false, lineSize: 0, lineDataSymbol: 'circle', lineDataSymbolSize: 8, showLabel: true,
      dataLabelFormatScatter: 'custom', dataLabelPosition: 'r', dataLabelFontSize: t.sizes.chart_label, dataLabelFontFace: t.fonts.labels,
      showValAxisTitle: true, valAxisTitle: cy.label, showCatAxisTitle: true, catAxisTitle: cx.label,
      valAxisTitleFontSize: t.sizes.chart_label, catAxisTitleFontSize: t.sizes.chart_label,
      valAxisLabelFormatCode: numberFormat(cy.type, cy.unit, ys), catLabelFormatCode: numberFormat(cx.type, cx.unit, xs)});
    return;
  }
  const {data, col, values} = chartData(visual, chart);
  const first = col(visual.series[0]);
  const format = numberFormat(first.type, first.unit, values(first.key));
  if (chart === 'line') {
    slide.addChart(pres.ChartType.line, data, {...box, ...axis, lineSize: 2, lineDataSymbol: 'circle', lineDataSymbolSize: 6,
      valAxisLabelFormatCode: format, showValue: lineLabels(visual), dataLabelPosition: 't',
      ...(lineAxisMin(visual) !== undefined ? {valAxisMinVal: lineAxisMin(visual)} : {}),
      dataLabelFontSize: t.sizes.chart_label, dataLabelFontFace: t.fonts.labels, dataLabelColor: bare(t.colors.secondary), dataLabelFormatCode: format});
    return;
  }
  const horizontal = chart === 'bar' || chart === 'stacked_bar';
  const grouping = chart === 'stacked' || chart === 'stacked_bar' ? 'stacked' : chart === 'percent' ? 'percentStacked' : 'clustered';
  const stacked = grouping !== 'clustered';
  // Values on the bars when they stay legible: every bar of a simple chart, inside the segments of a stacked one.
  const labelled = stacked ? visual.rows.length * series <= 40 : visual.rows.length * series <= 24;
  slide.addChart(pres.ChartType.bar, data, {...box, ...axis, barDir: horizontal ? 'bar' : 'col', barGrouping: grouping,
    barGapWidthPct: stacked ? 55 : 70, ...(stacked ? {barOverlapPct: 100} : {}),
    valAxisLabelFormatCode: chart === 'percent' ? '0%' : format, showValue: labelled,
    dataLabelPosition: stacked ? 'ctr' : 'outEnd', dataLabelFontSize: t.sizes.chart_label, dataLabelFontFace: t.fonts.labels,
    dataLabelColor: stacked ? 'FFFFFF' : bare(t.colors.secondary), dataLabelFormatCode: format});
}

function addElement(pres: PptxGenJS, slide: PptxGenJS.Slide, el: Element) {
  switch (el.type) {
    case 'rect':
      slide.addShape(pres.ShapeType.rect, {x: el.x, y: el.y, w: el.w, h: el.h, fill: {color: bare(el.fill)},
        line: el.line ? {color: bare(el.line), width: 0.75} : {type: 'none'}});
      return;
    case 'badge':
      slide.addText(el.text, {shape: pres.ShapeType.ellipse, x: el.x, y: el.y, w: el.w, h: el.h, fill: {color: bare(el.fill)},
        color: bare(el.color), fontFace: el.font, fontSize: el.size, bold: true, align: 'center', valign: 'middle', margin: 0});
      return;
    case 'text': {
      const inset = Math.round(el.inset * 72);
      slide.addText(textRuns(el.paras), {x: el.x, y: el.y, w: el.w, h: el.h, valign: el.valign, margin: [inset, inset, inset, inset],
        fit: 'none', wrap: true});
      return;
    }
    case 'table': {
      const rows = el.cells.map(row => row.map(c => ({text: c.text, options: {align: c.align, color: bare(c.color), bold: !!c.bold,
        ...(c.fill ? {fill: {color: bare(c.fill)}} : {})}})));
      slide.addTable(rows, {x: el.x, y: el.y, w: el.w, colW: el.colW, rowH: el.rowH, fontFace: el.font, fontSize: el.size,
        valign: 'middle', border: {type: 'solid', pt: 0.5, color: bare(el.line)}, margin: [0.02, 0.06, 0.02, 0.06], autoPage: false});
      return;
    }
    case 'chart':
      addChart(pres, slide, el);
  }
}

/** pptxgenjs writes a paragraph's settings again before each of its runs (a bullet with a bold lead-in has two runs),
 *  which PowerPoint reads as a damaged file: keep each paragraph's first settings only. */
export function tidyParagraphs(xml: string): string {
  return xml.replace(/<a:p>([\s\S]*?)<\/a:p>/g, (_, inner: string) => {
    let seen = false;
    return '<a:p>' + inner.replace(/<a:pPr\b[^>]*?(?:\/>|>[\s\S]*?<\/a:pPr>)/g, (pPr: string) => {
      if (seen) return '';
      seen = true;
      return pPr;
    }) + '</a:p>';
  });
}

/** The East Asian font on every run and in the theme (pptxgenjs writes the Latin font for both): Korean text then shows
 *  in the company's Korean font. Missing chart values are left out of the cache, as Office writes a blank. */
async function finish(file: ArrayBuffer, eastAsian: string): Promise<Blob> {
  const zip = await JSZip.loadAsync(file);
  const ea = eastAsian.replace(/[<>&"]/g, '');
  for (const name of Object.keys(zip.files)) {
    if (/^ppt\/slides\/slide\d+\.xml$/.test(name)) {
      let xml = tidyParagraphs(await zip.file(name)!.async('string'));
      if (ea) xml = xml.replace(/<a:ea typeface="[^"]*"/g, `<a:ea typeface="${ea}"`);
      zip.file(name, xml);
    } else if (/^ppt\/theme\/theme\d+\.xml$/.test(name) && ea) {
      zip.file(name, (await zip.file(name)!.async('string')).replace(/<a:ea typeface=""\/>/g, `<a:ea typeface="${ea}"/>`));
    } else if (/^ppt\/charts\/chart\d*\.xml$/.test(name)) {
      zip.file(name, (await zip.file(name)!.async('string')).replace(/<c:pt idx="\d+"><c:v><\/c:v><\/c:pt>/g, ''));
    }
  }
  return zip.generateAsync({type: 'blob', mimeType: 'application/vnd.openxmlformats-officedocument.presentationml.presentation', compression: 'DEFLATE'});
}

export async function deckPptx(deck: Deck): Promise<Blob> {
  const {default: Pptx} = await import('pptxgenjs');
  const t = deck.design.tokens;
  const pres = new Pptx();
  // 13.33 in is PowerPoint's 16:9 width (12,192,000 EMU): a rounded width in the tokens still makes the standard slide.
  const snap = (v: number, to: number) => Math.abs(v - to) < 0.02 ? to : v;
  pres.defineLayout({name: 'WIZARD', width: snap(t.slide.width, 40 / 3), height: snap(t.slide.height, 7.5)});
  pres.layout = 'WIZARD';
  pres.theme = {headFontFace: t.fonts.title, bodyFontFace: t.fonts.body};
  pres.author = 'Wizard';
  pres.company = '';
  pres.title = deck.title;
  pres.subject = deck.storyline;
  for (const page of layoutDeck(deck)) {
    const slide = pres.addSlide();
    slide.background = {color: bare(page.background)};
    for (const el of page.elements) addElement(pres, slide, el);
    if (page.notes) slide.addNotes(page.notes);
  }
  return finish(await pres.write({outputType: 'arraybuffer'}) as ArrayBuffer, t.fonts.east_asian);
}

/** What a chart's value looks like on a slide (the preview's labels). */
export function chartValue(visual: Visual, key: string, value: unknown): string {
  const column = visual.columns.find(c => c.key === key);
  return formatValue(value, column?.type, column?.unit);
}
