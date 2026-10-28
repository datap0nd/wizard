import type {ComponentType, CSSProperties} from 'react';
import {BookOpen, ChartColumn, Coins, Database, Paperclip, Truck, Waves} from 'lucide-react';
import hat from '@/assets/wizard-mark.svg';
import {cn} from '@/lib/utils';

/** A white line drawing on a 24 x 24 grid, as lucide's icons are. */
export type Glyph = ComponentType<{style?: CSSProperties; strokeWidth?: number}>;

export interface Brand { color: string; deep: string; icon: Glyph | null; mark: string; image?: string }

/** Metronome's own logo (its app header): the case, the swinging arm with its weight, and the base. */
function MetronomeGlyph({style, strokeWidth = 2}: {style?: CSSProperties; strokeWidth?: number}) {
  return (
    <svg viewBox="0 0 24 24" style={style} fill="none" stroke="currentColor" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M7.5 21h9L14.6 4.5H9.4L7.5 21Z" fill="currentColor" fillOpacity={0.18} strokeWidth={strokeWidth * 0.8} />
      <path d="M12 6.2l3.2 10.2M6 21h12" strokeWidth={strokeWidth * 0.75} />
      <circle cx="14" cy="12.4" r="1.9" fill="currentColor" stroke="none" />
    </svg>
  );
}

/** Orchestra's mark: a sound wave on a line. */
function OrchestraGlyph({style, strokeWidth = 2}: {style?: CSSProperties; strokeWidth?: number}) {
  return (
    <svg viewBox="0 0 24 24" style={style} fill="none" stroke="currentColor" strokeLinecap="round" aria-hidden="true">
      <path d="M2.2 12h2.9M5.1 6.1v9.4M7.9 8.7v5.4M11.1 4.1v14.6M13.7 8.7v4.8M16.9 7.5v8.6M16.9 12h4.9" strokeWidth={strokeWidth * 0.85} />
    </svg>
  );
}

/** Each system's mark and colours. A system not listed here (a new platform) gets a monogram in a stable colour. */
const BRANDS: Record<string, Brand> = {
  wizard: {color: '#1428a0', deep: '#0b1869', icon: null, mark: 'W', image: hat},
  postgresql: {color: '#7c3aed', deep: '#4c1d95', icon: Database, mark: 'AI'},
  knowledge: {color: '#059669', deep: '#065f46', icon: BookOpen, mark: 'KB'},
  asap: {color: '#2563eb', deep: '#1e40af', icon: ChartColumn, mark: 'AS'},
  gscm: {color: '#ea580c', deep: '#9a3412', icon: Truck, mark: 'GS'},
  nerp: {color: '#ca8a04', deep: '#854d0e', icon: Coins, mark: 'NE'},
  bdp: {color: '#0891b2', deep: '#155e75', icon: Waves, mark: 'BD'},
  attachment: {color: '#475569', deep: '#1e293b', icon: Paperclip, mark: 'F'},
  metronome: {color: '#0d7377', deep: '#084b4e', icon: MetronomeGlyph, mark: 'ME'},
  orchestra: {color: '#0125c4', deep: '#561ad4', icon: OrchestraGlyph, mark: 'OR'},
  scplus: {color: '#e11d48', deep: '#881337', icon: null, mark: 'SC+'},
  powerpoint: {color: '#d24726', deep: '#8a2a12', icon: null, mark: 'P'},
};
const SPARE = [['#db2777', '#831843'], ['#0d9488', '#134e4a'], ['#9333ea', '#581c87'], ['#dc2626', '#7f1d1d'], ['#4f46e5', '#312e81']];

export function brand(id: string, name?: string): Brand {
  if (BRANDS[id]) return BRANDS[id];
  const named = name?.trim().toLowerCase();  // a platform documented under another id, e.g. "Orchestra"
  if (named && BRANDS[named] && named !== 'wizard') return BRANDS[named];
  const hash = Array.from(id).reduce((h, c) => (h * 31 + c.charCodeAt(0)) >>> 0, 7);
  const [color, deep] = SPARE[hash % SPARE.length];
  const mark = (name ?? id).replace(/[^A-Za-z0-9 ]/g, '').split(/\s+/).map(w => w[0]).join('').slice(0, 3).toUpperCase() || id.slice(0, 2).toUpperCase();
  return {color, deep, icon: null, mark};
}

/** A system's logo tile: its mark on its colour. */
export function SystemLogo({id, name, size = 44, className}: {id: string; name?: string; size?: number; className?: string}) {
  const b = brand(id, name);
  const Icon = b.icon;
  if (b.image) {
    return (
      <span aria-hidden="true" className={cn('relative grid shrink-0 place-items-center rounded-[28%] bg-gradient-to-br from-white to-accent-soft shadow-sm ring-1 ring-inset ring-accent-line', className)}
        style={{width: size, height: size}}>
        <img src={b.image} alt="" className="[image-rendering:pixelated]" style={{width: size * 0.68, height: size * 0.68}} />
      </span>
    );
  }
  return (
    <span aria-hidden="true" className={cn('relative grid shrink-0 place-items-center rounded-[28%] text-white shadow-sm', className)}
      style={{width: size, height: size, background: `linear-gradient(135deg, ${b.color}, ${b.deep})`}}>
      {Icon ? <Icon style={{width: size * 0.5, height: size * 0.5}} strokeWidth={2.1} />
        : <span className="font-semibold tracking-tight" style={{fontSize: size * 0.34}}>{b.mark}</span>}
      <span className="pointer-events-none absolute inset-0 rounded-[28%] ring-1 ring-inset ring-white/25" />
    </span>
  );
}
