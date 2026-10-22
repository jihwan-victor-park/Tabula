// Small SVG charts. Missing data is drawn as a gap with a hatch, never as zero.

import { useState } from 'react';
import { C, day, num } from '../ops/kit';

export function DailyBars({ data, height = 160, unit = 'units' }: { data: { date: string; units: string | null }[]; height?: number; unit?: string }) {
  const [hover, setHover] = useState<number | null>(null);
  const values = data.map((d) => (d.units == null ? null : Number(d.units)));
  const max = Math.max(1, ...values.map((v) => v ?? 0));
  const w = 100 / Math.max(data.length, 1);
  const h = hover != null ? data[hover] : null;
  return (
    <div className="relative">
      <svg viewBox={`0 0 100 ${height}`} preserveAspectRatio="none" className="h-[160px] w-full" role="img" aria-label={`Daily ${unit}`}>
        <defs>
          <pattern id="nodata" width="3" height="3" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
            <line x1="0" y1="0" x2="0" y2="3" stroke="#D8CFC6" strokeWidth="1" />
          </pattern>
        </defs>
        {[0.25, 0.5, 0.75].map((f) => <line key={f} x1="0" x2="100" y1={height * f} y2={height * f} stroke={C.line} strokeWidth="0.2" />)}
        {values.map((v, i) => v == null
          ? <rect key={i} x={i * w + w * 0.12} width={w * 0.76} y={height * 0.55} height={height * 0.45} fill="url(#nodata)" onMouseEnter={() => setHover(i)} onMouseLeave={() => setHover(null)} />
          : <rect key={i} x={i * w + w * 0.12} width={w * 0.76} y={height - (v / max) * (height - 6)} height={Math.max((v / max) * (height - 6), 0.6)} rx="0.6"
              fill={hover === i ? C.navy : C.brand} onMouseEnter={() => setHover(i)} onMouseLeave={() => setHover(null)} />)}
      </svg>
      <div className="mt-1 flex justify-between text-[11px] text-[#5E6E78]"><span>{day(data[0]?.date)}</span><span>{day(data[data.length - 1]?.date)}</span></div>
      {h && (
        <div className="pointer-events-none absolute right-0 top-0 rounded-[8px] bg-[#16232B] px-2 py-1 text-[12px] text-white">
          {day(h.date)}: {h.units == null ? 'no sales data' : `${num(h.units)} ${unit}`}
        </div>
      )}
    </div>
  );
}

export function StockLine({ points, height = 140 }: { points: { label: string; value: number; short?: boolean }[]; height?: number }) {
  if (!points.length) return null;
  const max = Math.max(1, ...points.map((p) => p.value));
  const step = 100 / Math.max(points.length - 1, 1);
  const y = (v: number) => height - 4 - (v / max) * (height - 12);
  const path = points.map((p, i) => `${i ? 'L' : 'M'}${i * step},${y(p.value)}`).join(' ');
  return (
    <div>
      <svg viewBox={`0 0 100 ${height}`} preserveAspectRatio="none" className="h-[140px] w-full" role="img" aria-label="Projected stock">
        <line x1="0" x2="100" y1={y(0)} y2={y(0)} stroke={C.line} strokeWidth="0.4" />
        <path d={`${path} L100,${y(0)} L0,${y(0)} Z`} fill={C.brandSoft} />
        <path d={path} fill="none" stroke={C.brand} strokeWidth="0.8" vectorEffect="non-scaling-stroke" />
        {points.map((p, i) => p.short && <rect key={i} x={i * step - step / 2} width={step} y={0} height={height} fill="#B93A26" opacity="0.08" />)}
      </svg>
      <div className="mt-1 flex justify-between text-[11px] text-[#5E6E78]"><span>{points[0].label}</span><span>{points[points.length - 1].label}</span></div>
    </div>
  );
}
