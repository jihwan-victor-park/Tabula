// Inventory: a fast list (search, filter, sort) with Scan as the main action. Opening an item shows its
// details in a side panel over the list — barcode, suppliers and cost, sales, expected stock, changes.

import { useQuery } from '@tanstack/react-query';
import { useEffect, useMemo, useState } from 'react';
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom';
import { SymbolIcon, cn } from '../components/ui';
import { api, loadSession } from '../ops/api';
import {
  ButtonLink, EmptyState, ErrorBox, Freshness, Notice, OpsShell, Panel, RequireSession, Skeleton, StatusChip, ago, day, daysUntil,
  inputCls, money, num, td, tdNum, th, thNum, when,
} from '../ops/kit';
import { DailyBars, StockLine } from './Charts';
import type { History, Overview, StockRow } from './types';

type Sort = 'urgency' | 'name' | 'stock';
const FILTERS: { value: string; label: string; match: (r: StockRow) => boolean }[] = [
  { value: 'all', label: 'All items', match: () => true },
  { value: 'low', label: 'Low stock', match: (r) => r.state === 'out_of_stock' || r.state === 'at_risk' },
  { value: 'out_of_stock', label: 'Out of stock', match: (r) => r.state === 'out_of_stock' },
  { value: 'incoming', label: 'On order', match: (r) => Number(r.incoming_confirmed) + Number(r.incoming_unconfirmed) > 0 },
  { value: 'uncounted', label: 'Not counted / old count', match: (r) => !r.stock_counted || r.stale },
];

const useOverview = (loc?: string) => useQuery({ queryKey: ['overview', loc], queryFn: () => api<Overview>(`/stock/overview?location_id=${loc}`), enabled: !!loc });

export function InventoryPage() {
  const loc = loadSession()?.locationId;
  const o = useOverview(loc).data;
  const newest = o?.items.map((i) => i.stock_as_of).filter(Boolean).sort().pop();
  return (
    <OpsShell active="inventory" title="Inventory" subtitle={o ? `${o.items.length} items${newest ? ` · stock updated ${ago(newest)}` : ''}` : undefined}
      actions={<ButtonLink to="/app/inventory/scan" size="lg"><SymbolIcon icon="barcode_scanner" family="rounded" className="text-[19px]" />Scan</ButtonLink>}>
      <RequireSession><InventoryList /><ItemPanel /></RequireSession>
    </OpsShell>
  );
}

/** Kept for links to /app/inventory/:id — the list with that item's panel open. */
export const ItemPage = InventoryPage;

function InventoryList() {
  const loc = loadSession()!.locationId!;
  const navigate = useNavigate();
  const { id } = useParams();
  const [params, setParams] = useSearchParams();
  const [q, setQ] = useState('');
  const [sort, setSort] = useState<Sort>('urgency');
  const filter = FILTERS.find((f) => f.value === (params.get('state') ?? 'all')) ?? FILTERS[0];
  const overview = useOverview(loc);
  const o = overview.data;
  const rows = useMemo(() => {
    let r = (o?.items ?? []).filter(filter.match);
    if (q.trim()) {
      const t = q.trim().toLowerCase();
      r = r.filter((i) => i.name.toLowerCase().includes(t) || i.sku.toLowerCase().includes(t) || (i.barcode ?? '').includes(t));
    }
    const n = (v: string | null, d = Infinity) => (v == null ? d : Number(v));
    return [...r].sort((a, b) => sort === 'name' ? a.name.localeCompare(b.name) : sort === 'stock' ? n(a.on_hand) - n(b.on_hand) : 0);
  }, [o, filter, q, sort]);
  const owner = o?.stock_owner && o.stock_owner !== 'tabula' ? (o.stock_owner === 'square' ? 'Square' : 'your POS') : null;
  const open = (r: StockRow) => navigate(`/app/inventory/${r.variant_id}${params.toString() ? `?${params}` : ''}`);

  return (
    <>
      {owner && <Notice tone="info"><b>Stock is kept in {owner}.</b> Tabula reads it on each sync and never changes it — adjust stock there.</Notice>}
      <Panel padded={false}>
        <div className="flex flex-wrap items-center gap-2 p-3 md:px-5">
          <div className="relative min-w-[200px] flex-1">
            <SymbolIcon icon="search" family="rounded" className="absolute left-2.5 top-1/2 -translate-y-1/2 text-[19px] text-[#9AA3AC]" />
            <input className={`${inputCls} w-full pl-9`} placeholder="Search name, SKU or barcode" value={q} onChange={(e) => setQ(e.target.value)} aria-label="Search inventory" />
          </div>
          <select className={cn(inputCls, 'flex-1 sm:flex-none')} value={filter.value} onChange={(e) => setParams(e.target.value === 'all' ? {} : { state: e.target.value })} aria-label="Filter">
            {FILTERS.map((f) => <option key={f.value} value={f.value}>{f.label} ({o?.items.filter(f.match).length ?? 0})</option>)}
          </select>
          <select className={cn(inputCls, 'flex-1 sm:flex-none')} value={sort} onChange={(e) => setSort(e.target.value as Sort)} aria-label="Sort">
            <option value="urgency">Most urgent first</option><option value="stock">Lowest stock first</option><option value="name">Name A–Z</option>
          </select>
        </div>
        {overview.isLoading && <div className="px-5 pb-5"><Skeleton rows={6} /></div>}
        <div className="px-4"><ErrorBox error={overview.error} onRetry={() => overview.refetch()} /></div>
        {o && o.items.length === 0 && <EmptyState icon="inventory_2" title="No items yet" body="Import a stock file to see your inventory here."><ButtonLink to="/app/settings/data/import?kind=inventory">Import stock</ButtonLink></EmptyState>}
        {o && o.items.length > 0 && rows.length === 0 && <EmptyState icon="search_off" compact title="Nothing matches" body="Try another search or filter." />}
        {rows.length > 0 && <>
          <table className="hidden w-full border-t border-[#EDEFF2] text-[14px] md:table">
            <thead className="bg-[#F8F9FA]"><tr>
              <th className={th}>Item</th><th className={thNum}>Sellable</th><th className={thNum}>Incoming</th><th className={th}>Runs out</th><th className={th}>Status</th>
            </tr></thead>
            <tbody className="divide-y divide-[#EDEFF2]">
              {rows.map((r) => (
                <tr key={r.variant_id} onClick={() => open(r)} className={cn('cursor-pointer hover:bg-[#F8F9FA]', id === r.variant_id && 'bg-[#F3F6FC]')}>
                  <td className={td}><div className="font-medium">{r.name}</div><div className="text-[12px] text-[#66707A]">{r.sku}</div></td>
                  <td className={tdNum}><span className="font-semibold">{num(r.on_hand)}</span>
                    {(r.stale || !r.stock_counted) && r.stock_as_of && <div className="text-[11px] font-medium text-[#A15C07]">{r.stock_counted ? 'old count' : 'not counted'}</div>}</td>
                  <td className={tdNum}><Incoming r={r} /></td>
                  <td className={td}><RunsOut r={r} /></td>
                  <td className={td}><StatusChip status={r.state} /></td>
                </tr>
              ))}
            </tbody>
          </table>
          <ul className="divide-y divide-[#EDEFF2] border-t border-[#EDEFF2] md:hidden">
            {rows.map((r) => (
              <li key={r.variant_id}><button onClick={() => open(r)} className="flex w-full items-center justify-between gap-3 px-4 py-3 text-left">
                <span className="min-w-0"><span className="block truncate font-medium">{r.name}</span>
                  <span className="mt-0.5 block"><StatusChip status={r.state} /></span></span>
                <span className="text-right"><span className="block text-[17px] font-semibold tabular-nums">{num(r.on_hand)}</span><span className="text-[12px]"><RunsOut r={r} /></span></span>
              </button></li>
            ))}
          </ul>
        </>}
      </Panel>
    </>
  );
}

function Incoming({ r }: { r: StockRow }) {
  const c = Number(r.incoming_confirmed), u = Number(r.incoming_unconfirmed);
  if (!c && !u) return <span className="text-[#9AA3AC]">—</span>;
  return <>{c ? num(c) : ''}{u ? <div className="text-[11px] text-[#A15C07]">{num(u)} not confirmed</div> : null}</>;
}

function RunsOut({ r }: { r: StockRow }) {
  if (r.state === 'out_of_stock') return <span className="font-medium text-[#B42318]">Out now</span>;
  if (!r.stockout_date) return <span className="text-[13px] text-[#66707A]">{r.daily_demand ? 'not within 3 weeks' : '—'}</span>;
  const d = daysUntil(r.stockout_date) ?? 0;
  return <span className={cn('whitespace-nowrap', r.state === 'at_risk' && 'font-medium text-[#A15C07]')}>{day(r.stockout_date)} <span className="text-[12px] font-normal text-[#66707A]">{d <= 0 ? 'today' : `in ${d}d`}</span></span>;
}

const REASON: Record<string, string> = { count: 'Counted', adjustment: 'Adjusted', damage: 'Damaged', receipt: 'Received', return: 'Returned', transfer: 'Transfer' };

/** The selected item, in a side panel over the list (full screen on phones). */
function ItemPanel() {
  const { id } = useParams();
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const loc = loadSession()!.locationId!;
  const overview = useOverview(loc);
  const history = useQuery({ queryKey: ['history', id, loc], queryFn: () => api<History>(`/items/${id}/history?location_id=${loc}&days=42`), enabled: !!id });
  const close = () => navigate(`/app/inventory${params.toString() ? `?${params}` : ''}`);
  useEffect(() => {
    if (!id) return;
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') close(); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [id]); // eslint-disable-line react-hooks/exhaustive-deps
  if (!id) return null;
  const r = overview.data?.items.find((i) => i.variant_id === id);
  const h = history.data;
  const readOnly = overview.data && overview.data.stock_owner !== 'tabula';
  return (
    <>
      <div className="fixed inset-0 z-40 bg-[#14181D]/20" onClick={close} aria-hidden="true" />
      <aside role="dialog" aria-label={r?.name ?? 'Item'} className="fixed inset-y-0 right-0 z-50 flex w-full max-w-[540px] flex-col border-l border-[#E2E5E9] bg-white">
        <div className="flex items-start justify-between gap-3 border-b border-[#EDEFF2] px-5 py-4">
          <div className="min-w-0">
            <h2 className="text-[17px] font-semibold leading-snug">{r?.name ?? '…'}</h2>
            <div className="text-[12px] text-[#66707A]">{r?.sku}{r?.barcode ? ` · barcode ${r.barcode}` : ' · no barcode'}</div>
          </div>
          <button onClick={close} aria-label="Close" className="flex h-8 w-8 items-center justify-center rounded-[6px] text-[#3B444D] hover:bg-[#F0F2F4]"><SymbolIcon icon="close" family="rounded" className="text-[20px]" /></button>
        </div>
        <div className="flex-1 overflow-y-auto px-5 py-4">
          <ErrorBox error={overview.error ?? history.error} />
          {!r && <Skeleton rows={5} />}
          {r && <>
            <div className="grid grid-cols-2 gap-x-4 gap-y-3 sm:grid-cols-4">
              <Fact label="Sellable" value={num(r.on_hand)} sub={<Freshness at={r.stock_as_of} stale={r.stale} estimated={r.estimated} counted={r.stock_counted} source={r.stock_source} />} />
              <Fact label="Sells / day" value={num(r.daily_demand)} sub={r.history_days ? `${r.history_days} days of sales` : 'no sales data'} />
              <Fact label="Runs out" value={<RunsOut r={r} />} sub="if nothing arrives" />
              <Fact label="Incoming" value={num(Number(r.incoming_confirmed) + Number(r.incoming_unconfirmed))} sub={Number(r.incoming_unconfirmed) ? `${num(r.incoming_unconfirmed)} not confirmed` : ' '} />
            </div>
            <div className="mt-4 flex flex-wrap gap-2">
              {!readOnly && <ButtonLink to={`/app/inventory/scan?code=${encodeURIComponent(r.barcode ?? r.sku)}`} variant="secondary" size="sm"><SymbolIcon icon="edit" family="rounded" className="text-[16px]" />Adjust or count</ButtonLink>}
              {r.reorder && !r.reorder.on_draft && <ButtonLink to="/app/orders/plan" size="sm">Reorder {num(r.reorder.qty)} {r.reorder.uom ?? ''}</ButtonLink>}
              {r.reorder?.on_draft && <Link to="/app/orders" className="self-center text-[13px] text-[#2457C5] hover:underline">On draft {r.reorder.on_draft}</Link>}
            </div>

            <Section title="Suppliers and cost">
              {h && h.suppliers.length === 0 && <div className="text-[13px] text-[#66707A]">No supplier sells this item yet. <Link to="/app/orders/suppliers" className="text-[#2457C5] hover:underline">Add one</Link></div>}
              <ul className="flex flex-col divide-y divide-[#EDEFF2]">
                {h?.suppliers.map((sp) => (
                  <li key={sp.supplier + sp.supplier_sku} className="flex justify-between gap-3 py-2 text-[13px]">
                    <span><span className="font-medium">{sp.supplier}</span><span className="block text-[12px] text-[#66707A]">SKU {sp.supplier_sku} · {sp.order_uom} of {num(sp.units_per_order_uom)}{sp.lead_time_days != null ? ` · ${sp.lead_time_days}-day lead time` : ''}</span></span>
                    <span className="text-right tabular-nums">{sp.price ? <><b>{money(sp.price.amount, sp.price.currency)}</b> <span className="text-[12px] text-[#66707A]">/ {sp.price.per}</span>
                      <span className="block text-[12px] text-[#66707A]">{money(Number(sp.price.amount) / Math.max(Number(sp.price.units_per), 1), sp.price.currency)} each</span></> : <span className="text-[#B42318]">no price</span>}</span>
                  </li>
                ))}
              </ul>
            </Section>

            <Section title="Daily sales" sub="last 6 weeks">{h ? <DailyBars data={h.sales} height={120} /> : <Skeleton rows={2} />}</Section>
            <Section title="Expected stock" sub="next 3 weeks">
              {h && h.projection.length > 0 ? <StockLine points={h.projection.map((p) => ({ label: day(p.date), value: Number(p.start), short: Number(p.short) > 0 }))} />
                : <div className="text-[13px] text-[#66707A]">Needs a stock count and sales history.</div>}
            </Section>
            <Section title="Changes">
              {h?.movements.length === 0 && <div className="text-[13px] text-[#66707A]">No changes recorded in Tabula{readOnly ? ' — this store\'s stock is kept in the POS' : ''}.</div>}
              <ul className="flex flex-col divide-y divide-[#EDEFF2]">
                {h?.movements.slice(0, 12).map((m) => (
                  <li key={m.id} className="flex items-start justify-between gap-3 py-2 text-[13px]">
                    <span><span className="font-medium">{m.undo_of ? 'Undone' : REASON[m.reason] ?? m.reason}</span>
                      <span className="block text-[12px] text-[#66707A]">{when(m.at)}{m.by ? ` · ${m.by}` : ''}{m.note ? ` · ${m.note}` : ''}</span></span>
                    <span className={cn('font-semibold tabular-nums', Number(m.delta) < 0 ? 'text-[#B42318]' : Number(m.delta) > 0 ? 'text-[#1F7A4D]' : 'text-[#66707A]')}>{Number(m.delta) > 0 ? '+' : ''}{num(m.delta)}</span>
                  </li>
                ))}
              </ul>
              {h && h.pos_readings.length > 0 && <div className="mt-2 text-[12px] text-[#66707A]">POS readings: {h.pos_readings.slice(0, 5).map((p) => `${num(p.qty)} (${when(p.at)})`).join(' · ')}</div>}
            </Section>
            <Section title="Orders">
              {h?.orders.length === 0 && <div className="text-[13px] text-[#66707A]">Nothing on order.</div>}
              <ul className="flex flex-col divide-y divide-[#EDEFF2]">
                {h?.orders.map((o) => (
                  <li key={o.po_id}><Link to={`/app/orders/${o.po_id}`} className="flex flex-wrap items-center justify-between gap-2 py-2 text-[13px] hover:underline">
                    <span>{o.number} · {num(o.ordered)} {o.unit}{o.eta ? ` · expected ${day(o.eta)}` : ''}</span><StatusChip status={o.status} /></Link></li>
                ))}
              </ul>
            </Section>
          </>}
        </div>
      </aside>
    </>
  );
}

function Fact({ label, value, sub }: { label: string; value: React.ReactNode; sub?: React.ReactNode }) {
  return <div><div className="text-[12px] text-[#66707A]">{label}</div><div className="text-[18px] font-semibold tabular-nums leading-tight">{value}</div><div className="text-[12px] text-[#66707A]">{sub}</div></div>;
}

function Section({ title, sub, children }: { title: string; sub?: string; children: React.ReactNode }) {
  return <section className="mt-6"><h3 className="mb-2 text-[13px] font-semibold">{title}{sub && <span className="ml-1.5 font-normal text-[#66707A]">{sub}</span>}</h3>{children}</section>;
}
