// Orders: run the order analysis (the existing plan engine), adjust quantities, create drafts
// per supplier, then the existing approval → supplier reply → receiving flow.

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Fragment, useEffect, useMemo, useState, type ReactNode } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { SymbolIcon, cn } from '../components/ui';
import { api, loadSession, type PlanLine, type PoSummary, type Recommendations } from '../ops/api';
import { Button, EmptyState, ErrorBox, Notice, OpsShell, Panel, RequireSession, Skeleton, StatusChip, day, money, num, when } from '../ops/kit';
import { OpenOrderLinks } from '../ops/Attention';
import { LineDetail } from '../ops/TodayPage';
import type { Overview, Readiness } from './types';

function OrdersTabs({ active }: { active: 'suggestions' | 'list' | 'receiving' }) {
  const tab = (key: typeof active, to: string, label: string) => (
    <Link to={to} className={cn('rounded-[9px] px-3 py-1.5 text-[13px] font-semibold', active === key ? 'bg-white shadow-sm' : 'text-[#5E6E78]')}>{label}</Link>
  );
  return <div className="inline-flex rounded-[12px] bg-[#EFE9E2] p-1">{tab('suggestions', '/app/orders', 'Suggestions')}{tab('list', '/app/orders/list', 'Purchase orders')}{tab('receiving', '/app/receiving', 'Receiving')}</div>;
}

export function OrdersShell({ active, title, children, actions }: { active: 'suggestions' | 'list' | 'receiving'; title: string; children: ReactNode; actions?: ReactNode }) {
  return <OpsShell active="orders" title={title} actions={<><OrdersTabs active={active} />{actions}</>}><RequireSession>{children}</RequireSession></OpsShell>;
}

const STALE: Record<string, string> = {
  no_plan_yet: 'No analysis has been run yet.', inputs_changed: 'Stock, sales or orders changed since the last analysis.',
  updates_in_progress: 'A file or sync is still being imported.', older_than_24h: 'The last analysis is more than a day old.',
};

export function SuggestionsPage() {
  return <OrdersShell active="suggestions" title="Order suggestions"><Suggestions /></OrdersShell>;
}

function Suggestions() {
  const s = loadSession()!;
  const loc = s.locationId!;
  const qc = useQueryClient();
  const navigate = useNavigate();
  const rec = useQuery({ queryKey: ['recommendations', loc], queryFn: () => api<Recommendations>(`/recommendations?location_id=${loc}`) });
  const overview = useQuery({ queryKey: ['overview', loc], queryFn: () => api<Overview>(`/stock/overview?location_id=${loc}`) });
  const names = Object.fromEntries((overview.data?.items ?? []).map((i) => [i.variant_id, i.name]));
  const readiness = useQuery({ queryKey: ['readiness', loc], queryFn: () => api<Readiness>(`/readiness?location_id=${loc}`) });
  const run = useMutation({ mutationFn: () => api('/replenishment-runs', { body: { location_id: loc } }), onSuccess: () => qc.invalidateQueries({ queryKey: ['recommendations', loc] }) });
  const plan = rec.data?.run;
  const lines = plan?.lines ?? [];
  const orderLines = lines.filter((l) => l.status === 'order' && !l.open_po);
  const [qty, setQty] = useState<Record<string, string>>({});
  const [skip, setSkip] = useState<Set<string>>(new Set());
  const [open, setOpen] = useState<string | null>(null);
  useEffect(() => { setQty(Object.fromEntries(orderLines.map((l) => [l.variant_id, l.order_qty]))); setSkip(new Set()); }, [plan?.id]); // eslint-disable-line react-hooks/exhaustive-deps
  const chosen = orderLines.filter((l) => !skip.has(l.variant_id) && Number(qty[l.variant_id] ?? 0) > 0);
  const cost = (l: PlanLine) => (Number(qty[l.variant_id] ?? 0) * Number(l.line_cost ?? 0)) / Math.max(Number(l.order_qty), 1);
  const bySupplier = useMemo(() => {
    const m = new Map<string, { lines: PlanLine[]; total: number; ccy: string | null }>();
    for (const l of chosen) {
      const k = l.supplier ?? '—';
      const e = m.get(k) ?? { lines: [], total: 0, ccy: l.currency };
      e.lines.push(l); e.total += cost(l); m.set(k, e);
    }
    return m;
  }, [chosen, qty]); // eslint-disable-line react-hooks/exhaustive-deps
  const draft = useMutation({
    mutationFn: () => api<PoSummary[]>('/purchase-orders/from-run', { body: {
      run_id: plan!.id, variant_ids: chosen.map((l) => l.variant_id),
      quantities: Object.fromEntries(chosen.map((l) => [l.variant_id, qty[l.variant_id]])) } }),
    onSuccess: (pos) => { qc.invalidateQueries({ queryKey: ['pos'] }); navigate(pos.length === 1 ? `/app/orders/${pos[0].id}` : '/app/orders/list'); },
  });
  const suggestions = readiness.data?.features.find((f) => f.key === 'suggestions');
  const orders = readiness.data?.features.find((f) => f.key === 'orders');

  return (
    <>
      <Panel>
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <div className="text-[16px] font-semibold">{plan ? 'Order analysis' : 'Run an order analysis'}</div>
            <div className="text-[13px] text-[#5E6E78]">{plan ? <>Based on stock, sales, open orders and supplier terms as of {when(plan.cutoff)}.</> :
              'Tabula looks at stock, recent sales, what is already on order and each supplier’s lead time and pack size.'}</div>
          </div>
          <Button onClick={() => run.mutate()} loading={run.isPending} variant={!plan || rec.data?.stale ? 'primary' : 'secondary'} size="lg">
            <SymbolIcon icon="calculate" family="rounded" className="text-[20px]" />{plan ? 'Run again' : 'Run order analysis'}</Button>
        </div>
        {rec.data?.stale && plan && <div className="mt-3"><Notice><b>These numbers may be out of date.</b> {rec.data.stale_reasons.map((r) => STALE[r] ?? 'New data arrived since.').join(' ')} Run the analysis again before ordering.</Notice></div>}
        <div className="mt-3"><ErrorBox error={run.error ?? rec.error} /></div>
      </Panel>
      {suggestions && !suggestions.ready && <Notice><b>Suggestions are limited:</b> needs {suggestions.missing.map((m) => m.what).join(', ')}. {suggestions.partial} <Link className="font-semibold underline" to="/app/data">Add data</Link></Notice>}
      {orders && !orders.ready && <Notice tone="info"><b>To turn suggestions into orders</b> you still need {orders.missing.map((m) => m.what).join(', ')}. <Link className="font-semibold underline" to={orders.missing.some((m) => m.what.includes('address')) && orders.missing.length === 1 ? '/app/settings' : '/app/suppliers'}>Set it up</Link></Notice>}
      <OpenOrderLinks locationId={loc} />
      {rec.isLoading && <Skeleton rows={5} />}
      {plan && (
        <>
          <div className="grid gap-5 lg:grid-cols-[1fr_320px]">
            <Panel padded={false} title={<>Suggested orders <span className="text-[13px] font-normal text-[#5E6E78]">· {orderLines.length} item{orderLines.length === 1 ? '' : 's'}</span></>}>
              {orderLines.length === 0 && <EmptyState icon="task_alt" title="Nothing needs ordering right now" body="Stock and incoming orders cover the coming days. Items on hold or without a supplier are listed below." />}
              {orderLines.length > 0 && (
                <div className="overflow-x-auto">
                  <table className="w-full min-w-[720px] text-[14px]">
                    <thead><tr className="border-y border-[#F1EBE4] bg-[#FBF8F5] text-left text-[12px] font-semibold uppercase tracking-wide text-[#5E6E78]">
                      <th className="w-10 py-2.5 pl-5" /><th>Item</th><th className="whitespace-nowrap text-right">In stock</th><th className="whitespace-nowrap pl-4 text-right">Sells/day</th>
                      <th className="text-right">Order</th><th className="pl-5">Supplier</th><th className="pr-5 text-right">Cost</th><th className="pr-5" />
                    </tr></thead>
                    <tbody>
                      {orderLines.map((l) => (
                        <Fragment key={l.variant_id}>
                          <tr className={cn('border-b border-[#F1EBE4]', skip.has(l.variant_id) && 'opacity-50')}>
                            <td className="py-3 pl-5"><input type="checkbox" aria-label={`Include ${l.sku}`} checked={!skip.has(l.variant_id)}
                              onChange={(e) => setSkip((x) => { const n = new Set(x); e.target.checked ? n.delete(l.variant_id) : n.add(l.variant_id); return n; })} /></td>
                            <td><span className="block font-semibold">{names[l.variant_id] ?? l.sku}</span><span className="line-clamp-2 text-[12px] text-[#5E6E78]" title={l.reasons[0]?.message}>{l.sku} · {l.reasons[0]?.message ?? `runs out ${l.stockout_days_without_order[0] ? `in ${l.stockout_days_without_order[0]} days` : 'later'}`}</span></td>
                            <td className="text-right">{num(l.on_hand)}</td>
                            <td className="text-right">{num(l.daily_demand)}</td>
                            <td className="text-right"><span className="inline-flex items-center gap-1">
                              <input aria-label={`Quantity for ${l.sku}`} inputMode="decimal" className="w-[64px] rounded-[8px] border border-[#DCD2C8] px-2 py-1 text-right font-semibold"
                                value={qty[l.variant_id] ?? ''} onChange={(e) => setQty((q) => ({ ...q, [l.variant_id]: e.target.value }))} />
                              <span className="text-[12px] text-[#5E6E78]">{l.order_uom}</span></span>
                              <span className="block text-[11px] text-[#5E6E78]">{qty[l.variant_id] !== l.order_qty ? `suggested ${num(l.order_qty)}` : `= ${num(l.base_qty)} units`}</span></td>
                            <td className="pl-5">{l.supplier}</td>
                            <td className="pr-5 text-right font-semibold">{money(cost(l), l.currency)}</td>
                            <td className="pr-5 text-right"><button className="text-[13px] font-semibold text-[#B23F27]" onClick={() => setOpen(open === l.variant_id ? null : l.variant_id)}>{open === l.variant_id ? 'Hide' : 'Why?'}</button></td>
                          </tr>
                          {open === l.variant_id && <tr><td colSpan={8} className="bg-[#FBF8F5] px-5 py-4"><LineDetail line={l} /></td></tr>}
                        </Fragment>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </Panel>
            <Panel title="Your order">
              {chosen.length === 0 && <div className="text-[14px] text-[#5E6E78]">Choose items to order.</div>}
              {[...bySupplier.entries()].map(([supplier, e]) => (
                <div key={supplier} className="mb-3 rounded-[12px] bg-[#F7F3EE] p-3 text-[14px]">
                  <div className="flex justify-between font-semibold"><span>{supplier}</span><span>{money(e.total, e.ccy)}</span></div>
                  <div className="text-[12px] text-[#5E6E78]">{e.lines.length} item{e.lines.length > 1 ? 's' : ''} · items only; shipping and tax confirmed by the supplier</div>
                </div>
              ))}
              {chosen.length > 0 && <Button size="lg" onClick={() => draft.mutate()} loading={draft.isPending} disabled={!!rec.data?.stale}>Create {bySupplier.size} order draft{bySupplier.size > 1 ? 's' : ''}</Button>}
              {rec.data?.stale && chosen.length > 0 && <div className="mt-2 text-[12px] text-[#A86A12]">Run the analysis again first — data changed.</div>}
              <div className="mt-3"><ErrorBox error={draft.error} /></div>
              <p className="mt-3 text-[12px] text-[#5E6E78]">Drafts are not sent. You review each order, the owner approves it, and in test mode it is kept in Tabula instead of being emailed.</p>
            </Panel>
          </div>
          <OtherLines lines={lines.filter((l) => l.status !== 'order' || l.open_po)} />
        </>
      )}
    </>
  );
}

function OtherLines({ lines }: { lines: PlanLine[] }) {
  const [open, setOpen] = useState<string | null>(null);
  const groups: [string, string, PlanLine[]][] = [
    ['on_hold', 'On hold — already ordered', lines.filter((l) => l.status === 'on_hold')],
    ['draft', 'Already in a draft order', lines.filter((l) => l.open_po)],
    ['no_supplier', 'No supplier to order from', lines.filter((l) => l.status === 'no_supplier')],
    ['insufficient_data', 'Not enough data', lines.filter((l) => l.status === 'insufficient_data')],
  ];
  if (!groups.some(([, , g]) => g.length)) return null;
  return (
    <Panel title="Not suggested, and why">
      <div className="flex flex-col gap-4">
        {groups.filter(([, , g]) => g.length).map(([key, title, g]) => (
          <div key={key}>
            <div className="mb-1 text-[13px] font-semibold text-[#5E6E78]">{title} ({g.length})</div>
            <ul className="flex flex-col divide-y divide-[#F1EBE4]">
              {g.map((l) => (
                <li key={l.variant_id} className="py-2 text-[14px]">
                  <div className="flex items-center justify-between gap-2"><span><b>{l.sku}</b> <span className="text-[#5E6E78]">{l.open_po ? `on draft ${l.open_po}` : l.reasons[0]?.message ?? ''}</span></span>
                    <button className="text-[13px] font-semibold text-[#B23F27]" onClick={() => setOpen(open === l.variant_id ? null : l.variant_id)}>{open === l.variant_id ? 'Hide' : 'Details'}</button></div>
                  {open === l.variant_id && <div className="mt-2"><LineDetail line={l} /></div>}
                  {key === 'no_supplier' && <Link to="/app/suppliers" className="text-[12px] font-semibold text-[#B23F27]">Add a supplier for it →</Link>}
                </li>
              ))}
            </ul>
          </div>
        ))}
      </div>
    </Panel>
  );
}

export function OrdersListPage() {
  const s = loadSession();
  const pos = useQuery({ queryKey: ['pos', s?.tenantId], queryFn: () => api<PoSummary[]>('/purchase-orders'), enabled: !!s?.tenantId,
    refetchInterval: (q) => (q.state.data?.some((p) => p.status === 'queued') ? 1500 : false) });
  return (
    <OrdersShell active="list" title="Purchase orders">
      {pos.isLoading && <Skeleton rows={4} />}
      <ErrorBox error={pos.error} onRetry={() => pos.refetch()} />
      {pos.data?.length === 0 && <Panel><EmptyState icon="receipt_long" title="No orders yet" body="Run an order analysis to create your first draft."><Link to="/app/orders"><Button>Order suggestions</Button></Link></EmptyState></Panel>}
      {pos.data && pos.data.length > 0 && (
        <Panel padded={false}>
          <ul className="divide-y divide-[#F1EBE4]">
            {pos.data.map((p) => (
              <li key={p.id}><Link to={`/app/orders/${p.id}`} className="flex flex-wrap items-center justify-between gap-3 px-5 py-4 hover:bg-[#FBF8F5]">
                <span className="min-w-0"><span className="block text-[15px] font-semibold">{p.supplier}</span>
                  <span className="text-[13px] text-[#5E6E78]">{p.number} · {p.lines} item{p.lines > 1 ? 's' : ''} · {money(p.estimated_total, p.currency)} · updated {day(p.updated_at)}</span></span>
                <span className="flex flex-wrap items-center gap-2">{p.open_issues > 0 && <span className="text-[12px] font-semibold text-[#B93A26]">{p.open_issues} issue(s)</span>}<StatusChip status={p.status} /></span>
              </Link></li>
            ))}
          </ul>
        </Panel>
      )}
    </OrdersShell>
  );
}
