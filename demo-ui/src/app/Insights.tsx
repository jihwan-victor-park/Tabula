// Insights: sales trend with period comparison, best and slow sellers, expected stockouts —
// all from recorded sales; missing days stay missing. Leads into the order analysis.

import { useQuery } from '@tanstack/react-query';
import { useState } from 'react';
import { Link } from 'react-router-dom';
import { cn } from '../components/ui';
import { api, loadSession } from '../ops/api';
import { ButtonLink, EmptyState, ErrorBox, OpsShell, Panel, RequireSession, Skeleton, Stat, StatStrip, Tabs, day, money, num, through } from '../ops/kit';
import { DailyBars } from './Charts';
import type { Analytics } from './types';

export function InsightsPage() {
  return <OpsShell active="insights" title="Insights" subtitle="What sells, what doesn't, and what runs out — from recorded sales only."
    actions={<ButtonLink to="/app/orders/plan" variant="secondary">Review reorder plan</ButtonLink>}><RequireSession><Insights /></RequireSession></OpsShell>;
}

// Periods are compared per day that has sales data, so a half-covered previous period doesn't inflate the change.
function pct(cur: string | null, prev: string | null, curDays = 1, prevDays = 1) {
  if (cur == null || prev == null || !curDays || !prevDays) return null;
  const a = Number(cur) / curDays, b = Number(prev) / prevDays;
  return b === 0 ? null : Math.round(((a - b) / b) * 100);
}

function Insights() {
  const loc = loadSession()!.locationId!;
  const [days, setDays] = useState<'7' | '14' | '28' | '56'>('28');
  const a = useQuery({ queryKey: ['analytics', loc, Number(days)], queryFn: () => api<Analytics>(`/analytics?location_id=${loc}&days=${days}`) });
  if (a.error) return <ErrorBox error={a.error} onRetry={() => a.refetch()} />;
  const d = a.data;
  const change = d ? pct(d.current.units, d.previous.units, d.current.days_with_data, d.previous.days_with_data) : null;
  const partialPrev = d && d.previous.days_with_data > 0 && d.previous.days_with_data < d.previous.days;
  return (
    <>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <Tabs value={days} onChange={setDays} items={[{ value: '7', label: '7 days' }, { value: '14', label: '14 days' }, { value: '28', label: '4 weeks' }, { value: '56', label: '8 weeks' }]} />
        {d && <span className="text-[13px] text-[#66707A]">{day(d.current.from)} – {day(d.current.to)} vs {day(d.previous.from)} – {day(d.previous.to)}{d.sales_through ? ` · sales through ${through(d.sales_through)}` : ''}</span>}
      </div>
      {!d && <Skeleton rows={5} />}
      {d && !d.has_data && (
        <Panel><EmptyState icon="query_stats" title="No sales data for this period" body="Insights use your recorded sales only — nothing is estimated. Import a sales export covering these dates.">
          <ButtonLink to="/app/settings/data/import?kind=sales">Import sales</ButtonLink></EmptyState></Panel>
      )}
      {d?.has_data && <>
        <StatStrip cols={4}>
          <Stat label="Units sold" value={num(d.current.units)} sub={d.previous.units == null ? 'no data for the previous period' : `${num(d.previous.units)} in the previous period`} />
          <Stat label="Change per day" value={change == null ? '—' : `${change > 0 ? '+' : ''}${change}%`} tone={change == null ? undefined : change >= 0 ? 'good' : 'bad'}
            sub={change == null ? 'needs data for both periods' : partialPrev ? `previous period has data for ${d.previous.days_with_data} of ${d.previous.days} days` : 'average units per day vs previous period'} />
          <Stat label="Sales" value={d.current.revenue ? money(d.current.revenue) : '—'} sub={d.current.revenue ? 'from prices in your sales data' : d.current.sales_without_price ? `${num(d.current.sales_without_price)} sale line(s) have no price` : 'your sales data has no prices'} />
          <Stat label="Days with data" value={`${d.current.days_with_data}/${d.current.days}`} sub={d.current.days_with_data < d.current.days ? 'missing days are not counted as zero' : 'complete'} />
        </StatStrip>
        <Panel title="Units sold per day"><DailyBars data={d.daily} /><div className="mt-2 text-[12px] text-[#66707A]">Striped = no sales data for that day.</div></Panel>
        <div className="grid gap-5 lg:grid-cols-2">
          <Panel title="Best sellers"><ItemTable rows={d.top_sellers} showChange days={[d.current.days_with_data, d.previous.days_with_data]} /></Panel>
          <Panel title="Slow movers" aside={<span className="text-[12px] text-[#66707A]">in stock, selling well below average</span>}>
            {(() => {
              const avg = d.top_sellers.reduce((x, r) => x + Number(r.units), 0) / Math.max(d.top_sellers.length, 1);
              const slow = d.slow_movers.filter((r) => Number(r.units) < avg * 0.5).slice(0, 8);
              return slow.length ? <ItemTable rows={slow} /> : <div className="text-[14px] text-[#66707A]">No item is selling well below the average.</div>;
            })()}
          </Panel>
        </div>
      </>}
      {d && (
        <Panel title="Expected to run out" aside={<Link to="/app/orders/plan" className="text-[13px] font-medium text-[#2457C5] hover:underline">Reorder plan</Link>}>
          {d.stockouts_ahead.length === 0 && <div className="text-[14px] text-[#66707A]">No item is expected to run out within the planning window{d.has_data ? '' : ' (needs sales data to estimate)'}.</div>}
          <ul className="flex flex-col divide-y divide-[#EDEFF2]">
            {d.stockouts_ahead.map((r) => (
              <li key={r.variant_id}><Link to={`/app/inventory/${r.variant_id}`} className="flex items-center justify-between gap-3 py-2.5 text-[14px]">
                <span><b>{r.name}</b> <span className="text-[#66707A]">{r.sku}</span></span>
                <span className="text-right"><span className="font-semibold text-[#A15C07]">{day(r.stockout_date)}</span>
                  <span className="block text-[12px] text-[#66707A]">{num(r.on_hand)} left · {num(r.daily_demand)}/day</span></span>
              </Link></li>
            ))}
          </ul>
        </Panel>
      )}
    </>
  );
}

function ItemTable({ rows, showChange, days = [1, 1] }: { rows: Analytics['top_sellers']; showChange?: boolean; days?: number[] }) {
  if (!rows.length) return <div className="text-[14px] text-[#66707A]">No items.</div>;
  const max = Math.max(1, ...rows.map((r) => Number(r.units)));
  return (
    <ul className="flex flex-col gap-2.5">
      {rows.map((r) => {
        const c = pct(r.units, r.previous_units, days[0], days[1]);
        return (
          <li key={r.variant_id}><Link to={`/app/inventory/${r.variant_id}`} className="block">
            <div className="flex items-baseline justify-between gap-2 text-[14px]"><span className="truncate font-medium">{r.name}</span>
              <span className="whitespace-nowrap font-semibold">{num(r.units)}{showChange && c != null && <span className={cn('ml-2 text-[12px]', c >= 0 ? 'text-[#1F7A4D]' : 'text-[#B42318]')}>{c >= 0 ? '+' : ''}{c}%</span>}</span></div>
            <div className="mt-1 h-1.5 rounded-full bg-[#EDEFF2]"><div className="h-1.5 rounded-full bg-[#2457C5]" style={{ width: `${Math.max((Number(r.units) / max) * 100, 2)}%` }} /></div>
            <div className="mt-0.5 text-[12px] text-[#66707A]">{r.sku} · {num(r.on_hand)} in stock</div>
          </Link></li>
        );
      })}
    </ul>
  );
}
