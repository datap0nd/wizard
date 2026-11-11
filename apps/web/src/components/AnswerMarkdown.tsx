import {memo, useMemo} from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import {prepareAnswer} from '@/citations';
import {tableVisual, type HastNode} from '@/answerTable';
import {VisualBlock, VisualExport} from './VisualBlock';
import type {Visual} from '@/types';

interface Props {
  text: string;
  visuals: Visual[];
  streaming?: boolean;
  onEvidence: (id: string) => void;
}

/** A table in the answer, with the copies and downloads a visual has (a picture or a table for PowerPoint, cells for
 *  Excel), built from the table as it is written. */
function AnswerTable({node, children}: {node?: unknown; children?: React.ReactNode}) {
  // One component for every render (not a new function each time), so an open menu survives the answer streaming on.
  const visual = useMemo(() => node ? tableVisual(node as HastNode) : null, [node]);
  return (
    <div data-testid="answer-table">
      {visual && <div className="mb-1.5 flex flex-wrap items-center justify-end gap-2"><VisualExport visual={visual} compact /></div>}
      <div className="table-wrap"><table>{children}</table></div>
    </div>
  );
}

/** Gemini's Markdown answer with evidence chips and placed visuals. Raw HTML in model output is never rendered. */
export const AnswerMarkdown = memo(function AnswerMarkdown({text, visuals, streaming, onEvidence}: Props) {
  const prepared = useMemo(() => prepareAnswer(text), [text]);
  return (
    <div className="answer" data-testid="answer">
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={{
        a: ({href, children}) => {
          const target = href ?? '';
          if (target.startsWith('#evidence-')) {
            const id = target.slice('#evidence-'.length);
            return <button type="button" onClick={() => onEvidence(id)} data-testid="citation" aria-label={`Show evidence ${id}`}
              className="mx-0.5 inline-flex h-[18px] items-center rounded bg-accent-soft px-1 align-[1px] text-[11px] font-semibold text-accent hover:bg-accent-line/60">{id}</button>;
          }
          if (target.startsWith('#visual-')) {
            const id = target.slice('#visual-'.length);
            return <a href={`#visual-${id}`} className="!no-underline"><span className="rounded bg-surface px-1 text-[11px] font-semibold text-ink-2">{id}</span></a>;
          }
          const safe = /^https?:\/\//i.test(target);
          return safe ? <a href={target} target="_blank" rel="noopener noreferrer nofollow">{children}</a> : <span>{children}</span>;
        },
        code: ({className, children}) => {
          if (className === 'language-wizard-visual') {
            const id = String(children).trim();
            const visual = visuals.find(v => v.id === id);
            return visual ? <VisualBlock visual={visual} onEvidence={onEvidence} /> : <span className="text-xs text-ink-3">[{id} not available]</span>;
          }
          return <code className={className}>{children}</code>;
        },
        pre: ({children}) => <>{children}</>,
        table: AnswerTable,
        img: ({alt}) => <span className="text-xs text-ink-3">[image omitted: {alt}]</span>,
      }}>{prepared}</ReactMarkdown>
      {streaming && <span className="caret" aria-hidden="true" />}
    </div>
  );
});
