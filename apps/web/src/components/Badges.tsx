import {AlertTriangle, BadgeCheck, CircleDashed, FlaskConical, PlayCircle, Radio, Sparkles} from 'lucide-react';
import {Hint} from './ui/menu';
import {CHECK_TEXT, DATA_MODE_TEXT} from '@/format';
import {cn} from '@/lib/utils';
import type {CheckStatus, DataMode, RuntimeKind} from '@/types';

const base = 'inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[11.5px] font-medium leading-5 [&_svg]:size-3.5';

export function DataModeBadge({mode, className}: {mode: DataMode | null | undefined; className?: string}) {
  if (!mode) return <span className={cn(base, 'border-line bg-surface text-ink-3', className)}>No source data</span>;
  const text = DATA_MODE_TEXT[mode];
  const tone = mode === 'SYNTHETIC' ? 'border-warn-line bg-warn-soft text-warn' : mode === 'LIVE_VERIFIED' ? 'border-ok-line bg-ok-soft text-ok' : 'border-accent-line bg-accent-soft text-accent';
  return <Hint text={text.hint}><span tabIndex={0} className={cn(base, tone, className)} data-testid="data-mode" data-mode={mode}>
    {mode === 'SYNTHETIC' ? <FlaskConical /> : mode === 'LIVE_VERIFIED' ? <Radio /> : <BadgeCheck />}{mode === 'SYNTHETIC' ? 'SYNTHETIC' : text.label}
  </span></Hint>;
}

export function CheckBadge({status, className}: {status: CheckStatus; className?: string}) {
  const text = CHECK_TEXT[status];
  const tone = status === 'CHECKED' ? 'border-ok-line bg-ok-soft text-ok' : status === 'DISCREPANCY' ? 'border-danger-line bg-danger-soft text-danger' : 'border-line bg-canvas text-ink-3';
  return <Hint text={text.hint}><span tabIndex={0} className={cn(base, tone, className)} data-testid="check-status" data-status={status}>
    {status === 'CHECKED' ? <BadgeCheck /> : status === 'DISCREPANCY' ? <AlertTriangle /> : <CircleDashed />}{text.label}
  </span></Hint>;
}

export function RuntimeBadge({kind, label}: {kind: RuntimeKind; label: string}) {
  const replay = kind === 'replay';
  return <Hint text={replay ? 'Recorded transcript over synthetic data. Not a live Gemini model.' : `Answered by ${label} under your own Gemini account.`}>
    <span tabIndex={0} className={cn(base, replay ? 'border-warn-line bg-warn-soft text-warn' : 'border-line bg-canvas text-ink-2')} data-testid="runtime" data-kind={kind}>
      {replay ? <PlayCircle /> : <Sparkles />}{replay ? 'REPLAY · not a live model' : label}
    </span>
  </Hint>;
}

export function StatusPill({tone, children}: {tone: 'ok' | 'warn' | 'danger' | 'muted' | 'accent'; children: React.ReactNode}) {
  const tones = {ok: 'border-ok-line bg-ok-soft text-ok', warn: 'border-warn-line bg-warn-soft text-warn', danger: 'border-danger-line bg-danger-soft text-danger',
    muted: 'border-line bg-surface text-ink-3', accent: 'border-accent-line bg-accent-soft text-accent'};
  return <span className={cn(base, tones[tone])}>{children}</span>;
}
