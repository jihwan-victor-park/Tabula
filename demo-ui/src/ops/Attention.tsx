// "What needs me?" for the store: every open decision or stale input, why, and where to resolve it.
// Plus the one decision made right here: is an order in an open-orders export one of Tabula's POs?

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import { Link } from 'react-router-dom';
import { cn } from '../components/ui';
import { api, type AttentionItem, type OpenOrderLinkView } from './api';
import { Button, ErrorBox, Loading, Panel, num } from './kit';

const TONE = {
  high: 'border-[#F7B4B4] bg-[#FEF2F2]',
  medium: 'border-[#F5D58A] bg-[#FFFBEB]',
  low: 'border-[#E8D4C6] bg-white',
};

export function AttentionPanel({ locationId }: { locationId: string }) {
  const items = useQuery({ queryKey: ['attention', locationId], queryFn: () => api<AttentionItem[]>(`/attention?location_id=${locationId}`), refetchInterval: 15000 });
  if (items.isLoading) return <Panel title="Needs your attention"><Loading /></Panel>;
  if (items.error) return <Panel title="Needs your attention"><ErrorBox error={items.error} onRetry={() => items.refetch()} /></Panel>;
  const list = items.data!;
  return (
    <Panel title="Needs your attention" aside={<span className="text-[12px] text-[#5C7A8A]">{list.length ? `${list.length} item(s)` : 'Nothing waiting'}</span>}>
      {list.length === 0 && <div className="text-[13px] text-[#065F46]">Nothing is waiting on you: data is fresh, no orders are stuck.</div>}
      <ul className="flex flex-col gap-2">
        {list.map((a, i) => (
          <li key={i} className={cn('flex flex-wrap items-start justify-between gap-2 rounded-[12px] border px-4 py-2.5 text-[13px]', TONE[a.severity])}>
            <div className="min-w-0 flex-1">
              <div className="font-medium">{a.title}</div>
              {a.why && <div className="text-[12px] text-[#5C7A8A]">{a.why}</div>}
            </div>
            {a.href.startsWith('/ops/today#') ? <a className="whitespace-nowrap text-[#E8654A] underline" href="#links">{a.action}</a>
              : <Link className="whitespace-nowrap text-[#E8654A] underline" to={a.href}>{a.action} →</Link>}
          </li>
        ))}
      </ul>
    </Panel>
  );
}

export function OpenOrderLinks({ locationId }: { locationId: string }) {
  const qc = useQueryClient();
  const links = useQuery({ queryKey: ['links', locationId], queryFn: () => api<OpenOrderLinkView[]>(`/open-order-links?location_id=${locationId}`) });
  const suggested = links.data?.filter((l) => l.status === 'suggested') ?? [];
  if (!suggested.length) return null;
  return (
    <Panel title="Is this export order one of your Tabula orders?" aside={<span id="links" className="text-[12px] text-[#5C7A8A]">Matched by order number only — never by items or quantities</span>}>
      <ul className="flex flex-col gap-3">
        {suggested.map((l) => <LinkRow key={`${l.supplier_id}:${l.external_po_number}`} link={l} locationId={locationId}
          onDone={() => { qc.invalidateQueries({ queryKey: ['links', locationId] }); qc.invalidateQueries({ queryKey: ['attention', locationId] }); qc.invalidateQueries({ queryKey: ['recommendations', locationId] }); }} />)}
      </ul>
    </Panel>
  );
}

function LinkRow({ link, locationId, onDone }: { link: OpenOrderLinkView; locationId: string; onDone: () => void }) {
  const [note, setNote] = useState('');
  const decide = useMutation({
    mutationFn: (v: { decision: 'same_order' | 'different_order'; po_id?: string }) => api('/open-order-links', { body: {
      location_id: locationId, supplier_id: link.supplier_id, external_po_number: link.external_po_number, note: note || null, ...v } }),
    onSuccess: onDone,
  });
  return (
    <li className="rounded-[12px] border border-[#F5D58A] bg-[#FFFBEB] p-3 text-[13px]">
      <div><b>{link.external_po_number}</b> from {link.supplier} in your open-orders file: {link.lines.map((x) => `${x.sku} ${num(x.outstanding)}${x.confirmed ? ' (confirmed)' : ''}`).join(', ')}</div>
      <div className="mt-1 text-[12px] text-[#6B4A00]">The number nearly matches {link.candidates.map((c) => c.number).join(', ')}. Until you decide, it is not counted — the plan notes it on the item.</div>
      <div className="mt-2 flex flex-wrap items-center gap-2">
        {link.candidates.map((c) => (
          <Button key={c.po_id} variant="secondary" onClick={() => decide.mutate({ decision: 'same_order', po_id: c.po_id })} loading={decide.isPending}>Same order as {c.number}</Button>
        ))}
        <Button variant="secondary" onClick={() => decide.mutate({ decision: 'different_order' })} loading={decide.isPending}>A different order</Button>
        <input className="min-w-[220px] rounded-[8px] border border-[#E8D4C6] px-2 py-1 text-[12px]" placeholder="Note (how you know)" value={note} onChange={(e) => setNote(e.target.value)} />
      </div>
      <ErrorBox error={decide.error} />
    </li>
  );
}
