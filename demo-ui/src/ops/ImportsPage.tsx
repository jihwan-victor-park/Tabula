import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useEffect, useState } from 'react';
import { api, loadSession, upload, type ImportRecord, type Location, type Preview } from './api';
import { Button, EmptyState, ErrorBox, Loading, Notice, OpsShell, Panel, RequireSession, StatusChip, when } from './kit';

const KINDS = [
  { value: 'sales', label: 'Sales history' },
  { value: 'inventory', label: 'Stock count' },
  { value: 'open_orders', label: 'Open (not yet received) orders' },
];

// What each declared setting means, in the owner's words.
const SETTING_HELP: Record<string, { label: string; input: 'date' | 'datetime' | 'select' | 'text' | 'bool'; options?: string[] }> = {
  period_start: { label: 'Export covers sales from (date)', input: 'date' },
  period_end: { label: 'Export covers sales until (date)', input: 'date' },
  as_of: { label: 'This was true at', input: 'datetime' },
  quantity_unit: { label: 'Quantities are in', input: 'select', options: ['base', 'order_unit'] },
  complete_scope: { label: 'This report lists every open order for', input: 'select', options: ['none', 'suppliers_in_file', 'all_suppliers'] },
  create_missing_variants: { label: 'Create items not in Tabula yet', input: 'bool' },
  date_format: { label: 'Date format (if not YYYY-MM-DD)', input: 'select', options: ['', 'MM/DD/YYYY', 'DD/MM/YYYY', 'YYYY/MM/DD', 'MM-DD-YYYY'] },
  timezone: { label: 'Timezone (if not the store’s)', input: 'text' },
  supplier_id: { label: 'Supplier (if the file has no supplier column)', input: 'text' },
};

export function ImportsPage() {
  const session = loadSession();
  const qc = useQueryClient();
  const imports = useQuery({
    queryKey: ['imports', session?.tenantId],
    queryFn: () => api<ImportRecord[]>('/imports'),
    enabled: !!session?.tenantId,
    // Keep polling while something is being applied by the worker.
    refetchInterval: (q) => (q.state.data?.some((i) => ['confirmed', 'applying'].includes(i.status)) ? 1500 : false),
  });
  const [openId, setOpenId] = useState<string | null>(null);

  return (
    <OpsShell active="imports" title="Data imports" icon="upload_file">
      <RequireSession>
        <UploadPanel onUploaded={(id) => { setOpenId(id); qc.invalidateQueries({ queryKey: ['imports'] }); }} />
        {openId && <ReviewPanel id={openId} onDone={() => qc.invalidateQueries({ queryKey: ['imports'] })} />}
        <Panel title="Recent imports">
          {imports.isLoading && <Loading />}
          <ErrorBox error={imports.error} onRetry={() => imports.refetch()} />
          {imports.data?.length === 0 && <EmptyState icon="inbox" title="No imports yet" body="Upload a sales export and a stock count to get your first plan." />}
          <div className="overflow-x-auto">
            <table className="[&_td]:pr-3 [&_th]:pr-3 w-full min-w-[640px] text-[13px]">
              <thead><tr className="text-left text-[#5C7A8A]"><th className="py-2">File</th><th>Kind</th><th>Rows</th><th>Status</th><th>Uploaded</th><th /></tr></thead>
              <tbody>
                {imports.data?.map((i) => (
                  <tr key={i.id} className="border-t border-[#F1E4DA]">
                    <td className="py-2 font-medium">{i.file_name}</td>
                    <td>{KINDS.find((k) => k.value === i.kind)?.label ?? i.kind}</td>
                    <td className="text-right font-mono">{i.row_count}</td>
                    <td className="pl-3"><StatusChip status={i.status} />{i.failure && <div className="mt-1 text-[12px] text-[#991B1B]">{i.failure}</div>}</td>
                    <td>{when(i.created_at)}</td>
                    <td className="text-right">{i.status === 'uploaded' && <button className="text-[#E8654A] underline" onClick={() => setOpenId(i.id)}>Review</button>}</td>
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

function UploadPanel({ onUploaded }: { onUploaded: (id: string) => void }) {
  const session = loadSession()!;
  const [kind, setKind] = useState('sales');
  const [file, setFile] = useState<File | null>(null);
  const [locationId, setLocationId] = useState(session.locationId ?? '');
  const locations = useQuery({ queryKey: ['locations', session.tenantId], queryFn: () => api<Location[]>('/locations') });
  useEffect(() => { if (!locationId && locations.data?.[0]) setLocationId(locations.data[0].id); }, [locations.data, locationId]);
  const send = useMutation({
    mutationFn: () => {
      const form = new FormData();
      form.append('file', file!);
      form.append('kind', kind);
      form.append('location_id', locationId);
      if (kind === 'sales') form.append('source_system', 'square');
      return upload<ImportRecord>('/imports', form);
    },
    onSuccess: (r) => onUploaded(r.id),
  });
  return (
    <Panel title="Upload a file">
      <form className="flex flex-wrap items-end gap-3" onSubmit={(e) => { e.preventDefault(); send.mutate(); }}>
        <label className="flex flex-col gap-1 text-[13px]">What is it?
          <select className="rounded-[10px] border border-[#E8D4C6] px-3 py-2" value={kind} onChange={(e) => setKind(e.target.value)}>
            {KINDS.map((k) => <option key={k.value} value={k.value}>{k.label}</option>)}
          </select>
        </label>
        <label className="flex flex-col gap-1 text-[13px]">Location
          <select className="rounded-[10px] border border-[#E8D4C6] px-3 py-2" value={locationId} onChange={(e) => setLocationId(e.target.value)}>
            {locations.data?.map((l) => <option key={l.id} value={l.id}>{l.name}</option>)}
          </select>
        </label>
        <label className="flex flex-col gap-1 text-[13px]">CSV or XLSX
          <input type="file" accept=".csv,.xlsx" onChange={(e) => setFile(e.target.files?.[0] ?? null)} className="text-[13px]" />
        </label>
        <Button type="submit" disabled={!file || !locationId} loading={send.isPending}>Upload</Button>
      </form>
      {kind === 'sales' && <p className="mt-2 text-[12px] text-[#5C7A8A]">Sales are recorded as coming from Square exports (origin “square”).</p>}
      <div className="mt-3"><ErrorBox error={send.error} /></div>
    </Panel>
  );
}

function ReviewPanel({ id, onDone }: { id: string; onDone: () => void }) {
  const record = useQuery({ queryKey: ['import', id], queryFn: () => api<ImportRecord>(`/imports/${id}`) });
  const preview = useQuery({ queryKey: ['preview', id], queryFn: () => api<Preview>(`/imports/${id}/preview`) });
  const [settings, setSettings] = useState<Record<string, unknown>>({});
  useEffect(() => { if (record.data) setSettings(record.data.mapping.settings ?? {}); }, [record.data]);

  const save = useMutation({
    mutationFn: () => {
      const clean = Object.fromEntries(Object.entries(settings).filter(([, v]) => v !== '' && v !== undefined));
      return api(`/imports/${id}/mapping`, { method: 'PUT', body: { revision: record.data!.mapping_revision, columns: record.data!.mapping.columns, settings: clean } });
    },
    onSuccess: () => { record.refetch(); preview.refetch(); },
  });
  const confirm = useMutation({
    mutationFn: () => api(`/imports/${id}/confirm-mapping`, {
      body: { revision: preview.data!.mapping_revision, declared: preview.data!.declared_settings, accept_row_errors: false },
    }),
    onSuccess: () => { record.refetch(); onDone(); },
  });

  if (record.isLoading || preview.isLoading) return <Panel><Loading label="Reading the file…" /></Panel>;
  if (record.error || preview.error) return <Panel><ErrorBox error={record.error ?? preview.error} /></Panel>;
  const rec = record.data!, p = preview.data!;
  const declaredKeys = Object.keys(p.declared_settings);
  if (rec.status !== 'uploaded') {
    return <Panel title={rec.file_name}><StatusChip status={rec.status} /> <span className="ml-2 text-[13px] text-[#5C7A8A]">Nothing more to review here.</span></Panel>;
  }
  return (
    <Panel title={`Review: ${rec.file_name}`} aside={<span className="text-[12px] text-[#5C7A8A]">mapping revision {p.mapping_revision}</span>}>
      <div className="grid gap-4 md:grid-cols-2">
        <div>
          <div className="mb-2 text-[13px] font-semibold">Columns</div>
          <ul className="text-[13px]">
            {Object.entries(rec.mapping.columns).map(([field, col]) => <li key={field}><span className="text-[#5C7A8A]">{field}</span> ← “{col}”</li>)}
          </ul>
        </div>
        <div>
          <div className="mb-2 text-[13px] font-semibold">What the file means (you confirm these)</div>
          <div className="flex flex-col gap-2">
            {declaredKeys.filter((k) => SETTING_HELP[k]).map((k) => {
              const h = SETTING_HELP[k];
              const value = settings[k] as string | boolean | undefined;
              const set = (v: unknown) => setSettings((s) => ({ ...s, [k]: v }));
              return (
                <label key={k} className="flex flex-col gap-1 text-[13px]">{h.label}
                  {h.input === 'select' ? (
                    <select className="rounded-[10px] border border-[#E8D4C6] px-3 py-2" value={(value as string) ?? ''} onChange={(e) => set(e.target.value || undefined)}>
                      <option value="">—</option>{h.options!.filter(Boolean).map((o) => <option key={o} value={o}>{o}</option>)}
                    </select>
                  ) : h.input === 'bool' ? (
                    <input type="checkbox" checked={!!value} onChange={(e) => set(e.target.checked)} />
                  ) : (
                    <span className="flex flex-wrap items-center gap-2">
                      <input className="rounded-[10px] border border-[#E8D4C6] px-3 py-2"
                             type={h.input === 'datetime' ? 'datetime-local' : h.input === 'date' ? 'date' : 'text'}
                             value={h.input === 'datetime' && value ? localInput(String(value)) : (value as string) ?? ''}
                             onChange={(e) => set(h.input === 'datetime' ? new Date(e.target.value).toISOString() : e.target.value)} />
                      {h.input === 'datetime' && <button type="button" className="text-[12px] underline" onClick={() => set(new Date().toISOString())}>Now</button>}
                    </span>
                  )}
                </label>
              );
            })}
            {p.suggested_settings?.period_start && declaredKeys.includes('period_start') && (
              <div className="rounded-[10px] bg-[#EEF4FF] p-2 text-[12px] text-[#1E3A8A]">
                The file has sales from <b>{p.suggested_settings.period_start}</b> to <b>{p.suggested_settings.period_end}</b>.{' '}
                <button className="underline" onClick={() => setSettings((x) => ({ ...x, period_start: p.suggested_settings!.period_start, period_end: p.suggested_settings!.period_end }))}>
                  Use these dates</button>
                <div className="mt-1 text-[11px]">{p.suggested_settings.note}</div>
              </div>
            )}
            <Button variant="secondary" onClick={() => save.mutate()} loading={save.isPending}>Save and re-check</Button>
            <ErrorBox error={save.error} />
          </div>
        </div>
      </div>
      {p.blocking_issues.length > 0 && <div className="mt-4"><Notice>Before confirming: {p.blocking_issues.join(', ')}</Notice></div>}
      {p.counts && (
        <div className="mt-4 text-[13px]">
          <b>{p.counts.valid}</b> of {p.counts.rows} rows ready · {p.counts.with_errors} with errors · {p.counts.with_warnings} with warnings
        </div>
      )}
      <div className="mt-2 max-h-[260px] overflow-auto rounded-[10px] border border-[#F1E4DA]">
        <table className="[&_td]:pr-3 [&_th]:pr-3 w-full text-[12px]">
          <tbody>
            {p.rows.map((r) => (
              <tr key={r.row_number} className="border-t border-[#F7EDE5] align-top">
                <td className="px-2 py-1 font-mono text-[#5C7A8A]">{r.row_number}</td>
                <td className="px-2 py-1">{r.interpretation}</td>
                <td className="px-2 py-1 text-[#991B1B]">{r.errors.map((e) => e.message).join('; ')}</td>
                <td className="px-2 py-1 text-[#8A5A00]">{r.warnings.map((w) => w.message).join('; ')}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="mt-4 flex flex-wrap items-center gap-3">
        <Button onClick={() => confirm.mutate()} loading={confirm.isPending}
                disabled={p.blocking_issues.length > 0 || !p.counts || p.counts.with_errors > 0}>
          Confirm and apply
        </Button>
        <span className="text-[12px] text-[#5C7A8A]">Applies only what is shown here (pinned to revision {p.mapping_revision}).</span>
      </div>
      <div className="mt-2"><ErrorBox error={confirm.error} /></div>
    </Panel>
  );
}

// An ISO time shown in the browser's own time zone for a datetime-local input.
function localInput(iso: string): string {
  const d = new Date(iso);
  const pad = (n: number) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}
