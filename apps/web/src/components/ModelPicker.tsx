import {useState} from 'react';
import {Check, ChevronDown, Cpu, Loader2} from 'lucide-react';
import {api, ApiError} from '@/api';
import {DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuLabel, DropdownMenuTrigger, Hint} from './ui/menu';

/** The Gemini model for the next question. The list is the models this person's own Gemini entitlement has quota
 * for; the choice is saved on this PC and needs no restart. */
export function ModelPicker({model, onChanged, onMore}: {model: string; onChanged: () => void; onMore: () => void}) {
  const [options, setOptions] = useState<string[] | null>(null);
  const [reason, setReason] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function load(open: boolean) {
    if (!open) return;
    setError(null);
    try { const list = await api.models(); setOptions(list.options); setReason(list.reason); }
    catch (e) { setOptions([model]); setReason(e instanceof Error ? e.message : null); }
  }

  async function choose(next: string) {
    if (next === model) return;
    setBusy(true); setError(null);
    try { await api.saveSettings({WIZARD_GEMINI_MODEL: next}); onChanged(); }
    catch (e) { setError(e instanceof ApiError ? e.message : 'The model could not be changed.'); }
    finally { setBusy(false); }
  }

  return (
    <DropdownMenu onOpenChange={open => void load(open)}>
      <Hint text={error ?? 'Gemini model for the next question'}>
        <DropdownMenuTrigger asChild>
          <button type="button" data-testid="model-picker" aria-label={`Model: ${model}`}
            className="inline-flex h-7 max-w-[190px] items-center gap-1 rounded-full border border-line bg-canvas px-2.5 text-[11.5px] font-medium text-ink-2 hover:bg-surface hover:text-ink">
            {busy ? <Loader2 className="size-3.5 animate-spin" /> : <Cpu className="size-3.5 shrink-0" />}
            <span className="truncate">{model.replace(/^gemini-/, 'Gemini ')}</span><ChevronDown className="size-3 shrink-0" />
          </button>
        </DropdownMenuTrigger>
      </Hint>
      <DropdownMenuContent align="end" className="min-w-[15rem]">
        <DropdownMenuLabel>Gemini model</DropdownMenuLabel>
        {options === null && <DropdownMenuLabel className="font-normal">Loading…</DropdownMenuLabel>}
        {options?.map(option => (
          <DropdownMenuItem key={option} onSelect={() => void choose(option)} data-testid="model-option">
            <Check className={option === model ? 'size-3.5' : 'size-3.5 opacity-0'} />{option}
          </DropdownMenuItem>
        ))}
        {reason && <DropdownMenuLabel className="max-w-[16rem] font-normal">Only the current model is listed: {reason}</DropdownMenuLabel>}
        <DropdownMenuItem onSelect={onMore}>Another model or more settings…</DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
