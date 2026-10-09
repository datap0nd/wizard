import type {RunView, TimelineItem} from './types';
import type {WizardAnimation} from './wizardSheet';

/** What the wizard acts out for a tool. Read-only tools only; an unknown name searches. */
export function toolAnimation(name: string): WizardAnimation {
  if (name.includes('check_my_data')) return 'check';
  if (name.includes('render_visual')) return 'chart';
  if (name.includes('calculate')) return 'cast';
  if (name.endsWith('_run_report') || name.includes('query') || name.includes('read_') || name.includes('definitions')) return 'read';
  return 'search';
}

function activeTool(run: RunView): TimelineItem | undefined {
  for (let i = run.timeline.length - 1; i >= 0; i--) {
    const item = run.timeline[i];
    if (item.kind === 'tool' && item.state === 'running') return item;
  }
  return undefined;
}

/** The animation for a run, from its observed events only: the wizard never acts out a step Wizard did not take. */
export function wizardAnimation(run: RunView): WizardAnimation {
  if (run.status === 'succeeded') return 'success';
  if (run.status === 'failed') return 'fail';
  if (run.status === 'cancelled') return 'idle';
  const tool = activeTool(run);
  if (tool) return toolAnimation(tool.name ?? '');
  if (run.streamText) return 'write';
  return run.kind === 'check' ? 'check' : 'think';
}

const VERBS: Record<WizardAnimation, string> = {
  idle: 'Ready', wave: 'Hello', think: 'Deciding the next step', search: 'Searching', read: 'Reading', write: 'Writing',
  cast: 'Calculating', chart: 'Drawing a chart', check: 'Checking the figures', success: 'Done', fail: 'Could not finish',
};

/** The words under the wizard: what it is doing, and the step it is on (that step's own label). */
export function wizardCaption(run: RunView, animation: WizardAnimation): {verb: string; detail: string | null} {
  if (run.status === 'queued') return {verb: 'Getting ready', detail: null};
  return {verb: VERBS[animation], detail: activeTool(run)?.label ?? null};
}
