import {useEffect, useRef, useState} from 'react';
import {AlertTriangle, Loader2} from 'lucide-react';
import {api} from '@/api';

/** A recurring brief's email as it looked on its test run, drawn by the same code Metronome runs (charts as SVG here,
 *  PNG in the email). The HTML sits in a sandboxed frame without scripts; same-origin only so the frame can be sized
 *  to its content. */
export function EmailPreview({scheduleId, title}: {scheduleId: string; title: string}) {
  const [html, setHtml] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [height, setHeight] = useState(480);
  const frame = useRef<HTMLIFrameElement>(null);

  useEffect(() => {
    let live = true;
    setHtml(null);
    setError(null);
    api.schedulePreview(scheduleId).then(r => { if (live) setHtml(r.html); },
      e => { if (live) setError(e instanceof Error ? e.message : 'The preview could not be loaded.'); });
    return () => { live = false; };
  }, [scheduleId]);

  const fit = () => {
    const page = frame.current?.contentDocument?.documentElement;
    if (page) setHeight(Math.min(Math.max(page.scrollHeight, 200), 4000));
  };

  if (error) return <p className="flex items-start gap-1.5 text-[13px] text-danger" role="alert"><AlertTriangle className="mt-0.5 size-4 shrink-0" />{error}</p>;
  if (html === null) return <p className="flex items-center gap-1.5 text-[13px] text-ink-3"><Loader2 className="size-4 animate-spin" />Drawing the email…</p>;
  return (
    <iframe ref={frame} title={`Email preview: ${title}`} srcDoc={html} sandbox="allow-same-origin" onLoad={fit}
      className="block w-full rounded-lg border border-line bg-[#eef0f4]" style={{height}} data-testid="email-preview" />
  );
}
