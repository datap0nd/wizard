import {useEffect, useRef, useState} from 'react';

/** A number that counts up to its value (from zero the first time), easing out; `still` shows it at once. */
export function CountUp({value, duration = 1400, delay = 0, still = false}: {value: number; duration?: number; delay?: number; still?: boolean}) {
  const [shown, setShown] = useState(0);
  const from = useRef(0);
  useEffect(() => {
    const start = from.current, delta = value - start;
    const reduced = typeof matchMedia === 'function' && matchMedia('(prefers-reduced-motion: reduce)').matches;
    if (!delta || reduced || still || typeof requestAnimationFrame !== 'function') { setShown(value); from.current = value; return; }
    const began = performance.now() + delay;
    let frame = 0;
    const tick = (now: number) => {
      const t = Math.min(1, Math.max(0, (now - began) / duration));
      setShown(Math.round(start + delta * (1 - (1 - t) ** 3)));
      if (t < 1) frame = requestAnimationFrame(tick); else from.current = value;
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [value, duration, delay, still]);
  return <span className="tabular-nums">{shown.toLocaleString()}</span>;
}
