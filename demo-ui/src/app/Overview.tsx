// Overview: today's work. What is short, what to order (with quantities and cost), what is on
// its way — and, where data is missing, the next step instead of a made-up number.

import { useQuery } from '@tanstack/react-query';
import { Link, Navigate, useNavigate } from 'react-router-dom';
import { SymbolIcon, cn } from '../components/ui';
import { api, loadSession, type AttentionItem, type PoSummary } from '../ops/api';
import {
  ButtonLink, EmptyState, ErrorBox, OpsShell, Panel, RequireSession, Skeleton, Stat, StatStrip, StatusChip, ago, day, daysUntil,
  money, num, td, tdNum, th, thNum, through,
} from '../ops/kit';
import { nextAction, phase } from './orderState';
import type { Overview, Readiness, StockRow } from './types';

export function OverviewPage() {
  const s = loadSession();
  return (
    <OpsShell active="overview" title={s?.tenantName ?? 'Overview'} subtitle={<SyncLine />}
      actions={<ButtonLink to="/app/orders/plan" size="lg"><SymbolIcon icon="playlist_add_check" family="rounded" className="text-[19px]" />Review reorder plan</ButtonLink>}>
      <RequireSession><Today /></RequireSession>
    </OpsShell>
  );
}

const useOverview = (loc?: string) => useQuery({ queryKey: ['overview', loc], queryFn: () => api<Overview>(`/stock/overview?location_id=${loc}`), enabled: !!loc });

/** When the numbers on this screen were last brought up to date. */
function SyncLine() {
  const loc = loadSession()?.locationId;
  const o = useOverview(loc).data;
  if (!o) return null;
  const stock = o.items.map((i) => i.stock_as_of).filter(Boolean).sort().pop();
  const sales = o.items.map((i) => i.sales_through).filter(Boolean).sort().pop();
  if (!stock && !sales) return <>No data connected yet</>;
  return <>{stock ? <>Stock updated {ago(stock)}</> : 'Stock never counted'}{' · '}{sales ? <>sales through {through(sales)}</> : 'no sales data'}</>;
}

function Today() {
  const s = loadSession()!;
  const loc = s.locationId!;
  const overview = useOverview(loc);
  const readiness = useQuery({ queryKey: ['readiness', loc], queryFn: () => api<Readiness>(`/readiness?location_id=${loc}`) });
  const pos = useQuery({ queryKey: ['pos', s.tenantId], queryFn: () => api<PoSummary[]>('/purchase-orders') });
  const tasks = useQuery({ queryKey: ['attention', loc], queryFn: () => api<AttentionItem[]>(`/attention?location_id=${loc}`) });

  if (overview.error) return <ErrorBox error={overview.error} onRetry={() => overview.refetch()} />;
  if (readiness.data && readiness.data.facts.products === 0) return <Navigate to="/app/setup" replace />;
  const o = overview.data;
  const out = o?.counts.out_of_stock ?? 0, soon = o?.counts.at_risk ?? 0;
  const review = pos.data?.filter((p) => phase(p) === 'review') ?? [];
  const coming = pos.data?.filter((p) => phase(p) === 'progress') ?? [];
  const nextArrival = coming.map((p) => p.expected_at).filter(Boolean).sort()[0];

  return (
    <>
      <StatStrip>
        <Stat label="Low stock" value={o ? num(out + soon) : '—'} tone={out ? 'bad' : soon ? 'warn' : undefined}
          sub={o ? (out + soon ? `${out} out now · ${soon} within 7 days` : 'nothing runs out this week') : ' '} to="/app/inventory?state=low" />
        <Stat label="Orders to review" value={pos.data ? num(review.length) : '—'} sub={review.length ? 'drafts, approvals, supplier changes' : 'nothing waiting'} to="/app/orders" />
        <Stat label="Arriving" value={pos.data ? num(coming.length) : '—'} sub={coming.length ? (nextArrival ? `next expected ${day(nextArrival)}` : 'no date yet') : 'nothing on order'} to="/app/orders?tab=progress" />
      </StatStrip>

      <ReorderPanel o={o} readiness={readiness.data} />

      <div className="grid gap-5 lg:grid-cols-[1fr_340px]">
        <OnTheWay pos={coming} loading={pos.isLoading} />
        <Panel title="To do" aside={tasks.data && <span className="text-[12px] text-[#66707A]">{tasks.data.length || 'none'}</span>} padded={false}>
          {!tasks.data && <div className="p-4"><Skeleton rows={3} /></div>}
          {tasks.data?.length === 0 && <div className="px-4 pb-4 text-[13px] text-[#66707A] md:px-5">Nothing is waiting on you.</div>}
          <ul className="divide-y divide-[#EDEFF2] border-t border-[#EDEFF2]">
            {tasks.data?.slice(0, 6).map((t, i) => (
              <li key={i}><Link to={t.href.replace('#links', '')} className="flex items-start gap-2.5 px-4 py-2.5 hover:bg-[#F8F9FA] md:px-5">
                <span className={cn('mt-[7px] h-1.5 w-1.5 shrink-0 rounded-full', t.severity === 'high' ? 'bg-[#B42318]' : t.severity === 'medium' ? 'bg-[#D08A1E]' : 'bg-[#9AA3AC]')} />
                <span className="min-w-0 flex-1"><span className="block text-[13px] font-medium leading-snug">{t.title}</span>
                  <span className="block text-[12px] text-[#2457C5]">{t.action}</span></span>
              </Link></li>
            ))}
          </ul>
        </Panel>
      </div>
    </>
  );
}

// Out of stock first, then by the day it runs out; items the plan would order but that last longer come after.
function priority(a: StockRow, b: StockRow) {
  const rank = (r: StockRow) => (r.state === 'out_of_stock' ? 0 : r.state === 'at_risk' ? 1 : 2);
  return rank(a) - rank(b) || (a.stockout_date ?? '9999').localeCompare(b.stockout_date ?? '9999') || a.name.localeCompare(b.name);
}

function ReorderPanel({ o, readiness }: { o?: Overview; readiness?: Readiness }) {
  const navigate = useNavigate();
  if (!o) return <Panel title="Reorder"><Skeleton rows={4} /></Panel>;
  const rows = o.items.filter((i) => i.reorder || i.state === 'out_of_stock' || i.state === 'at_risk').sort(priority);
  const toOrder = rows.filter((r) => r.reorder && !r.reorder.on_draft);
  const total = toOrder.reduce((t, r) => t + Number(r.reorder!.cost ?? 0), 0);
  const ccy = toOrder.find((r) => r.reorder?.currency)?.reorder?.currency;
  const salesReady = readiness?.features.find((f) => f.key === 'suggestions')?.ready;
  const noSales = o.items.every((i) => i.state === 'no_sales_data' || i.state === 'no_stock_data');

  if (noSales) {
    return (
      <Panel title="Reorder">
        <EmptyState icon="query_stats" title="Add sales history to see what runs out" compact
          body="Stock is in. Tabula needs at least two weeks of sales to tell when each item runs out and how much to order — it won't guess.">
          <ButtonLink to="/app/settings/data/import?kind=sales">Import sales history</ButtonLink>
        </EmptyState>
      </Panel>
    );
  }
  return (
    <Panel padded={false} title="Reorder" sub={rows.length ? `${rows.length} item${rows.length > 1 ? 's' : ''} need attention, most urgent first` : undefined}
      aside={toOrder.length > 0 && <span className="text-[13px] text-[#66707A]">Suggested total <b className="tabular-nums text-[#14181D]">{money(total, ccy)}</b></span>}>
      {rows.length === 0 && <EmptyState icon="task_alt" compact title="Nothing needs ordering" body="Stock and incoming orders cover the coming days." />}
      {rows.length > 0 && (
        <>
          <div className="hidden md:block">
            <table className="w-full border-t border-[#EDEFF2] text-[14px]">
              <thead className="bg-[#F8F9FA]"><tr>
                <th className={th}>Item</th><th className={thNum}>In stock</th><th className={th}>Runs out</th>
                <th className={thNum}>Suggested order</th><th className={thNum}>Est. cost</th><th className={th}>Supplier</th>
              </tr></thead>
              <tbody className="divide-y divide-[#EDEFF2]">
                {rows.slice(0, 10).map((r) => (
                  <tr key={r.variant_id} className="cursor-pointer hover:bg-[#F8F9FA]" onClick={() => navigate(`/app/inventory/${r.variant_id}`)}>
                    <td className={td}><div className="font-medium">{r.name}</div><div className="text-[12px] text-[#66707A]">{r.sku}</div></td>
                    <td className={tdNum}><span className="font-medium">{num(r.on_hand)}</span>{(r.stale || !r.stock_counted) && <div className="text-[11px] text-[#A15C07]">{r.stock_counted ? 'old count' : 'not counted'}</div>}</td>
                    <td className={td}><RunsOut r={r} /></td>
                    <td className={tdNum}><Suggested r={r} /></td>
                    <td className={tdNum}>{r.reorder && !r.reorder.on_draft ? money(r.reorder.cost, r.reorder.currency) : <span className="text-[#9AA3AC]">—</span>}</td>
                    <td className={cn(td, 'text-[13px] text-[#3B444D]')}>{r.reorder?.supplier ?? <span className="text-[#9AA3AC]">—</span>}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <ul className="divide-y divide-[#EDEFF2] border-t border-[#EDEFF2] md:hidden">
            {rows.slice(0, 10).map((r) => (
              <li key={r.variant_id}><Link to={`/app/inventory/${r.variant_id}`} className="block px-4 py-3">
                <div className="flex items-baseline justify-between gap-3"><span className="truncate font-medium">{r.name}</span><RunsOut r={r} /></div>
                <div className="mt-0.5 flex items-baseline justify-between gap-3 text-[13px] text-[#66707A]">
                  <span>{num(r.on_hand)} in stock</span><span className="text-right"><Suggested r={r} />{r.reorder?.cost && !r.reorder.on_draft ? ` · ${money(r.reorder.cost, r.reorder.currency)}` : ''}</span></div>
              </Link></li>
            ))}
          </ul>
          <div className="flex flex-wrap items-center justify-between gap-3 border-t border-[#EDEFF2] px-4 py-3 md:px-5">
            <span className="text-[12px] text-[#66707A]">
              {salesReady === false ? 'Some suggestions are limited by missing data — see Settings › Data. ' : ''}
              Quantities use current stock, sales, open orders and each supplier's pack size and lead time.{rows.length > 10 ? ` ${rows.length - 10} more in Inventory.` : ''}
            </span>
            {toOrder.length > 0 && <ButtonLink to="/app/orders/plan" variant="secondary">Review and create drafts</ButtonLink>}
          </div>
        </>
      )}
    </Panel>
  );
}

function RunsOut({ r }: { r: StockRow }) {
  if (r.state === 'out_of_stock') return <span className="font-medium text-[#B42318]">Out now</span>;
  if (!r.stockout_date) return <span className="text-[13px] text-[#66707A]">{r.state === 'no_sales_data' ? 'no sales data' : 'not this month'}</span>;
  const d = daysUntil(r.stockout_date) ?? 0;
  return (
    <span className={cn('whitespace-nowrap', r.state === 'at_risk' ? 'font-medium text-[#A15C07]' : 'text-[#3B444D]')}>
      {day(r.stockout_date)} <span className="text-[12px] font-normal text-[#66707A]">{d <= 0 ? 'today' : `in ${d}d`}</span>
    </span>
  );
}

/** The suggested quantity, or why there isn't one and what to do about it. */
function Suggested({ r }: { r: StockRow }) {
  if (r.reorder?.on_draft) return <Link to="/app/orders" onClick={(e) => e.stopPropagation()} className="text-[13px] text-[#2457C5] hover:underline">on draft {r.reorder.on_draft}</Link>;
  if (r.reorder) return <span><b className="font-semibold">{num(r.reorder.qty)}</b> {r.reorder.uom}{r.reorder.uom && r.reorder.base_qty !== r.reorder.qty && <span className="text-[12px] text-[#66707A]"> · {num(r.reorder.base_qty)} units</span>}</span>;
  const why: Record<string, [string, string]> = {
    no_supplier: ['Add a supplier', '/app/orders/suppliers'], on_hold: ['Already ordered', '/app/orders?tab=progress'],
    covered: ['Covered by an order', '/app/orders?tab=progress'], insufficient_data: ['Needs sales history', '/app/settings/data/import?kind=sales'],
  };
  const w = why[r.plan_status];
  return w ? <Link to={w[1]} onClick={(e) => e.stopPropagation()} className="text-[13px] text-[#2457C5] hover:underline">{w[0]}</Link> : <span className="text-[#9AA3AC]">—</span>;
}

function OnTheWay({ pos, loading }: { pos: PoSummary[]; loading: boolean }) {
  const navigate = useNavigate();
  return (
    <Panel padded={false} title="On the way" aside={<Link to="/app/orders?tab=progress" className="text-[13px] font-medium text-[#2457C5] hover:underline">All orders</Link>}>
      {loading && <div className="p-4"><Skeleton rows={2} /></div>}
      {!loading && pos.length === 0 && <div className="border-t border-[#EDEFF2] px-4 py-6 text-center text-[13px] text-[#66707A] md:px-5">No orders on the way.</div>}
      {pos.length > 0 && (
        <table className="w-full border-t border-[#EDEFF2] text-[14px]">
          <thead className="bg-[#F8F9FA]"><tr><th className={th}>Supplier</th><th className={cn(thNum, 'hidden sm:table-cell')}>Amount</th><th className={th}>Expected</th><th className={cn(th, 'hidden sm:table-cell')}>Status</th></tr></thead>
          <tbody className="divide-y divide-[#EDEFF2]">
            {pos.map((p) => (
              <tr key={p.id} className="cursor-pointer hover:bg-[#F8F9FA]" onClick={() => navigate(`/app/orders/${p.id}`)}>
                <td className={td}><div className="font-medium">{p.supplier}</div><div className="text-[12px] text-[#66707A]">{p.number} · {nextAction(p)?.label ?? ''}</div></td>
                <td className={cn(tdNum, 'hidden sm:table-cell')}>{money(p.estimated_total, p.currency)}</td>
                <td className={td}>{p.expected_at ? <>{day(p.expected_at)}{p.expected_source === 'lead_time' && <div className="text-[11px] text-[#66707A]">estimate</div>}</> : <span className="text-[13px] text-[#66707A]">no date yet</span>}</td>
                <td className={cn(td, 'hidden sm:table-cell')}><StatusChip status={p.status} /></td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </Panel>
  );
}
