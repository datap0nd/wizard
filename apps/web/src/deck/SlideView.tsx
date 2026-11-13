// One slide as the page shows it, drawn from the same layout the PowerPoint file is written from (layout.ts): every box
// at its place and size on the slide, text in the company's fonts at its point size, scaled to the width it is shown at.
import {memo, useEffect, useRef, useState} from 'react';
import * as echarts from 'echarts/core';
import {BarChart, LineChart, ScatterChart} from 'echarts/charts';
import {GridComponent, LegendComponent} from 'echarts/components';
import {SVGRenderer} from 'echarts/renderers';
import {deckChartOption} from './chart';
import type {Element, Page, Para} from './layout';
import type {DesignTokens} from '../types';

echarts.use([BarChart, LineChart, ScatterChart, GridComponent, LegendComponent, SVGRenderer]);

interface Frame { W: number; H: number }

const pct = (v: number, of: number) => `${(v / of) * 100}%`;
/** A size in points as a share of the slide's width (container query units), so text scales with the slide. */
const pt = (size: number, f: Frame) => `${(size / 72 / f.W) * 100}cqw`;
const family = (font: string) => `"${font}", Arial, "Malgun Gothic", sans-serif`;

function place(el: {x: number; y: number; w: number; h: number}, f: Frame): React.CSSProperties {
  return {position: 'absolute', left: pct(el.x, f.W), top: pct(el.y, f.H), width: pct(el.w, f.W), height: pct(el.h, f.H)};
}

/** A length in inches as a share of the slide's width, wherever it is used inside the slide. */
const inch = (v: number, f: Frame) => `${(v / f.W) * 100}cqw`;

function Paragraph({p, f}: {p: Para; f: Frame}) {
  const indent = p.bullet ? (0.2 + (p.level ?? 0) * 0.25) : 0;
  return (
    <p style={{margin: 0, marginTop: pt(p.gap ?? 0, f), fontSize: pt(p.size, f), lineHeight: 1.2, color: p.color, fontFamily: family(p.font),
      fontWeight: p.bold ? 700 : 400, textAlign: p.align ?? 'left', paddingLeft: indent ? inch(indent, f) : undefined, position: 'relative'}}>
      {p.bullet && <span aria-hidden="true" style={{position: 'absolute', left: inch((p.level ?? 0) * 0.25 + 0.03, f)}}>{p.level ? '–' : '•'}</span>}
      {p.runs.map((r, i) => <span key={i} style={{fontWeight: r.bold ?? p.bold ? 700 : 400, color: r.color}}>{r.text}</span>)}
    </p>
  );
}

function Chart({el, f, width}: {el: Extract<Element, {type: 'chart'}>; f: Frame; width: number}) {
  const host = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!host.current || !width) return;
    const chart = echarts.init(host.current, undefined, {renderer: 'svg'});
    chart.setOption(deckChartOption(el.visual, el.chart, el.tokens, width / f.W));
    const observer = typeof ResizeObserver === 'undefined' ? null : new ResizeObserver(() => chart.resize());
    observer?.observe(host.current);
    return () => { observer?.disconnect(); chart.dispose(); };
  }, [el, f.W, width]);
  return <div ref={host} style={place(el, f)} role="img" aria-label={`Chart: ${el.visual.title}`} />;
}

function Item({el, f, width}: {el: Element; f: Frame; width: number}) {
  switch (el.type) {
    case 'rect':
      return <div style={{...place(el, f), background: el.fill, border: el.line ? `1px solid ${el.line}` : undefined}} />;
    case 'badge':
      return <div style={{...place(el, f), background: el.fill, color: el.color, borderRadius: '50%', display: 'grid', placeItems: 'center',
        fontFamily: family(el.font), fontSize: pt(el.size, f), fontWeight: 700}}>{el.text}</div>;
    case 'text':
      return <div style={{...place(el, f), display: 'flex', flexDirection: 'column', overflow: 'hidden', padding: inch(el.inset, f),
        justifyContent: el.valign === 'middle' ? 'center' : el.valign === 'bottom' ? 'flex-end' : 'flex-start'}}>
        {el.paras.map((p, i) => <Paragraph key={i} p={p} f={f} />)}
      </div>;
    case 'table':
      return <table style={{...place(el, f), height: undefined, borderCollapse: 'collapse', tableLayout: 'fixed', fontFamily: family(el.font), fontSize: pt(el.size, f)}}>
        <colgroup>{el.colW.map((w, i) => <col key={i} style={{width: pct(w, el.w)}} />)}</colgroup>
        <tbody>{el.cells.map((row, r) => <tr key={r} style={{height: `${(el.rowH / f.W) * 100}cqw`}}>
          {row.map((c, j) => <td key={j} style={{border: `1px solid ${el.line}`, padding: `0 ${inch(0.06, f)}`, background: c.fill, color: c.color,
            fontWeight: c.bold ? 700 : 400, textAlign: c.align, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis'}}>{c.text}</td>)}
        </tr>)}</tbody>
      </table>;
    case 'chart':
      return <Chart el={el} f={f} width={width} />;
  }
}

/** A slide, drawn at the width it is given. Charts are drawn once the slide's width is known. */
export const SlideView = memo(function SlideView({page, tokens, className, label}: {page: Page; tokens: DesignTokens; className?: string; label?: string}) {
  const f = {W: tokens.slide.width, H: tokens.slide.height};
  const box = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(0);
  useEffect(() => {
    const el = box.current;
    if (!el) return;
    setWidth(el.clientWidth);
    if (typeof ResizeObserver === 'undefined') return;
    const observer = new ResizeObserver(() => setWidth(el.clientWidth));
    observer.observe(el);
    return () => observer.disconnect();
  }, []);
  return (
    <div ref={box} className={className} role="group" aria-label={label ?? `Slide ${page.number}: ${page.title}`} data-testid="slide" data-kind={page.kind}
      style={{position: 'relative', width: '100%', aspectRatio: `${f.W} / ${f.H}`, background: page.background, overflow: 'hidden', containerType: 'inline-size'}}>
      {page.elements.map((el, i) => <Item key={i} el={el} f={f} width={width} />)}
    </div>
  );
});
