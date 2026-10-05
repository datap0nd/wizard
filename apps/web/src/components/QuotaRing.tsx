import {useEffect, useState} from 'react';
import {api} from '@/api';
import {cn} from '@/lib/utils';
import {formatDate} from '@/format';
import {Hint} from './ui/menu';
import type {GeminiQuota} from '@/types';

const REFRESH_MS = 5 * 60_000;

/** A small ring with how much of the person's Gemini quota for the configured model is used (Gemini CLI's
 * retrieveUserQuota, under their own sign-in). Refreshes every few minutes and after each answer (`busy` turning false). */
export function QuotaRing({enabled, busy}: {enabled: boolean; busy: boolean}) {
  const [quota, setQuota] = useState<GeminiQuota | null>(null);
  useEffect(() => {
    if (!enabled || busy) return undefined;
    let live = true;
    const load = (refresh: boolean) => api.quota(refresh).then(q => { if (live) setQuota(q); }).catch(() => undefined);
    void load(true);
    const timer = window.setInterval(() => void load(false), REFRESH_MS);
    return () => { live = false; window.clearInterval(timer); };
  }, [enabled, busy]);

  const bucket = quota?.available ? quota.selected : null;
  if (!enabled || !bucket) return null;
  const used = Math.min(1, Math.max(0, bucket.used_fraction));
  const percent = Math.round(used * 100);
  const radius = 8;
  const circumference = 2 * Math.PI * radius;
  const left = bucket.remaining !== null && bucket.limit
    ? `${bucket.remaining.toLocaleString()} of ${bucket.limit.toLocaleString()} left`
    : `${100 - percent}% left`;
  const reset = bucket.reset_time ? ` · resets ${formatDate(bucket.reset_time, true)}` : '';
  return (
    <Hint text={`${quota?.model} quota: ${percent}% used · ${left}${reset}`}>
      <span tabIndex={0} role="img" aria-label={`Gemini quota ${percent}% used`} data-testid="quota-ring"
        className="grid size-8 shrink-0 place-items-center rounded-full outline-none focus-visible:ring-2 focus-visible:ring-accent">
        <svg viewBox="0 0 20 20" className="size-6 -rotate-90" aria-hidden="true">
          <circle cx="10" cy="10" r={radius} fill="none" strokeWidth="2.5" className="stroke-line" />
          <circle cx="10" cy="10" r={radius} fill="none" strokeWidth="2.5" strokeLinecap="round"
            strokeDasharray={circumference} strokeDashoffset={circumference * (1 - used)}
            className={cn('stroke-current', used >= 0.9 ? 'text-danger' : used >= 0.7 ? 'text-warn' : 'text-emerald-600')} />
        </svg>
      </span>
    </Hint>
  );
}
