import {useEffect, useState} from 'react';
import {AlertTriangle, FileSpreadsheet, FileText, Loader2, Mail, Presentation, Search, X} from 'lucide-react';
import {api, ApiError} from '@/api';
import {formatDate} from '@/format';
import {cn} from '@/lib/utils';
import {Dialog, DialogContent} from './ui/dialog';
import {Hint} from './ui/menu';
import type {Attachment, LocalFile} from '@/types';

/** A file in the composer: being read, ready, or not readable (with the reason). */
export interface PendingFile {
  key: string;
  filename: string;
  state: 'reading' | 'ok' | 'failed';
  attachment?: Attachment;
  note?: string | null;
}

const PART_WORD: Record<string, string> = {slides: 'slide', spreadsheet: 'sheet', document: 'heading', email: 'part', text: 'part'};

export function KindIcon({kind, className}: {kind: string; className?: string}) {
  const Icon = kind === 'slides' ? Presentation : kind === 'spreadsheet' ? FileSpreadsheet : kind === 'email' ? Mail : FileText;
  return <Icon className={cn('size-3.5 shrink-0', className)} aria-hidden />;
}

export function kindOf(name: string): string {
  const ext = name.slice(name.lastIndexOf('.')).toLowerCase();
  if (['.pptx', '.pptm', '.ppsx', '.ppt'].includes(ext)) return 'slides';
  if (['.xlsx', '.xlsm', '.xls', '.xlsb', '.csv', '.tsv'].includes(ext)) return 'spreadsheet';
  if (['.eml', '.msg'].includes(ext)) return 'email';
  return ext === '.docx' || ext === '.doc' || ext === '.docm' || ext === '.rtf' ? 'document' : 'text';
}

function describe(attachment: Attachment): string {
  if (!attachment.parts) return `${attachment.chars.toLocaleString()} characters`;
  const word = PART_WORD[attachment.kind] ?? 'part';
  return `${attachment.parts} ${word}${attachment.parts === 1 ? '' : 's'}`;
}

/** Composer chip for a file waiting to be sent. */
export function PendingChip({file, onRemove}: {file: PendingFile; onRemove: () => void}) {
  const kind = file.attachment?.kind ?? kindOf(file.filename);
  const chip = (
    <span className={cn('inline-flex max-w-full items-center gap-1.5 rounded-lg border px-2 py-1 text-[12.5px]',
      file.state === 'failed' ? 'border-danger-line bg-danger-soft text-danger' : 'border-line bg-surface text-ink-2')}
      data-testid="pending-file" data-state={file.state}>
      {file.state === 'reading' ? <Loader2 className="size-3.5 shrink-0 animate-spin" aria-hidden /> : file.state === 'failed'
        ? <AlertTriangle className="size-3.5 shrink-0" aria-hidden /> : <KindIcon kind={kind} />}
      <span className="truncate font-medium text-ink">{file.filename}</span>
      <span className="shrink-0 text-ink-3">{file.state === 'reading' ? 'Reading…' : file.state === 'failed' ? 'Could not read'
        : file.attachment ? describe(file.attachment) : ''}</span>
      <button type="button" onClick={onRemove} aria-label={`Remove ${file.filename}`} className="-mr-0.5 rounded p-0.5 hover:bg-surface-2">
        <X className="size-3.5" />
      </button>
    </span>
  );
  return file.state === 'failed' && file.note ? <Hint text={file.note}>{chip}</Hint> : chip;
}

/** The files sent with a question, shown under it. */
export function SentFiles({files}: {files: Attachment[]}) {
  if (!files.length) return null;
  return (
    <div className="flex flex-wrap justify-end gap-1.5" data-testid="sent-files">
      {files.map(file => (
        <Hint key={file.id} text={file.status === 'ok' ? `${file.label}: ${describe(file)} read by Wizard${file.origin === 'local' ? ', from its place on this PC' : ''}` : file.note ?? 'Could not be read'}>
          <span tabIndex={0} className="inline-flex max-w-[320px] items-center gap-1.5 rounded-lg border border-line bg-canvas px-2 py-1 text-[12.5px] text-ink-2">
            <KindIcon kind={file.kind} />
            {file.label && <span className="font-semibold text-accent">{file.label}</span>}
            <span className="truncate">{file.filename}</span>
          </span>
        </Hint>
      ))}
    </div>
  );
}

/** "From this PC": recent Office files in the person's own folders, read where they are (protected files need that). */
export function LocalFilesDialog({open, onClose, onPick}: {open: boolean; onClose: () => void; onPick: (file: LocalFile) => void}) {
  const [query, setQuery] = useState('');
  const [files, setFiles] = useState<LocalFile[] | null>(null);
  const [folders, setFolders] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    if (!open) return;
    let live = true;
    const timer = setTimeout(() => {
      api.localFiles(query.trim()).then(result => { if (live) { setFiles(result.files); setFolders(result.folders); setError(null); } })
        .catch((e: unknown) => { if (live) setError(e instanceof ApiError ? e.message : 'The files could not be listed.'); });
    }, query ? 200 : 0);
    return () => { live = false; clearTimeout(timer); };
  }, [open, query]);
  return (
    <Dialog open={open} onOpenChange={value => { if (!value) onClose(); }}>
      <DialogContent title="Attach a file from this PC" className="w-[min(640px,94vw)]"
        description="Wizard reads the file where it is, which is how protected (NASCA) files open. Recent files from your folders:">
        <label className="flex items-center gap-2 rounded-lg border border-line px-3 py-2 focus-within:border-line-2">
          <Search className="size-4 text-ink-3" aria-hidden />
          <input value={query} onChange={e => setQuery(e.target.value)} placeholder="Search by file name" aria-label="Search files"
            className="flex-1 bg-transparent text-sm outline-none placeholder:text-ink-3" autoFocus />
        </label>
        {folders.length > 0 && <p className="mt-2 text-xs text-ink-3">Looking in: {folders.join(' · ')}</p>}
        {error && <p className="mt-3 text-sm text-danger">{error}</p>}
        <ul className="mt-3 max-h-[52dvh] divide-y divide-line overflow-auto rounded-lg border border-line scroll-thin" data-testid="local-files">
          {files === null && !error && <li className="px-3 py-4 text-sm text-ink-3">Loading…</li>}
          {files?.length === 0 && <li className="px-3 py-4 text-sm text-ink-3">No PowerPoint, Excel, Word or email files{query ? ' match' : ' from the last six months'}.</li>}
          {files?.map(file => (
            <li key={file.path}>
              <button type="button" onClick={() => { onPick(file); onClose(); }} className="flex w-full items-center gap-3 px-3 py-2.5 text-left hover:bg-surface">
                <KindIcon kind={file.kind} className="size-4 text-ink-3" />
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-sm font-medium">{file.name}</span>
                  <span className="block truncate text-xs text-ink-3">{file.folder}</span>
                </span>
                <span className="shrink-0 text-xs text-ink-3">{formatDate(file.modified)}</span>
              </button>
            </li>
          ))}
        </ul>
      </DialogContent>
    </Dialog>
  );
}
