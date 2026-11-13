import {Check, ChevronDown, MessageSquareText, Presentation} from 'lucide-react';
import {cn} from '@/lib/utils';
import {DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuLabel, DropdownMenuTrigger, Hint} from './ui/menu';
import type {Output} from '@/types';

const OUTPUTS: {id: Output; label: string; about: string; Icon: typeof Presentation}[] = [
  {id: 'analysis', label: 'Analysis', about: 'An answer in the chat, with its charts and tables', Icon: MessageSquareText},
  {id: 'presentation', label: 'PowerPoint', about: 'A presentation: Wizard asks which story to tell, then makes the slides', Icon: Presentation},
];

/** What a question asks for (owner, 13 Nov 2026: "the output can be analysis, powerpoint ... something they can toggle
 * after they click on output type at the bottom"): an analysis, or a PowerPoint presentation. */
export function OutputPicker({output, onChange, disabled}: {output: Output; onChange: (next: Output) => void; disabled?: boolean}) {
  const current = OUTPUTS.find(o => o.id === output) ?? OUTPUTS[0];
  const deck = output === 'presentation';
  return (
    <DropdownMenu>
      <Hint text="What Wizard makes for this question: an analysis or a PowerPoint presentation">
        <DropdownMenuTrigger asChild>
          <button type="button" disabled={disabled} data-testid="output-picker" data-output={output} aria-label={`Output: ${current.label}`}
            className={cn('mb-1 inline-flex h-9 shrink-0 items-center gap-1 rounded-full px-2.5 text-[12.5px] font-medium transition-colors disabled:text-ink-3',
              deck ? 'bg-accent-soft text-accent hover:bg-accent-line/60' : 'text-ink-2 hover:bg-surface hover:text-ink')}>
            <current.Icon className="size-4 shrink-0" /><span className="hidden sm:inline">{current.label}</span><ChevronDown className="size-3.5 shrink-0 opacity-70" />
          </button>
        </DropdownMenuTrigger>
      </Hint>
      <DropdownMenuContent align="start" className="w-[17rem]" data-testid="output-menu">
        <DropdownMenuLabel>Output</DropdownMenuLabel>
        {OUTPUTS.map(o => (
          <DropdownMenuItem key={o.id} onSelect={() => onChange(o.id)} data-testid="output-option" data-output={o.id}>
            <o.Icon className="size-4 text-ink-2" />
            <span className="flex-1"><span className="block">{o.label}</span><span className="block text-[11.5px] text-ink-3">{o.about}</span></span>
            {o.id === output && <Check className="size-4 text-accent" />}
          </DropdownMenuItem>
        ))}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
