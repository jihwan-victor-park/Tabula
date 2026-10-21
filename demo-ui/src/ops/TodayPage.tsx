import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Fragment, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { SymbolIcon, cn } from '../components/ui';
import { api, loadSession, type PlanLine, type PoSummary, type Recommendations } from './api';
import { AttentionPanel, OpenOrderLinks } from './Attention';
import { Button, EmptyState, ErrorBox, Loading, Notice, OpsShell, Panel, RequireSession, StatusChip, money, num, when } from './kit';

const STALE_TEXT: Record<string, string> = {
  no_plan_yet: 'No plan has been computed for this location yet.',
  inputs_changed: 'Stock, sales, orders or prices changed after this plan was computed.',
  updates_in_progress: 'An import or sync is still being applied.',
  older_than_24h: 'This plan is more than a day old.',
};

export function TodayPage() {
  const session = loadSession();
  return (
    <OpsShell active="today" title="Today — what to order" icon="today">
      <RequireSession>
        {session?.locationId ? <>
          <AttentionPanel locationId={session.locationId} />
          <OpenOrderLinks locationId={session.locationId} />
          <Plan locationId={session.locationId} />
        </> : (
          <Panel><EmptyState icon="location_on" title="Pick a store location" body="Choose the location to plan for."><Link className="text-[#E8654A] underline" to="/ops/setup">Workspace</Link></EmptyState></Panel>
        )}
      </RequireSession>
    </OpsShell>
  );
}

function Plan({ locationId }: { locationId: string }) {
  const qc = useQueryClient();
  const navigate = useNavigate();
  const rec = useQuery({ queryKey: ['recommendations', locationId], queryFn: () => api<Recommendations>(`/recommendations?location_id=${locationId}`) });
  const compute = useMutation({
    mutationFn: () => api('/replenishment-runs', { body: { location_id: locationId } }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['recommendations', locationId] }),
  });
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [open, setOpen] = useState<string | null>(null);
  const draft = useMutation({
    mutationFn: () => api<PoSummary[]>('/purchase-orders/from-run', { body: { run_id: rec.data!.run!.id, variant_ids: selected.size ? [...selected] : null } }),
    onSuccess: (pos) => { qc.invalidateQueries({ queryKey: ['pos'] }); navigate(pos.length === 1 ? `/ops/orders/${pos[0].id}` : '/ops/orders'); },
  });

  if (rec.isLoading) return <Panel><Loading label="Loading the plan…" /></Panel>;
  if (rec.error) return <Panel><ErrorBox error={rec.error} onRetry={() => rec.refetch()} /></Panel>;
  const data = rec.data!, run = data.run;
  const orderLines = run?.lines.filter((l) => l.status === 'order') ?? [];
  // Never add amounts in different currencies together.
  const spend = Object.entries(orderLines.reduce<Record<string, number>>((acc, l) => {
    const ccy = l.currency ?? '?';
    acc[ccy] = (acc[ccy] ?? 0) + Number(l.line_cost ?? 0);
    return acc;
  }, {})).map(([ccy, v]) => money(String(v), ccy)).join(' + ') || '—';
  const draftable = orderLines.filter((l) => !l.open_po);

  return (
    <>
      <div className="flex flex-wrap items-center gap-3">
        <Button onClick={() => compute.mutate()} loading={compute.isPending} variant={data.stale ? 'primary' : 'secondary'}>
          <SymbolIcon icon="calculate" className="text-[18px]" /> {run ? 'Recompute plan' : 'Compute plan'}
        </Button>
        {run && <span className="text-[12px] text-[#5C7A8A]">Plan of {when(run.cutoff)} · policy v{run.policy_version} · engine {run.engine_version} · data v{run.data_version}</span>}
      </div>
      <ErrorBox error={compute.error} />
      {data.stale && (
        <Notice>
          <b>This plan may be out of date.</b>{' '}
          {data.stale_reasons.map((r) => STALE_TEXT[r] ?? `New ${r.replace('newer_', '').replace('_', ' ')} since the plan.`).join(' ')}
          {data.pending_updates?.length ? ` (${data.pending_updates.join('; ')})` : ''} Next: press <b>Recompute plan</b> above before drafting orders.
        </Notice>
      )}
      {!run ? (
        <Panel><EmptyState icon="inventory" title="No plan yet" body="Import a sales export and a stock count, then compute a plan." /></Panel>
      ) : (
        <>
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
            <Stat label="Items to order" value={String(orderLines.length)} />
            <Stat label="On hold — already ordered" value={String(run.summary.lines.on_hold ?? 0)} />
            <Stat label="Need review" value={String(run.summary.needs_review)} />
            <Stat label="Planned spend (items only)" value={spend} />
          </div>
          <Panel title="Recommendations" aside={
            <Button onClick={() => draft.mutate()} loading={draft.isPending} disabled={!draftable.length || data.stale}
                    title={data.stale ? 'Recompute the plan first' : undefined}>
              Create PO drafts{selected.size ? ` (${selected.size})` : ''}
            </Button>}>
            <ErrorBox error={draft.error} />
            <div className="overflow-x-auto">
              <table className="[&_td]:pr-3 [&_th]:pr-3 w-full min-w-[860px] text-[13px]">
                <thead>
                  <tr className="text-left text-[#5C7A8A]">
                    <th className="w-8 py-2" /><th>Item</th><th>Status</th><th className="text-right">On hand</th>
                    <th className="text-right">Per day</th><th className="text-right">Recommended</th><th>Supplier</th>
                    <th className="text-right">Cost</th><th>Review</th><th />
                  </tr>
                </thead>
                <tbody>
                  {run.lines.map((l) => (
                    <Fragment key={l.variant_id}>
                      <tr className={cn('border-t border-[#F1E4DA]', open === l.variant_id && 'bg-[#FFFAF6]')}>
                        <td className="py-2">{l.status === 'order' && !l.open_po && (
                          <input type="checkbox" aria-label={`Select ${l.sku}`} checked={selected.has(l.variant_id)}
                                 onChange={(e) => setSelected((s) => { const n = new Set(s); e.target.checked ? n.add(l.variant_id) : n.delete(l.variant_id); return n; })} />)}</td>
                        <td className="font-medium">{l.sku}</td>
                        <td>
                          <StatusChip status={l.status === 'no_order' && l.reasons.some((r) => r.code === 'covered_by_open_orders') ? 'covered' : l.status} />
                          {l.open_po && <div className="mt-1 text-[11px] text-[#1D4ED8]">draft {l.open_po} (not sent)</div>}
                          {l.pos_pending.length > 0 && <div className="mt-1 text-[11px] font-medium text-[#991B1B]">stock mismatch: received, not in POS</div>}
                        </td>
                        <td className="text-right font-mono">{num(l.on_hand)}</td>
                        <td className="text-right font-mono">{num(l.daily_demand)}</td>
                        <td className="text-right font-mono">
                          {l.status === 'order' ? <>{num(l.order_qty)} {l.order_uom} <span className="text-[#5C7A8A]">= {num(l.base_qty)}</span></> :
                           l.status === 'on_hold' ? <span className="text-[#8A5A00]">0 (hold)</span> : '—'}
                        </td>
                        <td>{l.supplier ?? '—'}</td>
                        <td className="text-right font-mono">{l.line_cost ? money(l.line_cost, l.currency) : '—'}</td>
                        <td>{l.reasons.length ? <span className="text-[#8A5A00]">{l.reasons.length} note{l.reasons.length > 1 ? 's' : ''}</span> : '—'}</td>
                        <td className="text-right"><button className="text-[#E8654A] underline" onClick={() => setOpen(open === l.variant_id ? null : l.variant_id)}>{open === l.variant_id ? 'Hide' : 'Why?'}</button></td>
                      </tr>
                      {open === l.variant_id && <tr><td colSpan={10} className="pb-4"><LineDetail line={l} /></td></tr>}
                    </Fragment>
                  ))}
                </tbody>
              </table>
            </div>
          </Panel>
        </>
      )}
    </>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-[12px] border border-[#E8D4C6] bg-white px-5 py-4 shadow-sm">
      <div className="text-[12px] font-medium text-[#5C7A8A]">{label}</div>
      <div className="mt-1 font-mono text-[24px] font-semibold">{value}</div>
    </div>
  );
}

function LineDetail({ line }: { line: PlanLine }) {
  return (
    <div className="grid gap-4 rounded-[12px] border border-[#F1E4DA] bg-white p-4 lg:grid-cols-2">
      <div>
        {line.status === 'on_hold' && (
          <div className="mb-3 grid grid-cols-3 gap-2 text-center text-[12px]">
            <div className="rounded-[10px] bg-[#FDF5EF] p-2"><div className="text-[#5C7A8A]">Still needed</div><div className="font-mono text-[18px]">{num(line.need_before_held)}</div></div>
            <div className="rounded-[10px] bg-[#FFF8E1] p-2"><div className="text-[#5C7A8A]">Already requested, unconfirmed</div><div className="font-mono text-[18px]">{num(line.held_qty)}</div></div>
            <div className="rounded-[10px] bg-[#FEF3C7] p-2"><div className="text-[#5C7A8A]">Extra order</div><div className="text-[14px] font-semibold text-[#8A5A00]">On hold — confirm first</div>
              <div className="mt-1 text-[11px]">Next: get the supplier's answer (or update your open-orders file); if it is a Tabula order, record their reply on <a className="underline" href="/ops/orders">Purchase orders</a>.</div></div>
          </div>
        )}
        {line.arrival?.order_date && (
          <div className="mb-3 grid grid-cols-3 gap-2 text-center text-[12px]">
            <div className="rounded-[10px] bg-[#FDF5EF] p-2"><div className="text-[#5C7A8A]">Order placed</div><div className="font-mono">{line.arrival.order_date}</div></div>
            <div className="rounded-[10px] bg-[#FDF5EF] p-2"><div className="text-[#5C7A8A]">Delivered (end of day)</div><div className="font-mono">{line.arrival.delivery_date}</div></div>
            <div className="rounded-[10px] bg-[#FDF5EF] p-2"><div className="text-[#5C7A8A]">On the shelf from</div><div className="font-mono">{line.arrival.usable_date}</div></div>
          </div>
        )}
        <div className="mb-1 text-[13px] font-semibold">How it was calculated</div>
        <ol className="flex flex-col gap-1 text-[13px]">
          {line.steps.map((s, i) => (
            <li key={i}><b>{s.label}:</b> {s.value}{s.formula && <div className="text-[12px] text-[#5C7A8A]">{s.formula}</div>}</li>
          ))}
        </ol>
        <div className="mt-3 text-[12px] text-[#5C7A8A]">
          Data as of — stock: {when(line.data_as_of.stock)} ({line.data_as_of.stock_source ?? '—'}) · sales through: {when(line.data_as_of.sales_through)} · price from: {when(line.data_as_of.price)}
        </div>
        {line.reasons.length > 0 && (
          <ul className="mt-3 flex flex-col gap-1">
            {line.reasons.map((r, i) => <li key={i} className="rounded-[8px] bg-[#FFF8E1] px-3 py-1.5 text-[12px] text-[#6B4A00]">{r.message}</li>)}
          </ul>
        )}
      </div>
      <div>
        <div className="mb-1 text-[13px] font-semibold">Projected stock (start of each day, with this order)</div>
        <table className="[&_td]:pr-3 [&_th]:pr-3 w-full text-[12px]">
          <thead><tr className="text-left text-[#5C7A8A]"><th>Day</th><th>Date</th><th className="text-right">Start</th><th className="text-right">Sells</th><th className="text-right">Short</th><th className="text-right">Arrives (end of day)</th></tr></thead>
          <tbody>
            {line.projection.slice(0, 14).map((d) => (
              <tr key={d.day} className={cn('border-t border-[#F7EDE5]', Number(d.short) > 0 && 'bg-[#FEE2E2]')}>
                <td>{d.day}</td><td>{d.date}</td><td className="text-right font-mono">{num(d.start)}</td><td className="text-right font-mono">{num(d.demand)}</td>
                <td className="text-right font-mono">{Number(d.short) > 0 ? num(d.short) : ''}</td><td className="text-right font-mono">{Number(d.arriving) > 0 ? num(d.arriving) : ''}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
