// Settings: the store (details, delivery address, test mode), where its data comes from, and the team.

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useEffect, useState } from 'react';
import { api, loadSession, type Location } from '../ops/api';
import { Badge, Button, ErrorBox, Field, Notice, OpsShell, PageTabs, Panel, RequireSession, TestModeTag, inputCls, useMe } from '../ops/kit';

export function SettingsTabs({ active }: { active: 'store' | 'data' | 'team' }) {
  return <PageTabs active={active} items={[
    { key: 'store', label: 'Store', to: '/app/settings' },
    { key: 'data', label: 'Data sources', to: '/app/settings/data' },
    { key: 'team', label: 'Team', to: '/app/settings/team' },
  ]} />;
}

export function SettingsPage() {
  return <OpsShell active="settings" title="Settings" tabs={<SettingsTabs active="store" />}><RequireSession><Settings /></RequireSession></OpsShell>;
}

export function TeamPage() {
  const s = loadSession();
  const me = useMe();
  const role = me.data?.memberships.find((x) => x.tenant_id === s?.tenantId)?.role;
  return (
    <OpsShell active="settings" title="Settings" tabs={<SettingsTabs active="team" />}>
      <RequireSession>{role === 'owner' ? <Team /> : <Panel><div className="text-[13px] text-[#66707A]">Only the owner manages the team.</div></Panel>}</RequireSession>
    </OpsShell>
  );
}

function Settings() {
  const s = loadSession()!;
  const me = useMe();
  const m = me.data?.memberships.find((x) => x.tenant_id === s.tenantId);
  const qc = useQueryClient();
  const locations = useQuery({ queryKey: ['locations', s.tenantId], queryFn: () => api<Location[]>('/locations') });
  const loc = locations.data?.find((l) => l.id === s.locationId);
  const [addr, setAddrRaw] = useState({ address_line1: '', city: '', region: '', postal_code: '', country: 'US' });
  const [touched, setTouched] = useState(false);
  const setAddr = (a: typeof addr) => { setTouched(true); setAddrRaw(a); };
  useEffect(() => { if (loc && !touched) setAddrRaw({ address_line1: loc.address_line1 ?? '', city: loc.city ?? '', region: loc.region ?? '', postal_code: loc.postal_code ?? '', country: loc.country ?? 'US' }); }, [loc?.id]); // eslint-disable-line react-hooks/exhaustive-deps
  const saveAddr = useMutation({ mutationFn: () => api(`/locations/${s.locationId}/address`, { method: 'PUT', body: addr }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['locations'] }); qc.invalidateQueries({ queryKey: ['readiness'] }); } });
  return (
    <>
      <Panel title="Store">
        <dl className="grid grid-cols-2 gap-4 text-[14px] md:grid-cols-4">
          <div><dt className="text-[12px] text-[#66707A]">Name</dt><dd className="font-semibold">{m?.tenant_name}{m?.is_sample && <> <Badge tone="info">sample</Badge></>}</dd></div>
          <div><dt className="text-[12px] text-[#66707A]">Business</dt><dd className="capitalize">{m?.business_type ?? '—'}</dd></div>
          <div><dt className="text-[12px] text-[#66707A]">Currency</dt><dd>{m?.currency}</dd></div>
          <div><dt className="text-[12px] text-[#66707A]">Time zone · your role</dt><dd>{loc?.timezone} · <span className="capitalize">{m?.role}</span></dd></div>
        </dl>
      </Panel>
      <Panel title="Delivery address" aside={<span className="text-[12px] text-[#66707A]">printed on every order</span>}>
        <form className="grid gap-3 md:grid-cols-[2fr_1fr_100px_120px_90px_auto] md:items-end" onSubmit={(e) => { e.preventDefault(); saveAddr.mutate(); }}>
          <Field label="Street"><input className={inputCls} value={addr.address_line1} onChange={(e) => setAddr({ ...addr, address_line1: e.target.value })} required /></Field>
          <Field label="City"><input className={inputCls} value={addr.city} onChange={(e) => setAddr({ ...addr, city: e.target.value })} required /></Field>
          <Field label="State"><input className={inputCls} value={addr.region} onChange={(e) => setAddr({ ...addr, region: e.target.value })} /></Field>
          <Field label="ZIP"><input className={inputCls} value={addr.postal_code} onChange={(e) => setAddr({ ...addr, postal_code: e.target.value })} required /></Field>
          <Field label="Country"><input className={inputCls} value={addr.country} maxLength={2} onChange={(e) => setAddr({ ...addr, country: e.target.value.toUpperCase() })} required /></Field>
          <Button type="submit" loading={saveAddr.isPending}>Save</Button>
        </form>
        <div className="mt-2"><ErrorBox error={saveAddr.error} />{saveAddr.isSuccess && <span className="text-[13px] text-[#1F7A4D]">Saved.</span>}</div>
      </Panel>
      <Panel title="Sending orders" aside={<TestModeTag />}>
        <p className="text-[13px] leading-relaxed text-[#3B444D]">When the owner approves an order, Tabula prepares the email and keeps it — it is not sent to the supplier. Record the supplier's answer and the delivery yourself on the order. Tabula makes no payments.</p>
      </Panel>
    </>
  );
}

function Team() {
  const s = loadSession()!;
  const members = useQuery({ queryKey: ['members', s.tenantId], queryFn: () => api<{ user_id: string; email: string | null; role: string }[]>('/members') });
  const [email, setEmail] = useState('');
  const [role, setRole] = useState('manager');
  const add = useMutation({ mutationFn: () => api<{ email: string; has_account: boolean; invite_token: string | null }>('/members/invite', { body: { email: email.trim(), role } }),
    onSuccess: () => { setEmail(''); members.refetch(); } });
  const link = add.data?.invite_token ? `${location.origin}/signup?invite=${encodeURIComponent(add.data.invite_token)}&email=${encodeURIComponent(add.data.email)}` : null;
  return (
    <Panel title="Team">
      <ul className="mb-4 flex flex-col divide-y divide-[#EDEFF2] text-[14px]">
        {members.data?.map((x) => <li key={x.user_id} className="flex justify-between py-2"><span>{x.email}</span><span className="capitalize text-[#66707A]">{x.role}</span></li>)}
      </ul>
      <form className="grid gap-3 md:grid-cols-[1fr_180px_auto] md:items-end" onSubmit={(e) => { e.preventDefault(); add.mutate(); }}>
        <Field label="Invite by email" hint="You get a one-time sign-up link to pass on. Only the owner approves orders."><input className={inputCls} type="email" value={email} onChange={(e) => setEmail(e.target.value)} required /></Field>
        <Field label="Role"><select className={inputCls} value={role} onChange={(e) => setRole(e.target.value)}>
          <option value="manager">Manager — orders, suppliers, stock</option><option value="receiver">Receiver — deliveries and counts</option><option value="bookkeeper">Bookkeeper — imports, prices</option></select></Field>
        <Button type="submit" variant="secondary" loading={add.isPending}>Add</Button>
      </form>
      <div className="mt-2"><ErrorBox error={add.error} /></div>
      {add.data?.has_account && <Notice tone="ok">{add.data.email} already has a Tabula account — they'll see this store when they sign in.</Notice>}
      {link && (
        <Notice tone="info">
          <b>Send this link to {add.data!.email}</b> (it is shown only once and works for 14 days). Tabula doesn't email it in this version.
          <div className="mt-2 flex flex-wrap items-center gap-2">
            <input aria-label="Invite link" readOnly className={inputCls + ' flex-1 font-mono text-[12px]'} value={link} onFocus={(e) => e.target.select()} />
            <Button variant="secondary" size="sm" onClick={() => navigator.clipboard?.writeText(link)}>Copy</Button>
          </div>
        </Notice>
      )}
    </Panel>
  );
}
