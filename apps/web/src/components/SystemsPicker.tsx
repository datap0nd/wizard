import {Check, ChevronDown, Layers} from 'lucide-react';
import {cn} from '@/lib/utils';
import {choiceLabel, toggleSystem} from '@/systems';
import {DropdownMenu, DropdownMenuCheckboxItem, DropdownMenuContent, DropdownMenuItem, DropdownMenuLabel, DropdownMenuSeparator,
  DropdownMenuTrigger, Hint} from './ui/menu';
import {SystemLogo} from './SystemLogo';
import type {SystemInfo} from '@/types';

/** Which systems a question may use: Auto (Wizard picks from every system this person can use) or only the ones ticked.
 * While an answer is running, a change applies to it at once. */
export function SystemsPicker({systems, chosen, onChange, disabled, running}: {
  systems: SystemInfo[]; chosen: string[] | null; onChange: (next: string[] | null) => void; disabled?: boolean; running?: boolean;
}) {
  if (!systems.length) return null;
  const label = choiceLabel(chosen, systems);
  return (
    <DropdownMenu>
      <Hint text={running ? 'Systems this answer may use: a change applies to it now' : 'Systems Wizard may use for this question'}>
        <DropdownMenuTrigger asChild>
          <button type="button" disabled={disabled} data-testid="systems-picker" data-choice={chosen ? chosen.join(',') : 'auto'}
            aria-label={`Systems: ${label}`}
            className={cn('mb-1 inline-flex h-9 max-w-[11rem] shrink-0 items-center gap-1 rounded-full px-2.5 text-[12.5px] font-medium transition-colors disabled:text-ink-3',
              chosen ? 'bg-accent-soft text-accent hover:bg-accent-line/60' : 'text-ink-2 hover:bg-surface hover:text-ink')}>
            <Layers className="size-4 shrink-0" /><span className="truncate">{label}</span><ChevronDown className="size-3.5 shrink-0 opacity-70" />
          </button>
        </DropdownMenuTrigger>
      </Hint>
      <DropdownMenuContent align="start" className="w-[17rem]" data-testid="systems-menu">
        <DropdownMenuLabel>Systems Wizard may use</DropdownMenuLabel>
        <DropdownMenuItem onSelect={() => onChange(null)} data-testid="system-auto">
          <span className="grid size-[18px] place-items-center">{chosen === null && <Check className="size-4 text-accent" />}</span>
          <span className="flex-1"><span className="block">Auto</span><span className="block text-[11.5px] text-ink-3">Wizard picks from all of them</span></span>
        </DropdownMenuItem>
        <DropdownMenuSeparator />
        <DropdownMenuLabel>Only these</DropdownMenuLabel>
        {systems.map(system => (
          <DropdownMenuCheckboxItem key={system.id} checked={!!chosen?.includes(system.id)} data-testid="system-option" data-system={system.id}
            onSelect={() => onChange(toggleSystem(chosen, system.id, systems))}>
            <SystemLogo id={system.id} name={system.name} size={18} />
            <span className="flex-1 truncate">{system.name}</span>
            {chosen?.includes(system.id) && <Check className="size-4 text-accent" />}
          </DropdownMenuCheckboxItem>
        ))}
        <p className="px-2 pb-1 pt-1.5 text-[11.5px] leading-snug text-ink-3">The knowledge base comes on with the first system you tick, so
          Wizard keeps its definitions and table notes. Untick it if you want only data.</p>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
