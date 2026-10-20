import {useEffect, useRef, useState} from 'react';
import {WizardSprite} from './WizardSprite';

const hasFiles = (e: DragEvent) => Array.from(e.dataTransfer?.types ?? []).includes('Files');

/** Files dragged anywhere over the page: a full-window target with the wizard ready to read them. Without it, a file
 * dropped on the page would be opened by the browser (or, in WizardBar's panel, ignored). */
export function DropZone({onDrop, disabled}: {onDrop: (files: File[]) => void; disabled?: boolean}) {
  const [over, setOver] = useState(false);
  const depth = useRef(0);
  const latest = useRef(onDrop);
  latest.current = onDrop;
  useEffect(() => {
    const enter = (e: DragEvent) => { if (!hasFiles(e)) return; e.preventDefault(); depth.current += 1; setOver(true); };
    const over = (e: DragEvent) => {
      if (!hasFiles(e)) return;
      e.preventDefault();
      if (e.dataTransfer) e.dataTransfer.dropEffect = disabled ? 'none' : 'copy';
    };
    const leave = (e: DragEvent) => { if (!hasFiles(e)) return; depth.current = Math.max(0, depth.current - 1); if (!depth.current) setOver(false); };
    const drop = (e: DragEvent) => {
      if (!hasFiles(e)) return;
      e.preventDefault();
      depth.current = 0;
      setOver(false);
      const files = Array.from(e.dataTransfer?.files ?? []);
      if (files.length && !disabled) latest.current(files);
    };
    window.addEventListener('dragenter', enter);
    window.addEventListener('dragover', over);
    window.addEventListener('dragleave', leave);
    window.addEventListener('drop', drop);
    return () => {
      window.removeEventListener('dragenter', enter);
      window.removeEventListener('dragover', over);
      window.removeEventListener('dragleave', leave);
      window.removeEventListener('drop', drop);
    };
  }, [disabled]);
  if (!over || disabled) return null;
  return (
    <div className="pointer-events-none fixed inset-0 z-50 grid place-items-center bg-accent-soft/80 p-6 backdrop-blur-[2px]" data-testid="drop-zone">
      <div className="stage-enter flex flex-col items-center gap-1 rounded-3xl border-2 border-dashed border-accent bg-canvas/90 px-10 py-6 text-center shadow-card">
        <WizardSprite animation="read" scale={3} />
        <p className="text-[17px] font-semibold text-ink">Drop to attach</p>
        <p className="text-[13px] text-ink-2">PowerPoint, Excel, Word, email, CSV or text. Wizard reads it with your question.</p>
      </div>
    </div>
  );
}
