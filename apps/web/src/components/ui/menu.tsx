import * as React from 'react';
import * as Menu from '@radix-ui/react-dropdown-menu';
import * as TooltipPrimitive from '@radix-ui/react-tooltip';
import {cn} from '@/lib/utils';

export const DropdownMenu = Menu.Root;
export const DropdownMenuTrigger = Menu.Trigger;

export function DropdownMenuContent({className, sideOffset = 4, ...props}: React.ComponentProps<typeof Menu.Content>) {
  return <Menu.Portal><Menu.Content sideOffset={sideOffset} className={cn('z-50 min-w-[12rem] rounded-lg border border-line bg-canvas p-1 text-sm shadow-lg', className)} {...props} /></Menu.Portal>;
}

export function DropdownMenuItem({className, danger, ...props}: React.ComponentProps<typeof Menu.Item> & {danger?: boolean}) {
  return <Menu.Item className={cn('flex cursor-pointer select-none items-center gap-2 rounded-md px-2 py-1.5 outline-none data-[highlighted]:bg-surface', danger && 'text-danger', className)} {...props} />;
}

export const DropdownMenuLabel = ({className, ...props}: React.ComponentProps<typeof Menu.Label>) =>
  <Menu.Label className={cn('px-2 py-1 text-xs font-medium text-ink-3', className)} {...props} />;

/** A ticked or unticked choice; the menu stays open so several can be ticked in a row. */
export function DropdownMenuCheckboxItem({className, onSelect, ...props}: React.ComponentProps<typeof Menu.CheckboxItem>) {
  return <Menu.CheckboxItem className={cn('flex cursor-pointer select-none items-center gap-2 rounded-md px-2 py-1.5 outline-none data-[highlighted]:bg-surface', className)}
    onSelect={event => { event.preventDefault(); onSelect?.(event); }} {...props} />;
}

export const DropdownMenuSeparator = ({className, ...props}: React.ComponentProps<typeof Menu.Separator>) =>
  <Menu.Separator className={cn('-mx-1 my-1 h-px bg-line', className)} {...props} />;

export const TooltipProvider = TooltipPrimitive.Provider;

/** Tooltip that also opens on keyboard focus. */
export function Hint({text, children}: {text: React.ReactNode; children: React.ReactElement}) {
  return (
    <TooltipPrimitive.Root>
      <TooltipPrimitive.Trigger asChild>{children}</TooltipPrimitive.Trigger>
      <TooltipPrimitive.Portal>
        <TooltipPrimitive.Content sideOffset={6} className="z-50 max-w-xs rounded-md bg-ink px-2.5 py-1.5 text-xs text-white shadow-md">{text}</TooltipPrimitive.Content>
      </TooltipPrimitive.Portal>
    </TooltipPrimitive.Root>
  );
}
