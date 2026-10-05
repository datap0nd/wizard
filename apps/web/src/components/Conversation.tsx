import {useEffect, useRef, useState} from 'react';
import {ArrowDown} from 'lucide-react';
import {Button} from './ui/button';
import {SentFiles} from './Attachments';
import {RunCard} from './RunCard';
import type {RunView} from '@/types';

interface Props {
  runs: RunView[];
  empty: React.ReactNode;
  busy: boolean;
  onEvidence: (run: RunView, id: string | null) => void;
  onCheck: (run: RunView) => void;
  onCancel: (run: RunView) => void;
  onRetry: (run: RunView) => void;
  onFeedback: (run: RunView, category: string) => void;
}

/** Questions and answers. New output scrolls into view only while the reader follows the latest turn (B2B behaviour). */
export function Conversation({runs, empty, ...handlers}: Props) {
  const scroller = useRef<HTMLDivElement>(null);
  const [following, setFollowing] = useState(true);
  const lastKey = useRef('');
  useEffect(() => {
    const el = scroller.current; if (!el) return;
    const last = runs[runs.length - 1];
    const key = last ? `${runs.length}:${last.lastSeq}:${last.streamText.length}` : '';
    if (key === lastKey.current) return;
    const added = runs.length.toString() !== lastKey.current.split(':')[0];
    lastKey.current = key;
    if (following || added) requestAnimationFrame(() => el.scrollTo({top: el.scrollHeight, behavior: added ? 'smooth' : 'auto'}));
  }, [runs, following]);

  return (
    <div className="relative flex-1 overflow-hidden">
      <div ref={scroller} className="h-full overflow-y-auto scroll-thin" data-testid="conversation"
        onScroll={() => { const el = scroller.current; if (el) setFollowing(el.scrollHeight - el.scrollTop - el.clientHeight < 120); }}>
        <div className="mx-auto flex w-full max-w-[1000px] flex-col gap-6 px-4 py-6 md:px-6">
          {runs.length === 0 && empty}
          {runs.map(run => (
            <article key={run.id} className="flex flex-col gap-3" data-testid="turn">
              {run.kind === 'ask' && <div className="flex flex-col items-end gap-1.5">
                <p className="max-w-[760px] whitespace-pre-wrap rounded-2xl bg-accent-soft px-4 py-2.5 text-[15px]" data-testid="user-turn">{run.question}</p>
                <SentFiles files={run.attachments} />
              </div>}
              <RunCard run={run} {...handlers} />
            </article>
          ))}
        </div>
      </div>
      {!following && runs.length > 0 && (
        <Button size="sm" className="absolute bottom-4 left-1/2 z-30 -translate-x-1/2 rounded-full shadow-lg" onClick={() => { scroller.current?.scrollTo({top: scroller.current.scrollHeight, behavior: 'smooth'}); setFollowing(true); }}>
          <ArrowDown />Latest
        </Button>
      )}
    </div>
  );
}
