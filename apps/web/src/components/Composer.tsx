import {useEffect, useRef, useState} from 'react';
import {ArrowUp, FolderOpen, Paperclip, Upload} from 'lucide-react';
import {cn} from '@/lib/utils';
import {PendingChip, type PendingFile} from './Attachments';
import {DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger, Hint} from './ui/menu';

const ACCEPT = '.pptx,.pptm,.ppsx,.ppt,.xlsx,.xlsm,.xls,.xlsb,.docx,.docm,.doc,.rtf,.csv,.tsv,.txt,.md,.json,.eml,.msg';

interface Props {
  onSubmit: (text: string) => Promise<void> | void;
  busy: boolean;
  draft: string;
  onDraftChange: (text: string) => void;
  placeholder?: string;
  disabledReason?: string | null;
  files?: PendingFile[];
  onFiles?: (files: File[]) => void;
  /** Set when "From this PC" is available (local installs). */
  onLocal?: () => void;
  onRemoveFile?: (key: string) => void;
}

/** B2B composer: one rounded surface growing to six lines; Enter submits, Shift+Enter adds a line, IME-safe. Files
 * attached here are read by Wizard before the question is sent. */
export function Composer({onSubmit, busy, draft, onDraftChange, placeholder, disabledReason, files = [], onFiles, onLocal, onRemoveFile}: Props) {
  const ref = useRef<HTMLTextAreaElement>(null);
  const picker = useRef<HTMLInputElement>(null);
  const [composing, setComposing] = useState(false);
  const submitting = useRef(false);
  const reading = files.some(f => f.state === 'reading');
  useEffect(() => {
    const el = ref.current; if (!el) return;
    el.style.height = 'auto';
    el.style.height = Math.min(24 * 6 + 20, Math.max(44, el.scrollHeight)) + 'px';
  }, [draft]);
  useEffect(() => { ref.current?.focus({preventScroll: true}); }, []);

  async function submit() {
    const text = draft.trim();
    if (!text || busy || reading || submitting.current || disabledReason) return;
    submitting.current = true;
    try { await onSubmit(text); } finally { submitting.current = false; }
  }

  const attachButton = (
    <button type="button" aria-label="Attach a file" disabled={!!disabledReason || files.length >= 5}
      onClick={onLocal ? undefined : () => picker.current?.click()} data-testid="attach"
      className="mb-1 grid size-9 shrink-0 place-items-center rounded-full text-ink-2 transition-colors hover:bg-surface hover:text-ink disabled:text-ink-3 disabled:hover:bg-transparent">
      <Paperclip className="size-4" />
    </button>
  );

  return (
    <form className="mx-auto w-full max-w-[820px]" onSubmit={e => { e.preventDefault(); void submit(); }}>
      <div className={cn('rounded-2xl border border-line bg-canvas px-2 py-2 shadow-card transition-colors focus-within:border-line-2', disabledReason && 'opacity-70')}>
        {files.length > 0 && (
          <div className="flex flex-wrap gap-1.5 px-2 pb-1.5 pt-0.5" aria-label="Attached files">
            {files.map(file => <PendingChip key={file.key} file={file} onRemove={() => onRemoveFile?.(file.key)} />)}
          </div>
        )}
        <div className="flex items-end gap-1">
          {onFiles && (onLocal ? (
            <DropdownMenu>
              <Hint text="Attach PowerPoint, Excel, Word, email or CSV files"><DropdownMenuTrigger asChild>{attachButton}</DropdownMenuTrigger></Hint>
              <DropdownMenuContent align="start">
                <DropdownMenuItem onSelect={() => picker.current?.click()}><Upload className="size-4" />Upload a file…</DropdownMenuItem>
                <DropdownMenuItem onSelect={() => onLocal()}><FolderOpen className="size-4" />From this PC (protected files)…</DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          ) : <Hint text="Attach PowerPoint, Excel, Word, email or CSV files">{attachButton}</Hint>)}
          <input ref={picker} type="file" multiple accept={ACCEPT} className="hidden" data-testid="file-input"
            onChange={e => { const chosen = Array.from(e.target.files ?? []); e.target.value = ''; if (chosen.length) onFiles?.(chosen); }} />
          <textarea ref={ref} value={draft} rows={1} maxLength={4000} placeholder={disabledReason ?? placeholder ?? 'Ask about markets, models, spend, share or switching'}
            aria-label="Your question" disabled={!!disabledReason} onChange={e => onDraftChange(e.target.value)}
            onCompositionStart={() => setComposing(true)} onCompositionEnd={() => setComposing(false)}
            onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey && !composing && !e.nativeEvent.isComposing) { e.preventDefault(); void submit(); } }}
            className={cn('max-h-[164px] min-h-[44px] flex-1 resize-none bg-transparent py-2.5 text-[15px] leading-6 outline-none placeholder:text-ink-3', !onFiles && 'pl-2')} />
          <button type="submit" aria-label={reading ? 'Wait until the files are read' : 'Send'} disabled={busy || reading || !draft.trim() || !!disabledReason}
            className="mb-1 mr-1 grid size-9 shrink-0 place-items-center rounded-full bg-ink text-white transition-colors hover:bg-ink/85 disabled:bg-surface-2 disabled:text-ink-3">
            <ArrowUp className="size-4" />
          </button>
        </div>
      </div>
      <p className="mt-1.5 text-center text-[11.5px] text-ink-3">{reading ? 'Reading your files…' : 'Check the evidence before acting on a number.'}</p>
    </form>
  );
}
