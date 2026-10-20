import type {CSSProperties, ReactNode} from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import {citedEvidence, placedVisuals, prepareAnswer} from './citations';
import {CHECK_TEXT, DATA_MODE_TEXT, formatDate, formatValue} from './format';
import {sourceGroups} from './sources';
import type {CheckStatus, DataMode, Evidence, EvidenceSummary, Visual} from './types';

/** The Email button's message: the question, the answer, how long it took and the sources the answer rests on.
 *  Inline styles only, because Outlook's Word engine ignores most style sheets. Charts go in as their data tables. */

export interface EmailInput {
  question: string;
  answer: string;
  visuals: Visual[];
  evidence: (Evidence | EvidenceSummary)[];
  createdAt: string;
  finishedAt: string | null;
  dataMode: DataMode | null;
  checkStatus: CheckStatus;
  model: string;
}

export interface EmailDraft { subject: string; html: string }
export interface SourceLine { system: string; name: string; ids: string[] }

/** The sources the answer actually rests on (cited in the text or behind a visual), one line per table, report or file.
 *  A report names its module (GSCM › Biz Plan). Lookups in the database catalog are not sources. */
export function finalSources(answer: string, visuals: Visual[], evidence: (Evidence | EvidenceSummary)[]): SourceLine[] {
  const shown = new Set([...citedEvidence(answer), ...visuals.flatMap(v => v.evidence_ids)]);
  const used = evidence.filter(e => shown.has(e.id));
  return sourceGroups(used.length ? used : evidence).filter(s => s.kind !== 'catalog')
    .map(s => ({system: [s.system, ...s.path].join(' › '), name: s.name, ids: s.ids}));
}

export function tookWords(start: string, end: string | null): string | null {
  if (!end) return null;
  const seconds = Math.round((new Date(end).getTime() - new Date(start).getTime()) / 1000);
  if (!Number.isFinite(seconds) || seconds < 0) return null;
  return seconds < 60 ? `${seconds} s` : `${Math.floor(seconds / 60)} min ${seconds % 60} s`;
}

const FONT = 'Segoe UI, Calibri, Arial, sans-serif';
const GREY = '#6b7280';
const CELL: CSSProperties = {border: '1px solid #d1d5db', padding: '4px 8px', verticalAlign: 'top'};
const TABLE: CSSProperties = {borderCollapse: 'collapse', margin: '0 0 12px', fontSize: '13px'};
const LABEL: CSSProperties = {margin: '0 0 2px', fontSize: '11px', letterSpacing: '0.08em', textTransform: 'uppercase', color: GREY};
const SMALL: CSSProperties = {margin: '0 0 6px', fontSize: '12px', color: GREY};
const RULE = <hr style={{border: 0, borderTop: '1px solid #e5e7eb', margin: '14px 0'}} />;

function VisualTable({visual}: {visual: Visual}) {
  return (
    <div style={{margin: '0 0 12px'}}>
      <p style={{margin: '0 0 4px', fontWeight: 600}}>{visual.title}</p>
      {visual.subtitle && <p style={SMALL}>{visual.subtitle}</p>}
      <table cellPadding={0} cellSpacing={0} style={TABLE}>
        <thead><tr>{visual.columns.map(c => <th key={c.key} style={{...CELL, background: '#f3f4f6', textAlign: 'left'}}>{c.label}</th>)}</tr></thead>
        <tbody>{visual.rows.map((row, r) => <tr key={r}>{row.map((value, i) => (
          <td key={i} style={{...CELL, textAlign: typeof value === 'number' ? 'right' : 'left'}}>{formatValue(value, visual.columns[i]?.type, visual.columns[i]?.unit)}</td>
        ))}</tr>)}</tbody>
      </table>
      {visual.kind !== 'table' && <p style={SMALL}>The data behind a {visual.kind} chart in Wizard.</p>}
    </div>
  );
}

function Answer({text, visuals}: {text: string; visuals: Visual[]}) {
  const heading = (size: string) => ({children}: {children?: ReactNode}) => <p style={{margin: '14px 0 6px', fontSize: size, fontWeight: 600}}>{children}</p>;
  return (
    <ReactMarkdown remarkPlugins={[remarkGfm]} components={{
      h1: heading('18px'), h2: heading('16px'), h3: heading('15px'), h4: heading('14px'), h5: heading('14px'), h6: heading('14px'),
      p: ({children}) => <p style={{margin: '0 0 10px'}}>{children}</p>,
      ul: ({children}) => <ul style={{margin: '0 0 10px', paddingLeft: '22px'}}>{children}</ul>,
      ol: ({children}) => <ol style={{margin: '0 0 10px', paddingLeft: '22px'}}>{children}</ol>,
      li: ({children}) => <li style={{margin: '0 0 4px'}}>{children}</li>,
      table: ({children}) => <table cellPadding={0} cellSpacing={0} style={TABLE}>{children}</table>,
      th: ({children, style}) => <th style={{...CELL, background: '#f3f4f6', textAlign: 'left', ...style}}>{children}</th>,
      td: ({children, style}) => <td style={{...CELL, ...style}}>{children}</td>,
      hr: () => RULE,
      blockquote: ({children}) => <blockquote style={{margin: '0 0 10px', paddingLeft: '10px', borderLeft: '3px solid #e5e7eb', color: '#4b5563'}}>{children}</blockquote>,
      a: ({href, children}) => {
        const target = href ?? '';
        if (target.startsWith('#evidence-')) return <span style={{color: GREY, fontSize: '11px'}}>[{target.slice('#evidence-'.length)}]</span>;
        if (target.startsWith('#visual-')) return <span>{target.slice('#visual-'.length)}</span>;
        return /^https?:\/\//i.test(target) ? <a href={target}>{children}</a> : <span>{children}</span>;
      },
      code: ({className, children}) => {
        if (className === 'language-wizard-visual') {
          const visual = visuals.find(v => v.id === String(children).trim());
          return visual ? <VisualTable visual={visual} /> : null;
        }
        return <code style={{fontFamily: 'Consolas, monospace', fontSize: '12px', background: '#f3f4f6', padding: '0 3px'}}>{children}</code>;
      },
      pre: ({children}) => <>{children}</>,
      img: ({alt}) => <span style={{color: GREY}}>[image omitted: {alt}]</span>,
    }}>{prepareAnswer(text)}</ReactMarkdown>
  );
}

/** The labels' hints, without the sentences that point at Wizard's screen ("Open the sources...", "Use Check my data"). */
function firstSentence(text: string): string {
  const end = text.indexOf('. ');
  return end < 0 ? text : text.slice(0, end + 1);
}

export function EmailBody(input: EmailInput) {
  const placed = placedVisuals(input.answer);
  const sources = finalSources(input.answer, input.visuals, input.evidence);
  const took = tookWords(input.createdAt, input.finishedAt);
  const mode = input.dataMode ? DATA_MODE_TEXT[input.dataMode] : null;
  const check = CHECK_TEXT[input.checkStatus];
  const meta = [took && `Answered by Wizard in ${took}`, input.finishedAt && formatDate(input.finishedAt, true), mode?.label, check?.label];
  return (
    <div style={{fontFamily: FONT, fontSize: '14px', lineHeight: 1.45, color: '#1f2937'}}>
      <p style={LABEL}>Question</p>
      <p style={{margin: '0 0 6px', fontSize: '16px', fontWeight: 600}}>{input.question}</p>
      <p style={SMALL}>{meta.filter(Boolean).join(' · ')}</p>
      {RULE}
      <Answer text={input.answer} visuals={input.visuals} />
      {input.visuals.filter(v => !placed.has(v.id)).map(v => <VisualTable key={v.id} visual={v} />)}
      {RULE}
      <p style={LABEL}>Sources</p>
      {sources.length > 0
        ? <ul style={{margin: '0 0 10px', paddingLeft: '22px'}}>{sources.map(s => (
            <li key={`${s.system}:${s.name}`} style={{margin: '0 0 2px'}}><b>{s.system}</b> {s.name} <span style={{color: GREY, fontSize: '12px'}}>({s.ids.join(', ')})</span></li>
          ))}</ul>
        : <p style={{margin: '0 0 10px'}}>No source data was retrieved.</p>}
      <p style={SMALL}>{[mode && `${mode.label}: ${firstSentence(mode.hint)}`, check && `${check.label}: ${firstSentence(check.hint)}`].filter(Boolean).join(' ')}</p>
      <p style={SMALL}>Prepared with Wizard ({input.model}). Check the evidence before acting on a number.</p>
    </div>
  );
}

export async function buildEmail(input: EmailInput): Promise<EmailDraft> {
  const {renderToStaticMarkup} = await import('react-dom/server');  // loaded only when someone emails an answer
  const question = input.question.replace(/\s+/g, ' ').trim();
  return {subject: `Wizard: ${question.length > 150 ? `${question.slice(0, 149)}…` : question}`,
          html: renderToStaticMarkup(<EmailBody {...input} />)};
}

function base64(text: string): string {
  const bytes = new TextEncoder().encode(text);
  let binary = '';
  for (let i = 0; i < bytes.length; i += 0x8000) binary += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
  return btoa(binary);
}

/** The same message as an .eml file that classic Outlook opens as an unsent draft (X-Unsent), for when Wizard cannot
 *  reach Outlook itself. */
export function emlFile(draft: EmailDraft): Blob {
  const page = `<!DOCTYPE html><html><head><meta charset="utf-8"></head><body>${draft.html}</body></html>`;
  const lines = ['X-Unsent: 1', `Subject: =?UTF-8?B?${base64(draft.subject)}?=`, 'MIME-Version: 1.0',
    'Content-Type: text/html; charset=UTF-8', 'Content-Transfer-Encoding: base64', '', ...(base64(page).match(/.{1,76}/g) ?? [])];
  return new Blob([lines.join('\r\n')], {type: 'message/rfc822'});
}

export function emlName(question: string): string {
  return `Wizard - ${question.replace(/[^\p{L}\p{N} _-]+/gu, ' ').replace(/\s+/g, ' ').trim().slice(0, 60) || 'answer'}.eml`;
}
