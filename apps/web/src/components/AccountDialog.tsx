import {Dialog, DialogContent} from './ui/dialog';
import {GeminiLink} from './GeminiLink';
import {RememberedNotes} from './RememberedNotes';
import type {Bootstrap, GeminiAccount} from '@/types';

/** Link the user's own enterprise Gemini account (Gemini CLI's user-code OAuth flow). Wizard never sees the password. */
export function AccountDialog({open, boot, onClose, onChanged}: {open: boolean; boot: Bootstrap; onClose: () => void; onChanged: (a: GeminiAccount) => void}) {
  const runtime = boot.runtime;
  return (
    <Dialog open={open} onOpenChange={value => { if (!value) onClose(); }}>
      <DialogContent title="Your account" description={[boot.identity?.name, boot.identity?.email, boot.identity?.role].filter(Boolean).join(' · ')}>
        <div className="space-y-4 text-sm" data-testid="account-dialog">
          <section className="rounded-xl border border-line p-4">
            <h3 className="font-semibold">Gemini</h3>
            <p className="mt-1 text-ink-2">Runtime: {runtime?.label}. {runtime?.reason}</p>
            <GeminiLink boot={boot} onChanged={onChanged} />
          </section>
          <RememberedNotes open={open} />
          <p className="text-xs text-ink-3">Source access comes from each system's own entitlements. Wizard shows only reports and markets you may see.</p>
        </div>
      </DialogContent>
    </Dialog>
  );
}
