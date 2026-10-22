// Suppliers: who you order from, on what terms, and which of your items they sell at what price.

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { SymbolIcon } from '../components/ui';
import { api, loadSession, type VariantLite } from '../ops/api';
import { Badge, Button, EmptyState, ErrorBox, Field, Notice, OpsShell, Panel, RequireSession, Skeleton, inputCls, money, num } from '../ops/kit';
import { OrdersShell } from './Orders';

type Supplier = {
  id: string; name: string; relationship_status: string; ordering_channel: string | null; merchant_account_number: string | null;
  currency: string; payment_terms: string; payment_net_days: number | null; min_order_amount: string | null; freight_notes: string | null;
  default_lead_time_days: number | null; delivery_weekdays: number[]; version: number; credit_hold: boolean;
};
type Item = { id: string; supplier_sku: string; description: string | null; variant_id: string | null; mapping_status: string; order_uom: string;
  units_per_order_uom: string; order_multiple: string; min_order_qty: string; status: string; version: number };
type Contact = { id: string; email: string | null; is_order_recipient: boolean; verified_at: string | null };

const STATUS_TONE: Record<string, 'good' | 'warn' | 'neutral'> = { approved: 'good', candidate: 'warn', suspended: 'neutral', archived: 'neutral' };
const STATUS_LABEL: Record<string, string> = { approved: 'Ready to order', candidate: 'Setting up', suspended: 'Paused', archived: 'Archived' };

export function SuppliersPage() {
  const s = loadSession();
  const list = useQuery({ queryKey: ['suppliers', s?.tenantId], queryFn: () => api<Supplier[]>('/suppliers'), enabled: !!s?.tenantId });
  const [adding, setAdding] = useState(false);
  return (
    <OrdersShell active="suppliers" actions={<Button onClick={() => setAdding(true)}>Add supplier</Button>}>
        {adding && <NewSupplier onClose={() => setAdding(false)} />}
        {list.isLoading && <Skeleton rows={3} />}
        <ErrorBox error={list.error} />
        {list.data?.length === 0 && !adding && <Panel><EmptyState icon="storefront" title="No suppliers yet" body="Add the distributors and brands you buy from. Order suggestions need at least one supplier with prices."><Button onClick={() => setAdding(true)}>Add your first supplier</Button></EmptyState></Panel>}
        {list.data && list.data.length > 0 && (
          <Panel padded={false}>
            <ul className="divide-y divide-[#EDEFF2]">
              {list.data.map((x) => (
                <li key={x.id}><Link to={`/app/orders/suppliers/${x.id}`} className="flex flex-wrap items-center justify-between gap-2 px-4 py-3 hover:bg-[#F8F9FA] md:px-5">
                  <span><span className="block font-medium">{x.name}</span>
                    <span className="text-[12px] text-[#66707A]">{x.default_lead_time_days != null ? `${x.default_lead_time_days}-day lead time` : 'lead time not set'} · {x.min_order_amount != null ? `min ${money(x.min_order_amount, x.currency)}` : 'no minimum set'}
                      {x.payment_terms === 'net' && x.payment_net_days ? ` · net ${x.payment_net_days}` : ''}</span></span>
                  <Badge tone={STATUS_TONE[x.relationship_status]}>{STATUS_LABEL[x.relationship_status]}</Badge>
                </Link></li>
              ))}
            </ul>
          </Panel>
        )}
    </OrdersShell>
  );
}

const DAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];

function NewSupplier({ onClose }: { onClose: () => void }) {
  const s = loadSession()!;
  const qc = useQueryClient();
  const navigate = useNavigate();
  const [f, setF] = useState({ name: '', email: '', account: '', noAccount: false, terms: 'net', net: '30', lead: '3', min: '0', freight: '', days: [] as number[] });
  const set = (patch: Partial<typeof f>) => setF((x) => ({ ...x, ...patch }));
  const create = useMutation({
    mutationFn: async () => {
      const tz = Intl.DateTimeFormat().resolvedOptions().timeZone;
      const sup = await api<Supplier>('/suppliers', { body: {
        name: f.name, currency: 'USD', timezone: tz, ordering_channel: 'email', payment_terms: f.terms,
        payment_net_days: f.terms === 'net' ? Number(f.net) : null, default_lead_time_days: Number(f.lead), min_order_amount: f.min || '0',
        freight_notes: f.freight || 'Not specified', delivery_weekdays: f.days,
        ...(f.noAccount ? { merchant_account_required: false } : { merchant_account_number: f.account }),
      } });
      const c = await api<Contact>(`/suppliers/${sup.id}/contacts`, { body: { email: f.email, is_order_recipient: true } });
      await api(`/suppliers/${sup.id}/contacts/${c.id}/verify`, { method: 'POST' });
      await api(`/suppliers/${sup.id}/coverage`, { method: 'PUT', body: { location_ids: [s.locationId] } });
      const fresh = await api<Supplier>(`/suppliers/${sup.id}`);
      await api(`/suppliers/${sup.id}/status`, { body: { version: fresh.version, status: 'approved' } });
      return sup;
    },
    onSuccess: (sup) => { qc.invalidateQueries({ queryKey: ['suppliers'] }); qc.invalidateQueries({ queryKey: ['readiness'] }); navigate(`/app/orders/suppliers/${sup.id}`); },
  });
  return (
    <Panel title="Add a supplier" aside={<button className="text-[13px] text-[#66707A] underline" onClick={onClose}>Cancel</button>}>
      <form className="grid gap-4 md:grid-cols-2" onSubmit={(e) => { e.preventDefault(); create.mutate(); }}>
        <Field label="Supplier name"><input className={inputCls} value={f.name} onChange={(e) => set({ name: e.target.value })} required /></Field>
        <Field label="Order email" hint="Where orders go. By saving you confirm this is their ordering address."><input className={inputCls} type="email" value={f.email} onChange={(e) => set({ email: e.target.value })} required /></Field>
        <Field label="Your account number with them" hint={<label className="flex items-center gap-1"><input type="checkbox" checked={f.noAccount} onChange={(e) => set({ noAccount: e.target.checked })} />They don't use account numbers</label>}>
          <input className={inputCls} value={f.account} onChange={(e) => set({ account: e.target.value })} disabled={f.noAccount} required={!f.noAccount} /></Field>
        <div className="grid grid-cols-2 gap-3">
          <Field label="Payment terms"><select className={inputCls} value={f.terms} onChange={(e) => set({ terms: e.target.value })}>
            <option value="net">Net (invoice)</option><option value="prepaid">Prepaid</option><option value="cod">Cash on delivery</option><option value="card_on_file">Card on file</option></select></Field>
          {f.terms === 'net' && <Field label="Days"><input className={inputCls} inputMode="numeric" value={f.net} onChange={(e) => set({ net: e.target.value })} /></Field>}
        </div>
        <div className="grid grid-cols-2 gap-3">
          <Field label="Lead time (days)" hint="Order to delivery."><input className={inputCls} inputMode="numeric" value={f.lead} onChange={(e) => set({ lead: e.target.value })} required /></Field>
          <Field label="Minimum order ($)" hint="0 if none."><input className={inputCls} inputMode="decimal" value={f.min} onChange={(e) => set({ min: e.target.value })} required /></Field>
        </div>
        <Field label="Delivery days" hint="Leave empty if they deliver any day.">
          <div className="flex flex-wrap gap-1">{DAYS.map((d, i) => (
            <button type="button" key={d} onClick={() => set({ days: f.days.includes(i + 1) ? f.days.filter((x) => x !== i + 1) : [...f.days, i + 1].sort() })}
              className={`rounded-[8px] border px-2.5 py-1.5 text-[13px] ${f.days.includes(i + 1) ? 'border-[#2457C5] bg-[#EAF0FB] text-[#2457C5]' : 'border-[#D5DAE0]'}`}>{d}</button>))}</div>
        </Field>
        <Field label="Shipping terms" hint="e.g. free over $250, else $15"><input className={inputCls} value={f.freight} onChange={(e) => set({ freight: e.target.value })} /></Field>
        <div className="md:col-span-2"><ErrorBox error={create.error} /></div>
        <div className="md:col-span-2"><Button type="submit" size="lg" loading={create.isPending}>Save supplier</Button></div>
      </form>
    </Panel>
  );
}

export function SupplierPage() {
  const { id } = useParams();
  const s = loadSession();
  const qc = useQueryClient();
  const sup = useQuery({ queryKey: ['supplier', id], queryFn: () => api<Supplier>(`/suppliers/${id}`), enabled: !!s?.tenantId });
  const contacts = useQuery({ queryKey: ['contacts', id], queryFn: () => api<Contact[]>(`/suppliers/${id}/contacts`), enabled: !!s?.tenantId });
  const items = useQuery({ queryKey: ['supplier-items', id], queryFn: () => api<Item[]>(`/suppliers/${id}/items`), enabled: !!s?.tenantId });
  const variants = useQuery({ queryKey: ['variants'], queryFn: () => api<VariantLite[]>('/variants'), enabled: !!s?.tenantId });
  const check = useQuery({ queryKey: ['approval-check', id], queryFn: () => api<{ approvable: boolean; blockers: string[] }>(`/suppliers/${id}/approval-check`), enabled: !!sup.data && sup.data.relationship_status !== 'approved' });
  const approve = useMutation({ mutationFn: () => api(`/suppliers/${id}/status`, { body: { version: sup.data!.version, status: 'approved' } }), onSuccess: () => qc.invalidateQueries({ queryKey: ['supplier', id] }) });
  const refresh = () => { qc.invalidateQueries({ queryKey: ['supplier-items', id] }); qc.invalidateQueries({ queryKey: ['readiness'] }); };
  const x = sup.data;
  const byId = Object.fromEntries((variants.data ?? []).map((v) => [v.id, v]));
  return (
    <OpsShell active="orders" title={x?.name ?? 'Supplier'} subtitle={<Link to="/app/orders/suppliers" className="hover:underline">← Suppliers</Link>}>
      <RequireSession>
        {sup.isLoading && <Skeleton rows={3} />}
        <ErrorBox error={sup.error} />
        {x && (
          <Panel title="Terms" aside={<Badge tone={STATUS_TONE[x.relationship_status]}>{STATUS_LABEL[x.relationship_status]}</Badge>}>
            <dl className="grid grid-cols-2 gap-x-6 gap-y-2 text-[14px] md:grid-cols-4">
              <div><dt className="text-[12px] text-[#66707A]">Order email</dt><dd>{contacts.data?.find((c) => c.is_order_recipient && c.verified_at)?.email ?? '—'}</dd></div>
              <div><dt className="text-[12px] text-[#66707A]">Account #</dt><dd>{x.merchant_account_number ?? 'none used'}</dd></div>
              <div><dt className="text-[12px] text-[#66707A]">Lead time</dt><dd>{x.default_lead_time_days ?? '—'} days{x.delivery_weekdays.length ? ` · delivers ${x.delivery_weekdays.map((d) => DAYS[d - 1]).join(', ')}` : ''}</dd></div>
              <div><dt className="text-[12px] text-[#66707A]">Minimum · payment</dt><dd>{money(x.min_order_amount, x.currency)} · {x.payment_terms === 'net' ? `net ${x.payment_net_days}` : x.payment_terms}</dd></div>
            </dl>
            {x.relationship_status !== 'approved' && check.data && (
              <div className="mt-4">{check.data.approvable ? <Button onClick={() => approve.mutate()} loading={approve.isPending}>Mark ready to order</Button>
                : <Notice>Before ordering: {check.data.blockers.map((b) => b.replace(/_/g, ' ')).join(', ')}.</Notice>}<ErrorBox error={approve.error} /></div>
            )}
          </Panel>
        )}
        <Panel title="Items and prices" aside={<Link to={`/app/settings/data/import?kind=supplier_price_list&supplier=${id}`}><Button variant="secondary"><SymbolIcon icon="upload_file" family="rounded" className="text-[18px]" />Upload price list</Button></Link>}>
          {items.data?.length === 0 && <div className="mb-3 text-[14px] text-[#66707A]">No items yet. Upload their price list, or add items one by one below.</div>}
          <ul className="flex flex-col divide-y divide-[#EDEFF2]">
            {items.data?.map((it) => <ItemRow key={it.id} it={it} variant={it.variant_id ? byId[it.variant_id] : undefined} variants={variants.data ?? []} currency={x?.currency ?? 'USD'} onChange={refresh} />)}
          </ul>
          <AddItem supplierId={id!} variants={variants.data ?? []} currency={x?.currency ?? 'USD'} onDone={refresh} />
        </Panel>
      </RequireSession>
    </OpsShell>
  );
}

function ItemRow({ it, variant, variants, currency, onChange }: { it: Item; variant?: VariantLite; variants: VariantLite[]; currency: string; onChange: () => void }) {
  const prices = useQuery({ queryKey: ['prices', it.id], queryFn: () => api<{ unit_price: string; superseded_at: string | null; expires_at: string | null }[]>(`/supplier-items/${it.id}/prices`) });
  const [pick, setPick] = useState(it.variant_id ?? '');
  const decide = useMutation({ mutationFn: () => api(`/supplier-items/${it.id}/mapping-decision`, { body: { version: it.version, decision: 'confirmed', variant_id: pick } }), onSuccess: onChange });
  const current = prices.data?.find((p) => !p.superseded_at);
  return (
    <li className="flex flex-wrap items-center justify-between gap-3 py-3 text-[14px]">
      <span className="min-w-0"><span className="block font-semibold">{it.supplier_sku}{it.description ? ` · ${it.description}` : ''}</span>
        <span className="text-[12px] text-[#66707A]">{it.order_uom} of {num(it.units_per_order_uom)} · {current ? `${money(current.unit_price, currency)} per ${it.order_uom}` : 'no price yet'}</span></span>
      {it.mapping_status === 'confirmed' ? <span className="text-[13px]">Your item: <b>{variant?.name ?? '—'}</b></span> : (
        <span className="flex flex-wrap items-center gap-2">
          <select aria-label={`Your item for ${it.supplier_sku}`} className={inputCls} value={pick} onChange={(e) => setPick(e.target.value)}>
            <option value="">Which of your items is this?</option>{variants.map((v) => <option key={v.id} value={v.id}>{v.name} ({v.sku})</option>)}</select>
          <Button size="sm" onClick={() => decide.mutate()} disabled={!pick} loading={decide.isPending}>Confirm</Button>
          <ErrorBox error={decide.error} />
        </span>
      )}
    </li>
  );
}

function AddItem({ supplierId, variants, currency, onDone }: { supplierId: string; variants: VariantLite[]; currency: string; onDone: () => void }) {
  const [open, setOpen] = useState(false);
  const [f, setF] = useState({ variant: '', sku: '', uom: 'case', per: '12', price: '' });
  const add = useMutation({
    mutationFn: async () => {
      const it = await api<Item>(`/suppliers/${supplierId}/items`, { body: { supplier_sku: f.sku, order_uom: f.uom, units_per_order_uom: f.per } });
      const confirmed = await api<Item>(`/supplier-items/${it.id}/mapping-decision`, { body: { version: it.version, decision: 'confirmed', variant_id: f.variant } });
      await api(`/supplier-items/${confirmed.id}/prices`, { body: { unit_price: f.price, currency, price_type: 'price_list', order_uom: f.uom, units_per_order_uom: f.per, source_ref: 'Entered in Tabula' } });
    },
    onSuccess: () => { setF({ variant: '', sku: '', uom: 'case', per: '12', price: '' }); setOpen(false); onDone(); },
  });
  if (!open) return <div className="mt-3"><Button variant="ghost" onClick={() => setOpen(true)}>+ Add an item</Button></div>;
  return (
    <form className="mt-4 grid gap-3 rounded-[8px] bg-[#F8F9FA] p-4 md:grid-cols-[1.5fr_1fr_100px_90px_120px_auto] md:items-end" onSubmit={(e) => { e.preventDefault(); add.mutate(); }}>
      <Field label="Your item"><select className={inputCls} value={f.variant} onChange={(e) => setF({ ...f, variant: e.target.value })} required>
        <option value="">Choose…</option>{variants.map((v) => <option key={v.id} value={v.id}>{v.name} ({v.sku})</option>)}</select></Field>
      <Field label="Their SKU"><input className={inputCls} value={f.sku} onChange={(e) => setF({ ...f, sku: e.target.value })} required /></Field>
      <Field label="Sold by"><input className={inputCls} value={f.uom} onChange={(e) => setF({ ...f, uom: e.target.value })} required /></Field>
      <Field label="Units each"><input className={inputCls} inputMode="decimal" value={f.per} onChange={(e) => setF({ ...f, per: e.target.value })} required /></Field>
      <Field label={`Price per ${f.uom || 'unit'}`}><input className={inputCls} inputMode="decimal" value={f.price} onChange={(e) => setF({ ...f, price: e.target.value })} required /></Field>
      <Button type="submit" loading={add.isPending}>Add</Button>
      <div className="md:col-span-6"><ErrorBox error={add.error} /></div>
    </form>
  );
}
