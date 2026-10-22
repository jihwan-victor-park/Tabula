// Setup: the first screen of a new store. Connect data step by step; each step says what it unlocks.
// Done or not, the person can go to the Overview at any point — it shows what is still missing.

import { useQuery } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import { SymbolIcon, cn } from '../components/ui';
import { api, loadSession } from '../ops/api';
import { ButtonLink, OpsShell, Panel, RequireSession, Skeleton } from '../ops/kit';
import type { Readiness } from './types';

export function SetupPage() {
  return (
    <OpsShell active="overview" title="Set up your store" subtitle="Connect your data. Each step unlocks more of Tabula; you can stop at any point.">
      <RequireSession><Steps /></RequireSession>
    </OpsShell>
  );
}

function Steps() {
  const loc = loadSession()!.locationId!;
  const r = useQuery({ queryKey: ['readiness', loc], queryFn: () => api<Readiness>(`/readiness?location_id=${loc}`) }).data;
  if (!r) return <Skeleton rows={4} />;
  const f = r.facts;
  const feature = (k: string) => r.features.find((x) => x.key === k);
  const steps = [
    { done: f.products > 0 && f.stock_readings > 0, title: 'Stock on hand', unlocks: 'Inventory list and barcode scanning',
      detail: f.products ? `${f.products} items` : 'A spreadsheet of items with SKU or barcode and how many you have.',
      action: <ButtonLink to="/app/settings/data/import?kind=inventory&return=/app/setup" size="sm" variant={f.products ? 'secondary' : 'primary'}>{f.products ? 'Upload again' : 'Upload stock file'}</ButtonLink>,
      alt: <Link to="/app/settings/data" className="text-[12px] text-[#2457C5] hover:underline">or connect Square</Link> },
    { done: !!feature('suggestions')?.ready, title: 'Sales history', unlocks: 'What runs out, trends and order suggestions',
      detail: f.sales_days ? `${f.sales_days} days so far — at least 14 needed for suggestions` : 'An export of past sales (date, SKU, quantity), ideally 4 weeks or more.',
      action: <ButtonLink to="/app/settings/data/import?kind=sales&return=/app/setup" size="sm" variant={f.products && !f.sales_days ? 'primary' : 'secondary'}>Import sales</ButtonLink> },
    { done: f.approved_suppliers > 0 && f.priced_items > 0, title: 'Suppliers and prices', unlocks: 'Order quantities in cases, with cost',
      detail: f.approved_suppliers ? `${f.approved_suppliers} supplier(s), ${f.priced_items} item(s) with a price` : 'Who you buy from, their order email, and what each item costs.',
      action: <ButtonLink to="/app/orders/suppliers" size="sm" variant="secondary">{f.approved_suppliers ? 'Manage suppliers' : 'Add a supplier'}</ButtonLink> },
    { done: f.ship_to_address, title: 'Delivery address', unlocks: 'Printed on every order',
      detail: f.ship_to_address ? 'Saved' : 'Where suppliers deliver.', action: <ButtonLink to="/app/settings" size="sm" variant="secondary">{f.ship_to_address ? 'Edit address' : 'Add address'}</ButtonLink> },
  ];
  const done = steps.filter((s) => s.done).length;
  return (
    <>
      <Panel padded={false} title={`${done} of ${steps.length} done`} aside={<ButtonLink to="/app" variant={steps[0].done ? 'primary' : 'ghost'}>Go to Overview</ButtonLink>}>
        <ol className="divide-y divide-[#EDEFF2] border-t border-[#EDEFF2]">
          {steps.map((s, i) => (
            <li key={s.title} className="flex flex-wrap items-center gap-x-4 gap-y-2 px-4 py-4 md:flex-nowrap md:px-5">
              <span className={cn('flex h-7 w-7 shrink-0 items-center justify-center rounded-full text-[13px] font-semibold',
                s.done ? 'bg-[#1F7A4D] text-white' : 'border border-[#D5DAE0] text-[#3B444D]')}>
                {s.done ? <SymbolIcon icon="check" family="rounded" className="text-[17px]" /> : i + 1}</span>
              <div className="min-w-0 flex-1">
                <div className="text-[14px] font-semibold">{s.title} <span className="font-normal text-[#66707A]">— {s.unlocks}</span></div>
                <div className="text-[13px] text-[#66707A]">{s.detail}</div>
              </div>
              <div className="flex shrink-0 flex-col items-end gap-1">{s.action}{s.alt}</div>
            </li>
          ))}
        </ol>
      </Panel>
      <p className="text-[13px] text-[#66707A]">Just looking? <Link to="/app/stores" className="text-[#2457C5] hover:underline">Open the sample store</Link> — a fictional pet shop with everything filled in, kept apart from yours.</p>
    </>
  );
}
