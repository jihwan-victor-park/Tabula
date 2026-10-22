// Inventory list (search, filter, sort; cards on phones) and one item's detail.

import { useQuery } from '@tanstack/react-query';
import { useMemo, useState } from 'react';
import { Link, useParams, useSearchParams } from 'react-router-dom';
import { SymbolIcon, cn } from '../components/ui';
import { api, loadSession } from '../ops/api';
import { Button, EmptyState, ErrorBox, Freshness, Notice, OpsShell, Panel, RequireSession, Skeleton, StatusChip, Tabs, day, inputCls, num, when } from '../ops/kit';
import { DailyBars, StockLine } from './Charts';
import type { History, Overview, StockRow } from './types';

type Sort = 'urgency' | 'name' | 'stock' | 'cover';

export function InventoryPage() {
  return <OpsShell active="inventory" title="Inventory" actions={<Link to="/app/scan"><Button variant="secondary"><SymbolIcon icon="barcode_scanner" family="rounded" className="text-[18px]" />Scan</Button></Link>}>
    <RequireSession><InventoryList /></RequireSession></OpsShell>;
}

function InventoryList() {
  const loc = loadSession()!.locationId!;
  const [params, setParams] = useSearchParams();
  const [q, setQ] = useState('');
  const [sort, setSort] = useState<Sort>('urgency');
  const state = params.get('state') ?? 'all';
  const overview = useQuery({ queryKey: ['overview', loc], queryFn: () => api<Overview>(`/stock/overview?location_id=${loc}`) });
  const rows = useMemo(() => {
    let r = overview.data?.items ?? [];
    if (state !== 'all') r = r.filter((i) => i.state === state);
    if (q.trim()) {
      const t = q.trim().toLowerCase();
      r = r.filter((i) => i.name.toLowerCase().includes(t) || i.sku.toLowerCase().includes(t) || (i.barcode ?? '').includes(t));
    }
    const n = (v: string | null, d = Infinity) => (v == null ? d : Number(v));
    return [...r].sort((a, b) => sort === 'name' ? a.name.localeCompare(b.name) : sort === 'stock' ? n(a.on_hand) - n(b.on_hand)
      : sort === 'cover' ? n(a.days_of_cover) - n(b.days_of_cover) : 0);
  }, [overview.data, state, q, sort]);
  const o = overview.data;
  const stale = o?.items.filter((i) => i.stale && i.stock_as_of).length ?? 0;
  return (
    <>
      {o?.stock_owner && o.stock_owner !== 'tabula' && (
        <Notice tone="info"><b>Stock comes from {o.stock_owner === 'square' ? 'Square' : o.stock_owner}.</b> Tabula reads it on each sync and doesn't change it — adjust stock in {o.stock_owner === 'square' ? 'Square' : 'your POS'}.</Notice>
      )}
      {stale > 0 && <Notice>{stale} item{stale > 1 ? 's were' : ' was'} last counted more than a day ago — those numbers are estimates (count minus sales since). <Link className="font-semibold underline" to="/app/scan">Count by scanning</Link> or upload a new stock count.</Notice>}
      <Panel padded={false}>
        <div className="flex flex-wrap items-center gap-3 p-4 md:p-5">
          <div className="relative min-w-[220px] flex-1">
            <SymbolIcon icon="search" family="rounded" className="absolute left-3 top-1/2 -translate-y-1/2 text-[20px] text-[#9AA6AD]" />
            <input className={`${inputCls} w-full pl-10`} placeholder="Search name, SKU or barcode" value={q} onChange={(e) => setQ(e.target.value)} aria-label="Search inventory" />
          </div>
          <select className={inputCls} value={state} onChange={(e) => setParams(e.target.value === 'all' ? {} : { state: e.target.value })} aria-label="Filter">
            <option value="all">All items ({o?.items.length ?? 0})</option>
            <option value="out_of_stock">Out of stock ({o?.counts.out_of_stock ?? 0})</option>
            <option value="at_risk">Runs out within 7 days ({o?.counts.at_risk ?? 0})</option>
            <option value="ok">In stock ({o?.counts.ok ?? 0})</option>
            <option value="no_sales_data">No sales data ({o?.counts.no_sales_data ?? 0})</option>
            <option value="no_stock_data">Not counted ({o?.counts.no_stock_data ?? 0})</option>
          </select>
          <Tabs value={sort} onChange={setSort} items={[{ value: 'urgency', label: 'Urgent first' }, { value: 'cover', label: 'Days left' }, { value: 'stock', label: 'Stock' }, { value: 'name', label: 'A–Z' }]} />
        </div>
        {overview.isLoading && <div className="px-5 pb-5"><Skeleton rows={6} /></div>}
        <div className="px-5"><ErrorBox error={overview.error} onRetry={() => overview.refetch()} /></div>
        {o && o.items.length === 0 && <EmptyState icon="inventory_2" title="No items yet" body="Import a stock file to see your inventory here."><Link to="/app/data"><Button>Import stock</Button></Link></EmptyState>}
        {o && o.items.length > 0 && rows.length === 0 && <EmptyState icon="search_off" title="Nothing matches" body="Try another search or filter." />}
        {rows.length > 0 && <>
          <table className="hidden w-full text-[14px] md:table">
            <thead><tr className="border-y border-[#F1EBE4] bg-[#FBF8F5] text-left text-[12px] font-semibold uppercase tracking-wide text-[#5E6E78]">
              <th className="py-2.5 pl-6">Item</th><th>Status</th><th className="text-right">Sellable</th><th className="text-right">Incoming</th>
              <th className="text-right">Sells / day</th><th className="text-right">Runs out</th><th className="pr-6 text-right">Stock as of</th>
            </tr></thead>
            <tbody>{rows.map((r) => <Row key={r.variant_id} r={r} />)}</tbody>
          </table>
          <ul className="divide-y divide-[#F1EBE4] border-t border-[#F1EBE4] md:hidden">{rows.map((r) => <Card key={r.variant_id} r={r} />)}</ul>
        </>}
      </Panel>
    </>
  );
}

function incoming(r: StockRow) {
  const c = Number(r.incoming_confirmed), u = Number(r.incoming_unconfirmed);
  if (!c && !u) return '—';
  return <>{c ? num(c) : ''}{u ? <span className="text-[#A86A12]">{c ? ' + ' : ''}{num(u)} unconfirmed</span> : ''}</>;
}

function Row({ r }: { r: StockRow }) {
  return (
    <tr className="border-b border-[#F1EBE4] hover:bg-[#FBF8F5]">
      <td className="py-3 pl-6"><Link to={`/app/inventory/${r.variant_id}`} className="block"><span className="block font-semibold">{r.name}</span>
        <span className="text-[12px] text-[#5E6E78]">{r.sku}{r.barcode ? ` · ${r.barcode}` : ''}</span></Link></td>
      <td><StatusChip status={r.state} /></td>
      <td className="text-right text-[16px] font-bold">{num(r.on_hand)}</td>
      <td className="text-right">{incoming(r)}</td>
      <td className="text-right">{num(r.daily_demand)}</td>
      <td className={cn('text-right', r.state === 'at_risk' && 'font-semibold text-[#A86A12]', r.state === 'out_of_stock' && 'font-semibold text-[#B93A26]')}>
        {r.state === 'out_of_stock' ? 'Now' : r.stockout_date ? day(r.stockout_date) : r.days_of_cover ? `~${Math.floor(Number(r.days_of_cover))} days` : '—'}</td>
      <td className="pr-6 text-right"><Freshness at={r.stock_as_of} stale={r.stale} estimated={r.estimated} counted={r.stock_counted} source={r.stock_source} /></td>
    </tr>
  );
}

function Card({ r }: { r: StockRow }) {
  return (
    <li><Link to={`/app/inventory/${r.variant_id}`} className="flex items-center justify-between gap-3 px-4 py-3">
      <span className="min-w-0"><span className="block truncate font-semibold">{r.name}</span>
        <span className="block text-[12px] text-[#5E6E78]">{r.sku} · <Freshness at={r.stock_as_of} stale={r.stale} estimated={r.estimated} counted={r.stock_counted} /></span>
        <span className="mt-1 block"><StatusChip status={r.state} /></span></span>
      <span className="text-right"><span className="block text-[20px] font-bold">{num(r.on_hand)}</span>
        <span className="text-[12px] text-[#5E6E78]">{r.stockout_date ? `out ${day(r.stockout_date)}` : r.daily_demand ? `${num(r.daily_demand)}/day` : ''}</span></span>
    </Link></li>
  );
}

const REASON: Record<string, string> = { count: 'Counted', adjustment: 'Adjusted', damage: 'Damaged', receipt: 'Received', return: 'Returned', transfer: 'Transfer' };

export function ItemPage() {
  const { id } = useParams();
  const loc = loadSession()?.locationId;
  const overview = useQuery({ queryKey: ['overview', loc], queryFn: () => api<Overview>(`/stock/overview?location_id=${loc}`), enabled: !!loc });
  const history = useQuery({ queryKey: ['history', id, loc], queryFn: () => api<History>(`/items/${id}/history?location_id=${loc}&days=42`), enabled: !!loc });
  const r = overview.data?.items.find((i) => i.variant_id === id);
  return (
    <OpsShell active="inventory" title={r?.name ?? 'Item'} subtitle={r ? `${r.sku}${r.barcode ? ` · barcode ${r.barcode}` : ''}` : undefined}
      actions={<Link to="/app/inventory" className="text-[14px] font-semibold text-[#5E6E78]">← Inventory</Link>}>
      <RequireSession>
        <ErrorBox error={overview.error ?? history.error} />
        {!r && overview.isLoading && <Skeleton rows={4} />}
        {r && (
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
            <div className="rounded-[16px] border border-[#E8E0D8] bg-white px-5 py-4"><div className="text-[13px] text-[#5E6E78]">Sellable now</div>
              <div className="text-[28px] font-bold">{num(r.on_hand)}</div><Freshness at={r.stock_as_of} stale={r.stale} estimated={r.estimated} counted={r.stock_counted} source={r.stock_source} /></div>
            <div className="rounded-[16px] border border-[#E8E0D8] bg-white px-5 py-4"><div className="text-[13px] text-[#5E6E78]">Sells per day</div>
              <div className="text-[28px] font-bold">{num(r.daily_demand)}</div><span className="text-[12px] text-[#5E6E78]">{r.history_days ? `from ${r.history_days} days of sales` : 'no sales data'}</span></div>
            <div className="rounded-[16px] border border-[#E8E0D8] bg-white px-5 py-4"><div className="text-[13px] text-[#5E6E78]">Runs out</div>
              <div className={cn('text-[28px] font-bold', r.state === 'at_risk' && 'text-[#A86A12]', r.state === 'out_of_stock' && 'text-[#B93A26]')}>{r.state === 'out_of_stock' ? 'Now' : r.stockout_date ? day(r.stockout_date) : '—'}</div>
              <span className="text-[12px] text-[#5E6E78]">if nothing new arrives</span></div>
            <div className="rounded-[16px] border border-[#E8E0D8] bg-white px-5 py-4"><div className="text-[13px] text-[#5E6E78]">Incoming</div>
              <div className="text-[28px] font-bold">{num(Number(r.incoming_confirmed) + Number(r.incoming_unconfirmed))}</div>
              <span className="text-[12px] text-[#5E6E78]">{Number(r.incoming_unconfirmed) ? `${num(r.incoming_unconfirmed)} not confirmed by supplier` : 'confirmed'}</span></div>
          </div>
        )}
        <div className="grid gap-5 lg:grid-cols-2">
          <Panel title="Daily sales (6 weeks)">{history.data ? <DailyBars data={history.data.sales} /> : <Skeleton rows={3} />}</Panel>
          <Panel title="Expected stock (3 weeks)" aside={<span className="text-[12px] text-[#5E6E78]">red = runs short</span>}>
            {history.data && history.data.projection.length > 0 ? <StockLine points={history.data.projection.map((p) => ({ label: day(p.date), value: Number(p.start), short: Number(p.short) > 0 }))} />
              : <div className="py-6 text-[14px] text-[#5E6E78]">Needs a stock count and sales history.</div>}
          </Panel>
        </div>
        <div className="grid gap-5 lg:grid-cols-2">
          <Panel title="Stock changes">
            {history.data?.movements.length === 0 && <div className="text-[14px] text-[#5E6E78]">No changes recorded in Tabula{overview.data?.stock_owner !== 'tabula' ? ' — this store\'s stock is kept in the POS' : ''}.</div>}
            <ul className="flex flex-col divide-y divide-[#F1EBE4]">
              {history.data?.movements.map((m) => (
                <li key={m.id} className="flex items-start justify-between gap-3 py-2 text-[14px]">
                  <span><span className="font-medium">{m.undo_of ? 'Undone' : REASON[m.reason] ?? m.reason}</span>
                    <span className="block text-[12px] text-[#5E6E78]">{when(m.at)}{m.by ? ` · ${m.by}` : ''}{m.note ? ` · ${m.note}` : ''}</span></span>
                  <span className={cn('font-bold', Number(m.delta) < 0 ? 'text-[#B93A26]' : 'text-[#1E7F55]')}>{Number(m.delta) > 0 ? '+' : ''}{num(m.delta)}</span>
                </li>
              ))}
            </ul>
            {history.data && history.data.pos_readings.length > 0 && (
              <div className="mt-3 text-[13px] text-[#5E6E78]">POS stock readings: {history.data.pos_readings.slice(0, 5).map((p) => `${num(p.qty)} (${when(p.at)})`).join(' · ')}</div>
            )}
          </Panel>
          <Panel title="Orders for this item">
            {history.data?.orders.length === 0 && <div className="text-[14px] text-[#5E6E78]">Nothing on order.</div>}
            <ul className="flex flex-col divide-y divide-[#F1EBE4]">
              {history.data?.orders.map((o) => (
                <li key={o.po_id}><Link to={`/app/orders/${o.po_id}`} className="flex flex-wrap items-center justify-between gap-2 py-2 text-[14px]">
                  <span>{o.number} · {num(o.ordered)} {o.unit}{o.eta ? ` · expected ${day(o.eta)}` : ''}</span><StatusChip status={o.status} /></Link></li>
              ))}
            </ul>
          </Panel>
        </div>
      </RequireSession>
    </OpsShell>
  );
}
