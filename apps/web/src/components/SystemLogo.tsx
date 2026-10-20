import {BookOpen, ChartColumn, Coins, Database, Paperclip, Truck, Waves} from 'lucide-react';
import type {LucideIcon} from 'lucide-react';
import hat from '@/assets/wizard-mark.svg';
import {cn} from '@/lib/utils';

export interface Brand { color: string; deep: string; icon: LucideIcon | null; mark: string; image?: string }

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
};
const SPARE = [['#db2777', '#831843'], ['#0d9488', '#134e4a'], ['#9333ea', '#581c87'], ['#dc2626', '#7f1d1d'], ['#4f46e5', '#312e81']];

export function brand(id: string, name?: string): Brand {
  if (BRANDS[id]) return BRANDS[id];
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
