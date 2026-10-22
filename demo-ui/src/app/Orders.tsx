// Orders: the reorder plan (the existing plan engine → drafts with the owner's quantities), and every
// purchase order by where it stands — needs review, in progress, done — with suppliers alongside.

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Fragment, useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import { SymbolIcon, cn } from '../components/ui';
import { api, loadSession, type PlanLine, type PoSummary, type Recommendations } from '../ops/api';
import {
  Button, ButtonLink, Disclosure, EmptyState, ErrorBox, Notice, OpsShell, PageTabs, Panel, RequireSession, Skeleton, StatusChip,
  day, daysUntil, money, num, td, tdNum, th, thNum, when, useMe,
} from '../ops/kit';
import { OpenOrderLinks } from '../ops/Attention';
import { LineDetail } from '../ops/TodayPage';
import { nextAction, phase, type Phase } from './orderState';
import type { Overview, Readiness } from './types';

type Section = Phase | 'suppliers';

const usePos = () => {
  const s = loadSession();
  return useQuery({ queryKey: ['pos', s?.tenantId], queryFn: () => api<PoSummary[]>('/purchase-orders'), enabled: !!s?.tenantId,
    refetchInterval: (q) => (q.state.data?.some((p) => p.status === 'queued') ? 1500 : false) });
};

export function OrdersTabs({ active }: { active: Section }) {
  const pos = usePos().data ?? [];
  const count = (k: Phase) => pos.filter((p) => phase(p) === k).length;
  return <PageTabs active={active} items={[
    { key: 'review', label: 'Needs review', to: '/app/orders', count: count('review') },
    { key: 'progress', label: 'In progress', to: '/app/orders?tab=progress', count: count('progress') },
    { key: 'done', label: 'Done', to: '/app/orders?tab=done' },
    { key: 'suppliers', label: 'Suppliers', to: '/app/orders/suppliers' },
  ]} />;
}

/** Orders section frame: the tabs, and the reorder plan as the main way to start an order. */
export function OrdersShell({ active, title = 'Orders', children, actions }: { active: Section; title?: string; children: ReactNode; actions?: ReactNode }) {
  return (
    <OpsShell active="orders" title={title} tabs={<OrdersTabs active={active} />}
      actions={actions ?? <ButtonLink to="/app/orders/plan"><SymbolIcon icon="playlist_add_check" family="rounded" className="text-[19px]" />Review reorder plan</ButtonLink>}>
      <RequireSession>{children}</RequireSession>
    </OpsShell>
  );
}

export function OrdersPage() {
  const [params] = useSearchParams();
  const tab = (params.get('tab') as Phase) || 'review';
  return <OrdersShell active={tab}><OrderList tab={tab} /></OrdersShell>;
}

function OrderList({ tab }: { tab: Phase }) {
  const s = loadSession()!;
  const pos = usePos();
  const me = useMe();
  const role = me.data?.memberships.find((m) => m.tenant_id === s.tenantId)?.role;
  const navigate = useNavigate();
  const rows = (pos.data ?? []).filter((p) => phase(p) === tab);
  const empty: Record<Phase, [string, string]> = {
    review: ['Nothing to review', 'Drafts, approvals and supplier changes appear here. Start from the reorder plan.'],
    progress: ['Nothing on order', 'Approved orders stay here until everything has arrived.'],
    done: ['No finished orders yet', 'Completed and cancelled orders are kept here.'],
  };
  return (
    <>
      {tab === 'review' && <PlanTeaser />}
      {pos.isLoading && <Skeleton rows={4} />}
      <ErrorBox error={pos.error} onRetry={() => pos.refetch()} />
      {pos.data && rows.length === 0 && <Panel><EmptyState icon="receipt_long" compact title={empty[tab][0]} body={empty[tab][1]} /></Panel>}
      {rows.length > 0 && (
        <Panel padded={false}>
          <table className="hidden w-full text-[14px] md:table">
            <thead className="bg-[#F8F9FA]"><tr className="border-b border-[#EDEFF2]">
              <th className={th}>Supplier</th><th className={thNum}>Items</th><th className={thNum}>Amount</th><th className={th}>Status</th>
              <th className={th}>Expected</th><th className={th}>Next step</th>
            </tr></thead>
            <tbody className="divide-y divide-[#EDEFF2]">
              {rows.map((p) => {
                const next = nextAction(p, role);
                const href = next?.to === 'receive' ? `/app/receiving/${p.id}` : `/app/orders/${p.id}`;
                return (
                  <tr key={p.id} className="cursor-pointer hover:bg-[#F8F9FA]" onClick={() => navigate(`/app/orders/${p.id}`)}>
                    <td className={td}><div className="font-medium">{p.supplier}</div><div className="text-[12px] text-[#66707A]">{p.number} · updated {day(p.updated_at)}</div></td>
                    <td className={tdNum}>{p.lines}</td>
                    <td className={tdNum}><span className="font-medium">{money(p.estimated_total, p.currency)}</span></td>
                    <td className={td}><StatusChip status={p.status} />{p.open_issues > 0 && <div className="text-[12px] text-[#B42318]">{p.open_issues} delivery issue{p.open_issues > 1 ? 's' : ''}</div>}</td>
                    <td className={td}><Expected p={p} /></td>
                    <td className={td}>{next && (next.label === 'Sending…' || next.label === 'Waiting for the owner'
                      ? <span className="text-[13px] text-[#66707A]">{next.label}</span>
                      : <Link to={href} onClick={(e) => e.stopPropagation()} className="text-[13px] font-medium text-[#2457C5] hover:underline">{next.label} →</Link>)}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          <ul className="divide-y divide-[#EDEFF2] md:hidden">
            {rows.map((p) => {
              const next = nextAction(p, role);
              return (
                <li key={p.id}><Link to={next?.to === 'receive' ? `/app/receiving/${p.id}` : `/app/orders/${p.id}`} className="block px-4 py-3">
                  <div className="flex items-baseline justify-between gap-3"><span className="font-medium">{p.supplier}</span><span className="font-medium tabular-nums">{money(p.estimated_total, p.currency)}</span></div>
                  <div className="mt-0.5 flex items-center justify-between gap-3 text-[13px]"><StatusChip status={p.status} /><Expected p={p} /></div>
                  {next && <div className="mt-1 text-[13px] font-medium text-[#2457C5]">{next.label} →</div>}
                </Link></li>
              );
            })}
          </ul>
        </Panel>
      )}
    </>
  );
}

function Expected({ p }: { p: PoSummary }) {
  if (phase(p) === 'done') return <span className="text-[13px] text-[#66707A]">—</span>;
  if (!p.expected_at) return <span className="text-[13px] text-[#66707A]">{p.sent_at ? 'no date yet' : '—'}</span>;
  const d = daysUntil(p.expected_at) ?? 0;
  const late = d < 0 && !!p.sent_at;
  return (
    <span className="whitespace-nowrap text-[13px]">
      <span className={cn(late && 'font-medium text-[#B42318]')}>{day(p.expected_at)}</span>
      <span className="text-[12px] text-[#66707A]"> {late ? 'late' : p.expected_source === 'lead_time' ? 'estimate' : 'supplier date'}</span>
    </span>
  );
}

/** Top of "Needs review": what the plan would order now, so starting an order is one click away. */
function PlanTeaser() {
  const loc = loadSession()?.locationId;
  const o = useQuery({ queryKey: ['overview', loc], queryFn: () => api<Overview>(`/stock/overview?location_id=${loc}`), enabled: !!loc }).data;
  const items = o?.items.filter((i) => i.reorder && !i.reorder.on_draft) ?? [];
  if (!items.length) return null;
  const total = items.reduce((t, i) => t + Number(i.reorder!.cost ?? 0), 0);
  const suppliers = new Set(items.map((i) => i.reorder!.supplier)).size;
  return (
    <div className="flex flex-wrap items-center justify-between gap-3 rounded-[8px] border border-[#C9D6F2] bg-[#F3F6FC] px-4 py-3 md:px-5">
      <div><div className="text-[14px] font-semibold">{items.length} item{items.length > 1 ? 's' : ''} to reorder · {money(total, items[0].reorder!.currency)}</div>
        <div className="text-[13px] text-[#3B444D]">From {suppliers} supplier{suppliers > 1 ? 's' : ''}. Review the quantities, then create the drafts.</div></div>
      <ButtonLink to="/app/orders/plan" variant="secondary">Open the plan</ButtonLink>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Reorder plan
// ---------------------------------------------------------------------------

const STALE: Record<string, string> = {
  no_plan_yet: 'No plan has been worked out yet.', inputs_changed: 'Stock, sales or orders changed since.',
  updates_in_progress: 'A file or sync is still being imported.', older_than_24h: 'It is more than a day old.',
};

export function PlanPage() {
  return (
    <OpsShell active="orders" title="Reorder plan" subtitle={<Link to="/app/orders" className="hover:underline">← Orders</Link>}>
      <RequireSession><Plan /></RequireSession>
    </OpsShell>
  );
}

function Plan() {
  const s = loadSession()!;
  const loc = s.locationId!;
  const qc = useQueryClient();
  const navigate = useNavigate();
  const rec = useQuery({ queryKey: ['recommendations', loc], queryFn: () => api<Recommendations>(`/recommendations?location_id=${loc}`) });
  const overview = useQuery({ queryKey: ['overview', loc], queryFn: () => api<Overview>(`/stock/overview?location_id=${loc}`) });
  const readiness = useQuery({ queryKey: ['readiness', loc], queryFn: () => api<Readiness>(`/readiness?location_id=${loc}`) });
  const stock = Object.fromEntries((overview.data?.items ?? []).map((i) => [i.variant_id, i]));
  const run = useMutation({ mutationFn: () => api('/replenishment-runs', { body: { location_id: loc } }), onSuccess: () => qc.invalidateQueries({ queryKey: ['recommendations', loc] }) });
  const plan = rec.data?.run;
  // Open on current numbers: work the plan out again when it is missing or out of date (not while data is importing).
  const autoRan = useRef(false);
  useEffect(() => {
    if (!rec.data || autoRan.current || run.isPending) return;
    const outdated = !rec.data.run || (rec.data.stale && !rec.data.stale_reasons.includes('updates_in_progress'));
    if (outdated) { autoRan.current = true; run.mutate(); }
  }, [rec.data]); // eslint-disable-line react-hooks/exhaustive-deps
  const lines = plan?.lines ?? [];
  const orderLines = lines.filter((l) => l.status === 'order' && !l.open_po).sort((a, b) =>
    (stock[a.variant_id]?.stockout_date ?? '9999').localeCompare(stock[b.variant_id]?.stockout_date ?? '9999'));
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
  const grand = [...bySupplier.values()].reduce((t, e) => t + e.total, 0);
  const edited = chosen.filter((l) => qty[l.variant_id] !== l.order_qty).length;
  const draft = useMutation({
    mutationFn: () => api<PoSummary[]>('/purchase-orders/from-run', { body: {
      run_id: plan!.id, variant_ids: chosen.map((l) => l.variant_id),
      quantities: Object.fromEntries(chosen.map((l) => [l.variant_id, qty[l.variant_id]])) } }),
    onSuccess: (pos) => { qc.invalidateQueries({ queryKey: ['pos'] }); qc.invalidateQueries({ queryKey: ['overview'] }); navigate(pos.length === 1 ? `/app/orders/${pos[0].id}` : '/app/orders'); },
  });
  const suggestions = readiness.data?.features.find((f) => f.key === 'suggestions');
  const orders = readiness.data?.features.find((f) => f.key === 'orders');
  const stale = !!(rec.data?.stale && plan);

  return (
    <>
      <div className="flex flex-wrap items-center justify-between gap-3 text-[13px] text-[#66707A]">
        <span>{run.isPending ? 'Working out the plan from current data…' : plan ? <>Worked out {when(plan.cutoff)} from stock, sales, open orders and supplier terms.</> : ' '}</span>
        <Button variant="secondary" size="sm" onClick={() => run.mutate()} loading={run.isPending}><SymbolIcon icon="refresh" family="rounded" className="text-[17px]" />Recalculate</Button>
      </div>
      {stale && !run.isPending && <Notice><b>Data changed since this plan.</b> {rec.data!.stale_reasons.map((r) => STALE[r] ?? '').join(' ')} Recalculate before creating drafts.</Notice>}
      <ErrorBox error={run.error ?? rec.error} />
      {suggestions && !suggestions.ready && <Notice><b>Suggestions are limited:</b> needs {suggestions.missing.map((m) => m.what).join(', ')}. <Link className="font-medium underline" to="/app/settings/data">Add data</Link></Notice>}
      {orders && !orders.ready && <Notice tone="info"><b>Before an order can be sent</b> you still need {orders.missing.map((m) => m.what).join(', ')}. <Link className="font-medium underline" to={orders.missing.length === 1 && orders.missing[0].what.includes('address') ? '/app/settings' : '/app/orders/suppliers'}>Set it up</Link></Notice>}
      <OpenOrderLinks locationId={loc} />
      {(rec.isLoading || (run.isPending && !plan)) && <Skeleton rows={5} />}
      {plan && (
        <div className={cn('grid items-start gap-5', orderLines.length > 0 && 'lg:grid-cols-[1fr_300px]')}>
          <Panel padded={false} title="Suggested orders" sub={orderLines.length ? `${orderLines.length} item${orderLines.length === 1 ? '' : 's'} · soonest to run out first · untick to leave out` : undefined}>
            {orderLines.length === 0 && <EmptyState icon="task_alt" compact title="Nothing needs ordering right now" body="Stock and incoming orders cover the coming days. Items on hold or without a supplier are listed below." />}
            {orderLines.length > 0 && (
              <div className="overflow-x-auto">
                <table className="w-full min-w-[760px] border-t border-[#EDEFF2] text-[14px]">
                  <thead className="bg-[#F8F9FA]"><tr>
                    <th className={cn(th, 'w-8')} /><th className={th}>Item</th><th className={thNum}>In stock</th><th className={th}>Runs out</th>
                    <th className={thNum}>Order</th><th className={th}>Supplier</th><th className={thNum}>Cost</th><th className={th} />
                  </tr></thead>
                  <tbody className="divide-y divide-[#EDEFF2]">
                    {orderLines.map((l) => {
                      const changed = qty[l.variant_id] !== l.order_qty;
                      const r = stock[l.variant_id];
                      return (
                        <Fragment key={l.variant_id}>
                          <tr className={cn(skip.has(l.variant_id) && 'opacity-45')}>
                            <td className={td}><input type="checkbox" className="h-4 w-4 accent-[#2457C5]" aria-label={`Include ${l.sku}`} checked={!skip.has(l.variant_id)}
                              onChange={(e) => setSkip((x) => { const n = new Set(x); e.target.checked ? n.delete(l.variant_id) : n.add(l.variant_id); return n; })} /></td>
                            <td className={td}><div className="font-medium">{r?.name ?? l.sku}</div><div className="text-[12px] text-[#66707A]">{l.sku} · sells {num(l.daily_demand)}/day</div></td>
                            <td className={tdNum}>{num(l.on_hand)}</td>
                            <td className={td}><RunsOut state={r?.state} date={r?.stockout_date ?? null} /></td>
                            <td className={tdNum}>
                              <span className="inline-flex items-center gap-1.5">
                                <input aria-label={`Quantity for ${l.sku}`} inputMode="decimal" className={cn('h-8 w-[60px] rounded-[6px] border px-2 text-right font-semibold tabular-nums outline-none focus:border-[#2457C5]',
                                  changed ? 'border-[#D08A1E] bg-[#FEF8EC]' : 'border-[#D5DAE0]')}
                                  value={qty[l.variant_id] ?? ''} onChange={(e) => setQty((q) => ({ ...q, [l.variant_id]: e.target.value }))} />
                                <span className="w-9 text-left text-[12px] text-[#66707A]">{l.order_uom}</span></span>
                              <div className={cn('text-[11px]', changed ? 'font-medium text-[#A15C07]' : 'text-[#66707A]')}>{changed ? `suggested ${num(l.order_qty)}` : `${num(l.base_qty)} units`}</div>
                            </td>
                            <td className={cn(td, 'text-[13px]')}>{l.supplier}</td>
                            <td className={tdNum}><span className="font-medium">{money(cost(l), l.currency)}</span></td>
                            <td className={cn(td, 'text-right')}><button className="text-[13px] font-medium text-[#2457C5] hover:underline" onClick={() => setOpen(open === l.variant_id ? null : l.variant_id)}>{open === l.variant_id ? 'Hide' : 'Why?'}</button></td>
                          </tr>
                          {open === l.variant_id && <tr><td colSpan={8} className="bg-[#F8F9FA] px-5 py-4"><LineDetail line={l} /></td></tr>}
                        </Fragment>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )}
          </Panel>
          {orderLines.length > 0 && <div className="lg:sticky lg:top-6">
            <Panel title="Drafts to create">
              {chosen.length === 0 && <div className="text-[13px] text-[#66707A]">Tick the items to order.</div>}
              <ul className="flex flex-col divide-y divide-[#EDEFF2]">
                {[...bySupplier.entries()].map(([supplier, e]) => (
                  <li key={supplier} className="flex justify-between gap-3 py-2 text-[14px]">
                    <span><span className="font-medium">{supplier}</span><span className="block text-[12px] text-[#66707A]">{e.lines.length} item{e.lines.length > 1 ? 's' : ''}</span></span>
                    <span className="font-medium tabular-nums">{money(e.total, e.ccy)}</span>
                  </li>
                ))}
              </ul>
              {chosen.length > 0 && <>
                <div className="mt-1 flex justify-between border-t border-[#E2E5E9] pt-2 text-[14px] font-semibold"><span>Items total</span><span className="tabular-nums">{money(grand, chosen[0].currency)}</span></div>
                <div className="mt-0.5 text-[12px] text-[#66707A]">Shipping and tax are confirmed by each supplier.</div>
                {edited > 0 && <div className="mt-2 text-[12px] font-medium text-[#A15C07]">{edited} quantit{edited > 1 ? 'ies differ' : 'y differs'} from the suggestion — the draft shows both for approval.</div>}
                <div className="mt-3"><Button size="lg" onClick={() => draft.mutate()} loading={draft.isPending} disabled={stale || run.isPending}>
                  Create {bySupplier.size} order draft{bySupplier.size > 1 ? 's' : ''}</Button></div>
              </>}
              <div className="mt-2"><ErrorBox error={draft.error} /></div>
              <p className="mt-3 text-[12px] leading-snug text-[#66707A]">Drafts are not sent. The owner approves each order; in test mode an approved order is kept in Tabula, not emailed.</p>
            </Panel>
          </div>}
        </div>
      )}
      {plan && <OtherLines lines={lines.filter((l) => l.status !== 'order' || l.open_po)} names={Object.fromEntries(Object.entries(stock).map(([k, v]) => [k, v.name]))} />}
    </>
  );
}

/** Same wording as Overview and Inventory: the date it runs out, and how many days away. */
function RunsOut({ state, date }: { state?: string; date: string | null }) {
  if (state === 'out_of_stock') return <span className="font-medium text-[#B42318]">Out now</span>;
  if (!date) return <span className="text-[#66707A]">later</span>;
  const d = daysUntil(date) ?? 0;
  return <span className={cn('whitespace-nowrap', state === 'at_risk' && 'font-medium text-[#A15C07]')}>{day(date)} <span className="text-[12px] font-normal text-[#66707A]">{d <= 0 ? 'today' : `in ${d}d`}</span></span>;
}

function OtherLines({ lines, names }: { lines: PlanLine[]; names: Record<string, string> }) {
  const [open, setOpen] = useState<string | null>(null);
  const groups: [string, string, PlanLine[]][] = [
    ['draft', 'Already on a draft order', lines.filter((l) => l.open_po)],
    ['on_hold', 'On hold — already ordered, not confirmed', lines.filter((l) => l.status === 'on_hold')],
    ['no_supplier', 'No supplier to order from', lines.filter((l) => l.status === 'no_supplier')],
    ['insufficient_data', 'Not enough data', lines.filter((l) => l.status === 'insufficient_data')],
  ];
  const shown = groups.filter(([, , g]) => g.length);
  if (!shown.length) return null;
  const total = shown.reduce((t, [, , g]) => t + g.length, 0);
  return (
    <Disclosure title="Not in this plan, and why" sub={`${total} item${total > 1 ? 's' : ''}`} defaultOpen={shown.some(([k]) => k === 'no_supplier')}>
      <div className="flex flex-col gap-4">
        {shown.map(([key, title, g]) => (
          <div key={key}>
            <div className="mb-1 text-[12px] font-medium text-[#66707A]">{title} ({g.length})</div>
            <ul className="flex flex-col divide-y divide-[#EDEFF2]">
              {g.map((l) => (
                <li key={l.variant_id} className="py-2 text-[14px]">
                  <div className="flex items-center justify-between gap-3">
                    <span className="min-w-0"><span className="font-medium">{names[l.variant_id] ?? l.sku}</span> <span className="text-[13px] text-[#66707A]">{l.open_po ? `on draft ${l.open_po}` : l.reasons[0]?.message ?? ''}</span></span>
                    <span className="flex shrink-0 items-center gap-3">
                      {key === 'no_supplier' && <Link to="/app/orders/suppliers" className="text-[13px] font-medium text-[#2457C5] hover:underline">Add a supplier</Link>}
                      <button className="text-[13px] text-[#66707A] hover:underline" onClick={() => setOpen(open === l.variant_id ? null : l.variant_id)}>{open === l.variant_id ? 'Hide' : 'Details'}</button>
                    </span>
                  </div>
                  {open === l.variant_id && <div className="mt-2"><LineDetail line={l} /></div>}
                </li>
              ))}
            </ul>
          </div>
        ))}
      </div>
    </Disclosure>
  );
}
