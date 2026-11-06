import {useEffect, useRef, useState} from 'react';
import {GIVE_UP_MS, HEAD, HOLD_MS, introAt, introSeen, WAIT_MS, wizardScale} from '@/brainIntro';
import {FRAME} from '@/wizardSheet';
import {WizardSprite} from '../WizardSprite';

/** Where an element's box is on the page, from its layout (offsets), which the intro's own scaling does not move. */
function layoutBox(el: HTMLElement): {left: number; top: number; width: number; height: number} {
  let left = 0, top = 0;
  for (let at: HTMLElement | null = el; at; at = at.offsetParent as HTMLElement | null) { left += at.offsetLeft; top += at.offsetTop; }
  return {left, top, width: el.offsetWidth, height: el.offsetHeight};
}

/**
 * The first visit's intro (brainIntro.ts): the pixel wizard thinking while the page reads the knowledge base, then his
 * brain lights up and the view dives into it, the graph growing out of his head into its place. It drives the page
 * (`page`, drawn above the wizard with a clear background) by its style alone; the graph itself is the page's own.
 * A click or any key ends it at once. `ready`: the graph is laid out; `inset`, `bottom`: the room the panels take, so
 * his head sits where the graph's middle will be.
 */
export function BrainIntro({page, ready, inset, bottom, onDone}: {page: {current: HTMLDivElement | null}; ready: boolean; inset: number;
  bottom: number; onDone: () => void}) {
  const wizard = useRef<HTMLDivElement>(null);
  const live = useRef({ready, onDone});
  live.current = {ready, onDone};
  const [scale] = useState(() => wizardScale(window.innerWidth, window.innerHeight, FRAME));
  const [skippable, setSkippable] = useState(false);
  const finish = useRef<() => void>(() => undefined);

  useEffect(() => {
    let raf = 0, over = false, readyAt: number | null = null;
    const started = performance.now();
    const end = () => {
      if (over) return;
      over = true;
      cancelAnimationFrame(raf);
      const root = page.current;
      // Shown at once: the page's own class (hidden while the intro runs) goes with the next render.
      if (root) { root.style.transform = ''; root.style.transformOrigin = ''; root.style.opacity = '1'; }
      introSeen();
      live.current.onDone();
    };
    finish.current = end;
    if (page.current) page.current.style.opacity = '0';  // played again: the page hides until his brain lights up
    const frame = (now: number) => {
      const root = page.current, el = wizard.current, stage = root?.querySelector<HTMLElement>('[data-testid=brain-stage]');
      if (!el) { raf = requestAnimationFrame(frame); return; }
      // His brain goes where the graph's middle is (the stage, less the panels); before the page is there, mid-window.
      const box = stage ? layoutBox(stage) : null;
      const cx = box ? box.left + (box.width + inset) / 2 : window.innerWidth / 2;
      const cy = box ? box.top + (box.height - bottom) / 2 : window.innerHeight / 2;
      el.style.left = `${cx - HEAD.x * scale}px`; el.style.top = `${cy - HEAD.y * scale}px`;
      if (readyAt === null && root && stage && (live.current.ready || now - started > WAIT_MS)) readyAt = Math.max(now, started + HOLD_MS);
      if (readyAt === null) {
        if (now - started > GIVE_UP_MS) { end(); return; }
        if (root) root.style.opacity = '0';
        raf = requestAnimationFrame(frame);
        return;
      }
      const graphSize = Math.max(120, Math.min(box!.width - inset, box!.height - bottom) * 0.8);
      const depth = Math.max(4, graphSize / (HEAD.width * scale));
      const at = introAt(now - readyAt, depth);
      el.style.transform = `scale(${at.wizard})`;
      el.style.opacity = String(at.wizardOpacity);
      root!.style.transformOrigin = `${cx}px ${cy}px`;
      root!.style.transform = `scale(${at.graph})`;
      root!.style.opacity = String(now < readyAt ? 0 : at.graphOpacity);
      if (at.done) { end(); return; }
      raf = requestAnimationFrame(frame);
    };
    raf = requestAnimationFrame(frame);
    // A click (on the layer over everything) or any key ends it; the key does nothing else.
    const key = (e: KeyboardEvent) => { e.preventDefault(); e.stopImmediatePropagation(); end(); };
    window.addEventListener('keydown', key, {capture: true});
    const hint = setTimeout(() => setSkippable(true), 900);
    return () => { cancelAnimationFrame(raf); clearTimeout(hint); window.removeEventListener('keydown', key, {capture: true}); };
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <>
      <div className="pointer-events-none fixed inset-0 z-0 overflow-hidden bg-[#0f1117]" aria-hidden data-testid="brain-intro">
        <div ref={wizard} className="brain-intro-wizard absolute" style={{width: FRAME * scale, height: FRAME * scale, transformOrigin: `${HEAD.x * scale}px ${HEAD.y * scale}px`}}>
          <WizardSprite animation="think" scale={scale} />
        </div>
      </div>
      <button type="button" onClick={() => finish.current()} className="fixed inset-0 z-30 cursor-default bg-transparent" aria-label="Skip the intro"
        data-testid="brain-intro-skip">
        <span className={`absolute bottom-6 left-1/2 -translate-x-1/2 text-[12px] text-slate-500 transition-opacity duration-700 ${skippable ? 'opacity-100' : 'opacity-0'}`}>
          Click or press any key to skip</span>
      </button>
    </>
  );
}
