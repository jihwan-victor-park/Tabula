import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Fragment, useEffect, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { cn } from '../components/ui';
import { api, loadSession, type Me, type PoDetail, type PoLine, type PoSummary } from './api';
import { AfterSending } from './AfterSending';
import { Button, EmptyState, ErrorBox, Loading, Notice, OpsShell, Panel, RequireSession, StatusChip, money, num, when } from './kit';

export function OrdersPage() {
  const session = loadSession();
  const pos = useQuery({
    queryKey: ['pos', session?.tenantId], queryFn: () => api<PoSummary[]>('/purchase-orders'), enabled: !!session?.tenantId,
    refetchInterval: (q) => (q.state.data?.some((p) => p.status === 'queued') ? 1500 : false),
  });
  return (
    <OpsShell active="orders" title="Purchase orders" icon="receipt_long">
      <RequireSession>
        <Notice tone="info">Sending is in <b>capture</b> mode: an approved order is stored in Tabula as a test message and is <b>not</b> delivered to the supplier.</Notice>
        <Panel title="Orders">
          {pos.isLoading && <Loading />}
          <ErrorBox error={pos.error} onRetry={() => pos.refetch()} />
          {pos.data?.length === 0 && <EmptyState icon="receipt_long" title="No purchase orders yet" body="Create drafts from the plan on the Today page."><Link className="text-[#E8654A] underline" to="/ops/today">Go to Today</Link></EmptyState>}
          <div className="overflow-x-auto">
            <table className="[&_td]:pr-3 [&_th]:pr-3 w-full min-w-[720px] text-[13px]">
              <thead><tr className="text-left text-[#5C7A8A]"><th className="py-2">Number</th><th>Supplier</th><th>Ship to</th><th>Status</th><th>Supplier</th><th className="text-right">Lines</th><th className="text-right">Items total</th><th>Updated</th></tr></thead>
              <tbody>
                {pos.data?.map((p) => (
                  <tr key={p.id} className="border-t border-[#F1E4DA]">
                    <td className="py-2"><Link className="font-medium text-[#E8654A] underline" to={`/ops/orders/${p.id}`}>{p.number}</Link></td>
                    <td>{p.supplier}</td><td>{p.ship_to}</td>
                    <td><StatusChip status={p.status} />{p.needs_attention && <span className="ml-2 text-[12px] text-[#8A5A00]">notes</span>}</td>
                    <td className="text-[12px]">{p.sent_at ? (p.awaiting_reply ? <span className="text-[#8A5A00]">awaiting answer</span> : p.ack_status.replace('_', ' ')) : '—'}{p.open_issues ? <span className="ml-1 text-[#991B1B]">· {p.open_issues} issue(s)</span> : ''}</td>
                    <td className="text-right font-mono">{p.lines}</td>
                    <td className="text-right font-mono">{money(p.estimated_total, p.currency)}</td>
                    <td>{when(p.updated_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Panel>
      </RequireSession>
    </OpsShell>
  );
}

export function OrderPage() {
  const { id } = useParams();
  const session = loadSession();
  const qc = useQueryClient();
  const po = useQuery({
    queryKey: ['po', id], queryFn: () => api<PoDetail>(`/purchase-orders/${id}`), enabled: !!session?.tenantId,
    refetchInterval: (q) => (q.state.data?.status === 'queued' ? 1500 : false),
  });
  const me = useQuery({ queryKey: ['me', session?.user], queryFn: () => api<Me>('/me'), enabled: !!session });
  const role = me.data?.memberships.find((m) => m.tenant_id === session?.tenantId)?.role;
  const [qty, setQty] = useState<Record<number, string>>({});
  const [why, setWhy] = useState<number | null>(null);
  useEffect(() => {
    if (po.data) setQty(Object.fromEntries(po.data.content.lines.map((l) => [l.line_no, l.order_qty])));
  }, [po.data?.revision]); // eslint-disable-line react-hooks/exhaustive-deps

  const refresh = () => { qc.invalidateQueries({ queryKey: ['po', id] }); qc.invalidateQueries({ queryKey: ['pos'] }); };
  const useAct = (path: string, body: (p: PoDetail) => unknown, method = 'POST') =>
    useMutation({ mutationFn: () => api<PoDetail>(`/purchase-orders/${id}/${path}`, { method, body: body(po.data!) }), onSuccess: refresh });
  const save = useAct('lines', (p) => ({ revision: p.revision, lines: p.content.lines.filter((l) => qty[l.line_no] !== l.order_qty).map((l) => ({ line_no: l.line_no, order_qty: qty[l.line_no] })) }), 'PATCH');
  const submit = useAct('submit', (p) => ({ revision: p.revision }));
  const approve = useAct('approve', (p) => ({ revision: p.revision, digest: p.digest }));
  const refreshTerms = useAct('refresh', (p) => ({ revision: p.revision }));
  const cancel = useAct('cancel', () => ({ reason: 'Cancelled from order page' }));

  return (
    <OpsShell active="orders" title={po.data ? `Purchase order ${po.data.number}` : 'Purchase order'} icon="receipt_long"
              actions={<Link className="text-[13px] text-[#5C7A8A] underline" to="/ops/orders">All orders</Link>}>
      <RequireSession>
        {po.isLoading && <Panel><Loading /></Panel>}
        <ErrorBox error={po.error} onRetry={() => po.refetch()} />
        {po.data && (() => {
          const p = po.data, c = p.content;
          const editable = ['draft', 'awaiting_approval', 'queued', 'failed'].includes(p.status);
          const dirty = c.lines.some((l) => qty[l.line_no] !== undefined && qty[l.line_no] !== l.order_qty);
          const busy = save.isPending || submit.isPending || approve.isPending || refreshTerms.isPending || cancel.isPending;
          return (
            <>
              <div className="flex flex-wrap items-center gap-3">
                <StatusChip status={p.status} />
                <span className="text-[12px] text-[#5C7A8A]">Revision {p.revision} · digest {p.digest.slice(0, 12)}… · this order's numbers checked at data v{p.data.checked_version} (its own check — the store plan on Today is separate)</span>
                {p.captured_message && <span className="text-[12px] font-medium text-[#1D4ED8]">Captured in Tabula only (capture mode) — no supplier received this order. Supplier answers below are what you recorded.</span>}
              </div>
              {[save, submit, approve, refreshTerms, cancel].map((m, i) => <ErrorBox key={i} error={m.error} />)}
              {p.status === 'failed' && (
                <Notice>Not sent — see “Approvals and sends” for why. Use <b>Refresh prices & details</b> to load current numbers; that creates a new revision to submit and approve again.</Notice>
              )}
              {p.data.changed_since_check && editable && (
                <Notice>Stock, sales or prices changed since these quantities were checked. Approval will recompute the plan and stop if any recommended quantity moved.</Notice>
              )}
              {p.data.pending_updates.length > 0 && <Notice>Updates in progress: {p.data.pending_updates.join('; ')}. Approval waits until they finish.</Notice>}

              <div className="grid gap-4 lg:grid-cols-3">
                <Panel title="Supplier" className="lg:col-span-1">
                  <dl className="grid grid-cols-[110px_1fr] gap-y-1 text-[13px]">
                    <dt className="text-[#5C7A8A]">Name</dt><dd>{c.supplier.name}</dd>
                    <dt className="text-[#5C7A8A]">Account #</dt><dd>{c.supplier.account_number ?? '—'}</dd>
                    <dt className="text-[#5C7A8A]">Order email</dt><dd>{c.supplier.order_email ?? <span className="text-[#991B1B]">none verified</span>}</dd>
                    <dt className="text-[#5C7A8A]">Terms</dt><dd>{c.supplier.payment_terms}</dd>
                  </dl>
                </Panel>
                <Panel title="Ship to" className="lg:col-span-1">
                  <div className="text-[13px] font-medium">{c.ship_to.name}</div>
                  <div className={cn('text-[13px]', !c.ship_to.complete && 'text-[#991B1B]')}>{c.address_text || 'No address on file'}</div>
                </Panel>
                <Panel title="Totals" className="lg:col-span-1">
                  <dl className="grid grid-cols-[1fr_auto] gap-y-1 text-[13px]">
                    <dt>Items subtotal</dt><dd className="text-right font-mono">{money(c.totals.subtotal, c.currency)}</dd>
                    <dt>Shipping</dt><dd className="text-right text-[#8A5A00]">Not confirmed</dd>
                    <dt>Tax</dt><dd className="text-right text-[#8A5A00]">Not estimated</dd>
                    <dt className="font-semibold">Estimated total</dt><dd className="text-right font-mono font-semibold">{money(c.totals.estimated_total, c.currency)}</dd>
                  </dl>
                  <p className="mt-2 text-[11px] text-[#5C7A8A]">{c.totals.estimate_note}{c.totals.shipping.note ? ` Supplier freight terms: ${c.totals.shipping.note}.` : ''}</p>
                </Panel>
              </div>

              <Panel title="Lines">
                <div className="overflow-x-auto">
                  <table className="[&_td]:pr-3 [&_th]:pr-3 w-full min-w-[900px] text-[13px]">
                    <thead><tr className="text-left text-[#5C7A8A]">
                      <th className="py-2">#</th><th>Item</th><th>Supplier SKU</th><th className="text-right">Order qty</th><th>Pack</th>
                      <th className="text-right">Units</th><th className="text-right">Unit price</th><th className="text-right">Line total</th><th>Recommended</th>
                    </tr></thead>
                    <tbody>
                      {c.lines.map((l) => (
                        <Fragment key={l.line_no}>
                        <tr className="border-t border-[#F1E4DA] align-top">
                          <td className="py-2">{l.line_no}</td>
                          <td><div className="font-medium">{l.sku}</div><div className="text-[12px] text-[#5C7A8A]">{l.name}</div></td>
                          <td className="font-mono">{l.supplier_sku}</td>
                          <td className="text-right">
                            {editable ? (
                              <input aria-label={`Quantity for line ${l.line_no}`} inputMode="decimal"
                                     className="w-[72px] rounded-[8px] border border-[#E8D4C6] px-2 py-1 text-right font-mono"
                                     value={qty[l.line_no] ?? l.order_qty} onChange={(e) => setQty((q) => ({ ...q, [l.line_no]: e.target.value }))} />
                            ) : <span className="font-mono">{num(l.order_qty)}</span>}
                            <div className="text-[11px] text-[#5C7A8A]">{l.order_uom}{Number(l.order_multiple) > 1 ? ` ×${l.order_multiple}` : ''}{Number(l.min_order_qty) > 1 ? `, min ${l.min_order_qty}` : ''}</div>
                          </td>
                          <td>{l.order_uom} of {num(l.units_per_order_uom)}</td>
                          <td className="text-right font-mono">{num(l.base_qty)}</td>
                          <td className="text-right font-mono" title={l.price ? `${l.price.type}${l.price.source ? `, ${l.price.source}` : ''}, valid from ${when(l.price.valid_from)}` : ''}>
                            {money(l.unit_price, c.currency)}<div className="text-[11px] text-[#5C7A8A]">{l.price?.basis}</div>
                            <div className="text-[11px] text-[#5C7A8A]">{l.price?.type}{l.price?.source ? ` · ${l.price.source}` : ''}</div>
                          </td>
                          <td className="text-right font-mono">{money(l.line_total, c.currency)}</td>
                          <td className="text-[12px]">
                            {num(l.recommendation.order_qty)} {l.order_uom}{l.edited && <span className="ml-1 rounded bg-[#FEF3C7] px-1 text-[#8A5A00]">differs</span>}
                            <div className="text-[#5C7A8A]">on hand {num(l.recommendation.on_hand)}, {num(l.recommendation.daily_demand)}/day</div>
                            {l.blockers.length > 0 && <div className="text-[#991B1B]">{l.blockers.join(', ')}</div>}
                            <button className="text-[#E8654A] underline" onClick={() => setWhy(why === l.line_no ? null : l.line_no)}>{why === l.line_no ? 'Hide basis' : 'Basis'}</button>
                          </td>
                        </tr>
                        {why === l.line_no && (
                          <tr><td colSpan={9} className="pb-3"><LineBasis line={l} /></td></tr>
                        )}
                        </Fragment>
                      ))}
                    </tbody>
                  </table>
                </div>
                {(c.notices.length > 0 || c.blockers.length > 0) && (
                  <div className="mt-3 flex flex-col gap-1">
                    {c.blockers.map((b, i) => <div key={`b${i}`} className="rounded-[8px] bg-[#FEE2E2] px-3 py-1.5 text-[12px] text-[#7F1D1D]">Must fix: {b}</div>)}
                    {c.notices.map((n, i) => <div key={`n${i}`} className="rounded-[8px] bg-[#FFF8E1] px-3 py-1.5 text-[12px] text-[#6B4A00]">Review: {n.message}</div>)}
                  </div>
                )}
                <div className="mt-4 flex flex-wrap items-center gap-2">
                  {editable && <Button variant="secondary" onClick={() => save.mutate()} disabled={!dirty || busy} loading={save.isPending}>Save quantities</Button>}
                  {editable && <Button variant="secondary" onClick={() => refreshTerms.mutate()} disabled={busy} loading={refreshTerms.isPending}>Refresh prices & details</Button>}
                  {p.status === 'draft' && <Button onClick={() => submit.mutate()} disabled={dirty || busy || c.blockers.length > 0} loading={submit.isPending}>Submit for approval</Button>}
                  {p.status === 'awaiting_approval' && (
                    <Button onClick={() => approve.mutate()} disabled={dirty || busy || role !== 'owner'} loading={approve.isPending}
                            title={role !== 'owner' ? 'Only the owner can approve' : `Approves revision ${p.revision} exactly as shown`}>
                      Approve revision {p.revision} — {money(c.totals.estimated_total, c.currency)} to {c.supplier.order_email}
                    </Button>
                  )}
                  {editable && <Button variant="danger" onClick={() => cancel.mutate()} disabled={busy} loading={cancel.isPending}>Cancel order</Button>}
                  {dirty && <span className="text-[12px] text-[#8A5A00]">Save changes first — saving creates revision {p.revision + 1} and needs a new approval.</span>}
                  {p.status === 'awaiting_approval' && role && role !== 'owner' && <span className="text-[12px] text-[#5C7A8A]">Waiting for the owner to approve.</span>}
                </div>
              </Panel>

              {p.progress && <AfterSending po={p} role={role} onChange={refresh} />}

              {p.captured_message && (
                <Panel title="Test send result (captured, not delivered)">
                  <div className="text-[13px]"><b>To:</b> {p.captured_message.to} · <b>Subject:</b> {p.captured_message.subject} · revision {p.captured_message.revision} · {when(p.captured_message.at)}</div>
                  <pre className="mt-2 max-h-[220px] overflow-auto whitespace-pre-wrap rounded-[10px] bg-[#FDF5EF] p-3 text-[12px]">{p.captured_message.body}</pre>
                  <details className="mt-2 text-[12px]"><summary className="cursor-pointer">Attachment {p.captured_message.attachment_name}</summary>
                    <pre className="mt-1 overflow-auto rounded-[10px] bg-[#FDF5EF] p-3">{p.captured_message.attachment_csv}</pre></details>
                </Panel>
              )}

              <div className="grid gap-4 lg:grid-cols-2">
                <Panel title="Approvals and sends">
                  {p.approvals.length === 0 && p.send_attempts.length === 0 && <div className="text-[13px] text-[#5C7A8A]">Nothing yet.</div>}
                  <ul className="flex flex-col gap-1 text-[13px]">
                    {p.approvals.map((a, i) => <li key={`a${i}`}>✓ Revision {a.revision} approved by {a.by} ({a.role}) · {when(a.at)} · {a.digest.slice(0, 10)}…</li>)}
                    {p.send_attempts.map((s, i) => <li key={`s${i}`}>→ Revision {s.revision}: <b>{s.outcome}</b> ({s.mode}{s.recipient ? `, ${s.recipient}` : ''}) · {when(s.at)}<div className="text-[12px] text-[#5C7A8A]">{s.detail}</div></li>)}
                    {p.send_job && p.status === 'queued' && <li className="text-[#1D4ED8]">Send job: {p.send_job.status} (attempt {p.send_job.attempts})</li>}
                  </ul>
                </Panel>
                <Panel title="History">
                  <ul className="flex flex-col gap-1 text-[13px]">
                    {p.history.map((h, i) => <li key={i}><span className="font-mono text-[12px] text-[#5C7A8A]">{when(h.at)}</span> {h.action.replace('po.', '')} — {h.by}{h.reason ? ` (${h.reason})` : ''}</li>)}
                  </ul>
                  <div className="mt-2 text-[12px] text-[#5C7A8A]">Revisions: {p.revisions.map((r) => `#${r.revision} ${money(r.total)}`).join(' · ')}</div>
                </Panel>
              </div>
            </>
          );
        })()}
      </RequireSession>
    </OpsShell>
  );
}

// The recommendation this line was built from, as it stood when the revision was made.
function LineBasis({ line }: { line: PoLine }) {
  const r = line.recommendation;
  return (
    <div className="rounded-[12px] border border-[#F1E4DA] bg-[#FFFAF6] p-3 text-[12px]">
      {r.status === 'other_supplier' && <div className="mb-2 text-[#8A5A00]">The current plan buys this item from another supplier.</div>}
      {r.order_date && (
        <div className="mb-2 flex flex-wrap gap-4">
          <span>Order placed <b className="font-mono">{r.order_date}</b></span>
          <span>Delivered (end of day) <b className="font-mono">{r.delivery_date}</b></span>
          <span>On the shelf from <b className="font-mono">{r.usable_date}</b></span>
        </div>
      )}
      <ol className="flex flex-col gap-0.5">
        {(r.steps ?? []).map((s, i) => <li key={i}><b>{s.label}:</b> {s.value}{s.formula && <span className="text-[#5C7A8A]"> — {s.formula}</span>}</li>)}
      </ol>
      <div className="mt-2 text-[#5C7A8A]">Stock as of {when(r.stock_as_of)} ({r.stock_source ?? '—'}) · sales through {when(r.sales_through)}</div>
    </div>
  );
}
