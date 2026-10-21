import { useMutation, useQuery } from '@tanstack/react-query';
import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { api, loadSession, saveSession, type DevInfo, type Location, type Me } from './api';
import { Button, EmptyState, ErrorBox, Loading, Notice, OpsShell, Panel } from './kit';

export function SetupPage() {
  const session = loadSession();
  const navigate = useNavigate();
  const [email, setEmail] = useState(session?.user ?? '');
  const [submitted, setSubmitted] = useState(session?.user ?? '');
  const [storeName, setStoreName] = useState('');

  const me = useQuery({
    queryKey: ['me', submitted],
    queryFn: () => api<Me>('/me', { userOverride: submitted }),
    enabled: !!submitted,
  });
  const create = useMutation({
    mutationFn: () => api<{ tenant_id: string; tenant_name: string }>('/tenants', { body: { name: storeName }, userOverride: submitted }),
    onSuccess: (t) => { saveSession({ user: submitted, tenantId: t.tenant_id, tenantName: t.tenant_name }); me.refetch(); },
  });

  const choose = (tenantId: string, tenantName: string) => {
    saveSession({ user: submitted, tenantId, tenantName });
    navigate('/ops/today');
  };

  return (
    <OpsShell active="setup" title="Workspace" icon="storefront">
      <Notice tone="info">
        Local development sign-in: the API trusts the email you type, and only from this computer
        (<code>TABULA_AUTH_MODE=dev</code>, <code>TABULA_ENV=development</code>). Real sign-in uses Auth0.
      </Notice>
      <Panel title="Sign in (local)">
        <form className="flex flex-wrap items-end gap-3" onSubmit={(e) => { e.preventDefault(); setSubmitted(email.trim()); }}>
          <label className="flex flex-col gap-1 text-[13px]">
            Email
            <input className="min-w-[280px] rounded-[10px] border border-[#E8D4C6] px-3 py-2" value={email}
                   onChange={(e) => setEmail(e.target.value)} placeholder="owner@yourstore.com" required />
          </label>
          <Button type="submit">Continue</Button>
        </form>
      </Panel>

      {submitted && (
        <Panel title="Your workspaces">
          {me.isLoading && <Loading />}
          <ErrorBox error={me.error} onRetry={() => me.refetch()} />
          {me.data && me.data.memberships.length === 0 && (
            <EmptyState icon="add_business" title="No workspace yet"
                        body="Run the demo seed script (see README) or create an empty workspace below." />
          )}
          <ul className="flex flex-col gap-2">
            {me.data?.memberships.map((m) => (
              <li key={m.tenant_id} className="flex flex-wrap items-center justify-between gap-2 rounded-[12px] border border-[#E8D4C6] px-4 py-3">
                <div>
                  <div className="font-medium">{m.tenant_name}</div>
                  <div className="text-[12px] text-[#5C7A8A]">Role: {m.role}</div>
                </div>
                <Button variant={session?.tenantId === m.tenant_id ? 'secondary' : 'primary'} onClick={() => choose(m.tenant_id, m.tenant_name)}>
                  {session?.tenantId === m.tenant_id ? 'Current — open' : 'Open'}
                </Button>
              </li>
            ))}
          </ul>
          <DemoWorkspace user={submitted} onCreated={() => me.refetch()} />
          <form className="mt-4 flex flex-wrap items-end gap-3" onSubmit={(e) => { e.preventDefault(); create.mutate(); }}>
            <label className="flex flex-col gap-1 text-[13px]">
              New empty workspace
              <input className="min-w-[240px] rounded-[10px] border border-[#E8D4C6] px-3 py-2" value={storeName}
                     onChange={(e) => setStoreName(e.target.value)} placeholder="Store name" required />
            </label>
            <Button type="submit" variant="secondary" loading={create.isPending}>Create</Button>
          </form>
          <ErrorBox error={create.error} />
        </Panel>
      )}
      {session?.tenantId && <LocationPicker />}
    </OpsShell>
  );
}

function LocationPicker() {
  const session = loadSession()!;
  const locations = useQuery({ queryKey: ['locations', session.tenantId], queryFn: () => api<Location[]>('/locations') });
  const [, force] = useState(0);
  return (
    <Panel title={`Store location — ${session.tenantName}`}>
      {locations.isLoading && <Loading />}
      <ErrorBox error={locations.error} onRetry={() => locations.refetch()} />
      {locations.data?.length === 0 && <EmptyState icon="location_off" title="No locations" body="The demo seed script creates one." />}
      <ul className="flex flex-col gap-2">
        {locations.data?.map((l) => (
          <li key={l.id} className="flex flex-wrap items-center justify-between gap-2 rounded-[12px] border border-[#E8D4C6] px-4 py-3">
            <div>
              <div className="font-medium">{l.name}</div>
              <div className="text-[12px] text-[#5C7A8A]">
                {[l.address_line1, l.city, l.region, l.postal_code, l.country].filter(Boolean).join(', ') || 'No ship-to address'} · {l.timezone} · stock owned by {l.inventory_write_owner}
              </div>
            </div>
            <Button variant={session.locationId === l.id ? 'secondary' : 'primary'}
                    onClick={() => { saveSession({ ...session, locationId: l.id }); force((n) => n + 1); }}>
              {session.locationId === l.id ? 'Selected' : 'Use this location'}
            </Button>
          </li>
        ))}
      </ul>
    </Panel>
  );
}

// Development only (the API answers 404 otherwise): a fictional store with its files already imported.
function DemoWorkspace({ user, onCreated }: { user: string; onCreated: () => void }) {
  const info = useQuery({ queryKey: ['dev-info'], queryFn: () => api<DevInfo>('/dev/info'), retry: false });
  const make = useMutation({ mutationFn: () => api('/dev/demo-workspace', { method: 'POST', userOverride: user }), onSuccess: onCreated });
  if (!info.data) return null;
  return (
    <div className="mt-4 rounded-[12px] border border-dashed border-[#B8CFFB] bg-[#EEF4FF] p-3 text-[13px]">
      <b>Demo store (development only).</b> Creates “Paws & Co (demo)” with fictional suppliers, 28 days of sales, a stock
      count and an open order already imported — so you can go straight to the plan. Sending stays in {info.data.send_mode} mode.
      <div className="mt-2"><Button variant="secondary" onClick={() => make.mutate()} loading={make.isPending}>Create a demo store</Button></div>
      <ErrorBox error={make.error} />
    </div>
  );
}
