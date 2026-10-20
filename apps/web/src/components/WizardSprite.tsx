import sheet from '@/assets/wizard-sprite.png';
import {cn} from '@/lib/utils';
import {ANIMATIONS, COLUMNS, FRAME, ROWS, type WizardAnimation} from '@/wizardSheet';

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
