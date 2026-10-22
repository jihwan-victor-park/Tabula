// Scan: find an item by barcode (scanner, typing or camera), then choose what happened.
// Scanning alone never changes stock.

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { SymbolIcon, cn } from '../components/ui';
import { ApiError, api, loadSession, type VariantLite } from '../ops/api';
import { Badge, Button, EmptyState, ErrorBox, Field, Freshness, Notice, OpsShell, Panel, RequireSession, inputCls, num, when } from '../ops/kit';
import type { Lookup, Overview, StockAction } from './types';

const ACTIONS = [
  { key: 'stock_in', label: 'Stock in', hint: 'Arrived without a Tabula order', icon: 'add_box', sign: '+' },
  { key: 'used', label: 'Sold / used', hint: 'Not in your sales data (e.g. used in store)', icon: 'shopping_bag', sign: '−' },
  { key: 'damaged', label: 'Damaged', hint: 'Broken, expired or lost', icon: 'heart_broken', sign: '−' },
  { key: 'count', label: 'Count', hint: 'Set to what is on the shelf', icon: 'fact_check', sign: '=' },
] as const;
type ActionKey = (typeof ACTIONS)[number]['key'];

export function ScanPage() {
  return <OpsShell active="scan" title="Scan" subtitle="Scan or type a barcode, then choose what happened."><RequireSession><Scanner /></RequireSession></OpsShell>;
}

function Scanner() {
  const loc = loadSession()!.locationId!;
  const [code, setCode] = useState('');
  const [current, setCurrent] = useState<string | null>(null);
  const input = useRef<HTMLInputElement>(null);
  const qc = useQueryClient();
  const found = useQuery({
    queryKey: ['lookup', current, loc], enabled: !!current,
    queryFn: () => api<Lookup>(`/items/lookup?code=${encodeURIComponent(current!)}&location_id=${loc}`),
  });
  const recent = useQuery({ queryKey: ['stock-actions', loc], queryFn: () => api<StockAction[]>(`/stock-actions?location_id=${loc}`) });
  const focus = () => setTimeout(() => input.current?.focus(), 30);
  useEffect(() => { focus(); }, []); // eslint-disable-line react-hooks/exhaustive-deps
  const done = () => { qc.invalidateQueries({ queryKey: ['stock-actions'] }); qc.invalidateQueries({ queryKey: ['overview'] }); qc.invalidateQueries({ queryKey: ['lookup'] }); };
  const submit = (c: string) => { const v = c.trim(); if (v) { setCurrent(v); setCode(''); } };
  return (
    <div className="grid gap-5 lg:grid-cols-[1.2fr_1fr]">
      <div className="flex flex-col gap-5">
        <Panel>
          <form onSubmit={(e) => { e.preventDefault(); submit(code); }} className="flex flex-wrap gap-2">
            <div className="relative min-w-[220px] flex-1">
              <SymbolIcon icon="barcode" family="rounded" className="absolute left-3 top-1/2 -translate-y-1/2 text-[22px] text-[#9AA6AD]" />
              <input ref={input} aria-label="Barcode or SKU" className={`${inputCls} w-full pl-11 text-[18px] tracking-wide`} inputMode="numeric"
                placeholder="Scan or type a barcode / SKU" value={code} onChange={(e) => setCode(e.target.value)} autoComplete="off" />
            </div>
            <Button type="submit" size="lg">Find</Button>
            <Camera onCode={(c) => submit(c)} />
          </form>
          <p className="mt-2 text-[12px] text-[#5E6E78]">USB or Bluetooth scanners work here directly: scan into this box (it ends with Enter).</p>
        </Panel>
        {current && found.isLoading && <Panel><div className="h-24 animate-pulse rounded-[12px] bg-[#F7F3EE]" /></Panel>}
        <ErrorBox error={found.error} />
        {found.data?.found && <ItemCard key={`${found.data.variant_id}:${current}`} item={found.data} onDone={() => { done(); focus(); }} />}
        {found.data && !found.data.found && <Unknown code={found.data.code} onLinked={() => { found.refetch(); done(); }} />}
      </div>
      <Panel title="Recent changes" aside={<span className="text-[12px] text-[#5E6E78]">who · what · when</span>}>
        {recent.data?.length === 0 && <div className="text-[14px] text-[#5E6E78]">Nothing yet. Changes you make by scanning appear here and can be undone.</div>}
        <ul className="flex flex-col divide-y divide-[#F1EBE4]">
          {recent.data?.map((r) => <RecentRow key={r.id} r={r} onDone={done} />)}
        </ul>
      </Panel>
    </div>
  );
}

function ItemCard({ item, onDone }: { item: Lookup; onDone: () => void }) {
  const loc = loadSession()!.locationId!;
  const [action, setAction] = useState<ActionKey | null>(null);
  const [qty, setQty] = useState('');
  const [note, setNote] = useState('');
  const [key, setKey] = useState(() => crypto.randomUUID()); // one key per change: a double tap is the same change
  const [saved, setSaved] = useState<string | null>(null);
  const save = useMutation({
    mutationFn: () => api<{ delta: string }>('/stock-actions', { body: { location_id: loc, variant_id: item.variant_id, action, qty, note: note || null, request_key: key } }),
    onSuccess: (r) => { setKey(crypto.randomUUID()); setSaved(`Saved: ${Number(r.delta) > 0 ? '+' : ''}${num(r.delta)} ${item.name}`); setAction(null); setQty(''); setNote(''); onDone(); },
  });
  const s = item.stock;
  const readOnly = item.stock_owner && item.stock_owner !== 'tabula';
  return (
    <Panel>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="text-[20px] font-bold leading-tight">{item.name}</div>
          <div className="mt-0.5 text-[13px] text-[#5E6E78]">{item.sku}{item.barcode ? ` · ${item.barcode}` : ''}</div>
          <Link to={`/app/inventory/${item.variant_id}`} className="text-[13px] font-semibold text-[#B23F27]">History →</Link>
        </div>
        <div className="text-right"><div className="text-[12px] text-[#5E6E78]">In stock</div><div className="text-[32px] font-bold leading-none">{num(s?.on_hand)}</div>
          <Freshness at={s?.stock_as_of} stale={s?.stale} estimated={s?.estimated} counted={s?.stock_counted ?? true} /></div>
      </div>
      {item.expected_orders && item.expected_orders.length > 0 && (
        <div className="mt-4 rounded-[12px] bg-[#F1F6FC] p-3 text-[14px] text-[#24507F]">
          Expected from an order: {item.expected_orders.map((o) => (
            <Link key={o.po_id} to={`/app/receiving/${o.po_id}`} className="ml-1 font-semibold underline">{o.number} ({num(o.expected)} {o.unit}) — receive it</Link>))}
          <div className="text-[12px]">Deliveries for an order are recorded on Receiving, so they count once.</div>
        </div>
      )}
      {readOnly ? (
        <div className="mt-4"><Notice tone="info"><b>{item.stock_owner === 'square' ? 'Square' : 'Your POS'} keeps this store's stock.</b> Make the change there; Tabula reads it on the next sync. (Tabula doesn't write to Square, so stock is never counted twice.)</Notice></div>
      ) : (
        <>
          <div className="mt-5 grid grid-cols-2 gap-2 sm:grid-cols-4">
            {ACTIONS.map((a) => (
              <button key={a.key} onClick={() => { setAction(a.key); setSaved(null); }} className={cn('flex flex-col items-start gap-1 rounded-[12px] border p-3 text-left transition-colors',
                action === a.key ? 'border-[#E25C3F] bg-[#FCE9E3]' : 'border-[#E8E0D8] hover:bg-[#F7F3EE]')}>
                <SymbolIcon icon={a.icon} family="rounded" className="text-[22px] text-[#B23F27]" />
                <span className="text-[14px] font-semibold">{a.label}</span><span className="text-[11px] leading-tight text-[#5E6E78]">{a.hint}</span>
              </button>
            ))}
          </div>
          {action && (
            <form className="mt-4 grid gap-3 sm:grid-cols-[160px_1fr_auto] sm:items-end" onSubmit={(e) => { e.preventDefault(); save.mutate(); }}>
              <Field label={action === 'count' ? 'On the shelf now' : 'How many'}>
                <input aria-label="Quantity" autoFocus className={`${inputCls} text-[18px]`} inputMode="decimal" value={qty} onChange={(e) => setQty(e.target.value)} required />
              </Field>
              <Field label="Reason / note (optional)"><input className={inputCls} value={note} onChange={(e) => setNote(e.target.value)} placeholder={action === 'damaged' ? 'e.g. torn bag' : ''} /></Field>
              <Button type="submit" size="lg" loading={save.isPending} disabled={!qty}>
                {action === 'count' ? `Set to ${qty || '…'}` : `${ACTIONS.find((a) => a.key === action)!.sign}${qty || '…'}`} — save</Button>
            </form>
          )}
          {action === 'count' && qty && s?.on_hand != null && <div className="mt-2 text-[13px] text-[#5E6E78]">Change: {num(Number(qty) - Number(s.on_hand))} (Tabula has {num(s.on_hand)})</div>}
          <div className="mt-3"><ErrorBox error={save.error} /></div>
          {saved && <div className="mt-3"><Notice tone="ok">{saved}. Scan the next item.</Notice></div>}
        </>
      )}
    </Panel>
  );
}

function Unknown({ code, onLinked }: { code: string; onLinked: () => void }) {
  const loc = loadSession()!.locationId!;
  const [mode, setMode] = useState<'new' | 'link' | null>(null);
  const [name, setName] = useState('');
  const [sku, setSku] = useState(code);
  const [search, setSearch] = useState('');
  const overview = useQuery({ queryKey: ['overview', loc], queryFn: () => api<Overview>(`/stock/overview?location_id=${loc}`), enabled: mode === 'link' });
  const variants = useQuery({ queryKey: ['variants'], queryFn: () => api<VariantLite[]>('/variants'), enabled: mode === 'link' });
  const create = useMutation({ mutationFn: () => api('/variants', { body: { sku, name, barcode: code } }), onSuccess: onLinked });
  const link = useMutation({
    mutationFn: (v: VariantLite) => api(`/variants/${v.id}`, { method: 'PATCH', body: { version: v.version, barcode: code, reason: 'Linked by scanning' } }),
    onSuccess: onLinked,
  });
  const matches = (variants.data ?? []).filter((v) => !search || v.name.toLowerCase().includes(search.toLowerCase()) || v.sku.toLowerCase().includes(search.toLowerCase())).slice(0, 8);
  return (
    <Panel>
      <EmptyState icon="help" title={`No item has barcode ${code}`} body="Add it as a new item, or attach this barcode to an item you already have.">
        <Button onClick={() => setMode('new')} variant={mode === 'new' ? 'primary' : 'secondary'}>Add new item</Button>
        <Button onClick={() => setMode('link')} variant={mode === 'link' ? 'primary' : 'secondary'}>Attach to existing item</Button>
      </EmptyState>
      {mode === 'new' && (
        <form className="grid gap-3 sm:grid-cols-[1fr_200px_auto] sm:items-end" onSubmit={(e) => { e.preventDefault(); create.mutate(); }}>
          <Field label="Item name"><input className={inputCls} value={name} onChange={(e) => setName(e.target.value)} required autoFocus /></Field>
          <Field label="SKU"><input className={inputCls} value={sku} onChange={(e) => setSku(e.target.value)} required /></Field>
          <Button type="submit" loading={create.isPending}>Add item</Button>
        </form>
      )}
      {mode === 'link' && (
        <div className="flex flex-col gap-2">
          <input className={inputCls} placeholder="Search your items" value={search} onChange={(e) => setSearch(e.target.value)} autoFocus />
          {(variants.isLoading || overview.isLoading) && <div className="text-[13px] text-[#5E6E78]">Loading items…</div>}
          <ul className="flex flex-col divide-y divide-[#F1EBE4]">
            {matches.map((v) => (
              <li key={v.id} className="flex items-center justify-between gap-2 py-2 text-[14px]">
                <span><b>{v.name}</b> <span className="text-[#5E6E78]">{v.sku}{v.barcode ? ` · has ${v.barcode}` : ''}</span></span>
                <Button size="sm" variant="secondary" onClick={() => link.mutate(v)} loading={link.isPending}>Attach</Button>
              </li>
            ))}
          </ul>
        </div>
      )}
      <ErrorBox error={create.error ?? link.error} />
    </Panel>
  );
}

function RecentRow({ r, onDone }: { r: StockAction; onDone: () => void }) {
  const undo = useMutation({ mutationFn: () => api(`/stock-actions/${r.id}/undo`, { body: { note: null } }), onSuccess: onDone });
  return (
    <li className="flex items-start justify-between gap-3 py-2.5 text-[14px]">
      <span className="min-w-0">
        <span className="block truncate font-medium">{r.name} <span className={cn('font-bold', Number(r.delta) < 0 ? 'text-[#B93A26]' : 'text-[#1E7F55]')}>{Number(r.delta) > 0 ? '+' : ''}{num(r.delta)}</span></span>
        <span className="block text-[12px] text-[#5E6E78]">{r.note ?? r.reason} · {r.by ?? '—'} · {when(r.at)}</span>
      </span>
      {r.is_undo ? <Badge>undo</Badge> : r.undone ? <Badge>undone</Badge>
        : r.reason === 'count' ? <span className="whitespace-nowrap text-[12px] text-[#5E6E78]" title="A count resets the level; count again to correct it">count again to fix</span>
        : <Button size="sm" variant="ghost" onClick={() => undo.mutate()} loading={undo.isPending}>Undo</Button>}
      {undo.error instanceof ApiError && <span className="text-[12px] text-[#B93A26]">{undo.error.message}</span>}
    </li>
  );
}

// Camera scanning where the browser can read barcodes itself (Chrome on Android / desktop).
function Camera({ onCode }: { onCode: (code: string) => void }) {
  const supported = typeof window !== 'undefined' && 'BarcodeDetector' in window && !!navigator.mediaDevices?.getUserMedia;
  const [open, setOpen] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const video = useRef<HTMLVideoElement>(null);
  useEffect(() => {
    if (!open) return;
    let stream: MediaStream | null = null, timer = 0, stopped = false;
    (async () => {
      try {
        stream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: 'environment' } });
        if (!video.current) return;
        video.current.srcObject = stream;
        await video.current.play();
        const detector = new (window as any).BarcodeDetector({ formats: ['ean_13', 'ean_8', 'upc_a', 'upc_e', 'code_128', 'code_39'] });
        const tick = async () => {
          if (stopped || !video.current) return;
          const codes = await detector.detect(video.current).catch(() => []);
          if (codes[0]?.rawValue) { onCode(codes[0].rawValue); setOpen(false); return; }
          timer = window.setTimeout(tick, 250);
        };
        tick();
      } catch {
        setError('Camera not available — allow camera access, or use a scanner / type the code.');
        setOpen(false);
      }
    })();
    return () => { stopped = true; clearTimeout(timer); stream?.getTracks().forEach((t) => t.stop()); };
  }, [open, onCode]);
  if (!supported) return <span className="self-center text-[12px] text-[#5E6E78]" title="This browser cannot read barcodes from the camera">Camera scanning isn't supported in this browser</span>;
  return (
    <>
      <Button variant="secondary" size="lg" onClick={() => setOpen((o) => !o)}><SymbolIcon icon="photo_camera" family="rounded" className="text-[20px]" />{open ? 'Stop' : 'Camera'}</Button>
      {open && <video ref={video} className="mt-2 w-full rounded-[12px] bg-black" playsInline muted />}
      {error && <div className="w-full text-[12px] text-[#B93A26]">{error}</div>}
    </>
  );
}
