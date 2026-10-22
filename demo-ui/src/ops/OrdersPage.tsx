// One purchase order. First what is being bought — items, quantities, cost, where it goes — and the
// one next step; then the supplier's answer and deliveries; the working (calculation, the email as
// kept, approvals, history) is folded away until asked for. Decisions are never folded away:
// quantities that differ from the suggestion, notices about prices, and whether it was really sent.

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Fragment, useEffect, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { cn } from '../components/ui';
import { api, loadSession, type Me, type PoDetail, type PoLine } from './api';
import { AfterSending } from './AfterSending';
import {
  Button, ButtonLink, Disclosure, ErrorBox, Notice, OpsShell, Panel, RequireSession, Skeleton, StatusChip, day, money, num, td, tdNum, th, thNum, when,
} from './kit';

const PRICE_TYPE: Record<string, string> = { price_list: 'price list', contract: 'contract price', quote: 'quote', invoice: 'from an invoice' };
const OUTCOME: Record<string, string> = {
  captured: 'Kept in test mode (not emailed)', refused: 'Not sent', blocked: 'Stopped before sending', failed: 'Not sent',
  skipped: 'Skipped — the order changed', unknown: 'Outcome unknown',
};
const HISTORY: Record<string, string> = {
  'po.drafted': 'Draft created', 'po.revised': 'Changed', 'po.submitted': 'Sent for approval', 'po.approved': 'Approved',
  'po.test_sent': 'Kept in test mode (not emailed)', 'po.send_refused': 'Not sent', 'po.send_blocked': 'Stopped before sending',
  'po.cancelled': 'Cancelled', 'po.reply_recorded': 'Supplier reply added', 'po.reply_applied': 'Supplier reply applied',
  'po.change_decided': 'Change decided', 'po.received': 'Delivery recorded', 'po.issue_resolved': 'Issue resolved',
  'po.send_reconciled': 'Send outcome checked', 'po.delivery_resolved': 'Delivery outcome recorded', 'po.reply_dismissed': 'Reply dismissed',
};
const EDITABLE = ['draft', 'awaiting_approval', 'queued', 'failed'];

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
  useEffect(() => {
    if (po.data) setQty(Object.fromEntries(po.data.content.lines.map((l) => [l.line_no, l.order_qty])));
  }, [po.data?.revision]); // eslint-disable-line react-hooks/exhaustive-deps

  const refresh = () => { qc.invalidateQueries({ queryKey: ['po', id] }); qc.invalidateQueries({ queryKey: ['pos'] }); qc.invalidateQueries({ queryKey: ['overview'] }); };
  const useAct = (path: string, body: (p: PoDetail) => unknown, method = 'POST') =>
    useMutation({ mutationFn: () => api<PoDetail>(`/purchase-orders/${id}/${path}`, { method, body: body(po.data!) }), onSuccess: refresh });
  const save = useAct('lines', (p) => ({ revision: p.revision, lines: p.content.lines.filter((l) => qty[l.line_no] !== l.order_qty).map((l) => ({ line_no: l.line_no, order_qty: qty[l.line_no] })) }), 'PATCH');
  const submit = useAct('submit', (p) => ({ revision: p.revision }));
  const approve = useAct('approve', (p) => ({ revision: p.revision, digest: p.digest }));
  const refreshTerms = useAct('refresh', (p) => ({ revision: p.revision }));
  const cancel = useAct('cancel', () => ({ reason: 'Cancelled from order page' }));

  const p = po.data;
  const c = p?.content;
  const editable = !!p && EDITABLE.includes(p.status);
  const dirty = !!c && c.lines.some((l) => qty[l.line_no] !== undefined && qty[l.line_no] !== l.order_qty);
  const busy = save.isPending || submit.isPending || approve.isPending || refreshTerms.isPending || cancel.isPending;

  // The one main step for this order, at the top right.
  let primary = null;
  if (p && c) {
    if (dirty) primary = <Button onClick={() => save.mutate()} loading={save.isPending} disabled={busy}>Save quantities</Button>;
    else if (p.status === 'draft') primary = <Button onClick={() => submit.mutate()} disabled={busy || c.blockers.length > 0} loading={submit.isPending}>Submit for approval</Button>;
    else if (p.status === 'awaiting_approval') primary = (
      <Button onClick={() => approve.mutate()} disabled={busy || role !== 'owner'} loading={approve.isPending}
        title={role !== 'owner' ? 'Only the owner can approve' : `Approves version ${p.revision} exactly as shown`}>
        Approve version {p.revision} · {money(c.totals.estimated_total, c.currency)}</Button>);
    else if (p.status === 'failed') primary = <Button onClick={() => refreshTerms.mutate()} disabled={busy} loading={refreshTerms.isPending}>Refresh prices & details</Button>;
    else if (p.progress && !['closed', 'cancelled'].includes(p.status)) primary = p.awaiting_reply && p.status !== 'partially_received'
      ? <><ButtonLink to={`/app/receiving/${p.id}`} variant="secondary">Record a delivery</ButtonLink><ButtonLink to="#replies">Record supplier's answer</ButtonLink></>
      : <ButtonLink to={`/app/receiving/${p.id}`}>Record a delivery</ButtonLink>;
  }

  return (
    <OpsShell active="orders" title={p ? <>{p.number} <span className="font-normal text-[#66707A]">· {p.supplier}</span></> : 'Purchase order'}
      subtitle={<span className="flex flex-wrap items-center gap-x-3 gap-y-1"><Link to="/app/orders" className="hover:underline">← Orders</Link>{p && <><StatusChip status={p.status} /><span>version {p.revision}</span></>}</span>}
      actions={primary}>
      <RequireSession>
        {po.isLoading && <Skeleton rows={6} />}
        <ErrorBox error={po.error} onRetry={() => po.refetch()} />
        {p && c && (
          <>
            {[save, submit, approve, refreshTerms, cancel].map((m, i) => <ErrorBox key={i} error={m.error} />)}
            <SendingNote p={p} />
            {c.blockers.map((b, i) => <Notice key={`b${i}`}><b>Must fix before sending:</b> {b}</Notice>)}
            {c.notices.map((n, i) => <Notice key={`n${i}`}><b>Check:</b> {n.message}</Notice>)}
            {p.status === 'failed' && <Notice>Not sent — see “Approvals and sends” below. Refreshing loads current prices into a new version to approve again.</Notice>}
            {p.data.changed_since_check && editable && <Notice>Stock, sales or prices changed since these quantities were checked. Approval re-checks the plan and stops if a suggested quantity moved.</Notice>}
            {p.data.pending_updates.length > 0 && <Notice tone="info">Updates in progress: {p.data.pending_updates.join('; ')}. Approval waits until they finish.</Notice>}
            {p.status === 'awaiting_approval' && role && role !== 'owner' && <Notice tone="info">Waiting for the owner to approve.</Notice>}

            <div className="grid items-start gap-5 lg:grid-cols-[1fr_300px]">
              <Panel padded={false} title="Items" sub={`${c.lines.length} line${c.lines.length > 1 ? 's' : ''}${c.lines.some((l) => l.edited) ? ' · some quantities differ from the suggestion' : ''}`}>
                <div className="overflow-x-auto">
                  <table className="w-full min-w-[640px] border-t border-[#EDEFF2] text-[14px]">
                    <thead className="bg-[#F8F9FA]"><tr>
                      <th className={th}>Item</th><th className={thNum}>Quantity</th><th className={thNum}>Units</th><th className={thNum}>Unit price</th><th className={thNum}>Total</th>
                    </tr></thead>
                    <tbody className="divide-y divide-[#EDEFF2]">
                      {c.lines.map((l) => <ItemRow key={l.line_no} l={l} ccy={c.currency} editable={editable} value={qty[l.line_no] ?? l.order_qty}
                        onChange={(v) => setQty((q) => ({ ...q, [l.line_no]: v }))} />)}
                    </tbody>
                    <tfoot className="border-t border-[#E2E5E9] text-[13px]">
                      <tr><td className={td} colSpan={4}>Items subtotal<div className="text-[12px] text-[#66707A]">Shipping and tax are set by the supplier</div></td><td className={tdNum}>{money(c.totals.subtotal, c.currency)}</td></tr>
                      <tr className="text-[14px] font-semibold"><td className={td} colSpan={4}>Estimated total</td><td className={tdNum}>{money(c.totals.estimated_total, c.currency)}</td></tr>
                    </tfoot>
                  </table>
                </div>
                {editable && (
                  <div className="flex flex-wrap items-center gap-2 border-t border-[#EDEFF2] px-4 py-3 md:px-5">
                    {dirty ? <span className="text-[12px] font-medium text-[#A15C07]">Saving makes version {p.revision + 1}; it needs approval again.</span>
                      : <span className="text-[12px] text-[#66707A]">Change a quantity above to edit the order.</span>}
                    <span className="ml-auto flex gap-2">
                      {dirty && <Button variant="ghost" size="sm" onClick={() => setQty(Object.fromEntries(c.lines.map((l) => [l.line_no, l.order_qty])))}>Undo changes</Button>}
                      <Button variant="ghost" size="sm" onClick={() => refreshTerms.mutate()} disabled={busy} loading={refreshTerms.isPending}>Refresh prices</Button>
                      <Button variant="danger" size="sm" onClick={() => cancel.mutate()} disabled={busy} loading={cancel.isPending}>Cancel order</Button>
                    </span>
                  </div>
                )}
              </Panel>

              <div className="flex flex-col gap-5">
                <Panel title="Supplier">
                  <dl className="flex flex-col gap-2 text-[13px]">
                    <div><dt className="text-[#66707A]">Name</dt><dd className="font-medium">{c.supplier.name}</dd></div>
                    <div><dt className="text-[#66707A]">Order email</dt><dd>{c.supplier.order_email ?? <span className="font-medium text-[#B42318]">none verified</span>}</dd></div>
                    <div className="flex gap-6"><div><dt className="text-[#66707A]">Account</dt><dd>{c.supplier.account_number ?? '—'}</dd></div>
                      <div><dt className="text-[#66707A]">Terms</dt><dd>{c.supplier.payment_terms}</dd></div></div>
                  </dl>
                </Panel>
                <Panel title="Delivery">
                  <dl className="flex flex-col gap-2 text-[13px]">
                    <div><dt className="text-[#66707A]">Deliver to</dt><dd className="font-medium">{c.ship_to.name}</dd>
                      <dd className={cn(!c.ship_to.complete && 'font-medium text-[#B42318]')}>{c.address_text || 'No address — add it in Settings'}</dd></div>
                    <div><dt className="text-[#66707A]">Expected</dt><dd><ExpectedArrival p={p} /></dd></div>
                  </dl>
                </Panel>
              </div>
            </div>

            {p.progress && <AfterSending po={p} role={role} onChange={refresh} />}

            <div className="flex flex-col gap-3">
              <Disclosure title="How the quantities were worked out" sub="stock, sales and supplier terms when this version was made">
                <div className="flex flex-col gap-4">{c.lines.map((l) => <div key={l.line_no}><div className="mb-1 text-[13px] font-semibold">{l.name || l.sku}</div><LineBasis line={l} /></div>)}</div>
              </Disclosure>
              {p.captured_message && (
                <Disclosure title="Order email" sub="kept in Tabula in test mode — not sent">
                  <div className="text-[13px]"><b>To:</b> {p.captured_message.to} · <b>Subject:</b> {p.captured_message.subject} · version {p.captured_message.revision} · {when(p.captured_message.at)}</div>
                  <pre className="mt-2 max-h-[260px] overflow-auto whitespace-pre-wrap rounded-[6px] bg-[#F8F9FA] p-3 font-mono text-[12px]">{p.captured_message.body}</pre>
                  <details className="mt-2 text-[12px]"><summary className="cursor-pointer text-[#2457C5]">Attachment {p.captured_message.attachment_name}</summary>
                    <pre className="mt-1 overflow-auto rounded-[6px] bg-[#F8F9FA] p-3 font-mono">{p.captured_message.attachment_csv}</pre></details>
                </Disclosure>
              )}
              <Disclosure title="Approvals and sends" sub={p.approvals.length ? `${p.approvals.length} approval${p.approvals.length > 1 ? 's' : ''}` : 'none yet'}>
                {p.approvals.length === 0 && p.send_attempts.length === 0 && <div className="text-[13px] text-[#66707A]">Nothing yet.</div>}
                <ul className="flex flex-col gap-1.5 text-[13px]">
                  {p.approvals.map((a, i) => <li key={`a${i}`} title={`Approval fingerprint ${a.digest.slice(0, 12)}…`}>Version {a.revision} approved by {a.by} ({a.role}) · {when(a.at)}</li>)}
                  {p.send_attempts.map((s, i) => <li key={`s${i}`}>Version {s.revision}: <b>{OUTCOME[s.outcome] ?? s.outcome}</b>{s.recipient ? ` · ${s.recipient}` : ''} · {when(s.at)}<div className="text-[12px] text-[#66707A]">{s.detail}</div></li>)}
                  {p.send_job && p.status === 'queued' && <li className="text-[#1F4FB3]">Sending: {p.send_job.status} (attempt {p.send_job.attempts})</li>}
                </ul>
              </Disclosure>
              <Disclosure title="History" sub={`${p.revisions.length} version${p.revisions.length > 1 ? 's' : ''}`}>
                <ul className="flex flex-col gap-1 text-[13px]">
                  {p.history.map((h, i) => <li key={i}><span className="text-[12px] tabular-nums text-[#66707A]">{when(h.at)}</span> {HISTORY[h.action] ?? h.action.replace('po.', '').replace(/_/g, ' ')} — {h.by}{h.reason ? ` (${h.reason})` : ''}</li>)}
                </ul>
                <div className="mt-2 text-[12px] text-[#66707A]">Versions: {p.revisions.map((r) => `v${r.revision} ${money(r.total)}`).join(' · ')}</div>
              </Disclosure>
            </div>
          </>
        )}
      </RequireSession>
    </OpsShell>
  );
}

/** Whether this order reaches the supplier — said plainly where it matters for the decision. */
function SendingNote({ p }: { p: PoDetail }) {
  const to = p.content.supplier.order_email ?? 'the supplier';
  if (p.captured_message) {
    return <Notice tone="info"><b>Test order — not sent.</b> Version {p.captured_message.revision} was kept in Tabula on {when(p.captured_message.at)}; nothing was emailed to {p.captured_message.to}. Record the supplier's answer and the delivery yourself below.</Notice>;
  }
  if (['draft', 'awaiting_approval', 'failed', 'queued'].includes(p.status)) {
    return <Notice tone="info"><b>Test mode:</b> approving keeps this order in Tabula. Nothing is emailed to {to}, and no payment is made.</Notice>;
  }
  return null;
}

function ExpectedArrival({ p }: { p: PoDetail }) {
  const etas = p.progress?.lines.map((l) => l.eta).filter(Boolean).sort() ?? [];
  if (etas.length) return <>{day(etas[0])}{etas.length > 1 && etas[etas.length - 1] !== etas[0] ? ` – ${day(etas[etas.length - 1])}` : ''} <span className="text-[12px] text-[#66707A]">supplier date</span></>;
  const est = p.content.lines.map((l) => l.recommendation.delivery_date).filter(Boolean).sort()[0];
  if (est) return <>{day(est)} <span className="text-[12px] text-[#66707A]">estimate from the supplier's lead time</span></>;
  return <span className="text-[#66707A]">no date yet</span>;
}

function ItemRow({ l, ccy, editable, value, onChange }: { l: PoLine; ccy: string; editable: boolean; value: string; onChange: (v: string) => void }) {
  const suggested = l.recommendation.order_qty;
  const changed = value !== l.order_qty;
  return (
    <Fragment>
      <tr className="align-top">
        <td className={td}>
          <div className="font-medium">{l.name || l.sku}</div>
          <div className="text-[12px] text-[#66707A]">{l.sku} · supplier SKU {l.supplier_sku} · {l.order_uom} of {num(l.units_per_order_uom)}</div>
          {l.edited && suggested && <div className="mt-0.5 text-[12px] font-medium text-[#A15C07]">Differs from the suggestion: suggested {num(suggested)} {l.order_uom}</div>}
          {l.blockers.length > 0 && <div className="mt-0.5 text-[12px] font-medium text-[#B42318]">{l.blockers.join(', ')}</div>}
        </td>
        <td className={tdNum}>
          {editable ? (
            <span className="inline-flex items-center gap-1.5">
              <input aria-label={`Quantity for line ${l.line_no}`} inputMode="decimal" value={value} onChange={(e) => onChange(e.target.value)}
                className={cn('h-8 w-[64px] rounded-[6px] border px-2 text-right font-semibold tabular-nums outline-none focus:border-[#2457C5]', changed ? 'border-[#D08A1E] bg-[#FEF8EC]' : 'border-[#D5DAE0]')} />
              <span className="w-9 text-left text-[12px] text-[#66707A]">{l.order_uom}</span></span>
          ) : <><b className="font-semibold">{num(l.order_qty)}</b> <span className="text-[12px] text-[#66707A]">{l.order_uom}</span></>}
          {(Number(l.order_multiple) > 1 || Number(l.min_order_qty) > 1) && <div className="text-[11px] text-[#66707A]">{Number(l.order_multiple) > 1 ? `in steps of ${l.order_multiple}` : ''}{Number(l.min_order_qty) > 1 ? ` min ${l.min_order_qty}` : ''}</div>}
        </td>
        <td className={tdNum}>{num(l.base_qty)}</td>
        <td className={tdNum} title={l.price ? `valid from ${when(l.price.valid_from)}` : ''}>{money(l.unit_price, ccy)}
          <div className="text-[11px] text-[#66707A]">{l.price ? `${l.price.basis}${PRICE_TYPE[l.price.type] ? ` · ${PRICE_TYPE[l.price.type]}` : ''}` : <span className="text-[#B42318]">no price</span>}</div></td>
        <td className={tdNum}><span className="font-medium">{money(l.line_total, ccy)}</span></td>
      </tr>
    </Fragment>
  );
}

// The recommendation this line was built from, as it stood when the version was made.
function LineBasis({ line }: { line: PoLine }) {
  const r = line.recommendation;
  return (
    <div className="rounded-[6px] bg-[#F8F9FA] p-3 text-[12px]">
      {r.status === 'other_supplier' && <div className="mb-2 font-medium text-[#A15C07]">The current plan buys this item from another supplier.</div>}
      {r.order_date && (
        <div className="mb-2 flex flex-wrap gap-4">
          <span>Ordered <b className="tabular-nums">{day(r.order_date)}</b></span>
          <span>Delivered <b className="tabular-nums">{day(r.delivery_date)}</b></span>
          <span>On the shelf <b className="tabular-nums">{day(r.usable_date)}</b></span>
        </div>
      )}
      <ol className="flex flex-col gap-0.5">
        {(r.steps ?? []).map((s, i) => <li key={i}><b>{s.label}:</b> {s.value}{s.formula && <span className="text-[#66707A]"> — {s.formula}</span>}</li>)}
      </ol>
      <div className="mt-2 text-[#66707A]">Stock as of {when(r.stock_as_of)} ({r.stock_source ?? '—'}) · sales through {when(r.sales_through)}</div>
    </div>
  );
}

