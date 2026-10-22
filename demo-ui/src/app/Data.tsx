// Data: where the store's data comes from (spreadsheet, Google Sheet, Square), what each source
// last delivered, what the data supports yet — and the import wizard.

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useEffect, useRef, useState } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import { SymbolIcon, cn } from '../components/ui';
import { api, loadSession, upload, type ConnectorAccount, type ImportRecord, type Preview } from '../ops/api';
import { Badge, Button, ButtonLink, ErrorBox, Field, Notice, OpsShell, Panel, RequireSession, Skeleton, StatusChip, inputCls, when } from '../ops/kit';
import { SettingsTabs } from './Settings';
import type { Readiness } from './types';

type SquareStatus = { environment: string | null; available: boolean; missing: string[]; demo?: boolean };

export function DataPage() {
  return (
    <OpsShell active="settings" title="Settings" tabs={<SettingsTabs active="data" />}
      actions={<ButtonLink to="/app/settings/data/import">Import a file</ButtonLink>}>
      <RequireSession><Sources /></RequireSession>
    </OpsShell>
  );
}

const KIND_LABEL: Record<string, string> = { inventory: 'Stock', sales: 'Sales', open_orders: 'Open orders', supplier_price_list: 'Price list' };

function Sources() {
  const s = loadSession()!;
  const loc = s.locationId!;
  const readiness = useQuery({ queryKey: ['readiness', loc], queryFn: () => api<Readiness>(`/readiness?location_id=${loc}`) });
  const imports = useQuery({ queryKey: ['imports', s.tenantId], queryFn: () => api<ImportRecord[]>('/imports') });
  const square = useQuery({ queryKey: ['square-status'], queryFn: () => api<SquareStatus>('/connectors/square/status') });
  const accounts = useQuery({ queryKey: ['connectors', s.tenantId], queryFn: () => api<ConnectorAccount[]>('/connectors') });
  const lastFile = (kind: string) => imports.data?.find((i) => i.kind === kind && i.status === 'applied');
  const acct = accounts.data?.find((a) => a.status !== 'revoked');
  return (
    <>
      <Panel title="Data sources" padded={false} sub="Where products, stock and sales come from">
      <ul className="divide-y divide-[#EDEFF2] border-t border-[#EDEFF2]">
        <Source icon="table_view" title="Excel or CSV" state={<Badge tone="good">Works</Badge>}
          body="Upload exports from your POS or spreadsheet: stock, sales, open orders, supplier price lists."
          foot={lastFile('inventory') || lastFile('sales') ? `Last import ${when((lastFile('sales') ?? lastFile('inventory'))!.created_at)}` : 'Nothing imported yet'}
          action={<ButtonLink to="/app/settings/data/import" variant="secondary" size="sm">Upload a file</ButtonLink>} />
        <Source icon="grid_on" title="Google Sheets" state={<Badge tone="good">Works with a shared link</Badge>}
          body="Paste the link of a sheet shared as “Anyone with the link can view”. Read once per import — automatic syncing isn't available yet."
          foot="Private sheets: download as CSV instead"
          action={<ButtonLink to="/app/settings/data/import?source=sheet" variant="secondary" size="sm">Use a sheet link</ButtonLink>} />
        <Source icon="point_of_sale" title="Square"
          state={square.data == null ? null : acct ? <Badge tone={acct.status === 'active' ? 'good' : 'bad'}>{acct.status === 'active' ? 'Connected' : 'Reconnect needed'}</Badge>
            : square.data.demo ? <Badge tone="info">Demo connection</Badge> : square.data.available ? <Badge tone="good">Ready to connect</Badge> : <Badge tone="warn">Needs setup</Badge>}
          body={square.data?.demo ? 'This server uses a built-in practice Square (no real account). Real Square needs an app set up by your Tabula admin.'
            : square.data && !square.data.available ? 'Square isn\'t set up on this Tabula server yet, so it can\'t be connected. Use files meanwhile.'
            : 'Read sales, items and stock from Square automatically. Tabula never changes your Square data.'}
          foot={acct ? (acct.last_error ? `Last error: ${acct.last_error}` : `Last successful sync ${when(acct.last_success_at)}`) : square.data && !square.data.available ? `Admin: set ${square.data.missing.join(', ')}` : ''}
          action={square.data?.available || acct ? <ButtonLink to="/app/settings/data/square" variant="secondary" size="sm">{acct ? 'Manage' : 'Connect'}</ButtonLink> : null} />
      </ul>
      </Panel>

      <Panel title="What your data supports">
        {!readiness.data && <Skeleton rows={3} />}
        <ul className="flex flex-col divide-y divide-[#EDEFF2]">
          {readiness.data?.features.map((f) => (
            <li key={f.key} className="flex items-start gap-2.5 py-2.5 text-[13px]">
              <SymbolIcon icon={f.ready ? 'check_circle' : 'radio_button_unchecked'} family="rounded" className={cn('mt-px text-[18px]', f.ready ? 'text-[#1F7A4D]' : 'text-[#A15C07]')} />
              <div className="min-w-0 flex-1"><span className="font-medium">{f.label}</span>
                {f.ready ? <span className="text-[#66707A]"> — ready</span> : <span className="text-[#5C3A06]"> — needs {f.missing.map((m) => m.what).join(', ')}. <span className="text-[#66707A]">{f.missing[0]?.how}.</span></span>}
                {!f.ready && f.partial && <div className="text-[12px] text-[#66707A]">{f.partial}</div>}</div>
            </li>
          ))}
        </ul>
        {readiness.data && <div className="mt-3 text-[12px] text-[#66707A]">{readiness.data.facts.products} items · {readiness.data.facts.sales_days} days of sales · {readiness.data.facts.approved_suppliers} supplier(s) ready to order from</div>}
      </Panel>

      <Panel title="Recent imports" padded={false}>
        {imports.isLoading && <div className="p-5"><Skeleton rows={3} /></div>}
        {imports.data?.length === 0 && <div className="px-5 pb-5 text-[14px] text-[#66707A] md:px-6">No files imported yet.</div>}
        <ul className="divide-y divide-[#EDEFF2]">
          {imports.data?.slice(0, 12).map((i) => (
            <li key={i.id} className="flex flex-wrap items-center justify-between gap-2 px-5 py-3 text-[14px] md:px-6">
              <span className="min-w-0"><span className="block truncate font-medium">{i.file_name}</span>
                <span className="text-[12px] text-[#66707A]">{KIND_LABEL[i.kind] ?? i.kind} · {i.row_count} rows · {when(i.created_at)}</span>
                {i.failure && <span className="block text-[12px] text-[#B42318]">{i.failure}</span>}</span>
              <span className="flex items-center gap-2"><StatusChip status={i.status} />{i.status === 'uploaded' && <Link className="text-[13px] font-semibold text-[#2457C5]" to={`/app/settings/data/import?review=${i.id}`}>Review</Link>}</span>
            </li>
          ))}
        </ul>
      </Panel>
    </>
  );
}

function Source({ icon, title, state, body, foot, action }: { icon: string; title: string; state: React.ReactNode; body: string; foot?: string; action: React.ReactNode }) {
  return (
    <li className="flex flex-wrap items-start gap-x-4 gap-y-2 px-4 py-3.5 md:flex-nowrap md:px-5">
      <SymbolIcon icon={icon} family="rounded" className="mt-0.5 text-[22px] text-[#3B444D]" />
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-2"><span className="text-[14px] font-semibold">{title}</span>{state}</div>
        <p className="mt-0.5 text-[13px] leading-snug text-[#66707A]">{body}</p>
        {foot && <div className="mt-1 text-[12px] text-[#3B444D]">{foot}</div>}
      </div>
      {action && <div className="shrink-0">{action}</div>}
    </li>
  );
}

// ---------------------------------------------------------------- import wizard

const KINDS = [
  { value: 'inventory', title: 'Stock on hand', body: 'Items and how many you have. SKU or barcode, name, quantity.', icon: 'inventory_2' },
  { value: 'sales', title: 'Sales history', body: 'What sold and when — at least 2 weeks for order suggestions.', icon: 'receipt' },
  { value: 'supplier_price_list', title: 'Supplier price list', body: 'Supplier SKUs, case size and cost for one supplier.', icon: 'sell' },
  { value: 'open_orders', title: 'Open orders', body: 'Orders placed outside Tabula and not yet received.', icon: 'local_shipping' },
];

const SETTING: Record<string, { label: string; input: 'date' | 'datetime' | 'select' | 'text' | 'bool' | 'number'; options?: [string, string][]; help?: string }> = {
  period_start: { label: 'The export covers sales from', input: 'date' },
  period_end: { label: '…until (inclusive)', input: 'date' },
  as_of: { label: 'This was true at', input: 'datetime', help: 'When the count was taken / the report was run.' },
  quantity_unit: { label: 'Quantities are counted in', input: 'select', options: [['base', 'Single units (each)'], ['order_unit', 'Cases / order units']] },
  complete_scope: { label: 'This file lists', input: 'select', options: [['none', 'Some open orders'], ['suppliers_in_file', 'All open orders for the suppliers in it'], ['all_suppliers', 'All open orders, every supplier']] },
  create_missing_variants: { label: 'Add items that are not in Tabula yet', input: 'bool' },
  date_format: { label: 'Dates are written as', input: 'select', options: [['', 'YYYY-MM-DD (or with time)'], ['MM/DD/YYYY', 'MM/DD/YYYY'], ['DD/MM/YYYY', 'DD/MM/YYYY'], ['YYYY/MM/DD', 'YYYY/MM/DD'], ['MM-DD-YYYY', 'MM-DD-YYYY']] },
  price_basis: { label: 'Prices in this file are', input: 'select', options: [['per_order_unit', 'Per case / order unit'], ['per_base_unit', 'Per single unit']] },
  units_per_order_uom: { label: 'Units in one case (if the file has no pack column)', input: 'number' },
  order_uom: { label: 'Order unit name (if the file has no unit column)', input: 'text', help: 'e.g. case, bag, box' },
  currency: { label: 'Currency (if not the supplier’s)', input: 'text' },
  price_type: { label: 'These prices are', input: 'select', options: [['price_list', 'A price list'], ['contract', 'Contract prices'], ['quote', 'A quote'], ['invoice', 'From an invoice']] },
  update_pack_on_change: { label: 'Accept changed case sizes from this file', input: 'bool', help: 'Items whose pack changed need re-confirming before ordering.' },
};
const ADVANCED = new Set(['date_format', 'timezone', 'currency', 'price_type', 'update_pack_on_change', 'supplier_id']);

export function ImportPage() {
  const [params] = useSearchParams();
  const back = params.get('return') === '/app/setup' ? ['/app/setup', '← Setup'] : ['/app/settings/data', '← Data sources'];
  return <OpsShell active="settings" title="Import data" subtitle={<Link to={back[0]} className="hover:underline">{back[1]}</Link>}><RequireSession><Wizard /></RequireSession></OpsShell>;
}

function Wizard() {
  const s = loadSession()!;
  const [params, setParams] = useSearchParams();
  const [kind, setKind] = useState(params.get('kind') ?? '');
  const [via, setVia] = useState<'file' | 'sheet'>(params.get('source') === 'sheet' ? 'sheet' : 'file');
  const [file, setFile] = useState<File | null>(null);
  const [link, setLink] = useState('');
  const [supplierId, setSupplierId] = useState(params.get('supplier') ?? '');
  const review = params.get('review');
  const ret = params.get('return');
  const suppliers = useQuery({ queryKey: ['suppliers', s.tenantId], queryFn: () => api<{ id: string; name: string }[]>('/suppliers'), enabled: kind === 'supplier_price_list' });
  const send = useMutation({
    mutationFn: () => {
      const ctx = kind === 'supplier_price_list' ? { supplier_id: supplierId } : { location_id: s.locationId, ...(kind === 'sales' ? { source_system: 'other_pos' } : {}) };
      if (via === 'sheet') return api<ImportRecord>('/imports/google-sheet', { body: { url: link, kind, ...ctx } });
      const form = new FormData();
      form.append('file', file!); form.append('kind', kind);
      Object.entries(ctx).forEach(([k, v]) => v && form.append(k, v));
      return upload<ImportRecord>('/imports', form);
    },
    onSuccess: (r) => setParams({ review: r.id, ...(ret ? { return: ret } : {}) }),
  });
  if (review) return <Review id={review} />;
  return (
    <>
      <Panel title="1. What's in the file?">
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          {KINDS.map((k) => (
            <button key={k.value} onClick={() => setKind(k.value)} className={cn('flex flex-col items-start gap-1 rounded-[8px] border p-4 text-left transition-colors',
              kind === k.value ? 'border-[#2457C5] bg-[#EAF0FB]' : 'border-[#E2E5E9] hover:bg-[#F4F5F7]')}>
              <SymbolIcon icon={k.icon} family="rounded" className="text-[24px] text-[#2457C5]" />
              <span className="text-[15px] font-semibold">{k.title}</span><span className="text-[12px] leading-snug text-[#66707A]">{k.body}</span>
            </button>
          ))}
        </div>
      </Panel>
      {kind && (
        <Panel title="2. Choose the file">
          <div className="mb-4 inline-flex rounded-[6px] bg-[#F0F2F4] p-1">
            {(['file', 'sheet'] as const).map((v) => <button key={v} onClick={() => setVia(v)} className={cn('rounded-[5px] px-3 py-1.5 text-[13px] font-semibold', via === v ? 'bg-white' : 'text-[#66707A]')}>{v === 'file' ? 'Excel / CSV file' : 'Google Sheets link'}</button>)}
          </div>
          <form className="flex flex-col gap-4" onSubmit={(e) => { e.preventDefault(); send.mutate(); }}>
            {kind === 'supplier_price_list' && (
              <Field label="Supplier" hint={suppliers.data?.length === 0 ? <>No suppliers yet — <Link className="underline" to="/app/orders/suppliers">add one first</Link>.</> : undefined}>
                <select className={inputCls} value={supplierId} onChange={(e) => setSupplierId(e.target.value)} required>
                  <option value="">Choose…</option>{suppliers.data?.map((x) => <option key={x.id} value={x.id}>{x.name}</option>)}
                </select>
              </Field>
            )}
            {via === 'file' ? (
              <label className="flex cursor-pointer flex-col items-center gap-2 rounded-[8px] border-2 border-dashed border-[#D5DAE0] bg-[#F8F9FA] px-4 py-8 text-center hover:border-[#2457C5]">
                <SymbolIcon icon="upload_file" family="rounded" className="text-[32px] text-[#9AA3AC]" />
                <span className="text-[14px] font-semibold">{file ? file.name : 'Choose a .csv or .xlsx file'}</span>
                <span className="text-[12px] text-[#66707A]">Columns are matched automatically; you'll check them before anything is imported.</span>
                <input aria-label="File" type="file" accept=".csv,.xlsx" className="sr-only" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
              </label>
            ) : (
              <Field label="Link to the Google Sheet" hint="Share → General access → “Anyone with the link” (Viewer). The first tab is read, or the tab in the link.">
                <input className={inputCls} value={link} onChange={(e) => setLink(e.target.value)} placeholder="https://docs.google.com/spreadsheets/d/…" />
              </Field>
            )}
            <ErrorBox error={send.error} />
            <div><Button type="submit" size="lg" loading={send.isPending} disabled={(via === 'file' ? !file : !link) || (kind === 'supplier_price_list' && !supplierId)}>Check the file</Button></div>
          </form>
        </Panel>
      )}
    </>
  );
}

function Review({ id }: { id: string }) {
  const qc = useQueryClient();
  const navigate = useNavigate();
  const ret = useSearchParams()[0].get('return');
  const record = useQuery({ queryKey: ['import', id], queryFn: () => api<ImportRecord>(`/imports/${id}`),
    refetchInterval: (q) => (['confirmed', 'applying'].includes(q.state.data?.status ?? '') ? 1200 : false) });
  const preview = useQuery({ queryKey: ['preview', id], queryFn: () => api<Preview & { unused_columns?: { column: string; why: string }[] }>(`/imports/${id}/preview?limit=12`) });
  const [settings, setSettings] = useState<Record<string, unknown>>({});
  const [columns, setColumns] = useState<Record<string, string>>({});
  const [advanced, setAdvanced] = useState(false);
  const dirtyRef = useRef(false);
  useEffect(() => { if (record.data) { setSettings(record.data.mapping.settings ?? {}); setColumns(record.data.mapping.columns); } }, [record.data?.mapping_revision]); // eslint-disable-line react-hooks/exhaustive-deps
  const save = useMutation({
    mutationFn: () => api(`/imports/${id}/mapping`, { method: 'PUT', body: { revision: record.data!.mapping_revision, columns,
      settings: Object.fromEntries(Object.entries(settings).filter(([, v]) => v !== '' && v !== undefined && v !== null)) } }),
    onSuccess: () => { record.refetch(); preview.refetch(); },
  });
  const confirm = useMutation({
    // One click: save any changed answers, re-check, then import exactly what the re-check shows.
    mutationFn: async () => {
      let pv = preview.data!;
      if (dirtyRef.current) {
        await api(`/imports/${id}/mapping`, { method: 'PUT', body: { revision: record.data!.mapping_revision, columns,
          settings: Object.fromEntries(Object.entries(settings).filter(([, v]) => v !== '' && v !== undefined && v !== null)) } });
        pv = await api<Preview>(`/imports/${id}/preview?limit=12`);
        await Promise.all([record.refetch(), preview.refetch()]);
        if (pv.blocking_issues.length || !pv.counts || pv.counts.with_errors > 0) throw new Error('Some rows still have problems — see the preview below.');
      }
      return api(`/imports/${id}/confirm-mapping`, { body: { revision: pv.mapping_revision, declared: pv.declared_settings, accept_row_errors: false } });
    },
    onSuccess: () => { record.refetch(); qc.invalidateQueries({ queryKey: ['imports'] }); },
  });
  if (record.isLoading || preview.isLoading) return <Panel><Skeleton rows={5} /></Panel>;
  if (record.error || preview.error) return <ErrorBox error={record.error ?? preview.error} />;
  const rec = record.data!, p = preview.data!;
  if (rec.status !== 'uploaded') return <Done rec={rec} ret={ret} onAnother={() => navigate(`/app/settings/data/import${ret ? `?return=${encodeURIComponent(ret)}` : ''}`)} />;
  const declared = Object.keys(p.declared_settings).filter((k) => SETTING[k]);
  const needed = declared.filter((k) => !ADVANCED.has(k));
  const dirty = Object.keys(settings).some((k) => JSON.stringify(settings[k] ?? null) !== JSON.stringify((rec.mapping.settings ?? {})[k] ?? null))
    || JSON.stringify(columns) !== JSON.stringify(rec.mapping.columns);
  dirtyRef.current = dirty;
  const fields = Object.fromEntries(p.fields.map((f) => [f.name, f.label]));
  const blocking = p.blocking_issues.map((b) => b.startsWith('map_required_field:') ? `choose the column for ${fields[b.split(':')[1]] ?? b.split(':')[1]}`
    : b.startsWith('declare_') ? `answer “${SETTING[b.replace('declare_', '')]?.label ?? b.replace('declare_', '').replace(/_/g, ' ')}”` : b.replace(/_/g, ' '));
  const shown = p.fields.filter((f) => columns[f.name] || f.required);
  return (
    <>
      <Panel title={<>Check <span className="text-[#2457C5]">{rec.file_name}</span></>} aside={<span className="text-[13px] text-[#66707A]">{rec.row_count} rows</span>}>
        <div className="grid gap-6 lg:grid-cols-2">
          <div>
            <div className="mb-2 text-[13px] font-semibold uppercase tracking-wide text-[#66707A]">Columns we matched</div>
            <div className="mb-2 text-[12px] text-[#66707A]">Change any that look wrong.</div>
            <ul className="flex flex-col gap-1.5 text-[14px]">
              {shown.map((f) => (
                <li key={f.name} className="flex flex-wrap items-center gap-2">
                  <SymbolIcon icon={columns[f.name] ? 'check' : 'help'} family="rounded" className={`text-[18px] ${columns[f.name] ? 'text-[#1F7A4D]' : 'text-[#A15C07]'}`} />
                  <span className="min-w-[140px] text-[#66707A]">{f.label}{f.required ? '' : ''}</span>
                  <select aria-label={`Column for ${f.label}`} className="rounded-[8px] border border-[#D5DAE0] px-2 py-1 text-[13px] font-medium"
                    value={columns[f.name] ?? ''} onChange={(e) => setColumns((c) => { const n = { ...c }; if (e.target.value) n[f.name] = e.target.value; else delete n[f.name]; return n; })}>
                    <option value="">{f.required ? 'Which column is it?' : '(not in this file)'}</option>
                    {rec.header.filter((h) => h.trim()).map((h) => <option key={h} value={h}>“{h}”</option>)}
                  </select>
                </li>
              ))}
              {p.unused_columns?.map((u) => (
                <li key={u.column} className="flex items-start gap-2 text-[#66707A]"><SymbolIcon icon="remove" family="rounded" className="text-[18px]" />
                  <span>“{u.column}” — not used: {u.why}</span></li>
              ))}
            </ul>
            {p.fields.some((f) => f.required && !columns[f.name]) && (
              <div className="mt-3"><Notice>Choose which column holds {p.fields.filter((f) => f.required && !columns[f.name]).map((f) => f.label.toLowerCase()).join(', ')} — then save.</Notice></div>
            )}
          </div>
          <div>
            <div className="mb-2 text-[13px] font-semibold uppercase tracking-wide text-[#66707A]">{needed.length ? 'A few questions' : 'Nothing to confirm'}</div>
            <div className="flex flex-col gap-3">
              {(advanced ? declared : needed).map((k) => <SettingInput key={k} name={k} value={settings[k]} set={(v) => setSettings((x) => ({ ...x, [k]: v }))} />)}
              {p.suggested_settings?.period_start && declared.includes('period_start') && (
                <div className="rounded-[6px] bg-[#F3F6FC] p-3 text-[13px] text-[#1B3566]">The file has sales from <b>{p.suggested_settings.period_start}</b> to <b>{p.suggested_settings.period_end}</b>.{' '}
                  <button className="font-semibold underline" onClick={() => setSettings((x) => ({ ...x, period_start: p.suggested_settings!.period_start, period_end: p.suggested_settings!.period_end }))}>Use these dates</button>
                  <div className="mt-1 text-[12px]">{p.suggested_settings.note}</div></div>
              )}
              {declared.some((k) => ADVANCED.has(k)) && <button className="self-start text-[13px] font-semibold text-[#66707A] underline" onClick={() => setAdvanced((a) => !a)}>{advanced ? 'Fewer options' : 'Date format and other options'}</button>}
              {dirty && <div><Button variant="secondary" onClick={() => save.mutate()} loading={save.isPending}>Re-check with these answers</Button></div>}
              <ErrorBox error={save.error} />
            </div>
          </div>
        </div>
      </Panel>
      <Panel title="Preview" aside={p.counts && <span className="text-[13px]"><b className="text-[#1F7A4D]">{p.counts.valid}</b> ready · <b className={p.counts.with_errors ? 'text-[#B42318]' : ''}>{p.counts.with_errors}</b> with problems · {p.counts.with_warnings} to note</span>}>
        {blocking.length > 0 && !dirty && <Notice>Before importing: {blocking.join(', ')}.</Notice>}
        <div className="mt-3 max-h-[340px] overflow-auto rounded-[6px] border border-[#EDEFF2]">
          <table className="w-full text-[13px]">
            <tbody>
              {[...p.rows, ...((p as any).more_errors ?? [])].map((r: Preview['rows'][number]) => (
                <tr key={r.row_number} className={cn('border-b border-[#EDEFF2] align-top', r.errors.length > 0 && 'bg-[#FDF3F2]')}>
                  <td className="w-12 px-3 py-2 text-[#9AA3AC]">{r.row_number}</td>
                  <td className="px-3 py-2">{r.interpretation}</td>
                  <td className="px-3 py-2 text-[#B42318]">{r.errors.map((e) => e.message).join('; ')}</td>
                  <td className="px-3 py-2 text-[#8A5A0E]">{r.warnings.map((w) => w.message).join('; ')}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="mt-4 flex flex-wrap items-center gap-3">
          <Button size="lg" onClick={() => confirm.mutate()} loading={confirm.isPending} disabled={!dirty && (blocking.length > 0 || !p.counts || p.counts.with_errors > 0)}>
            {p.counts && !dirty ? `Import ${p.counts.valid} rows` : 'Import'}</Button>
          {p.counts && p.counts.with_errors > 0 && !dirty && <span className="text-[13px] text-[#B42318]">Fix the rows with problems in your file and upload it again.</span>}
        </div>
        <div className="mt-2"><ErrorBox error={confirm.error} /></div>
      </Panel>
    </>
  );
}

function SettingInput({ name, value, set }: { name: string; value: unknown; set: (v: unknown) => void }) {
  const h = SETTING[name];
  if (h.input === 'bool') return <label className="flex items-center gap-2 text-[14px]"><input type="checkbox" checked={!!value} onChange={(e) => set(e.target.checked)} />{h.label}</label>;
  if (h.input === 'select') return (
    <Field label={h.label} hint={h.help}><select className={inputCls} value={(value as string) ?? ''} onChange={(e) => set(e.target.value || undefined)}>
      {!h.options!.some(([v]) => v === '') && <option value="">Choose…</option>}{h.options!.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select></Field>
  );
  const local = (iso: string) => { const d = new Date(iso); const p = (n: number) => String(n).padStart(2, '0'); return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}T${p(d.getHours())}:${p(d.getMinutes())}`; };
  return (
    <Field label={h.label} hint={h.help}>
      <span className="flex items-center gap-2">
        <input className={`${inputCls} flex-1`} type={h.input === 'datetime' ? 'datetime-local' : h.input === 'date' ? 'date' : h.input === 'number' ? 'number' : 'text'}
          value={h.input === 'datetime' && value ? local(String(value)) : (value as string) ?? ''}
          onChange={(e) => set(h.input === 'datetime' ? (e.target.value ? new Date(e.target.value).toISOString() : undefined) : e.target.value)} />
        {h.input === 'datetime' && <Button size="sm" variant="secondary" onClick={() => set(new Date().toISOString())}>Now</Button>}
      </span>
    </Field>
  );
}

function Done({ rec, onAnother, ret }: { rec: ImportRecord; onAnother: () => void; ret: string | null }) {
  const loc = loadSession()!.locationId!;
  const readiness = useQuery({ queryKey: ['readiness', loc, rec.status], queryFn: () => api<Readiness>(`/readiness?location_id=${loc}`), enabled: rec.status === 'applied' });
  const busy = ['confirmed', 'applying'].includes(rec.status);
  return (
    <Panel>
      <div className="flex flex-col items-center gap-2 py-6 text-center">
        <StatusChip status={rec.status} />
        <div className="text-[18px] font-semibold">{busy ? `Importing ${rec.file_name}…` : rec.status === 'applied' ? `${rec.file_name} is in` : rec.file_name}</div>
        {rec.failure && <div className="text-[14px] text-[#B42318]">{rec.failure}</div>}
        {rec.status === 'applied' && readiness.data && (
          <ul className="mt-2 flex flex-wrap justify-center gap-2">
            {readiness.data.features.map((f) => <li key={f.key}><Badge tone={f.ready ? 'good' : 'warn'}>{f.ready ? '✓' : '…'} {f.label}</Badge></li>)}
          </ul>
        )}
        {!busy && <div className="mt-4 flex flex-wrap justify-center gap-2">
          {ret ? <ButtonLink to={ret}>Continue setup</ButtonLink> : <ButtonLink to="/app/inventory">See inventory</ButtonLink>}
          <Button variant="secondary" onClick={onAnother}>Import another file</Button>
        </div>}
      </div>
    </Panel>
  );
}
