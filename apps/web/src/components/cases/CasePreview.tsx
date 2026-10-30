import {useEffect, useState} from 'react';
import {api} from '@/api';
import {chosenTurns, type Case} from '@/cases';
import {CasePage} from './CasePage';

/** /case/<chat>: a chat as Share as case would publish it, shown in Wizard before anything reaches the site. `?runs=`
 *  keeps only the answers chosen in the dialog. */
export function CasePreview({conversationId}: {conversationId: string}) {
  const [item, setItem] = useState<Case | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    const runs = new URLSearchParams(location.search).get('runs');
    api.casePreview(conversationId).then(found => {
      const made = found.case;
      if (!made) { setError('This chat has no finished answer to share yet.'); return; }
      if ('problem' in made && made.problem) { setError(made.problem); return; }
      const full = made as Case;
      const params = new URLSearchParams(location.search);
      setItem({...full, title: params.get('title') || full.title, takeaway: params.get('takeaway') ?? full.takeaway,
        turns: chosenTurns(full.turns, runs ? runs.split(',') : null)});
    }).catch((e: unknown) => setError(e instanceof Error ? e.message : 'The chat could not be read.'));
  }, [conversationId]);
  if (error) return <div className="grid min-h-dvh place-items-center bg-page p-6 text-sm text-danger" role="alert">{error}</div>;
  if (!item) return <div className="grid min-h-dvh place-items-center bg-page text-sm text-ink-3">Loading the case…</div>;
  return <CasePage item={item} home="/" preview />;
}
