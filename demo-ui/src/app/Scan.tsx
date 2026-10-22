// Scan: pick what you are doing (look up, stock in, sold/used, damaged, count), then scan.
// A scan only finds the item; nothing changes until a quantity is confirmed. Each saved change
// shows the stock before → after, and can be undone from the list.

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useEffect, useRef, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { SymbolIcon, cn } from '../components/ui';
import { ApiError, api, loadSession, type VariantLite } from '../ops/api';
import { Badge, Button, EmptyState, ErrorBox, Field, Freshness, Notice, OpsShell, Panel, RequireSession, inputCls, num, when } from '../ops/kit';
import type { Lookup, Overview, StockAction } from './types';

const ACTIONS = [
  { key: 'stock_in', label: 'Stock in', hint: 'arrived without a Tabula order', sign: '+' },
  { key: 'used', label: 'Sold / used', hint: 'not in your sales data', sign: '−' },
  { key: 'damaged', label: 'Damaged', hint: 'broken, expired or lost', sign: '−' },
  { key: 'count', label: 'Count', hint: 'set to what is on the shelf', sign: '=' },
] as const;
type ActionKey = (typeof ACTIONS)[number]['key'];
type Mode = 'lookup' | ActionKey;

export function ScanPage() {
  return (
    <OpsShell active="inventory" title="Scan" subtitle={<Link to="/app/inventory" className="hover:underline">← Inventory</Link>}>
      <RequireSession><Scanner /></RequireSession>
    </OpsShell>
  );
}

function Scanner() {
  const loc = loadSession()!.locationId!;
  const [params] = useSearchParams();
  const [mode, setMode] = useState<Mode>('lookup');
  const [code, setCode] = useState('');
  const [current, setCurrent] = useState<string | null>(params.get('code'));
  const input = useRef<HTMLInputElement>(null);
  const qc = useQueryClient();
  const found = useQuery({
    queryKey: ['lookup', current, loc], enabled: !!current,
    queryFn: () => api<Lookup>(`/items/lookup?code=${encodeURIComponent(current!)}&location_id=${loc}`),
  });
  const recent = useQuery({ queryKey: ['stock-actions', loc], queryFn: () => api<StockAction[]>(`/stock-actions?location_id=${loc}`) });
  const focus = () => setTimeout(() => input.current?.focus(), 30);
  useEffect(() => { focus(); }, []); // eslint-disable-line react-hooks/exhaustive-deps
  const done = () => { qc.invalidateQueries({ queryKey: ['stock-actions'] }); qc.invalidateQueries({ queryKey: ['overview'] }); qc.invalidateQueries({ queryKey: ['lookup'] }); qc.invalidateQueries({ queryKey: ['history'] }); };
  const submit = (c: string) => { const v = c.trim(); if (v) { setCurrent(v); setCode(''); } };
  const modeInfo = ACTIONS.find((a) => a.key === mode);
  return (
    <div className="grid items-start gap-5 lg:grid-cols-[1.25fr_1fr]">
      <div className="flex flex-col gap-4">
        <Panel>
          <div className="mb-3" role="radiogroup" aria-label="What are you doing?">
            <div className="mb-1.5 text-[12px] font-medium text-[#66707A]">What are you doing?</div>
            <div className="grid grid-cols-3 gap-1.5 sm:grid-cols-5">
              {([['lookup', 'Look up'], ...ACTIONS.map((a) => [a.key, a.label])] as [Mode, string][]).map(([k, label]) => (
                <button key={k} role="radio" aria-checked={mode === k} onClick={() => { setMode(k); focus(); }}
                  className={cn('rounded-[6px] border px-2 py-2 text-[13px] font-semibold', mode === k ? 'border-[#14181D] bg-[#14181D] text-white' : 'border-[#D5DAE0] bg-white text-[#3B444D] hover:bg-[#F4F5F7]')}>{label}</button>
              ))}
            </div>
            <div className="mt-2 text-[12px] text-[#3B444D]">{mode === 'lookup' ? 'Scanning shows the item; choose what happened afterwards.' : <>Each scan asks how many, then saves <b>{modeInfo!.label.toLowerCase()}</b> ({modeInfo!.hint}).</>}</div>
          </div>
          <form onSubmit={(e) => { e.preventDefault(); submit(code); }} className="flex flex-wrap gap-2">
            <div className="relative min-w-[200px] flex-1">
              <SymbolIcon icon="barcode" family="rounded" className="absolute left-2.5 top-1/2 -translate-y-1/2 text-[20px] text-[#9AA3AC]" />
              <input ref={input} aria-label="Barcode or SKU" className={`${inputCls} min-h-[42px] w-full pl-9 text-[16px] tracking-wide`} inputMode="numeric"
                placeholder="Scan or type a barcode / SKU" value={code} onChange={(e) => setCode(e.target.value)} autoComplete="off" />
            </div>
            <Button type="submit" size="lg">Find</Button>
            <Camera onCode={(c) => submit(c)} />
          </form>
          <p className="mt-2 text-[12px] text-[#66707A]">USB and Bluetooth scanners type into this box and press Enter.</p>
        </Panel>
        {current && found.isLoading && <Panel><div className="h-24 animate-pulse rounded-[6px] bg-[#F4F5F7]" /></Panel>}
        <ErrorBox error={found.error} />
        {found.data?.found && <ItemCard key={`${found.data.variant_id}:${current}:${mode}`} item={found.data} mode={mode} onDone={() => { done(); focus(); }} />}
        {found.data && !found.data.found && <Unknown code={found.data.code} onLinked={() => { found.refetch(); done(); }} />}
      </div>
      <Panel title="Recent changes" sub="Undo a mistake here" padded={false}>
        {recent.data?.length === 0 && <div className="px-4 pb-4 text-[13px] text-[#66707A] md:px-5">Nothing yet.</div>}
        <ul className="divide-y divide-[#EDEFF2] border-t border-[#EDEFF2]">
          {recent.data?.map((r) => <RecentRow key={r.id} r={r} onDone={done} />)}
        </ul>
      </Panel>
    </div>
  );
}

function ItemCard({ item, mode, onDone }: { item: Lookup; mode: Mode; onDone: () => void }) {
  const loc = loadSession()!.locationId!;
  const [action, setAction] = useState<ActionKey | null>(mode === 'lookup' ? null : mode);
  const [qty, setQty] = useState(mode === 'lookup' || mode === 'count' ? '' : '1');
  const [note, setNote] = useState('');
  const [key, setKey] = useState(() => crypto.randomUUID()); // one key per change: a double tap is the same change
  const [saved, setSaved] = useState<{ before: number | null; delta: number; label: string } | null>(null);
  const s = item.stock;
  const save = useMutation({
    mutationFn: () => api<{ delta: string }>('/stock-actions', { body: { location_id: loc, variant_id: item.variant_id, action, qty, note: note || null, request_key: key } }),
    onSuccess: (r) => {
      setKey(crypto.randomUUID());
      setSaved({ before: s?.on_hand != null ? Number(s.on_hand) : null, delta: Number(r.delta), label: ACTIONS.find((a) => a.key === action)!.label });
      if (mode === 'lookup') setAction(null);
      setQty(mode === 'lookup' || mode === 'count' ? '' : '1'); setNote(''); onDone();
    },
  });
  const readOnly = item.stock_owner && item.stock_owner !== 'tabula';
  const info = ACTIONS.find((a) => a.key === action);
  return (
    <Panel>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="text-[17px] font-semibold leading-tight">{item.name}</div>
          <div className="mt-0.5 text-[12px] text-[#66707A]">{item.sku}{item.barcode ? ` · ${item.barcode}` : ''} · <Link to={`/app/inventory/${item.variant_id}`} className="text-[#2457C5] hover:underline">details</Link></div>
        </div>
        <div className="text-right"><div className="text-[12px] text-[#66707A]">In stock</div><div className="text-[26px] font-semibold tabular-nums leading-none">{num(s?.on_hand)}</div>
          <Freshness at={s?.stock_as_of} stale={s?.stale} estimated={s?.estimated} counted={s?.stock_counted ?? true} /></div>
      </div>
      {saved && (
        <div role="status" className="mt-3 flex flex-wrap items-center gap-2 rounded-[6px] bg-[#F0F8F3] px-3 py-2 text-[13px] text-[#164E33]">
          <SymbolIcon icon="check_circle" family="rounded" className="text-[18px]" />
          <b>Saved — {saved.label}:</b>
          {saved.before != null ? <span className="tabular-nums">{num(saved.before)} → {num(saved.before + saved.delta)} ({saved.delta > 0 ? '+' : ''}{num(saved.delta)})</span>
            : <span className="tabular-nums">{saved.delta > 0 ? '+' : ''}{num(saved.delta)}</span>}
          <span className="text-[#3B6B53]">· scan the next item, or undo on the right</span>
        </div>
      )}
      {item.expected_orders && item.expected_orders.length > 0 && (
        <div className="mt-3 rounded-[6px] bg-[#F3F6FC] px-3 py-2 text-[13px] text-[#1B3566]">
          Expected from {item.expected_orders.map((o) => (
            <Link key={o.po_id} to={`/app/receiving/${o.po_id}`} className="font-semibold underline">{o.number} ({num(o.expected)} {o.unit})</Link>))} — record it on the order so it counts once.
        </div>
      )}
      {readOnly ? (
        <div className="mt-3"><Notice tone="info"><b>{item.stock_owner === 'square' ? 'Square' : 'Your POS'} keeps this store's stock.</b> Make the change there; Tabula reads it on the next sync and never counts it twice.</Notice></div>
      ) : (
        <>
          {mode === 'lookup' && (
            <div className="mt-4 grid grid-cols-2 gap-1.5 sm:grid-cols-4">
              {ACTIONS.map((a) => (
                <button key={a.key} onClick={() => { setAction(a.key); setSaved(null); setQty(a.key === 'count' ? '' : '1'); }} className={cn('rounded-[6px] border px-3 py-2 text-left',
                  action === a.key ? 'border-[#2457C5] bg-[#EAF0FB]' : 'border-[#D5DAE0] hover:bg-[#F4F5F7]')}>
                  <span className="block text-[13px] font-semibold">{a.label}</span><span className="block text-[11px] leading-tight text-[#66707A]">{a.hint}</span>
                </button>
              ))}
            </div>
          )}
          {action && (
            <form className="mt-4 grid gap-3 sm:grid-cols-[150px_1fr_auto] sm:items-end" onSubmit={(e) => { e.preventDefault(); save.mutate(); }}>
              <Field label={action === 'count' ? 'On the shelf now' : `How many — ${info!.label.toLowerCase()}`}>
                <input aria-label="Quantity" autoFocus className={`${inputCls} min-h-[42px] text-[17px] tabular-nums`} inputMode="decimal" value={qty} onChange={(e) => setQty(e.target.value)} onFocus={(e) => e.target.select()} required />
              </Field>
              <Field label="Note (optional)"><input className={inputCls} value={note} onChange={(e) => setNote(e.target.value)} placeholder={action === 'damaged' ? 'e.g. torn bag' : ''} /></Field>
              <Button type="submit" size="lg" loading={save.isPending} disabled={!qty}>
                {action === 'count' ? `Set to ${qty || '…'}` : `Save ${info!.sign}${qty || '…'}`}</Button>
            </form>
          )}
          {action && qty && s?.on_hand != null && !save.isPending && (
            <div className="mt-2 text-[12px] text-[#66707A] tabular-nums">Stock will go from {num(s.on_hand)} to {num(action === 'count' ? Number(qty) : Number(s.on_hand) + (info!.sign === '+' ? 1 : -1) * Number(qty))}.</div>
          )}
          <div className="mt-3"><ErrorBox error={save.error} /></div>
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
          {(variants.isLoading || overview.isLoading) && <div className="text-[13px] text-[#66707A]">Loading items…</div>}
          <ul className="flex flex-col divide-y divide-[#EDEFF2]">
            {matches.map((v) => (
              <li key={v.id} className="flex items-center justify-between gap-2 py-2 text-[14px]">
                <span><b>{v.name}</b> <span className="text-[#66707A]">{v.sku}{v.barcode ? ` · has ${v.barcode}` : ''}</span></span>
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
    <li className="flex items-start justify-between gap-3 px-4 py-2.5 text-[13px] md:px-5">
      <span className="min-w-0">
        <span className="block truncate font-medium">{r.name} <span className={cn('font-bold', Number(r.delta) < 0 ? 'text-[#B42318]' : 'text-[#1F7A4D]')}>{Number(r.delta) > 0 ? '+' : ''}{num(r.delta)}</span></span>
        <span className="block text-[12px] text-[#66707A]">{r.note ?? r.reason} · {r.by ?? '—'} · {when(r.at)}</span>
      </span>
      {r.is_undo ? <Badge>undo</Badge> : r.undone ? <Badge>undone</Badge>
        : r.reason === 'count' ? <span className="whitespace-nowrap text-[12px] text-[#66707A]" title="A count resets the level; count again to correct it">count again to fix</span>
        : <Button size="sm" variant="ghost" onClick={() => undo.mutate()} loading={undo.isPending}>Undo</Button>}
      {undo.error instanceof ApiError && <span className="text-[12px] text-[#B42318]">{undo.error.message}</span>}
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
  if (!supported) return <span className="self-center text-[12px] text-[#66707A]" title="This browser cannot read barcodes from the camera">Camera scanning isn't supported in this browser</span>;
  return (
    <>
      <Button variant="secondary" size="lg" onClick={() => setOpen((o) => !o)}><SymbolIcon icon="photo_camera" family="rounded" className="text-[20px]" />{open ? 'Stop' : 'Camera'}</Button>
      {open && <video ref={video} className="mt-2 w-full rounded-[6px] bg-black" playsInline muted />}
      {error && <div className="w-full text-[12px] text-[#B42318]">{error}</div>}
    </>
  );
}
