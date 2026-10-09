import {useEffect, useState} from 'react';
import {ArrowRight, Megaphone, PackageSearch, Repeat2} from 'lucide-react';
import {WizardSprite} from './WizardSprite';

const ICONS: Record<string, React.ReactNode> = {Executive: <Megaphone />, Planner: <PackageSearch />, Conquest: <Repeat2 />};

export function EmptyState({suggestions, onPick, synthetic}: {suggestions: {story: string; question: string}[]; onPick: (q: string) => void; synthetic: boolean}) {
  const [hello, setHello] = useState(true);
  useEffect(() => { const timer = setTimeout(() => setHello(false), 2600); return () => clearTimeout(timer); }, []);
  return (
    <div className="mx-auto mt-[5vh] max-w-[860px] px-2 text-center" data-testid="empty-state">
      <WizardSprite animation={hello ? 'wave' : 'idle'} scale={3} label="Wizard" className="mb-2" />
      <p className="mb-3 text-xs font-semibold uppercase tracking-[0.18em] text-accent">Wizard · executive analyst</p>
      <h1 className="text-[clamp(28px,4vw,42px)] font-semibold leading-tight tracking-tight">Every approved source.<br />One question away.</h1>
      <p className="mx-auto mt-4 max-w-[540px] text-[15px] text-ink-2">Wizard searches NERP, GSCM and ASAP, compares what it finds and shows every number with its source. You see each step it takes.</p>
      {synthetic && <p className="mx-auto mt-3 w-fit rounded-full border border-warn-line bg-warn-soft px-3 py-1 text-xs font-medium text-warn">All connected sources are SYNTHETIC test data in this build</p>}
      <div className="mt-8 grid gap-3 text-left sm:grid-cols-3">
        {suggestions.map(s => (
          <button key={s.story} type="button" onClick={() => onPick(s.question)} data-testid="suggestion"
            className="group flex flex-col rounded-card border border-line bg-canvas p-4 text-[13.5px] shadow-card transition-colors hover:border-accent-line hover:bg-accent-soft/40">
            <span className="mb-2 inline-flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-accent [&_svg]:size-4">{ICONS[s.story]}{s.story}</span>
            <span className="flex-1 leading-snug text-ink">{s.question}</span>
            <span className="mt-3 inline-flex items-center gap-1 text-xs font-medium text-ink-3 group-hover:text-accent">Ask this<ArrowRight className="size-3.5" /></span>
          </button>
        ))}
      </div>
    </div>
  );
}
