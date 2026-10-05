import {useCallback, useEffect, useState} from 'react';
import {Copy, RefreshCw} from 'lucide-react';
import {api} from '@/api';
import {Button} from './ui/button';
import {Dialog, DialogContent} from './ui/dialog';

/** Dev mode: the server's recent log (warnings, failed runs, tracebacks), newest last. Refreshes every 3 s while open. */
export function LogDialog({open, onClose}: {open: boolean; onClose: () => void}) {
  const [lines, setLines] = useState<string[]>([]);
  const [error, setError] = useState('');
  const load = useCallback(() => {
    api.devLog().then(r => { setLines(r.lines); setError(''); }).catch(e => setError(e instanceof Error ? e.message : 'Could not load the log.'));
  }, []);
  useEffect(() => {
    if (!open) return undefined;
    load();
    const timer = window.setInterval(load, 3000);
    return () => window.clearInterval(timer);
  }, [open, load]);
  const text = lines.join('\n');
  return (
    <Dialog open={open} onOpenChange={value => { if (!value) onClose(); }}>
      <DialogContent side="right" title="Server log" description="Recent warnings and errors from this Wizard (dev mode).">
        <div className="flex min-h-0 flex-1 flex-col gap-2 p-5" data-testid="log-dialog">
          <div className="flex gap-2">
            <Button variant="outline" size="xs" onClick={load}><RefreshCw />Refresh</Button>
            <Button variant="outline" size="xs" onClick={() => void navigator.clipboard?.writeText(text)}><Copy />Copy all</Button>
          </div>
          {error && <p className="text-sm text-danger">{error}</p>}
          <pre className="min-h-0 flex-1 overflow-auto whitespace-pre-wrap break-words rounded-lg bg-surface p-3 font-mono text-[11.5px] leading-[1.5] text-ink-2">
            {text || 'Nothing logged yet.'}
          </pre>
        </div>
      </DialogContent>
    </Dialog>
  );
}
