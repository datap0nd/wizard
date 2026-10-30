import {useState} from 'react';
import {cn} from '@/lib/utils';

interface Props {
  text: string;
  /** Longer than this many lines or characters, it shows its start with Show all. */
  lines: number;
  chars: number;
  /** The clamp for those lines, written out so Tailwind finds it, e.g. 'line-clamp-12'. */
  clamp: string;
  className?: string;
  as?: 'p' | 'h1';
  testId?: string;
}

/** Text that can run long (a question with a pasted list or email): its first lines, with Show all. Prints in full. */
export function LongText({text, lines, chars, clamp, className, as: Tag = 'p', testId}: Props) {
  const [open, setOpen] = useState(false);
  const long = text.length > chars || text.split('\n').length > lines;
  return (
    <>
      <Tag className={cn('whitespace-pre-wrap break-words', className, long && !open && `${clamp} print:line-clamp-none`)} data-testid={testId}>{text}</Tag>
      {long && (
        <button type="button" onClick={() => setOpen(!open)} aria-expanded={open} data-testid="long-text-toggle"
          className="no-print rounded px-1 text-[11.5px] font-medium text-ink-3 hover:bg-surface hover:text-ink">
          {open ? 'Show less' : `Show all (${text.length.toLocaleString('en-US')} characters)`}
        </button>
      )}
    </>
  );
}
