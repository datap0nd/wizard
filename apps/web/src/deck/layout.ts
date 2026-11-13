// Where everything goes on each slide of a presentation Gemini made (deck_tools.py), in the company's design (its design
// tokens, from the knowledge base). One layout, two renderers: SlideView draws it in the page and pptx.ts writes it to
// PowerPoint with native text, tables and charts, so what the person sees is what they download. Pure: positions are
// inches on the slide, sizes are points.
import {formatDate} from '../format';
import {grid} from '../visuals';
import type {ChartStyle, Deck, DeckPoint, DeckSlide, DesignTokens, SlideKind, Visual} from '../types';

export interface Run { text: string; bold?: boolean; color?: string }
export interface Para {
  runs: Run[];
  size: number;
  color: string;
  font: string;
  bold?: boolean;
  bullet?: boolean;
  level?: number;
  align?: 'left' | 'center' | 'right';
  /** Space before the paragraph, in points. */
  gap?: number;
}
export interface TableCell { text: string; fill?: string; color: string; bold?: boolean; align: 'left' | 'right' | 'center' }
/** How a chart is drawn: a deck's chart style, resolved for its visual. */
export type DrawnChart = 'column' | 'stacked' | 'percent' | 'bar' | 'stacked_bar' | 'line' | 'scatter';

interface Box { x: number; y: number; w: number; h: number }
export type Element =
  | (Box & {type: 'rect'; fill: string; line?: string})
  | (Box & {type: 'text'; paras: Para[]; valign: 'top' | 'middle' | 'bottom'; inset: number})
  | (Box & {type: 'badge'; fill: string; text: string; color: string; size: number; font: string})
  | (Box & {type: 'chart'; visual: Visual; chart: DrawnChart; tokens: DesignTokens})
  | (Box & {type: 'table'; cells: TableCell[][]; colW: number[]; rowH: number; size: number; font: string; line: string});

export interface Page {
  number: number;
  kind: SlideKind;
  title: string;
  background: string;
  elements: Element[];
  notes: string;
}

export const SYNTHETIC_NOTE = 'SYNTHETIC test data, not corporate figures';

// ----------------------------------------------------------------------------------------------- measuring text

const WIDE = /[ᄀ-ᇿ⺀-鿿가-힯豈-﫿＀-￯]/;

/** How wide a text is set in a font of this size, in inches: an average-width estimate (Latin letters about half an
 *  em, capitals and figures more, Korean, Chinese and Japanese a full em). */
export function textWidth(text: string, size: number, bold = false): number {
  let em = 0;
  for (const ch of text) em += WIDE.test(ch) ? 1 : ch === ' ' ? 0.28 : /[A-Z0-9%$#@&MW]/.test(ch) ? 0.64 : /[iljtf.,:;'|!()[\]]/.test(ch) ? 0.3 : 0.52;
  return em * (bold ? 1.06 : 1) * size / 72;
}

const LINE = 1.2;  // line height, as a multiple of the font size

function paraLines(p: Para, width: number): number {
  const indent = p.bullet ? 0.2 + (p.level ?? 0) * 0.25 : 0;
  const room = Math.max(0.3, width - indent);
  const text = p.runs.map(r => r.text).join('');
  // Words wrap whole: a line holds a little less than its width.
  return Math.max(1, Math.ceil(textWidth(text, p.size, p.bold || p.runs.some(r => r.bold)) * 1.08 / room));
}

/** The height paragraphs take in a box this wide, in inches. */
export function textHeight(paras: Para[], width: number): number {
  return paras.reduce((h, p, i) => h + paraLines(p, width) * p.size * LINE / 72 + (i ? (p.gap ?? 0) / 72 : 0), 0);
}

/** The paragraphs at the largest size, down to `least` of it, that fits the box (a long title is drawn smaller, never
 *  cut). */
export function fit(paras: Para[], box: {w: number; h: number}, least = 0.6, inset = 0): Para[] {
  return scaled(paras, fitScale(paras, box, least, inset));
}

/** The largest scale, down to `least`, at which the paragraphs fit the box. */
export function fitScale(paras: Para[], box: {w: number; h: number}, least = 0.6, inset = 0): number {
  const w = box.w - inset * 2, h = box.h - inset * 2;
  for (let scale = 1; scale >= least - 1e-9; scale -= 0.04) {
    if (textHeight(scaled(paras, scale), w) <= h) return scale;
  }
  return least;
}

function scaled(paras: Para[], scale: number): Para[] {
  return scale === 1 ? paras : paras.map(p => ({...p, size: Math.round(p.size * scale * 2) / 2, gap: (p.gap ?? 0) * scale}));
}

/** A text's runs: **bold** marks a lead-in. */
export function runs(text: string, color?: string): Run[] {
  const out: Run[] = [];
  text.split(/(\*\*[^*]+\*\*)/).forEach(part => {
    if (!part) return;
    const bold = /^\*\*[^*]+\*\*$/.test(part);
    out.push({text: bold ? part.slice(2, -2) : part, bold: bold || undefined, color});
  });
  return out.length ? out : [{text: '', color}];
}

// ----------------------------------------------------------------------------------------------- charts and tables

/** How a slide's chart style draws its visual: auto draws a bar visual as columns when its few labels are short (time,
 *  segments) and as horizontal bars when they are many or long (rankings). */
export function drawnChart(visual: Visual, style: ChartStyle | undefined): DrawnChart {
  if (visual.kind === 'scatter') return 'scatter';
  if (style && style !== 'auto') return visual.kind === 'line' && style !== 'line' && style !== 'column' && style !== 'bar' ? 'line' : style;
  if (visual.kind === 'line') return 'line';
  const keys = visual.columns.map(c => c.key);
  const labels = visual.rows.map(r => String(r[keys.indexOf(visual.x ?? '')] ?? ''));
  const longest = Math.max(0, ...labels.map(l => l.length));
  return labels.length > 10 || longest > 14 ? 'bar' : 'column';
}

/** Where a line chart's value axis starts: at zero, unless the values sit in a narrow band far from it (shares, rates),
 *  where a zero start flattens every line; then a round number below the lowest value. */
export function lineAxisMin(visual: Visual): number | undefined {
  const keys = visual.columns.map(c => c.key);
  const values = visual.rows.flatMap(r => visual.series.map(s => r[keys.indexOf(s)])).filter((v): v is number => typeof v === 'number');
  if (!values.length) return undefined;
  const low = Math.min(...values), high = Math.max(...values);
  if (low <= 0 || (high - low) / high > 0.5) return undefined;
  const step = 10 ** Math.floor(Math.log10(Math.max(high - low, high * 0.01)));
  return Math.max(0, Math.floor((low - (high - low) * 0.25) / step) * step);
}

/** Values on a line chart: on every point of a single line that is short enough to read; several lines are told apart
 *  by the legend instead, where labels would collide. */
export function lineLabels(visual: Visual): boolean {
  return visual.series.length === 1 && visual.rows.length <= 12;
}

/** The unit a chart or table states in its corner, e.g. "(units)" or "(USD)": its measures' one unit, if they share one. */
export function unitLabel(visual: Visual): string {
  const keys = visual.kind === 'table' ? visual.columns.filter(c => c.type !== 'string').map(c => c.key) : visual.series;
  const measures = visual.columns.filter(c => keys.includes(c.key));
  const units = new Set(measures.map(c => c.type === 'percent' ? '%' : c.unit ?? (c.type === 'currency' ? 'USD' : '')));
  const [unit] = [...units];
  return units.size === 1 && unit ? `(${unit})` : '';
}

const norm = (text: string) => text.trim().toLowerCase();

/** A table slide's cells: the visual's grid (a heatmap keeps its shading) with the deck's highlights. */
export function tableCells(visual: Visual, highlights: DeckSlide['highlights'], t: DesignTokens): {cells: TableCell[][]; header: number} {
  const g = grid(visual);
  const columns = visual.kind === 'heatmap' ? [visual.x ?? '', ...visual.series] : visual.columns.map(c => c.key);
  const meta = columns.map(k => visual.columns.find(c => c.key === k));
  const head: TableCell[] = g.header.map((h, j) => ({text: h, fill: t.colors.card, color: t.colors.secondary, bold: true,
    align: g.types[j] === 'string' ? 'left' : 'right'}));
  const body: TableCell[][] = g.rows.map(row => row.map((c, j) => ({text: c.text, fill: c.fill, color: c.color ?? t.colors.text,
    align: c.numeric ? 'right' : 'left', bold: visual.kind === 'heatmap' && j === 0 ? true : undefined})));
  for (const h of highlights ?? []) {
    const i = g.rows.findIndex(r => norm(r[0].text) === norm(h.row) || norm(String(r[0].value ?? '')) === norm(h.row));
    const j = meta.findIndex(c => !!c && (norm(c.key) === norm(h.column) || norm(c.label) === norm(h.column)));
    if (i < 0 || j < 0) continue;
    body[i][j] = {...body[i][j], fill: h.tone === 'good' ? t.colors.good_fill : t.colors.bad_fill,
      color: h.tone === 'good' ? t.colors.good_text : t.colors.bad_text, bold: true};
  }
  return {cells: [head, ...body], header: 1};
}

// ----------------------------------------------------------------------------------------------- slides

interface Frame { W: number; H: number; M: number; sx: number; sy: number; t: DesignTokens }

function bullets(points: DeckPoint[] | undefined, t: DesignTokens, size: number, color = t.colors.text): Para[] {
  const out: Para[] = [];
  for (const point of points ?? []) {
    const text = typeof point === 'string' ? point : point.text;
    out.push({runs: runs(text), size, color, font: t.fonts.body, bullet: true, level: 0, gap: size * 0.55});
    for (const sub of typeof point === 'string' ? [] : point.sub ?? []) {
      out.push({runs: runs(sub), size: Math.max(7, size - 1), color: t.colors.secondary, font: t.fonts.body, bullet: true, level: 1, gap: size * 0.25});
    }
  }
  return out;
}

function text(box: Box, paras: Para[], valign: 'top' | 'middle' | 'bottom' = 'top', least = 0.6, inset = 0.04): Element {
  return {type: 'text', ...box, paras: fit(paras, box, least, inset), valign, inset};
}

/** The title, the subtitle and the brand rule under them; returns where the content starts. */
function header(f: Frame, slide: DeckSlide, elements: Element[], fallback = ''): number {
  const {M, W, sy, t} = f;
  const title = slide.title || fallback;
  const sub = slide.subtitle;
  elements.push(text({x: M, y: 0.32 * sy, w: W - 2 * M, h: 0.98 * sy},
    [{runs: [{text: title}], size: t.sizes.title, color: t.colors.title, font: t.fonts.title, bold: true}], 'bottom', 0.55));
  let y = 1.32 * sy;
  if (sub) {
    elements.push(text({x: M, y, w: W - 2 * M, h: 0.4 * sy}, [{runs: [{text: sub}], size: t.sizes.subtitle, color: t.colors.secondary, font: t.fonts.subtitle}], 'top', 0.7));
    y += 0.44 * sy;
  }
  elements.push({type: 'rect', x: M, y: y + 0.02 * sy, w: W - 2 * M, h: 0.025, fill: t.colors.brand});
  return y + 0.22 * sy;
}

/** Bullets in a box; on a panel (the card color behind them) the panel is as tall as its bullets need. */
function points(f: Frame, box: Box, list: DeckPoint[] | undefined, size: number, panel = false): Element[] {
  if (!panel) return [text(box, bullets(list, f.t, size), 'top', 0.62)];
  const pad = 0.2;
  const inner = {x: box.x + pad, y: box.y + pad, w: box.w - 2 * pad, h: box.h - 2 * pad};
  const paras = fit(bullets(list, f.t, size), inner, 0.62, 0.04);
  const h = Math.min(box.h, textHeight(paras, inner.w - 0.08) + 2 * pad + 0.12);
  return [{type: 'rect', ...box, h, fill: f.t.colors.card}, {type: 'text', ...inner, h: h - 2 * pad, paras, valign: 'top', inset: 0.04}];
}

function kpiTiles(f: Frame, box: Box, kpis: NonNullable<DeckSlide['kpis']>): Element[] {
  const {t} = f;
  const perRow = kpis.length <= 4 ? kpis.length : 3;
  const rows = Math.ceil(kpis.length / perRow);
  const gap = 0.22;
  const w = (box.w - gap * (perRow - 1)) / perRow;
  const h = (box.h - gap * (rows - 1)) / rows;
  const tiles = kpis.map(k => {
    const tone = k.tone === 'good' ? t.colors.positive : k.tone === 'bad' ? t.colors.negative : t.colors.secondary;
    const paras: Para[] = [{runs: [{text: k.value}], size: t.sizes.kpi, color: t.colors.brand, font: t.fonts.title, bold: true},
      {runs: [{text: k.label}], size: t.sizes.body, color: t.colors.text, font: t.fonts.body, gap: 4}];
    if (k.change) paras.push({runs: [{text: k.change}], size: t.sizes.body, color: tone, font: t.fonts.body, bold: true, gap: 3});
    return paras;
  });
  // One scale for every tile, so their figures and labels match.
  const inner = {w: w - 0.32, h: h - 0.24};
  const scale = Math.min(...tiles.map(paras => fitScale(paras, inner, 0.5, 0.04)));
  const out: Element[] = [];
  tiles.forEach((paras, i) => {
    const x = box.x + (i % perRow) * (w + gap), y = box.y + Math.floor(i / perRow) * (h + gap);
    out.push({type: 'rect', x, y, w, h, fill: t.colors.card});
    out.push({type: 'text', x: x + 0.16, y: y + 0.12, ...inner, paras: scaled(paras, scale), valign: 'top', inset: 0.04});
  });
  return out;
}

function visualBox(f: Frame, box: Box, visual: Visual | undefined, style: ChartStyle | undefined, slide: DeckSlide | null,
  notes: string[]): Element[] {
  const {t} = f;
  if (!visual) return [text(box, [{runs: [{text: 'This visual is not available.'}], size: t.sizes.body, color: t.colors.muted, font: t.fonts.body}])];
  const out: Element[] = [];
  const unit = unitLabel(visual);
  const top = unit ? 0.3 : 0;
  if (unit) out.push(text({x: box.x, y: box.y, w: box.w, h: 0.28}, [{runs: [{text: unit}], size: t.sizes.unit, color: t.colors.muted, font: t.fonts.labels}], 'bottom', 0.8, 0));
  const area = {x: box.x, y: box.y + top, w: box.w, h: box.h - top};
  if (visual.kind === 'table' || visual.kind === 'heatmap' || slide?.kind === 'table') {
    out.push(...table(f, area, visual, slide?.highlights, notes));
  } else {
    out.push({type: 'chart', ...area, visual, chart: drawnChart(visual, style), tokens: t});
  }
  return out;
}

function table(f: Frame, area: Box, visual: Visual, highlights: DeckSlide['highlights'], notes: string[]): Element[] {
  const {t} = f;
  const {cells} = tableCells(visual, highlights, t);
  let size = t.sizes.table;
  const rowH = (s: number) => s * 2 / 72;
  // Smaller type before fewer rows; a table that still does not fit shows its first rows and says so.
  while (size > 7 && rowH(size) * cells.length > area.h) size -= 0.5;
  const fits = Math.max(2, Math.floor(area.h / rowH(size)));
  let shown = cells;
  if (cells.length > fits) {
    shown = cells.slice(0, fits);
    notes.push(`The table shows the first ${fits - 1} of its ${cells.length - 1} rows; ${visual.id} in the answer has them all.`);
  }
  const weights = cells[0].map((_, j) => Math.max(5, ...cells.map(r => r[j].text.length)));
  const total = weights.reduce((a, b) => a + b, 0);
  // As wide as its area (a table of two or three short columns a little narrower), columns as wide as their text.
  const width = cells[0].length >= 4 ? area.w : Math.min(area.w, Math.max(area.w * 0.6, total * size * 0.75 / 72 + cells[0].length * 0.4));
  return [{type: 'table', x: area.x, y: area.y, w: width, h: rowH(size) * shown.length, cells: shown, colW: weights.map(w => width * w / total),
    rowH: rowH(size), size, font: t.fonts.body, line: t.colors.line}];
}

function sourceText(deck: Deck, slide: DeckSlide, notes: string[]): string {
  const ids = [...(slide.evidence_ids ?? []), ...(slide.kpis ?? []).flatMap(k => k.evidence_ids ?? [])];
  for (const v of [slide.visual, slide.left?.visual, slide.right?.visual]) if (v && deck.visuals[v]) ids.push(...deck.visuals[v].evidence_ids);
  const names = new Map<string, string>();
  for (const id of new Set(ids)) {
    const s = deck.sources[id];
    if (!s) continue;
    const key = s.name;
    if (!names.has(key)) names.set(key, s.as_of ? `${s.name} (as of ${formatDate(s.as_of)})` : s.name);
  }
  const parts = [...notes, slide.footnote ?? ''];
  if (names.size) parts.push(`Source: ${[...names.values()].join('; ')}`);
  const synthetic = ids.some(id => deck.sources[id]?.data_mode === 'SYNTHETIC');
  if (synthetic) parts.push(SYNTHETIC_NOTE);
  return parts.filter(Boolean).join(' · ');
}

function footer(f: Frame, deck: Deck, slide: DeckSlide, number: number, notes: string[], elements: Element[], dark = false) {
  const {M, W, H, sy, t} = f;
  const color = dark ? '#FFFFFF' : t.colors.muted;
  const label = t.footer.text;
  const right = (t.footer.page_numbers ? 0.6 : 0) + (label ? 2.6 : 0);
  const source = sourceText(deck, slide, notes);
  if (source) elements.push(text({x: M, y: H - 0.56 * sy, w: W - 2 * M - right - 0.2, h: 0.46 * sy},
    [{runs: [{text: source}], size: t.sizes.footnote, color, font: t.fonts.body}], 'bottom', 0.75, 0));
  if (label) elements.push(text({x: W - M - right, y: H - 0.4 * sy, w: 2.5, h: 0.3 * sy},
    [{runs: [{text: label}], size: t.sizes.footnote, color, font: t.fonts.body, align: 'right'}], 'bottom', 0.75, 0));
  if (t.footer.page_numbers) elements.push(text({x: W - M - 0.6, y: H - 0.4 * sy, w: 0.6, h: 0.3 * sy},
    [{runs: [{text: String(number)}], size: t.sizes.footnote, color, font: t.fonts.body, align: 'right'}], 'bottom', 1, 0));
}

/** Each section slide's pages: from it to the slide before the next section (or the end). */
export function sections(slides: DeckSlide[]): {title: string; from: number; to: number}[] {
  const at = slides.map((s, i) => s.kind === 'section' ? i : -1).filter(i => i >= 0);
  return at.map((i, n) => ({title: slides[i].title ?? '', from: i + 1, to: n + 1 < at.length ? at[n + 1] : slides.length}));
}

function slidePage(deck: Deck, slide: DeckSlide, index: number): Page {
  const t = deck.design.tokens;
  const W = t.slide.width, H = t.slide.height;
  const f: Frame = {W, H, M: 0.5 * W / 13.333, sx: W / 13.333, sy: H / 7.5, t};
  const {M, sy} = f;
  const elements: Element[] = [];
  const notes: string[] = [];
  const number = index + 1;
  let background = t.colors.background;
  let dark = false;
  const bottom = H - 0.66 * sy;
  const visual = (id?: string) => id ? deck.visuals[id] : undefined;

  switch (slide.kind) {
    case 'cover': {
      const brand = t.cover.background === 'brand';
      background = brand ? t.colors.brand : t.colors.background;
      dark = brand;
      const ink = brand ? '#FFFFFF' : t.colors.title;
      if (!brand) elements.push({type: 'rect', x: 0, y: 0, w: 0.22 * f.sx, h: H, fill: t.colors.brand});
      const x = M + 0.35 * f.sx, w = W * 0.78;
      elements.push(text({x, y: H * 0.26, w, h: H * 0.3}, [{runs: [{text: slide.title ?? deck.title}], size: t.sizes.cover_title, color: ink, font: t.fonts.title, bold: true}], 'bottom', 0.5));
      elements.push({type: 'rect', x, y: H * 0.585, w: 1.4 * f.sx, h: 0.05, fill: brand ? '#FFFFFF' : t.colors.brand});
      if (slide.subtitle) elements.push(text({x, y: H * 0.62, w, h: H * 0.14}, [{runs: [{text: slide.subtitle}], size: t.sizes.cover_subtitle, color: ink, font: t.fonts.subtitle, bold: true}], 'top', 0.6));
      if (slide.meta) elements.push(text({x, y: H - 1.25 * sy, w, h: 0.5 * sy}, [{runs: [{text: slide.meta}], size: t.sizes.cover_meta, color: ink, font: t.fonts.subtitle, bold: true}], 'bottom', 0.7));
      break;
    }
    case 'section': {
      background = t.colors.card;
      const n = deck.slides.slice(0, index + 1).filter(s => s.kind === 'section').length;
      elements.push({type: 'rect', x: 0, y: 0, w: 0.22 * f.sx, h: H, fill: t.colors.brand});
      elements.push(text({x: M + 0.35 * f.sx, y: H * 0.2, w: W * 0.5, h: H * 0.22}, [{runs: [{text: String(n).padStart(2, '0')}], size: t.sizes.section_title * 1.6, color: t.colors.brand, font: t.fonts.title, bold: true}], 'bottom'));
      const heading = text({x: M + 0.35 * f.sx, y: H * 0.44, w: W * 0.8, h: H * 0.26}, [{runs: [{text: slide.title ?? ''}], size: t.sizes.section_title, color: t.colors.title, font: t.fonts.title, bold: true}], 'top', 0.55);
      elements.push(heading);
      const used = heading.type === 'text' ? textHeight(heading.paras, heading.w - 0.08) : H * 0.1;
      if (slide.subtitle) elements.push(text({x: M + 0.35 * f.sx, y: H * 0.44 + used + 0.2 * sy, w: W * 0.8, h: H * 0.12}, [{runs: [{text: slide.subtitle}], size: t.sizes.subtitle, color: t.colors.secondary, font: t.fonts.subtitle}], 'top', 0.7));
      break;
    }
    case 'agenda': {
      const top = header(f, slide, elements, 'Agenda');
      const found = sections(deck.slides);
      const items = slide.items?.length ? slide.items.map(title => ({title, from: 0, to: 0})) : found;
      const paras: Para[] = items.map((item, i) => ({runs: [{text: `${String(i + 1).padStart(2, '0')}   `, color: t.colors.brand, bold: true},
        {text: item.title, bold: true}, ...(item.from ? [{text: `  (${item.from === item.to ? item.from : `${item.from}–${item.to}`})`, color: t.colors.muted}] : [])],
        size: t.sizes.agenda, color: t.colors.title, font: t.fonts.title, gap: t.sizes.agenda * 0.9}));
      elements.push(text({x: M + 0.3 * f.sx, y: top + 0.2, w: W - 2 * M - 0.6 * f.sx, h: bottom - top - 0.2},
        paras.length ? paras : [{runs: [{text: 'Add section slides or agenda items.'}], size: t.sizes.body, color: t.colors.muted, font: t.fonts.body}], 'top', 0.55));
      break;
    }
    case 'summary': {
      const top = header(f, slide, elements);
      let y = top;
      if (slide.kpis?.length) {
        const h = 1.45 * sy;
        elements.push(...kpiTiles(f, {x: M, y, w: W - 2 * M, h}, slide.kpis));
        y += h + 0.25 * sy;
      }
      if (slide.points?.length) elements.push(...points(f, {x: M, y, w: W - 2 * M, h: bottom - y}, slide.points, t.sizes.body + 1));
      break;
    }
    case 'kpis': {
      const top = header(f, slide, elements);
      const kpis = slide.kpis ?? [];
      const rows = kpis.length <= 4 ? 1 : 2;
      const room = Math.min(slide.points?.length ? (bottom - top) * 0.6 : bottom - top, rows * 1.75 * sy + (rows - 1) * 0.22);
      elements.push(...kpiTiles(f, {x: M, y: top + 0.1, w: W - 2 * M, h: room}, kpis));
      if (slide.points?.length) elements.push(...points(f, {x: M, y: top + room + 0.4 * sy, w: W - 2 * M, h: bottom - top - room - 0.4 * sy}, slide.points, t.sizes.body + 1));
      break;
    }
    case 'cards': {
      const top = header(f, slide, elements);
      const cards = slide.cards ?? [];
      const gap = 0.25 * f.sx;
      const w = (W - 2 * M - gap * (cards.length - 1)) / Math.max(1, cards.length);
      const d = 0.5 * f.sy;
      const need = (card: (typeof cards)[number]) => 0.55 + d + textHeight([{runs: [{text: card.heading}], size: t.sizes.heading, color: '', font: '', bold: true},
        ...(card.value ? [{runs: [{text: card.value}], size: t.sizes.kpi * 0.75, color: '', font: '', bold: true, gap: 4}] : [])], w - 0.4) + 0.3
        + textHeight(bullets(card.points, t, t.sizes.body), w - 0.4) + 0.3;
      const h = Math.min(bottom - top, Math.max((bottom - top) * 0.55, ...cards.map(need)));
      cards.forEach((card, i) => {
        const x = M + i * (w + gap);
        elements.push({type: 'rect', x, y: top, w, h, fill: t.colors.card});
        elements.push({type: 'badge', x: x + 0.2, y: top + 0.2, w: d, h: d, fill: t.colors.brand, text: String(i + 1), color: '#FFFFFF', size: t.sizes.heading + 2, font: t.fonts.title});
        const head: Para[] = [{runs: [{text: card.heading}], size: t.sizes.heading, color: t.colors.title, font: t.fonts.title, bold: true}];
        if (card.value) head.push({runs: [{text: card.value}], size: t.sizes.kpi * 0.75, color: t.colors.brand, font: t.fonts.title, bold: true, gap: 4});
        const headH = Math.min(1.3 * sy, textHeight(head, w - 0.4) + 0.12);
        elements.push(text({x: x + 0.2, y: top + 0.25 + d, w: w - 0.4, h: headH}, head, 'top', 0.6));
        elements.push(text({x: x + 0.2, y: top + 0.35 + d + headH, w: w - 0.4, h: h - 0.55 - d - headH}, bullets(card.points, t, t.sizes.body), 'top', 0.6));
      });
      break;
    }
    case 'chart':
    case 'table': {
      const top = header(f, slide, elements);
      const side = slide.points?.length ? (W - 2 * M) * 0.32 : 0;
      const gap = side ? 0.3 * f.sx : 0;
      elements.push(...visualBox(f, {x: M, y: top, w: W - 2 * M - side - gap, h: bottom - top}, visual(slide.visual), slide.chart, slide, notes));
      if (side) elements.push(...points(f, {x: W - M - side, y: top + 0.3, w: side, h: bottom - top - 0.3}, slide.points, t.sizes.body, true));
      break;
    }
    case 'split': {
      const top = header(f, slide, elements);
      const gap = 0.4 * f.sx;
      const w = (W - 2 * M - gap) / 2;
      [slide.left, slide.right].forEach((panel, i) => {
        if (!panel) return;
        const x = M + i * (w + gap);
        let y = top;
        if (panel.heading) {
          elements.push(text({x, y, w, h: 0.42 * sy}, [{runs: [{text: panel.heading}], size: t.sizes.heading, color: t.colors.title, font: t.fonts.title, bold: true}], 'bottom', 0.7));
          elements.push({type: 'rect', x, y: y + 0.46 * sy, w, h: 0.02, fill: t.colors.line});
          y += 0.58 * sy;
        }
        const own = visual(panel.visual);
        const pointsH = panel.visual && panel.points?.length ? (bottom - y) * 0.3 : 0;
        if (panel.visual) elements.push(...visualBox(f, {x, y, w, h: bottom - y - pointsH}, own, panel.chart, null, notes));
        if (panel.points?.length) elements.push(...points(f, {x, y: panel.visual ? bottom - pointsH + 0.1 : y, w, h: panel.visual ? pointsH - 0.1 : bottom - y}, panel.points, t.sizes.body));
      });
      break;
    }
    case 'closing': {
      if (!slide.points?.length) {
        background = t.colors.brand;
        dark = true;
        elements.push(text({x: M, y: H * 0.3, w: W - 2 * M, h: H * 0.32}, [{runs: [{text: slide.title ?? ''}], size: t.sizes.section_title, color: '#FFFFFF', font: t.fonts.title, bold: true, align: 'center'}], 'middle', 0.5));
        if (slide.subtitle) elements.push(text({x: M, y: H * 0.64, w: W - 2 * M, h: H * 0.12}, [{runs: [{text: slide.subtitle}], size: t.sizes.subtitle, color: '#FFFFFF', font: t.fonts.subtitle, align: 'center'}], 'top', 0.7));
        break;
      }
      const top = header(f, slide, elements);
      elements.push(...points(f, {x: M, y: top, w: W - 2 * M, h: bottom - top}, slide.points, t.sizes.body + 2, true));
      break;
    }
    default: {
      const top = header(f, slide, elements);
      elements.push(...points(f, {x: M, y: top, w: W - 2 * M, h: bottom - top}, slide.points, t.sizes.body + 1));
    }
  }
  if (slide.kind !== 'cover') footer(f, deck, slide, number, notes, elements, dark);
  const spoken = [slide.notes ?? '', sourceText(deck, slide, [])].filter(Boolean).join('\n\n');
  return {number, kind: slide.kind, title: slide.title ?? (slide.kind === 'agenda' ? 'Agenda' : ''), background, elements, notes: spoken};
}

/** Every slide of the deck, laid out. */
export function layoutDeck(deck: Deck): Page[] {
  return deck.slides.map((slide, i) => slidePage(deck, slide, i));
}

/** The deck's file name: its title, without the marks Windows refuses. */
export function deckFileName(deck: Deck): string {
  const stem = deck.title.replace(/[\\/:*?"<>|\u0000-\u001f]+/g, ' ').replace(/\s+/g, ' ').trim().slice(0, 80).trim() || `Wizard ${deck.id}`;
  return `${stem}${deck.version > 1 ? ` (v${deck.version})` : ''}.pptx`;
}
