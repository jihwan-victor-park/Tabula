// Receiving: record what physically arrived against a sent order — arrived, damaged,
// sellable — and settle damage with the supplier. A receipt key generated when the form
// opens (kept across a reload) makes a double submit the same receipt.

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { api, loadSession, type PoDetail, type PoSummary } from './api';
import { Button, EmptyState, ErrorBox, Loading, Notice, OpsShell, Panel, RequireSession, StatusChip, num, when } from './kit';

const SENT = ['test_sent', 'delivery_unknown', 'supplier_confirmed', 'changes_proposed', 'partially_received', 'received'];

export function ReceivingPage() {
  const session = loadSession();
  const pos = useQuery({ queryKey: ['pos', session?.tenantId], queryFn: () => api<PoSummary[]>('/purchase-orders'), enabled: !!session?.tenantId });
  const list = pos.data?.filter((p) => SENT.includes(p.status));
  return (
    <OpsShell active="receiving" title="Receiving" icon="inventory_2">
      <RequireSession>
        <Panel title="Orders with deliveries expected">
          {pos.isLoading && <Loading />}
          <ErrorBox error={pos.error} onRetry={() => pos.refetch()} />
          {list?.length === 0 && <EmptyState icon="local_shipping" title="Nothing is on its way" body="Sent orders show up here until everything has arrived." />}
          <ul className="flex flex-col gap-2">
            {list?.map((p) => (
              <li key={p.id} className="flex flex-wrap items-center justify-between gap-2 rounded-[12px] border border-[#E8D4C6] px-4 py-3 text-[13px]">
                <div><Link className="font-medium text-[#E8654A] underline" to={`/ops/receiving/${p.id}`}>{p.number}</Link> · {p.supplier} → {p.ship_to}
                  <div className="text-[12px] text-[#5C7A8A]">{p.expected_lines} line(s) expected{p.awaiting_reply ? ' · supplier has not confirmed everything' : ''}{p.open_issues ? ` · ${p.open_issues} open issue(s)` : ''}</div></div>
                <StatusChip status={p.status} />
              </li>
            ))}
          </ul>
        </Panel>
      </RequireSession>
    </OpsShell>
  );
}

function newKey(poId: string): string {
  const store = `tabula.receipt-key.${poId}`;
  try {
    const existing = sessionStorage.getItem(store);
    if (existing) return existing;
    const key = crypto.randomUUID();
    sessionStorage.setItem(store, key);
    return key;
  } catch {
    return crypto.randomUUID();
  }
}

function forgetKey(poId: string) {
  try { sessionStorage.removeItem(`tabula.receipt-key.${poId}`); } catch { /* not remembered */ }
}

export function ReceiveOrderPage() {
  const { id } = useParams();
  const qc = useQueryClient();
  const po = useQuery({ queryKey: ['po', id], queryFn: () => api<PoDetail>(`/purchase-orders/${id}`) });
  const [key, setKey] = useState(() => newKey(id!));
  const [arrived, setArrived] = useState<Record<number, string>>({});
  const [damaged, setDamaged] = useState<Record<number, string>>({});
  const refresh = () => { qc.invalidateQueries({ queryKey: ['po', id] }); qc.invalidateQueries({ queryKey: ['pos'] }); };
  const record = useMutation({
    mutationFn: () => api<{ created: boolean }>(`/purchase-orders/${id}/receipts`, { body: {
      receipt_key: key,
      lines: Object.entries(arrived).filter(([, v]) => v && Number(v) > 0).map(([n, v]) => ({ line_no: Number(n), arrived_qty: v, damaged_qty: damaged[Number(n)] || '0' })),
    } }),
    onSuccess: () => { forgetKey(id!); setKey(newKey(id!)); setArrived({}); setDamaged({}); refresh(); },
  });
  const posEntered = useMutation({ mutationFn: (lineId: string) => api(`/receipt-lines/${lineId}/pos-entered`, { method: 'POST' }), onSuccess: refresh });

  return (
    <OpsShell active="receiving" title={po.data ? `Receive ${po.data.number}` : 'Receive'} icon="inventory_2"
              actions={<Link className="text-[13px] text-[#5C7A8A] underline" to={`/ops/orders/${id}`}>Order</Link>}>
      <RequireSession>
        {po.isLoading && <Panel><Loading /></Panel>}
        <ErrorBox error={po.error} onRetry={() => po.refetch()} />
        {po.data && !po.data.progress && <Panel><EmptyState icon="schedule_send" title="Not sent yet" body="Deliveries are recorded once the order has been sent." /></Panel>}
        {po.data?.progress && (() => {
          const p = po.data, pr = p.progress!;
          const any = Object.values(arrived).some((v) => v && Number(v) > 0);
          return (
            <>
              <div className="flex flex-wrap items-center gap-3"><StatusChip status={p.status} /><span className="text-[13px]">{p.supplier} → {p.ship_to}</span></div>
              {p.status === 'test_sent' && <Notice tone="info">Test order (capture mode): the supplier never received it — recording a delivery here is for testing the flow.</Notice>}
              <Panel title="What arrived" aside={<span className="font-mono text-[11px] text-[#5C7A8A]">receipt key {key.slice(0, 8)}…</span>}>
                <div className="overflow-x-auto">
                  <table className="[&_td]:pr-3 [&_th]:pr-3 w-full min-w-[760px] text-[13px]">
                    <thead><tr className="text-left text-[#5C7A8A]"><th className="py-2">#</th><th>Item</th><th className="text-right">Still expected</th><th className="text-right">Not confirmed</th><th className="text-right">Already arrived</th><th className="text-right">Arrived now</th><th className="text-right">of which damaged</th><th className="text-right">Sellable</th></tr></thead>
                    <tbody>
                      {pr.lines.map((l) => {
                        const a = Number(arrived[l.line_no] || 0), d = Number(damaged[l.line_no] || 0);
                        return (
                          <tr key={l.line_no} className="border-t border-[#F1E4DA]">
                            <td className="py-2">{l.line_no}</td>
                            <td><b>{l.sku}</b> <span className="font-mono text-[12px] text-[#5C7A8A]">{l.supplier_sku}</span><div className="text-[11px] text-[#5C7A8A]">{l.order_uom} of {num(l.units_per_order_uom)}</div></td>
                            <td className="text-right font-mono">{num(l.outstanding)}</td>
                            <td className="text-right font-mono text-[#8A5A00]">{Number(l.unconfirmed) > 0 ? num(l.unconfirmed) : ''}</td>
                            <td className="text-right font-mono">{num(l.received)}</td>
                            <td className="text-right"><input aria-label={`Arrived for line ${l.line_no}`} inputMode="decimal" className="w-[70px] rounded-[8px] border border-[#E8D4C6] px-2 py-1 text-right font-mono" value={arrived[l.line_no] ?? ''} onChange={(e) => setArrived((x) => ({ ...x, [l.line_no]: e.target.value }))} /></td>
                            <td className="text-right"><input aria-label={`Damaged for line ${l.line_no}`} inputMode="decimal" className="w-[70px] rounded-[8px] border border-[#E8D4C6] px-2 py-1 text-right font-mono" value={damaged[l.line_no] ?? ''} onChange={(e) => setDamaged((x) => ({ ...x, [l.line_no]: e.target.value }))} /></td>
                            <td className="text-right font-mono">{a > 0 ? `${num(String(a - d))} ${l.order_uom} = ${num(String((a - d) * Number(l.units_per_order_uom)))} units` : ''}</td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
                <div className="mt-3 flex flex-wrap items-center gap-2">
                  <Button onClick={() => record.mutate()} disabled={!any} loading={record.isPending}>Record delivery</Button>
                  <span className="text-[12px] text-[#5C7A8A]">Damaged goods are not added to stock; they become an issue to settle with the supplier.</span>
                </div>
                <div className="mt-2"><ErrorBox error={record.error} /></div>
              </Panel>

              {pr.issues.length > 0 && (
                <Panel title="Damage to settle with the supplier">
                  <ul className="flex flex-col gap-2">{pr.issues.map((i) => <IssueRow key={i.id} issue={i} uom={pr.lines.find((l) => l.line_no === i.line_no)?.order_uom ?? ''} onChange={refresh} />)}</ul>
                  <p className="mt-2 text-[11px] text-[#5C7A8A]">A replacement is counted as on its way only after the supplier confirms it.</p>
                </Panel>
              )}

              <Panel title="Deliveries recorded">
                {pr.receipts.length === 0 && <div className="text-[13px] text-[#5C7A8A]">None yet.</div>}
                <ul className="flex flex-col gap-2 text-[13px]">
                  {pr.receipts.map((r) => (
                    <li key={r.id} className="rounded-[10px] border border-[#F1E4DA] px-3 py-2">
                      <div className="text-[12px] text-[#5C7A8A]">{when(r.received_at)} · key {r.receipt_key.slice(0, 8)}…</div>
                      {r.lines.map((rl) => (
                        <div key={rl.id} className="flex flex-wrap items-center gap-2">
                          line {rl.line_no}: arrived {num(rl.arrived)}, damaged {num(rl.damaged)}, +{num(rl.sellable_units)} sellable units
                          {rl.pos_status === 'ledger_posted' && <span className="text-[12px] text-[#065F46]">added to Tabula stock</span>}
                          {rl.pos_status === 'pending_pos' && <>
                            <span className="text-[12px] font-medium text-[#991B1B]">not in the POS yet — enter it there</span>
                            <Button variant="secondary" onClick={() => posEntered.mutate(rl.id)} loading={posEntered.isPending && posEntered.variables === rl.id}>I entered it in the POS</Button>
                          </>}
                          {rl.pos_status === 'pos_reported' && <span className="text-[12px] text-[#8A5A00]">entered in the POS — confirmed when the next POS stock reading shows it</span>}
                        </div>
                      ))}
                    </li>
                  ))}
                </ul>
                <ErrorBox error={posEntered.error} />
              </Panel>
            </>
          );
        })()}
      </RequireSession>
    </OpsShell>
  );
}

function IssueRow({ issue, uom, onChange }: { issue: NonNullable<PoDetail['progress']>['issues'][number]; uom: string; onChange: () => void }) {
  const [eta, setEta] = useState('');
  const resolve = useMutation({
    mutationFn: (resolution: string) => api(`/receipt-issues/${issue.id}/resolve`, { body: { resolution, qty: resolution === 'replacement_confirmed' ? issue.qty : null, eta: eta || null } }),
    onSuccess: onChange,
  });
  return (
    <li className="flex flex-wrap items-center gap-2 text-[13px]">
      line {issue.line_no}: {num(issue.qty)} {uom} {issue.kind} <StatusChip status={issue.status} />
      {issue.status === 'open' ? <>
        <input aria-label="Replacement ETA" type="date" className="rounded-[8px] border border-[#E8D4C6] px-2 py-1" value={eta} onChange={(e) => setEta(e.target.value)} />
        <Button variant="secondary" onClick={() => resolve.mutate('replacement_confirmed')} loading={resolve.isPending}>Supplier confirmed a replacement</Button>
        <Button variant="secondary" onClick={() => resolve.mutate('credit_confirmed')} loading={resolve.isPending}>Supplier confirmed a credit</Button>
        <Button variant="secondary" onClick={() => resolve.mutate('written_off')} loading={resolve.isPending}>Write off</Button>
      </> : issue.resolution_eta && <span className="text-[12px] text-[#5C7A8A]">replacement ETA {issue.resolution_eta}</span>}
      <ErrorBox error={resolve.error} />
    </li>
  );
}
