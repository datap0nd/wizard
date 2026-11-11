import JSZip from 'jszip';
import {afterEach, describe, expect, it, vi} from 'vitest';
import type {Visual} from './types';
import type {VisualEnv} from './visualEnv';
import {deliver, msoFormat, pptx, tableHtml, tableText, xlsx} from './visualExport';
import {excelFormat, fileName, grid, heatScale, sourceLine, textOn} from './visuals';

afterEach(() => vi.restoreAllMocks());

const growth: Visual = {
  id: 'V2', kind: 'heatmap', title: 'Sell-out growth by market and month', subtitle: 'Against the same month last year',
  columns: [{key: 'market', label: 'Market', type: 'string', unit: null}, {key: 'jul', label: 'Jul', type: 'percent', unit: '%'},
    {key: 'aug', label: 'Aug', type: 'percent', unit: '%'}, {key: 'sep', label: 'Sep', type: 'percent', unit: '%'}],
  rows: [['Egypt', 12.5, -4, 30], ['Saudi Arabia', -30, 0, null], ['UAE', 5, 8.25, 2]],
  x: 'market', series: ['jul', 'aug', 'sep'], evidence_ids: ['E1'], note: 'Units, not value.', derived_by: 'model',
};

const spend: Visual = {
  id: 'V1', kind: 'bar', title: 'Q3 spend by market', subtitle: null,
  columns: [{key: 'market', label: 'Market', type: 'string', unit: null}, {key: 'spend', label: 'Spend', type: 'currency', unit: 'USD'}],
  rows: [['Egypt', 1500000], ['Saudi Arabia', 4200000]], x: 'market', series: ['spend'], evidence_ids: ['E1'], note: null, derived_by: 'model',
};

const env = (over: Partial<VisualEnv> = {}): VisualEnv => ({
  dataMode: 'LIVE', rowsBehind: true,
  sources: async () => ({
    sources: [{id: 'E1', name: 'AI Team Database · SQL query on meto_db', dataMode: 'LIVE', asOf: '2026-11-08T00:00:00Z', totalRows: 3,
      query: 'SELECT market, month, growth FROM reporting.sellout_mv'}],
    rows: [{id: 'E1', columns: [{key: 'market', label: 'Market', type: 'string'}, {key: 'units', label: 'Units', type: 'integer'},
      {key: 'growth', label: 'Growth', type: 'percent'}], rows: [['Egypt', 1200, 12.5], ['UAE', 800, 5]]}],
  }),
  ...over,
});

async function parts(blob: Blob) {
  return JSZip.loadAsync(await blob.arrayBuffer());
}

describe('the heatmap', () => {
  it('diverges around zero when the values have both signs: red below, grey at zero, blue above', () => {
    const scale = heatScale(growth);
    expect(scale.kind).toBe('diverging');
    expect([scale.min, scale.max]).toEqual([-30, 30]);
    expect(scale.fill(0)).toBe('#f0efec');
    expect(scale.fill(30)).toBe('#0d366b');
    expect(scale.fill(-30)).toBe('#7c1e1e');
    expect(scale.fill(null)).toBe('#ffffff');
    expect(textOn(scale.fill(30))).toBe('#ffffff');
    expect(textOn(scale.fill(0))).toBe('#18233b');
  });

  it('is sequential for amounts, light to dark, unless the visual asks for a scale', () => {
    const units = {...growth, rows: [['Egypt', 10, 20, 40], ['UAE', 0, 5, null]]};
    expect(heatScale(units).kind).toBe('sequential');
    expect(heatScale(units).fill(0)).toBe('#cde2fb');
    expect(heatScale(units).fill(40)).toBe('#0d366b');
    expect(heatScale({...units, scale: 'diverging'}).kind).toBe('diverging');
  });

  it('shows its row labels and shaded columns, each value printed, a missing one as missing', () => {
    const g = grid(growth);
    expect(g.header).toEqual(['Market', 'Jul', 'Aug', 'Sep']);
    expect(g.rows[0].map(c => c.text)).toEqual(['Egypt', '12.5%', '-4%', '30%']);
    expect(g.rows[0][0].fill).toBeUndefined();
    expect(g.rows[1][3]).toMatchObject({text: '—', fill: '#ffffff'});
  });
});

describe('copying a visual', () => {
  it('puts the table on the clipboard as HTML Excel reads as numbers and PowerPoint as a table', () => {
    const html = tableHtml(growth, {dataMode: 'LIVE'});
    expect(html).toContain('xmlns:x="urn:schemas-microsoft-com:office:excel"');
    expect(html).toContain('x:num="0.125"');
    expect(html).toContain("mso-number-format:'0\\.0%'");
    expect(html).toContain('background:#0d366b;color:#ffffff');
    expect(html).toContain('>12.5%</td>');
    expect(html).not.toContain('SYNTHETIC');
    expect(tableHtml(growth, {dataMode: 'SYNTHETIC'})).toContain('SYNTHETIC test data, not corporate figures');
    expect(tableText(growth).split('\r\n')).toEqual(['Market\tJul\tAug\tSep', 'Egypt\t12.5%\t-4%\t30%', 'Saudi Arabia\t-30%\t0%\t', 'UAE\t5%\t8.25%\t2%']);
  });

  it('says where the values came from and their data label', () => {
    expect(sourceLine(growth, 'SYNTHETIC')).toBe('Prepared by Gemini in Wizard from E1 · SYNTHETIC test data, not corporate figures · Units, not value.');
    expect(sourceLine({...spend, evidence_ids: []}, 'LIVE')).toBe('Prepared by Gemini in Wizard; no cited evidence · Live');
    expect(fileName({...spend, title: 'Q3: spend / market?'}, 'pptx')).toBe('Q3 spend market.pptx');
  });

  it("formats each column in Excel as Wizard shows it", () => {
    expect(excelFormat('percent', '%', [12.5])).toBe('0.0%');
    expect(excelFormat('currency', 'USD', [1])).toBe('"$"#,##0');
    expect(excelFormat('currency', 'AED', [1])).toBe('#,##0 "AED"');
    expect(excelFormat('number', 'units', [1, 2])).toBe('#,##0');
    expect(excelFormat('number', 'kg', [1.5])).toBe('#,##0.00 "kg"');
    expect(excelFormat('string', null, ['a'])).toBeNull();
  });
});

describe('downloading a visual', () => {
  it('writes an Excel workbook of its values, its sources and the rows behind it', async () => {
    const zip = await parts(await xlsx(growth, env()));
    const workbook = await zip.file('xl/workbook.xml')!.async('string');
    expect([...workbook.matchAll(/<sheet name="([^"]+)"/g)].map(m => m[1])).toEqual(['V2 heatmap', 'Sources', 'E1 rows']);
    const data = await zip.file('xl/worksheets/sheet1.xml')!.async('string');
    expect(data).toContain('Sell-out growth by market and month');
    expect(data).toContain('<v>0.125</v>');
    expect(data).toContain('<pane ySplit="5"');
    const styles = await zip.file('xl/styles.xml')!.async('string');
    expect(styles).toContain('formatCode="0.0%"');
    expect(styles).toContain('<fgColor rgb="FF0D366B"/>');
    const sources = await zip.file('xl/worksheets/sheet2.xml')!.async('string');
    expect(sources).toContain('SELECT market, month, growth FROM reporting.sellout_mv');
    const rows = await zip.file('xl/worksheets/sheet3.xml')!.async('string');
    expect(rows).toContain('<v>1200</v>');
    expect(rows).toContain('2 rows kept by Wizard of 3 read');
    expect(zip.file('[Content_Types].xml')).not.toBeNull();
  });

  it('keeps a case to its published values: no rows sheet, and says why', async () => {
    const zip = await parts(await xlsx(growth, env({rowsBehind: false, sources: async () => ({sources: [{id: 'E1', name: 'NERP · Sell-out'}], rows: []})})));
    const workbook = await zip.file('xl/workbook.xml')!.async('string');
    expect([...workbook.matchAll(/<sheet name="([^"]+)"/g)].map(m => m[1])).toEqual(['V2 heatmap', 'Sources']);
    expect(await zip.file('xl/worksheets/sheet2.xml')!.async('string')).toContain('The rows are not published with a case');
  });

  it('makes a PowerPoint slide with an editable chart whose data opens in Excel', async () => {
    const zip = await parts(await pptx(spend, env()));
    const names = Object.keys(zip.files);
    expect(names).toContain('ppt/presentation.xml');
    expect(names.some(n => /^ppt\/charts\/chart\d*\.xml$/.test(n))).toBe(true);
    expect(names.some(n => /^ppt\/embeddings\/.+\.xlsx$/.test(n))).toBe(true);
    const chart = await zip.file(names.find(n => /^ppt\/charts\/chart\d*\.xml$/.test(n))!)!.async('string');
    expect(chart).toContain('<c:barDir val="bar"/>');
    expect(chart).toContain('Saudi Arabia');
    const slide = await zip.file('ppt/slides/slide1.xml')!.async('string');
    expect(slide).toContain('Q3 spend by market');
    expect(slide).toContain('Prepared by Gemini in Wizard from E1 · Live');
  });

  it('makes a heatmap slide a native table with its shading', async () => {
    const zip = await parts(await pptx(growth, env()));
    const slide = await zip.file('ppt/slides/slide1.xml')!.async('string');
    expect(slide).toContain('<a:tbl>');
    expect(slide).toContain('0D366B');
    expect(slide).toContain('12.5%');
  });

  it('saves into Downloads where Wizard runs on this PC, and lets the browser download it elsewhere', async () => {
    const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => undefined);
    URL.createObjectURL = vi.fn(() => 'blob:x');
    URL.revokeObjectURL = vi.fn();
    const saved = {id: 'a1', filename: 'Q3 spend by market.xlsx', folder: 'C:\\Users\\exec\\Downloads'};
    const save = vi.fn(async () => saved);
    expect(await deliver(env({save}), new Blob(['x']), 'Q3 spend by market.xlsx')).toEqual(saved);
    expect(click).not.toHaveBeenCalled();
    expect(await deliver(env({save: async () => null}), new Blob(['x']), 'Q3 spend by market.xlsx')).toBeNull();
    expect(click).toHaveBeenCalledTimes(1);
  });
});

const plan: Visual = {
  id: 'V3', kind: 'table', title: 'Sell-out against plan', subtitle: 'October 2026',
  columns: [{key: 'region', label: 'Region', type: 'string', unit: null}, {key: 'market', label: 'Market', type: 'string', unit: null},
    {key: 'a', label: '2026 · Actual', type: 'currency', unit: 'USD'}, {key: 'p', label: '2026 · Plan', type: 'currency', unit: 'USD'},
    {key: 'g', label: 'Growth YoY', type: 'percent', unit: '%'}],
  rows: [['Gulf', 'UAE', 1200, 1000, 12.5], ['Gulf', 'Saudi Arabia', 800, 900, -4], ['Gulf', 'Subtotal', 2000, 1900, 0],
    ['North Africa', 'Egypt', -50, null, null], ['Total', null, 1950, 1900, 3.2]],
  x: null, series: [], evidence_ids: ['E1'], note: null, derived_by: 'model',
};

describe('the Korean report style', () => {
  it('writes a number format into the clipboard the way Excel writes its own, so the attribute stays whole', () => {
    expect(msoFormat('"$"#,##0')).toBe('\\0022\\$\\0022\\#\\,\\#\\#0');
    expect(msoFormat('[Blue]"▲"0.0%;"-"')).toBe('\\[Blue\\]\\0022▲\\0022 0\\.0%\\;\\0022\\-\\0022');
    expect(tableHtml(spend, {dataMode: 'LIVE'})).not.toMatch(/style="[^"]*mso-number-format:'[^']*"/);
  });

  it('copies the table with merged labels, grouped headers, a unit line and Excel formats', () => {
    const html = tableHtml(plan, {dataMode: 'LIVE'}, 'korean');
    expect(html).toContain("font-family:'Malgun Gothic'");
    expect(html).toContain('>(Unit: USD)</td>');
    expect(html).toMatch(/<th colspan="2"[^>]*>2026<\/th>/);
    expect(html).toMatch(/<th rowspan="2"[^>]*>Region<\/th>/);
    expect(html).toMatch(/<td rowspan="3"[^>]*>Gulf<\/td>/);
    expect(html).toMatch(/x:num="0.125">▲12.5%<\/td>/);
    expect(html).toMatch(/color:#FF0000[^>]*x:num="-0.04">▼4.0%<\/td>/);
    expect(html).toMatch(/x:num="-50">\(50\)<\/td>/);
    expect(html).toMatch(/x:num="0">-<\/td>/);
    expect(html).not.toContain('SYNTHETIC');
    expect(tableHtml(plan, {dataMode: 'SYNTHETIC'}, 'korean')).toContain('SYNTHETIC test data, not corporate figures');
  });

  it('downloads a report sheet: title in B3, merged cells, no gridlines, the sources still with it', async () => {
    const zip = await parts(await xlsx(plan, env(), 'korean'));
    const sheet = await zip.file('xl/worksheets/sheet1.xml')!.async('string');
    expect(sheet).toContain('showGridLines="0"');
    expect(sheet).toContain('<mergeCell ref="B8:B10"/>');   // Gulf over its three rows
    expect(sheet).toContain('<mergeCell ref="D6:E6"/>');    // 2026 over Actual and Plan
    expect(sheet).toContain('<mergeCell ref="B6:B7"/>');    // Region over both header rows
    expect(sheet).toMatch(/<c r="B3"[^>]*><is><t[^>]*>Sell-out against plan/);
    expect(sheet).toMatch(/<c r="D8" s="\d+"><v>1200<\/v><\/c>/);
    expect(sheet).toMatch(/<c r="F8" s="\d+"><v>0.125<\/v><\/c>/);
    expect(sheet).toContain('Prepared by Gemini in Wizard from E1');
    expect(sheet).toContain('xSplit="3" ySplit="7"');
    const styles = await zip.file('xl/styles.xml')!.async('string');
    expect(styles).toContain('Malgun Gothic');
    expect(styles).toContain('[Blue]&quot;▲&quot;0.0%;[Red]&quot;▼&quot;0.0%;&quot;-&quot;');
    expect(styles).toContain('#,##0;[Red](#,##0);&quot;-&quot;');
    expect(await zip.file('xl/worksheets/sheet2.xml')!.async('string')).toContain('SELECT market, month, growth');
    expect(zip.file('xl/worksheets/sheet3.xml')).not.toBeNull();
  });
});
