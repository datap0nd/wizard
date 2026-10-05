import {useEffect, useRef, useState} from 'react';
import {ArrowUp} from 'lucide-react';
import {cn} from '@/lib/utils';

interface Props {
  onSubmit: (text: string) => Promise<void> | void;
  busy: boolean;
  draft: string;
  onDraftChange: (text: string) => void;
  placeholder?: string;
  disabledReason?: string | null;
}

/** B2B composer: one rounded surface growing to six lines; Enter submits, Shift+Enter adds a line, IME-safe. */
export function Composer({onSubmit, busy, draft, onDraftChange, placeholder, disabledReason}: Props) {
  const ref = useRef<HTMLTextAreaElement>(null);
  const [composing, setComposing] = useState(false);
  const submitting = useRef(false);
  useEffect(() => {
    const el = ref.current; if (!el) return;
    el.style.height = 'auto';
    el.style.height = Math.min(24 * 6 + 20, Math.max(44, el.scrollHeight)) + 'px';
  }, [draft]);
  useEffect(() => { ref.current?.focus({preventScroll: true}); }, []);

  async function submit() {
    const text = draft.trim();
    if (!text || busy || submitting.current || disabledReason) return;
    submitting.current = true;
    try { await onSubmit(text); } finally { submitting.current = false; }
  }

  return (
    <form className="mx-auto w-full max-w-[820px]" onSubmit={e => { e.preventDefault(); void submit(); }}>
      <div className={cn('flex items-end gap-2 rounded-2xl border border-line bg-canvas px-4 py-2 shadow-card transition-colors focus-within:border-line-2', disabledReason && 'opacity-70')}>
        <textarea ref={ref} value={draft} rows={1} maxLength={4000} placeholder={disabledReason ?? placeholder ?? 'Ask about markets, models, spend, share or switching'}
          aria-label="Your question" disabled={!!disabledReason} onChange={e => onDraftChange(e.target.value)}
          onCompositionStart={() => setComposing(true)} onCompositionEnd={() => setComposing(false)}
          onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey && !composing && !e.nativeEvent.isComposing) { e.preventDefault(); void submit(); } }}
          className="max-h-[164px] min-h-[44px] flex-1 resize-none bg-transparent py-2.5 text-[15px] leading-6 outline-none placeholder:text-ink-3" />
        <button type="submit" aria-label="Send" disabled={busy || !draft.trim() || !!disabledReason}
          className="mb-1 grid size-9 shrink-0 place-items-center rounded-full bg-ink text-white transition-colors hover:bg-ink/85 disabled:bg-surface-2 disabled:text-ink-3">
          <ArrowUp className="size-4" />
        </button>
      </div>
      <p className="mt-1.5 text-center text-[11.5px] text-ink-3">Check the evidence before acting on a number.</p>
    </form>
  );
}
