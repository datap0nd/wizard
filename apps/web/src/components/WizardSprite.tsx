import {useEffect, useRef, useState} from 'react';
import sheet from '@/assets/wizard-sprite.png';
import {cn} from '@/lib/utils';
import {wizardAnimation, wizardCaption} from '@/wizard';
import {ANIMATIONS, COLUMNS, FRAME, ROWS, type WizardAnimation} from '@/wizardSheet';
import type {RunView} from '@/types';

/** The wizard character from the sprite sheet (scripts/wizard_art.py draws it). Plain CSS steps through the frames;
 *  with reduced motion it holds the first frame. A new animation remounts, so it starts from its first frame. */
export function WizardSprite({animation, scale = 2, label, className}: {animation: WizardAnimation; scale?: number; label?: string; className?: string}) {
  const {row, frames, fps, loop} = ANIMATIONS[animation];
  const size = FRAME * scale;
  const style = {
    width: size, height: size,
    backgroundImage: `url(${sheet})`,
    backgroundSize: `${COLUMNS * size}px ${ROWS * size}px`,
    backgroundPositionY: `${-row * size}px`,
    // A loop runs past its last frame back to the first; a one-shot stops on its last frame.
    '--wizard-end': `${-(loop ? frames : frames - 1) * size}px`,
    animation: `wizard-frames ${frames / fps}s ${loop ? `steps(${frames}) infinite` : `steps(${frames}, jump-none) 1 forwards`}`,
  } as React.CSSProperties;
  return <span key={animation} className={cn('wizard-sprite', className)} style={style} data-testid="wizard-sprite" data-animation={animation}
    {...(label ? {role: 'img', 'aria-label': label} : {'aria-hidden': true})} />;
}

const FINALE_MS = 1600;

/** The wizard at work on a run: acts out the step in progress and says what it is. Shown while the run works, and for
 *  a moment after it ends live (a hop for an answer, a fizzle for a failure); a run loaded from history has none.
 *  Sticky, so it stays in view while a long answer streams in below it. */
export function WizardStage({run}: {run: RunView}) {
  const running = run.status === 'running' || run.status === 'queued';
  const was = useRef(running);
  const [finale, setFinale] = useState<WizardAnimation | null>(null);
  useEffect(() => {
    const ended = was.current && !running;
    was.current = running;
    if (!ended || (run.status !== 'succeeded' && run.status !== 'failed')) return;
    setFinale(run.status === 'succeeded' ? 'success' : 'fail');
    const timer = setTimeout(() => setFinale(null), FINALE_MS);
    return () => clearTimeout(timer);
  }, [running, run.status]);
  if (!running && !finale) return null;
  const animation = finale ?? wizardAnimation(run);
  const {verb, detail} = wizardCaption(run, animation);
  const steps = run.timeline.filter(t => t.kind === 'tool').length;
  return (
    <div className="sticky top-3 z-10 flex w-fit min-w-[240px] max-w-full items-center gap-3 rounded-xl border border-accent-line bg-canvas pr-5 shadow-card"
      data-testid="wizard-stage" aria-live="polite">
      <WizardSprite animation={animation} scale={2} />
      <div className="min-w-0 flex-1">
        <p className="text-[14px] font-semibold text-ink" data-testid="wizard-verb">{verb}</p>
        {detail && <p className="truncate text-xs text-ink-3" title={detail}>{detail}</p>}
        {running && steps > 0 && <p className="text-xs text-ink-3">{steps} step{steps === 1 ? '' : 's'} so far</p>}
      </div>
    </div>
  );
}
