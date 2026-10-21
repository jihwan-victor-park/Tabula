// Connections: Square status, which Square location feeds which store, which source owns each
// store's sales, syncs and the nightly reconciliation. Square is read-only for Tabula.

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import { api, loadSession, type ConnectorAccount, type DevInfo, type Location } from './api';
import { Button, EmptyState, ErrorBox, Loading, Notice, OpsShell, Panel, RequireSession, StatusChip, when } from './kit';

export function ConnectionsPage() {
  const session = loadSession();
  const qc = useQueryClient();
  const accounts = useQuery({ queryKey: ['connectors', session?.tenantId], queryFn: () => api<ConnectorAccount[]>('/connectors'), enabled: !!session?.tenantId });
  const dev = useQuery({ queryKey: ['dev-info'], queryFn: () => api<DevInfo>('/dev/info'), retry: false });
  const refresh = () => qc.invalidateQueries({ queryKey: ['connectors'] });
  const connect = useMutation({
    mutationFn: async () => {
      const { authorize_url } = await api<{ authorize_url: string }>('/connectors/square/authorize', { method: 'POST' });
      if (dev.data?.square_environment !== 'mock') { window.location.href = authorize_url; return; }
      // Mock Square (development): complete the consent step locally — no real Square account is involved.
      const state = new URL(authorize_url).searchParams.get('state');
      const res = await fetch(`/v1/connectors/square/callback?state=${encodeURIComponent(state!)}&code=mock-code`, { headers: { Accept: 'application/json' } });
      if (!res.ok) {
        const body = await res.json().catch(() => null);
        throw new Error(`Mock connection failed (${res.status})${body?.detail ? `: ${body.detail}` : ''}`);
      }
    },
    onSuccess: refresh,
  });
  const env = dev.data?.square_environment;
  return (
    <OpsShell active="connections" title="Connections" icon="hub">
      <RequireSession>
        <Notice tone="info">
          Square is <b>read-only</b> for Tabula: sales, items and stock are read; nothing is written back. Deliveries you record must also be entered in Square.
          {env && <> This server talks to Square <b>{env}</b>{env === 'mock' ? ' — a built-in fake for development; nothing here touches a real Square account' : ''}.</>}
        </Notice>
        <Panel title="Square" aside={<Button onClick={() => connect.mutate()} loading={connect.isPending}>{accounts.data?.length ? 'Reconnect / connect another' : 'Connect Square'}</Button>}>
          {accounts.isLoading && <Loading />}
          <ErrorBox error={accounts.error ?? connect.error} onRetry={() => accounts.refetch()} />
          {accounts.data?.length === 0 && <EmptyState icon="link" title="Not connected" body="Connect Square to read sales and stock automatically, or keep uploading files on Data imports." />}
          <div className="flex flex-col gap-4">
            {accounts.data?.map((a) => <Account key={a.id} a={a} onChange={refresh} />)}
          </div>
        </Panel>
      </RequireSession>
    </OpsShell>
  );
}

function Account({ a, onChange }: { a: ConnectorAccount; onChange: () => void }) {
  const session = loadSession()!;
  const locations = useQuery({ queryKey: ['locations', session.tenantId], queryFn: () => api<Location[]>('/locations') });
  const external = useQuery({ queryKey: ['ext-locations', a.id], queryFn: () => api<{ external_id: string; name: string }[]>(`/connectors/${a.id}/external-locations`), enabled: a.status === 'active' });
  const [ext, setExt] = useState('');
  const [loc, setLoc] = useState('');
  const link = useMutation({ mutationFn: () => api(`/connectors/${a.id}/locations`, { body: { external_location_id: ext, location_id: loc } }), onSuccess: onChange });
  const sync = useMutation({ mutationFn: (kind: string) => api(`/connectors/${a.id}/sync`, { body: { kind } }), onSuccess: onChange });
  const disconnect = useMutation({ mutationFn: () => api(`/connectors/${a.id}`, { method: 'DELETE' }), onSuccess: onChange });
  const recon = a.sync_state.reconciliations ?? [];
  return (
    <div className="rounded-[12px] border border-[#E8D4C6] p-4 text-[13px]">
      <div className="flex flex-wrap items-center gap-2">
        <b>{a.display_name ?? a.merchant_id}</b><StatusChip status={a.status === 'active' ? 'supplier_confirmed' : 'failed'} />
        <span className="rounded bg-[#F1F1F1] px-2 text-[12px]">{a.environment}</span>
        <span className="text-[12px] text-[#5C7A8A]">token valid until {when(a.token_expires_at)}{a.sync_state.token_refreshed_at ? ` · refreshed ${when(a.sync_state.token_refreshed_at)}` : ''}</span>
      </div>
      {a.status !== 'active' && <Notice>Square no longer accepts this connection ({a.status.replace('_', ' ')}). Reconnect above; location links and history are kept.</Notice>}
      {a.last_error && <div className="mt-1 text-[12px] text-[#991B1B]">Last error: {a.last_error}</div>}
      <div className="mt-1 text-[12px] text-[#5C7A8A]">Last successful sync {when(a.last_success_at)} · sales synced through {when(a.sync_state.sales_synced_through)} · runs every 15 min (sales), 30 min (stock), nightly reconciliation of the last 3 days</div>

      <div className="mt-3 font-semibold">Locations</div>
      <ul className="mt-1 flex flex-col gap-2">
        {a.locations.map((l) => {
          const mine = locations.data?.find((x) => x.id === l.location_id);
          return <li key={l.external_location_id}>Square {l.external_location_id} → <b>{mine?.name ?? l.location_id}</b> (stock owned by Square){mine && <SalesFeed location={mine} onChange={onChange} />}</li>;
        })}
      </ul>
      {a.status === 'active' && (
        <div className="mt-2 flex flex-wrap items-end gap-2">
          <select aria-label="Square location" className="rounded-[8px] border border-[#E8D4C6] px-2 py-1" value={ext} onChange={(e) => setExt(e.target.value)}>
            <option value="">Square location…</option>{external.data?.map((x) => <option key={x.external_id} value={x.external_id}>{x.name}</option>)}
          </select>
          <select aria-label="Tabula location" className="rounded-[8px] border border-[#E8D4C6] px-2 py-1" value={loc} onChange={(e) => setLoc(e.target.value)}>
            <option value="">Tabula store…</option>{locations.data?.map((x) => <option key={x.id} value={x.id}>{x.name}</option>)}
          </select>
          <Button variant="secondary" onClick={() => link.mutate()} disabled={!ext || !loc} loading={link.isPending}>Link</Button>
          <span className="text-[11px] text-[#5C7A8A]">Linking hands that store's stock count to Square. Sales stay on files until you switch the sales source.</span>
        </div>
      )}
      <ErrorBox error={link.error} />

      <div className="mt-3 flex flex-wrap gap-2">
        {['catalog', 'sales', 'inventory', 'reconcile'].map((k) => <Button key={k} variant="secondary" onClick={() => sync.mutate(k)} loading={sync.isPending && sync.variables === k} disabled={a.status !== 'active'}>Sync {k}</Button>)}
        <Button variant="danger" onClick={() => disconnect.mutate()} loading={disconnect.isPending} disabled={a.status === 'revoked'}>Disconnect</Button>
      </div>
      <ErrorBox error={sync.error ?? disconnect.error} />
      {recon.length > 0 && (
        <div className="mt-3">
          <div className="font-semibold">Reconciliation (re-reads recent days; catches missed webhooks)</div>
          <ul className="text-[12px]">{recon.slice(-5).reverse().map((r, i) => <li key={i}>{when(r.at)}: {r.recovered_sales_lines} missed sale line(s) recovered{r.unmapped_items ? `, ${r.unmapped_items} unmapped item(s)` : ''}, {r.stock_readings} stock reading(s)</li>)}</ul>
        </div>
      )}
    </div>
  );
}

function SalesFeed({ location, onChange }: { location: Location; onChange: () => void }) {
  const [since, setSince] = useState('');
  const qc = useQueryClient();
  const set = useMutation({
    mutationFn: (feed: string) => api(`/locations/${location.id}/sales-feed`, { method: 'PUT', body: { feed, since: since ? new Date(since).toISOString() : null } }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['locations'] }); onChange(); },
  });
  const square = location.sales_feed === 'square';
  return (
    <div className="mt-1 rounded-[10px] bg-[#FDF5EF] p-2 text-[12px]">
      Sales source: <b>{square ? 'Square' : 'uploaded files'}</b>{location.sales_feed_since ? ` since ${when(location.sales_feed_since)}` : ''}.
      One source at a time, so a sale is never counted twice. Switching is refused if the current source already recorded sales after the switch time.
      <div className="mt-1 flex flex-wrap items-center gap-2">
        <label>Switch at <input type="datetime-local" className="rounded border border-[#E8D4C6] px-1" value={since} onChange={(e) => setSince(e.target.value)} /> (empty = now)</label>
        <Button variant="secondary" onClick={() => set.mutate(square ? 'files' : 'square')} loading={set.isPending}>{square ? 'Go back to files' : 'Use Square for sales'}</Button>
      </div>
      <ErrorBox error={set.error} />
    </div>
  );
}
