import {useEffect, useRef, useState} from 'react';

/** A number that counts up to its value (from zero the first time), easing out. */
export function CountUp({value, duration = 1400, delay = 0}: {value: number; duration?: number; delay?: number}) {
  const [shown, setShown] = useState(0);
  const from = useRef(0);
  useEffect(() => {
    const start = from.current, delta = value - start;
    const reduced = typeof matchMedia === 'function' && matchMedia('(prefers-reduced-motion: reduce)').matches;
    if (!delta || reduced || typeof requestAnimationFrame !== 'function') { setShown(value); from.current = value; return; }
    const began = performance.now() + delay;
    let frame = 0;
    const tick = (now: number) => {
      const t = Math.min(1, Math.max(0, (now - began) / duration));
      setShown(Math.round(start + delta * (1 - (1 - t) ** 3)));
      if (t < 1) frame = requestAnimationFrame(tick); else from.current = value;
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [value, duration, delay]);
  return <span className="tabular-nums">{shown.toLocaleString()}</span>;
}
