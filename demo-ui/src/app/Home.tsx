// Home: the one screen to open every morning — stock state, what runs out, sales trend,
// what's on its way, and what needs the owner today.

import { useQuery } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import { SymbolIcon, cn } from '../components/ui';
import { api, loadSession, type AttentionItem, type PoSummary } from '../ops/api';
import { Button, EmptyState, ErrorBox, Freshness, OpsShell, Panel, RequireSession, Skeleton, Stat, StatusChip, day, num, through } from '../ops/kit';
import { DailyBars } from './Charts';
import type { Analytics, Overview, Readiness } from './types';

export function HomePage() {
  return <OpsShell active="home" title={greeting()} subtitle={loadSession()?.tenantName}><RequireSession><Home /></RequireSession></OpsShell>;
}

function greeting() {
  const h = new Date().getHours();
  return h < 12 ? 'Good morning' : h < 18 ? 'Good afternoon' : 'Good evening';
}

function Home() {
  const s = loadSession()!;
  const loc = s.locationId!;
  const overview = useQuery({ queryKey: ['overview', loc], queryFn: () => api<Overview>(`/stock/overview?location_id=${loc}`) });
  const analytics = useQuery({ queryKey: ['analytics', loc, 14], queryFn: () => api<Analytics>(`/analytics?location_id=${loc}&days=14`) });
  const readiness = useQuery({ queryKey: ['readiness', loc], queryFn: () => api<Readiness>(`/readiness?location_id=${loc}`) });
  const tasks = useQuery({ queryKey: ['attention', loc], queryFn: () => api<AttentionItem[]>(`/attention?location_id=${loc}`) });
  const pos = useQuery({ queryKey: ['pos', s.tenantId], queryFn: () => api<PoSummary[]>('/purchase-orders') });

  if (overview.error) return <ErrorBox error={overview.error} onRetry={() => overview.refetch()} />;
  const o = overview.data, a = analytics.data;
  const empty = o && o.items.length === 0;
  const incoming = pos.data?.filter((p) => ['test_sent', 'supplier_confirmed', 'partially_received', 'changes_proposed', 'delivery_unknown'].includes(p.status)) ?? [];
  const oldest = o?.items.filter((i) => i.stock_as_of).sort((x, y) => (x.stock_as_of! < y.stock_as_of! ? -1 : 1))[0];

  if (empty) {
    return (
      <Panel>
        <EmptyState icon="upload_file" title="Let's bring in your products and stock"
          body="Upload a spreadsheet of your stock (or connect Square). Add your sales history too and Tabula can tell you what runs out and what to order.">
          <Link to="/app/data"><Button size="lg">Connect your data</Button></Link>
        </EmptyState>
      </Panel>
    );
  }
  return (
    <>
      {readiness.data && readiness.data.features.some((f) => !f.ready) && <ReadinessStrip r={readiness.data} />}
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        {o ? <>
          <Stat label="Items tracked" value={num(o.items.length)} sub={oldest ? <>Oldest count: <Freshness at={oldest.stock_as_of} stale={oldest.stale} counted={oldest.stock_counted} /></> : undefined} to="/app/inventory" />
          <Stat label="Out of stock" value={num(o.counts.out_of_stock ?? 0)} tone={(o.counts.out_of_stock ?? 0) > 0 ? 'bad' : undefined} to="/app/inventory?state=out_of_stock" />
          <Stat label="Run out within 7 days" value={num(o.counts.at_risk ?? 0)} tone={(o.counts.at_risk ?? 0) > 0 ? 'warn' : undefined} to="/app/inventory?state=at_risk" />
          <Stat label="Orders on the way" value={num(incoming.length)} sub={incoming.length ? 'from your suppliers' : 'nothing ordered'} to="/app/orders/list" />
        </> : Array.from({ length: 4 }, (_, i) => <div key={i} className="h-[104px] animate-pulse rounded-[16px] bg-white" />)}
      </div>

      <div className="grid gap-5 lg:grid-cols-[1.4fr_1fr]">
        <Panel title="Sales, last 14 days" aside={a?.has_data && <Trend a={a} />}>
          {!a && <Skeleton rows={3} />}
          {a && !a.has_data && <EmptyState icon="query_stats" title="No sales data yet" body="Import a sales export to see trends and get demand-based order suggestions."><Link to="/app/data"><Button variant="secondary">Import sales</Button></Link></EmptyState>}
          {a?.has_data && <>
            <DailyBars data={a.daily} />
            <div className="mt-3 text-[12px] text-[#5E6E78]">{a.current.days_with_data} of {a.current.days} days have sales data{a.sales_through ? ` · through ${through(a.sales_through)}` : ''}. Striped days have no data (not zero sales).</div>
          </>}
        </Panel>
        <Panel title="Today" aside={<span className="text-[12px] text-[#5E6E78]">{tasks.data ? `${tasks.data.length} to do` : ''}</span>}>
          {!tasks.data && <Skeleton rows={3} />}
          {tasks.data?.length === 0 && <div className="py-6 text-center text-[14px] text-[#1E7F55]">You're all caught up.</div>}
          <ul className="flex flex-col divide-y divide-[#F1EBE4]">
            {tasks.data?.slice(0, 6).map((t, i) => (
              <li key={i}><Link to={t.href.replace('#links', '')} className="flex items-start gap-3 py-2.5">
                <span className={cn('mt-1 h-2 w-2 shrink-0 rounded-full', t.severity === 'high' ? 'bg-[#B93A26]' : t.severity === 'medium' ? 'bg-[#D6962B]' : 'bg-[#9AA6AD]')} />
                <span className="min-w-0 flex-1"><span className="block text-[14px] font-medium">{t.title}</span><span className="block truncate text-[12px] text-[#5E6E78]">{t.action}</span></span>
                <SymbolIcon icon="chevron_right" family="rounded" className="text-[20px] text-[#9AA6AD]" />
              </Link></li>
            ))}
          </ul>
        </Panel>
      </div>

      <div className="grid gap-5 lg:grid-cols-2">
        <Panel title="Runs out soonest" aside={<Link to="/app/inventory" className="text-[13px] font-semibold text-[#B23F27]">All stock →</Link>}>
          {!o && <Skeleton />}
          <ul className="flex flex-col divide-y divide-[#F1EBE4]">
            {o?.items.filter((i) => i.state === 'out_of_stock' || i.state === 'at_risk').slice(0, 6).map((i) => (
              <li key={i.variant_id}><Link to={`/app/inventory/${i.variant_id}`} className="flex items-center justify-between gap-3 py-2.5">
                <span className="min-w-0"><span className="block truncate text-[14px] font-medium">{i.name}</span><span className="text-[12px] text-[#5E6E78]">{i.sku} · <Freshness at={i.stock_as_of} stale={i.stale} estimated={i.estimated} counted={i.stock_counted} /></span></span>
                <span className="text-right"><span className="block text-[15px] font-bold">{num(i.on_hand)}</span>
                  <span className="text-[12px] text-[#A86A12]">{i.state === 'out_of_stock' ? 'out now' : `out ${day(i.stockout_date)}`}</span></span>
              </Link></li>
            ))}
            {o && !o.items.some((i) => i.state === 'out_of_stock' || i.state === 'at_risk') && <li className="py-6 text-center text-[14px] text-[#5E6E78]">Nothing is expected to run out this week.</li>}
          </ul>
          {o && o.items.some((i) => i.state === 'at_risk' || i.state === 'out_of_stock') && <div className="mt-3"><Link to="/app/orders"><Button>See order suggestions</Button></Link></div>}
        </Panel>
        <Panel title="On the way" aside={<Link to="/app/orders/list" className="text-[13px] font-semibold text-[#B23F27]">All orders →</Link>}>
          {!pos.data && <Skeleton />}
          {pos.data && incoming.length === 0 && <div className="py-6 text-center text-[14px] text-[#5E6E78]">No orders on the way.</div>}
          <ul className="flex flex-col divide-y divide-[#F1EBE4]">
            {incoming.slice(0, 6).map((p) => (
              <li key={p.id}><Link to={`/app/orders/${p.id}`} className="flex flex-wrap items-center justify-between gap-2 py-2.5">
                <span><span className="block text-[14px] font-medium">{p.supplier}</span><span className="text-[12px] text-[#5E6E78]">{p.number} · {p.lines} item{p.lines > 1 ? 's' : ''}</span></span>
                <StatusChip status={p.status} />
              </Link></li>
            ))}
          </ul>
        </Panel>
      </div>
    </>
  );
}

function Trend({ a }: { a: Analytics }) {
  if (a.current.units == null) return null;
  if (a.previous.units == null) return <span className="text-[12px] text-[#5E6E78]">{num(a.current.units)} units · no earlier data to compare</span>;
  const cur = Number(a.current.units), prev = Number(a.previous.units);
  // per day that has data, so a partly covered previous period doesn't distort the change
  const perCur = cur / Math.max(a.current.days_with_data, 1), perPrev = prev / Math.max(a.previous.days_with_data, 1);
  const pct = perPrev ? Math.round(((perCur - perPrev) / perPrev) * 100) : null;
  return <span className={cn('text-[13px] font-semibold', pct != null && pct >= 0 ? 'text-[#1E7F55]' : 'text-[#B93A26]')}>{num(cur)} units{pct != null ? ` · ${pct >= 0 ? '+' : ''}${pct}% vs previous 14 days` : ''}</span>;
}

function ReadinessStrip({ r }: { r: Readiness }) {
  const missing = r.features.filter((f) => !f.ready);
  return (
    <div className="rounded-[16px] border border-[#F1D9AE] bg-[#FDF6E9] px-5 py-4 text-[14px] text-[#6E4A0B]">
      <div className="font-semibold">Some features need more data</div>
      <ul className="mt-1 flex flex-col gap-0.5">
        {missing.map((f) => <li key={f.key}><b>{f.label}:</b> needs {f.missing.map((m) => m.what).join(', ')}. <span className="text-[#8A6A32]">{f.missing[0]?.how}.</span></li>)}
      </ul>
      <Link to="/app/data" className="mt-2 inline-block font-semibold underline">Add data</Link>
    </div>
  );
}
