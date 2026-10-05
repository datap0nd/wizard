import {useState} from 'react';
import {Copy, Terminal} from 'lucide-react';
import {Button} from './ui/button';

/** Dev mode: everything the server recorded about how a run went (CLI output, setup, tracebacks). Secrets are redacted
 * server-side. Open by default when the run failed. */
export function Diagnostics({items, open}: {items: Record<string, unknown>[]; open: boolean}) {
  const [copied, setCopied] = useState(false);
  const text = items.map(format).join('\n\n');
  return (
    <details open={open} className="no-print mx-5 mb-4 rounded-xl border border-line bg-surface sm:mx-6" data-testid="diagnostics">
      <summary className="flex cursor-pointer items-center gap-2 px-4 py-2 text-[13px] font-medium text-ink-2">
        <Terminal className="size-4" />Diagnostics
        <span className="text-xs font-normal text-ink-3">{summary(items)}</span>
      </summary>
      <div className="border-t border-line px-4 py-3">
        <Button variant="outline" size="xs" onClick={() => void navigator.clipboard?.writeText(text).then(() => setCopied(true))}>
          <Copy />{copied ? 'Copied' : 'Copy all'}
        </Button>
        <pre className="mt-2 max-h-[420px] overflow-auto whitespace-pre-wrap break-words font-mono text-[11.5px] leading-[1.5] text-ink-2">{text}</pre>
      </div>
    </details>
  );
}

function summary(items: Record<string, unknown>[]): string {
  const last = items[items.length - 1] ?? {};
  return [last.outcome, last.exit_code !== undefined && last.exit_code !== null ? `exit ${String(last.exit_code)}` : null,
    last.elapsed_s !== undefined ? `${String(last.elapsed_s)} s` : null].filter(Boolean).join(' · ');
}

/** Readable sections; long line lists (stderr, stdout) printed as-is so they can be pasted. */
function format(item: Record<string, unknown>): string {
  const sections: string[] = [];
  for (const [key, value] of Object.entries(item)) {
    if (value === null || value === undefined || (Array.isArray(value) && value.length === 0)) continue;
    if (Array.isArray(value) && value.every(v => typeof v === 'string')) {
      sections.push(`── ${key} ──\n${(value as string[]).join('\n')}`);
    } else if (typeof value === 'object') {
      sections.push(`── ${key} ──\n${JSON.stringify(value, null, 2)}`);
    } else if (typeof value === 'string' && value.includes('\n')) {
      sections.push(`── ${key} ──\n${value}`);
    } else {
      sections.push(`${key}: ${String(value)}`);
    }
  }
  return sections.join('\n');
}
