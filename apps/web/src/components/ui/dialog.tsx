import * as React from 'react';
import * as DialogPrimitive from '@radix-ui/react-dialog';
import {X} from 'lucide-react';
import {cn} from '@/lib/utils';

export const Dialog = DialogPrimitive.Root;

/** Centered dialog or right-hand panel sharing one accessible primitive (B2B pattern). */
export function DialogContent({className, side = 'center', children, title, description, ...props}:
  React.ComponentProps<typeof DialogPrimitive.Content> & {side?: 'center' | 'right'; title: string; description?: string}) {
  return (
    <DialogPrimitive.Portal>
      <DialogPrimitive.Overlay className="fixed inset-0 z-40 bg-ink/30" />
      <DialogPrimitive.Content
        aria-describedby={undefined}
        className={cn('fixed z-50 bg-canvas shadow-xl focus:outline-none',
          side === 'center' ? 'left-1/2 top-1/2 max-h-[90dvh] w-[min(520px,94vw)] -translate-x-1/2 -translate-y-1/2 overflow-auto rounded-card border border-line p-6'
            : 'inset-y-0 right-0 flex w-[min(720px,100vw)] flex-col border-l border-line', className)}
        {...props}>
        <div className={cn('flex items-start justify-between gap-4', side === 'right' && 'border-b border-line px-5 py-4')}>
          <div>
            <DialogPrimitive.Title className="text-base font-semibold">{title}</DialogPrimitive.Title>
            {description && <DialogPrimitive.Description className="mt-0.5 text-xs text-ink-3">{description}</DialogPrimitive.Description>}
          </div>
          <DialogPrimitive.Close className="rounded-md p-1 text-ink-3 hover:bg-surface hover:text-ink" aria-label="Close"><X className="size-4" /></DialogPrimitive.Close>
        </div>
        <div className={cn(side === 'right' ? 'flex-1 overflow-auto px-5 py-4 scroll-thin' : 'mt-3')}>{children}</div>
      </DialogPrimitive.Content>
    </DialogPrimitive.Portal>
  );
}
