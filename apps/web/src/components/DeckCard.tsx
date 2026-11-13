// A presentation Gemini made, under its answer: every slide as it will look in PowerPoint (one large, the rest in a strip
// to pick from), Download PowerPoint, and Open where Wizard saved it on this PC. Changes are asked for in the chat; each
// change is a new version shown in its own answer.
import {useContext, useEffect, useMemo, useState} from 'react';
import {ChevronLeft, ChevronRight, Download, FolderOpen, Loader2, Presentation} from 'lucide-react';
import {Button} from './ui/button';
import {Hint} from './ui/menu';
import {deckFileName, layoutDeck} from '@/deck/layout';
import {SlideView} from '@/deck/SlideView';
import {deliver} from '@/visualExport';
import {VisualEnvContext, type SavedExport} from '@/visualEnv';
import type {Deck} from '@/types';

type State = {step: 'idle'} | {step: 'busy'} | {step: 'done'; text: string; saved: SavedExport | null} | {step: 'failed'; text: string};

export function DeckCard({deck}: {deck: Deck}) {
  const env = useContext(VisualEnvContext);
  const pages = useMemo(() => layoutDeck(deck), [deck]);
  const tokens = deck.design.tokens;
  const [at, setAt] = useState(0);
  const [state, setState] = useState<State>({step: 'idle'});
  useEffect(() => { setAt(a => Math.min(a, pages.length - 1)); }, [pages.length]);
  const page = pages[at];
  const go = (by: number) => setAt(a => Math.max(0, Math.min(pages.length - 1, a + by)));

  const download = async () => {
    setState({step: 'busy'});
    try {
      const {deckPptx} = await import('@/deck/pptx');
      const filename = deckFileName(deck);
      const saved = await deliver(env, await deckPptx(deck), filename);
      setState({step: 'done', saved, text: saved ? `Saved in ${saved.folder} as ${saved.filename}.` : `Downloaded ${filename}.`});
    } catch (e) {
      setState({step: 'failed', text: e instanceof Error ? e.message : 'The presentation could not be made.'});
    }
  };
  const open = async (saved: SavedExport) => {
    try { await env.open?.(saved); } catch (e) { setState({step: 'failed', text: e instanceof Error ? e.message : 'It could not be opened.'}); }
  };

  return (
    <section id={`deck-${deck.id}`} className="overflow-hidden rounded-xl border border-line bg-canvas" aria-label={`Presentation ${deck.title}`}
      data-testid="deck" data-deck={deck.id}>
      <header className="flex flex-wrap items-start gap-x-3 gap-y-1 border-b border-line px-4 py-3">
        <span className="mt-0.5 grid size-8 shrink-0 place-items-center rounded-lg bg-accent-soft text-accent"><Presentation className="size-4" /></span>
        <div className="min-w-0 flex-1">
          <p className="truncate text-[15px] font-semibold text-ink" data-testid="deck-title">{deck.title}</p>
          <p className="text-[12.5px] text-ink-3">{pages.length} slides{deck.version > 1 ? ` · version ${deck.version}` : ''} · {deck.id}
            {deck.data_mode === 'SYNTHETIC' && <span className="ml-1.5 rounded border border-warn-line bg-warn-soft px-1 text-[11px] font-medium text-warn">SYNTHETIC test data</span>}</p>
        </div>
        <div className="flex items-center gap-1.5">
          <Button variant="accent" size="sm" onClick={() => void download()} disabled={state.step === 'busy'} data-testid="deck-download">
            {state.step === 'busy' ? <Loader2 className="animate-spin" /> : <Download />}Download PowerPoint
          </Button>
        </div>
      </header>
      <div className="space-y-3 px-4 py-3">
        <p className="text-[13px] text-ink-2" data-testid="deck-storyline"><span className="font-medium text-ink">Story:</span> {deck.storyline}</p>
        <div className="relative" onKeyDown={e => { if (e.key === 'ArrowRight') go(1); if (e.key === 'ArrowLeft') go(-1); }} tabIndex={0}
          aria-label="Slides: use the arrow keys to move" data-testid="deck-viewer">
          <div className="overflow-hidden rounded-lg border border-line shadow-card">
            {page && <SlideView page={page} tokens={tokens} />}
          </div>
          <div className="mt-2 flex items-center justify-center gap-2 text-[12.5px] text-ink-2">
            <Button variant="ghost" size="icon-sm" aria-label="Previous slide" disabled={at === 0} onClick={() => go(-1)}><ChevronLeft /></Button>
            <span className="tabular-nums" data-testid="deck-position">{at + 1} / {pages.length}</span>
            <Button variant="ghost" size="icon-sm" aria-label="Next slide" disabled={at === pages.length - 1} onClick={() => go(1)}><ChevronRight /></Button>
          </div>
        </div>
        <ol className="flex gap-2 overflow-x-auto pb-1 scroll-thin" aria-label="All slides" data-testid="deck-strip">
          {pages.map((p, i) => (
            <li key={p.number} className="w-[132px] shrink-0">
              <button type="button" onClick={() => setAt(i)} aria-current={i === at ? 'true' : undefined} aria-label={`Slide ${p.number}: ${p.title}`}
                className={`block w-full overflow-hidden rounded-md border text-left transition-colors ${i === at ? 'border-accent ring-2 ring-accent/30' : 'border-line hover:border-line-2'}`}>
                <SlideView page={p} tokens={tokens} label={`Slide ${p.number} preview`} />
              </button>
              <p className="mt-0.5 truncate text-[11px] text-ink-3"><span className="tabular-nums">{p.number}</span> {p.title}</p>
            </li>
          ))}
        </ol>
        {state.step === 'done' && <p className="text-[12.5px] text-ok" data-testid="deck-saved">{state.text}
          {state.saved && env.open && <button type="button" onClick={() => void open(state.saved!)} data-testid="deck-open"
            className="ml-2 inline-flex items-center gap-1 font-medium text-accent hover:underline"><FolderOpen className="size-3.5" />Open</button>}</p>}
        {state.step === 'failed' && <p className="text-[12.5px] text-danger" role="alert">{state.text}</p>}
        <p className="text-[12px] text-ink-3" data-testid="deck-hint">Ask for any change below, for example “make slide 3 a table” or “shorter titles”.{' '}
          {deck.design.source === 'default'
            ? <Hint text={deck.design.about}><span tabIndex={0} className="underline decoration-dotted underline-offset-2">Drawn in Wizard's neutral design.</span></Hint>
            : <Hint text={deck.design.about}><span tabIndex={0} className="underline decoration-dotted underline-offset-2">In the company's design ({deck.design.tokens.name}).</span></Hint>}
        </p>
      </div>
    </section>
  );
}
