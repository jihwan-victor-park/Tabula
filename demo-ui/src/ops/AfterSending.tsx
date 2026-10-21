// After an order is sent: what the supplier said (reviewed by a person), what is still
// expected, and the owner's decisions on changes. Server state only — nothing is assumed
// from the capture itself.

import { useMutation } from '@tanstack/react-query';
import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { cn } from '../components/ui';
import { api, upload, type PoDetail, type ProgressLine, type Reply, type ReplyReading } from './api';
import { Button, ErrorBox, Notice, Panel, StatusChip, money, num, when } from './kit';

const ACTION_LABEL: Record<string, string> = {
  accept: 'Accepted in full', partial: 'Partly accepted', reject: 'Cannot supply', eta: 'Delivery date only',
  cancel_remaining: 'Remaining cancelled', change: 'Proposes a change', none: 'Not mentioned', unclear: 'Unclear — decide',
};
const CHANGE_LABEL: Record<string, string> = {
  price: 'New price', pack: 'New pack size', substitute: 'Substitute product', qty_increase: 'More than ordered',
};

export function AfterSending({ po, role, onChange }: { po: PoDetail; role?: string; onChange: () => void }) {
  const pr = po.progress!;
  const pending = pr.replies.find((r) => r.status === 'pending_review');
  return (
    <>
      {po.status === 'delivery_unknown' && <DeliveryUnknown po={po} role={role} onChange={onChange} />}
      <Panel title="Supplier answer and delivery" aside={
        <div className="flex items-center gap-2 text-[12px] text-[#5C7A8A]">
          Supplier: <StatusChip status={`ack_${pr.ack_status}`} />
          <Link className="text-[#E8654A] underline" to={`/ops/receiving/${po.id}`}>Record a delivery</Link>
        </div>}>
        <div className="overflow-x-auto">
          <table className="[&_td]:pr-3 [&_th]:pr-3 w-full min-w-[920px] text-[13px]">
            <thead><tr className="text-left text-[#5C7A8A]">
              <th className="py-2">#</th><th>Item</th><th className="text-right">Ordered</th><th className="text-right">Confirmed</th>
              <th className="text-right">Won't come</th><th className="text-right">Arrived (sellable / damaged)</th>
              <th className="text-right">Still expected</th><th className="text-right">Not confirmed</th><th>ETA</th>
            </tr></thead>
            <tbody>
              {pr.lines.map((l) => (
                <tr key={l.line_no} className="border-t border-[#F1E4DA] align-top">
                  <td className="py-2">{l.line_no}</td>
                  <td>
                    <div className="font-medium">{l.sku} <span className="font-mono text-[12px] text-[#5C7A8A]">{l.supplier_sku}</span></div>
                    <div className="text-[11px] text-[#5C7A8A]">{l.order_uom} of {num(l.units_per_order_uom)} · {money(l.unit_price, po.currency)}{l.replaces_line_no ? ` · substitute for line ${l.replaces_line_no}` : ''}</div>
                    {l.pos_pending.length > 0 && <div className="mt-1 text-[11px] font-medium text-[#991B1B]">Stock mismatch: {l.pos_pending.join('; ')}</div>}
                  </td>
                  <td className="text-right font-mono">{num(l.ordered)}</td>
                  <td className="text-right font-mono">{l.confirmed == null ? <span className="text-[#8A5A00]">no answer</span> : num(l.confirmed)}</td>
                  <td className="text-right font-mono">{Number(l.rejected) + Number(l.cancelled) > 0 ? num(String(Number(l.rejected) + Number(l.cancelled))) : ''}</td>
                  <td className="text-right font-mono">{Number(l.received) > 0 ? `${num(l.sellable_received)} / ${num(l.damaged)}` : ''}</td>
                  <td className="text-right font-mono font-semibold">{num(l.outstanding)}</td>
                  <td className="text-right font-mono text-[#8A5A00]">{Number(l.unconfirmed) > 0 ? num(l.unconfirmed) : ''}</td>
                  <td className="font-mono">{l.eta ?? '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="mt-2 text-[11px] text-[#5C7A8A]">
          In the plan: <b>still expected</b> is counted as arriving on the ETA; <b>not confirmed</b> only stops a duplicate order and is never counted as arriving; quantities that won't come are dropped.
        </p>
        {pr.lines.filter((l) => l.proposal).map((l) => <ProposalCard key={l.line_no} po={po} line={l} role={role} onChange={onChange} />)}
        {pr.issues.length > 0 && (
          <div className="mt-3 text-[12px]">
            <b>Damage / issues:</b>{' '}
            {pr.issues.map((i) => <span key={i.id} className="mr-3">line {i.line_no}: {num(i.qty)} {i.kind} <StatusChip status={i.status} /></span>)}
            <Link className="ml-2 text-[#E8654A] underline" to={`/ops/receiving/${po.id}`}>resolve on Receiving</Link>
          </div>
        )}
      </Panel>

      <Panel title="Supplier replies" aside={<span className="text-[12px] text-[#5C7A8A]">A reply changes nothing until you review and apply it.</span>}>
        <AddReply po={po} onChange={onChange} />
        {pending && <ReviewReply key={pending.id} po={po} reply={pending} onChange={onChange} />}
        <ul className="mt-3 flex flex-col gap-2">
          {pr.replies.filter((r) => r.id !== pending?.id).map((r) => (
            <li key={r.id} className="rounded-[10px] border border-[#F1E4DA] px-3 py-2 text-[12px]">
              <div className="flex flex-wrap items-center gap-2"><StatusChip status={r.status} />
                <span>{r.source === 'mock' ? 'Mock reply (generated for testing)' : r.source === 'upload' ? `File ${r.file_name}` : 'Pasted'}</span>
                <span className="text-[#5C7A8A]">supplier time {when(r.replied_at)}</span></div>
              <details className="mt-1"><summary className="cursor-pointer text-[#5C7A8A]">Original text</summary>
                <pre className="mt-1 whitespace-pre-wrap rounded-[8px] bg-[#FDF5EF] p-2">{r.raw_text}</pre></details>
            </li>
          ))}
        </ul>
      </Panel>
    </>
  );
}

function DeliveryUnknown({ po, role, onChange }: { po: PoDetail; role?: string; onChange: () => void }) {
  const [note, setNote] = useState('');
  const m = useMutation({ mutationFn: () => api(`/purchase-orders/${po.id}/delivery-outcome`, { body: { outcome: 'not_received', note } }), onSuccess: onChange });
  return (
    <Notice>
      <b>Delivery unknown.</b> The sender stopped after handing the order over, so the supplier may already have it. It is not resent automatically and the plan keeps holding these quantities.
      Check with the supplier: if they have it, record their reply below; if they confirm they never received it:
      <div className="mt-2 flex flex-wrap items-center gap-2">
        <input className="min-w-[280px] rounded-[8px] border border-[#E8D4C6] px-2 py-1" placeholder="How you confirmed (e.g. phoned the order desk)" value={note} onChange={(e) => setNote(e.target.value)} />
        <Button variant="secondary" onClick={() => m.mutate()} disabled={!note.trim() || role !== 'owner'} loading={m.isPending}>Supplier never received it</Button>
      </div>
      <ErrorBox error={m.error} />
    </Notice>
  );
}

function ProposalCard({ po, line, role, onChange }: { po: PoDetail; line: ProgressLine; role?: string; onChange: () => void }) {
  const p = line.proposal!;
  const decide = useMutation({
    mutationFn: (decision: 'accept' | 'decline') => api(`/purchase-orders/${po.id}/lines/${line.line_no}/proposal`, { body: { decision, proposal_digest: p.digest } }),
    onSuccess: onChange,
  });
  const what = p.kind === 'price' ? `${money(p.was.unit_price, po.currency)} → ${money(p.unit_price!, po.currency)} per ${line.order_uom}`
    : p.kind === 'pack' ? `${num(p.was.units_per_order_uom)} → ${num(p.units_per_order_uom!)} per ${line.order_uom}`
    : p.kind === 'substitute' ? `${p.was.supplier_sku} → ${p.substitute_sku} (${num(p.qty!)} ${line.order_uom})`
    : `${num(p.was.ordered_qty)} → ${num(p.qty!)} ${line.order_uom}`;
  return (
    <div className="mt-3 rounded-[12px] border border-[#F5D58A] bg-[#FFF8E1] p-3 text-[13px]">
      <div><b>Line {line.line_no} — {CHANGE_LABEL[p.kind]}:</b> {what}{p.eta ? ` · ETA ${p.eta}` : ''}</div>
      <div className="mt-1 text-[12px] text-[#6B4A00]">Your approval covered the original terms, so this change needs the owner's decision. Until then the line is held, not counted as arriving.</div>
      <div className="mt-2 flex flex-wrap items-center gap-2">
        <Button onClick={() => decide.mutate('accept')} disabled={role !== 'owner'} loading={decide.isPending && decide.variables === 'accept'}>Accept change</Button>
        <Button variant="danger" onClick={() => decide.mutate('decline')} disabled={role !== 'owner'} loading={decide.isPending && decide.variables === 'decline'}>Decline (line won't come)</Button>
        {role !== 'owner' && <span className="text-[12px] text-[#5C7A8A]">Only the owner decides changes.</span>}
      </div>
      <ErrorBox error={decide.error} />
    </div>
  );
}

const SCENARIOS = [
  ['partial', 'Partial acceptance'], ['accept_all', 'Accept everything'], ['out_of_stock', 'Out of stock'],
  ['price_change', 'Price change'], ['eta_change', 'Later delivery'], ['substitute', 'Substitute offered'],
];

function AddReply({ po, onChange }: { po: PoDetail; onChange: () => void }) {
  const [mode, setMode] = useState<'paste' | 'upload' | 'mock'>('paste');
  const [text, setText] = useState('');
  const [repliedAt, setRepliedAt] = useState('');
  const [file, setFile] = useState<File | null>(null);
  const [scenario, setScenario] = useState('partial');
  const send = useMutation({
    mutationFn: () => {
      const at = repliedAt ? new Date(repliedAt).toISOString() : undefined;
      if (mode === 'upload') {
        const form = new FormData();
        form.append('file', file!);
        if (at) form.append('replied_at', at);
        return upload(`/purchase-orders/${po.id}/replies/upload`, form);
      }
      return api(`/purchase-orders/${po.id}/replies`, { body: mode === 'mock' ? { source: 'mock', scenario } : { source: 'paste', text, replied_at: at } });
    },
    onSuccess: () => { setText(''); setFile(null); onChange(); },
  });
  return (
    <div className="rounded-[12px] border border-[#F1E4DA] p-3">
      <div className="mb-2 flex flex-wrap gap-2 text-[13px]">
        {(['paste', 'upload', 'mock'] as const).map((m) => (
          <button key={m} onClick={() => setMode(m)} className={cn('rounded-full border px-3 py-1', mode === m ? 'border-[#E8654A] bg-[#E8654A14] text-[#B4462F]' : 'border-[#E8D4C6]')}>
            {m === 'paste' ? 'Paste email' : m === 'upload' ? 'Upload file (.txt .eml .csv)' : 'Mock reply (testing)'}
          </button>
        ))}
      </div>
      {mode === 'paste' && <textarea aria-label="Reply text" className="h-[110px] w-full rounded-[10px] border border-[#E8D4C6] p-2 font-mono text-[12px]" value={text} onChange={(e) => setText(e.target.value)} placeholder={'PH-LIT-20: we can only ship 6 case, the rest cannot be supplied.\nDelivery 2026-10-27.'} />}
      {mode === 'upload' && <input aria-label="Reply file" type="file" accept=".txt,.eml,.csv" onChange={(e) => setFile(e.target.files?.[0] ?? null)} className="text-[13px]" />}
      {mode === 'mock' && (
        <label className="flex flex-wrap items-center gap-2 text-[13px]">Scenario
          <select aria-label="Mock scenario" className="rounded-[8px] border border-[#E8D4C6] px-2 py-1" value={scenario} onChange={(e) => setScenario(e.target.value)}>
            {SCENARIOS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
          </select>
          <span className="text-[12px] text-[#5C7A8A]">Generated by Tabula in capture mode; labelled as a mock everywhere.</span>
        </label>
      )}
      {mode !== 'mock' && (
        <label className="mt-2 flex flex-wrap items-center gap-2 text-[12px] text-[#5C7A8A]">Supplier sent it at (if the text has no Date line)
          <input type="datetime-local" className="rounded-[8px] border border-[#E8D4C6] px-2 py-1" value={repliedAt} onChange={(e) => setRepliedAt(e.target.value)} />
        </label>
      )}
      <div className="mt-2"><Button onClick={() => send.mutate()} loading={send.isPending}
        disabled={(mode === 'paste' && !text.trim()) || (mode === 'upload' && !file)}>Read reply</Button></div>
      <div className="mt-2"><ErrorBox error={send.error} /></div>
    </div>
  );
}

type Draft = { line_no: number; action: string; confirmed_qty: string; eta: string; backorder: boolean; change: ReplyReading['change'] };

function ReviewReply({ po, reply, onChange }: { po: PoDetail; reply: Reply; onChange: () => void }) {
  const [draft, setDraft] = useState<Draft[]>([]);
  useEffect(() => {
    setDraft(reply.parsed.lines.map((l) => ({ line_no: l.line_no, action: l.action, confirmed_qty: l.confirmed_qty ?? '', eta: l.eta ?? '', backorder: l.backorder, change: l.change })));
  }, [reply.id]); // eslint-disable-line react-hooks/exhaustive-deps
  const set = (n: number, patch: Partial<Draft>) => setDraft((d) => d.map((x) => (x.line_no === n ? { ...x, ...patch } : x)));
  const apply = useMutation({
    mutationFn: () => api(`/supplier-replies/${reply.id}/apply`, { body: { decisions: draft.map((d) => ({
      line_no: d.line_no, action: d.action, confirmed_qty: d.confirmed_qty || null, eta: d.eta || null, backorder: d.backorder, change: d.change,
    })) } }),
    onSuccess: onChange,
  });
  const dismiss = useMutation({ mutationFn: () => api(`/supplier-replies/${reply.id}/dismiss`, { body: { reason: 'Not about this order' } }), onSuccess: onChange });
  const unclear = draft.some((d) => d.action === 'unclear');
  const lines = Object.fromEntries(po.progress!.lines.map((l) => [l.line_no, l]));
  return (
    <div className="mt-3 rounded-[12px] border border-[#F5D58A] p-3">
      <div className="mb-2 flex flex-wrap items-center gap-2 text-[13px]">
        <StatusChip status="pending_review" />
        <b>{reply.source === 'mock' ? 'Mock reply (generated for testing)' : reply.source === 'upload' ? `File ${reply.file_name}` : 'Pasted reply'}</b>
        <span className="text-[12px] text-[#5C7A8A]">supplier time {when(reply.replied_at)} ({reply.parsed.replied_at_source === 'reply' ? 'from the reply' : reply.parsed.replied_at_source === 'given' ? 'entered by you' : 'time recorded'})</span>
      </div>
      {reply.parsed.warnings.map((w, i) => <div key={i} className="mb-1 text-[12px] text-[#8A5A00]">⚠ {w}</div>)}
      <div className="grid gap-3 lg:grid-cols-[1fr_340px]">
        <table className="[&_td]:pr-3 [&_th]:pr-3 w-full text-[12px]">
          <thead><tr className="text-left text-[#5C7A8A]"><th className="py-1">Line</th><th>Tabula reads</th><th>Qty</th><th>ETA</th><th>Evidence in the reply</th></tr></thead>
          <tbody>
            {draft.map((d) => {
              const reading = reply.parsed.lines.find((l) => l.line_no === d.line_no)!;
              return (
                <tr key={d.line_no} className="border-t border-[#F7EDE5] align-top">
                  <td className="py-1"><b>{reading.supplier_sku}</b><div className="text-[#5C7A8A]">ordered {num(lines[d.line_no]?.ordered)} {lines[d.line_no]?.order_uom}</div></td>
                  <td>
                    <select aria-label={`Action for line ${d.line_no}`} className={cn('rounded-[6px] border px-1 py-0.5', d.action === 'unclear' ? 'border-[#F7B4B4]' : 'border-[#E8D4C6]')}
                            value={d.action} onChange={(e) => set(d.line_no, { action: e.target.value })}>
                      {Object.entries(ACTION_LABEL).filter(([k]) => k !== 'change' || d.change).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
                    </select>
                    {d.action === 'change' && d.change && <div className="mt-1 text-[#8A5A00]">{CHANGE_LABEL[d.change.kind]}: {d.change.unit_price ?? d.change.units_per_order_uom ?? d.change.substitute_sku ?? d.change.qty} — goes to the owner</div>}
                    {d.action === 'partial' && <label className="mt-1 flex items-center gap-1"><input type="checkbox" checked={d.backorder} onChange={(e) => set(d.line_no, { backorder: e.target.checked })} /> rest on backorder (still not confirmed)</label>}
                  </td>
                  <td>{d.action === 'partial' ? <input aria-label={`Confirmed quantity for line ${d.line_no}`} className="w-[60px] rounded-[6px] border border-[#E8D4C6] px-1 text-right font-mono" value={d.confirmed_qty} onChange={(e) => set(d.line_no, { confirmed_qty: e.target.value })} /> : d.action === 'accept' ? num(lines[d.line_no]?.ordered) : ''}</td>
                  <td><input aria-label={`ETA for line ${d.line_no}`} type="date" className="rounded-[6px] border border-[#E8D4C6] px-1" value={d.eta} onChange={(e) => set(d.line_no, { eta: e.target.value })} /></td>
                  <td>{reading.evidence.length ? reading.evidence.map((e, i) => <div key={i} className="font-mono text-[11px]"><span className="text-[#5C7A8A]">L{e.line}:</span> “{e.text}”</div>) : <span className="text-[#5C7A8A]">not mentioned</span>}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
        <pre className="max-h-[220px] overflow-auto whitespace-pre-wrap rounded-[10px] bg-[#FDF5EF] p-2 text-[11px]">{reply.raw_text.split('\n').map((t, i) => `${String(i + 1).padStart(2, ' ')}  ${t}`).join('\n')}</pre>
      </div>
      <div className="mt-3 flex flex-wrap items-center gap-2">
        <Button onClick={() => apply.mutate()} disabled={unclear} loading={apply.isPending}>Apply to the order</Button>
        <Button variant="secondary" onClick={() => dismiss.mutate()} loading={dismiss.isPending}>Dismiss</Button>
        {unclear && <span className="text-[12px] text-[#991B1B]">Decide the unclear lines first.</span>}
      </div>
      <ErrorBox error={apply.error ?? dismiss.error} />
    </div>
  );
}
