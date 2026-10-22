// Tabula design system + app shell. One look for every screen: sign-in, setup, stock, scanning,
// insights, orders. Colours: warm paper background, white surfaces, navy ink, coral for actions.

import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useEffect, useState, type ReactNode } from 'react';
import { Link, NavLink, useLocation, useNavigate } from 'react-router-dom';
import { SymbolIcon, cn } from '../components/ui';
import { ApiError, api, loadSession, saveSession, type Me } from './api';

export const C = {
  ink: '#16232B', muted: '#5E6E78', line: '#E8E0D8', paper: '#F7F3EE', brand: '#E25C3F', brandSoft: '#FCE9E3',
  navy: '#1F3A4A', good: '#1E7F55', warn: '#A86A12', bad: '#B93A26', info: '#2C64A0',
};

type NavKey = 'home' | 'inventory' | 'scan' | 'insights' | 'orders' | 'suppliers' | 'data' | 'settings';
const LEGACY: Record<string, NavKey> = { today: 'orders', imports: 'data', receiving: 'orders', connections: 'data', setup: 'settings' };
const NAV: { key: NavKey; label: string; icon: string; to: string }[] = [
  { key: 'home', label: 'Home', icon: 'space_dashboard', to: '/app' },
  { key: 'inventory', label: 'Inventory', icon: 'inventory_2', to: '/app/inventory' },
  { key: 'scan', label: 'Scan', icon: 'barcode_scanner', to: '/app/scan' },
  { key: 'insights', label: 'Insights', icon: 'monitoring', to: '/app/insights' },
  { key: 'orders', label: 'Orders', icon: 'local_shipping', to: '/app/orders' },
  { key: 'suppliers', label: 'Suppliers', icon: 'storefront', to: '/app/suppliers' },
  { key: 'data', label: 'Data', icon: 'sync_alt', to: '/app/data' },
  { key: 'settings', label: 'Settings', icon: 'settings', to: '/app/settings' },
];
const MOBILE: NavKey[] = ['home', 'inventory', 'scan', 'orders'];

export function useMe() {
  return useQuery({ queryKey: ['me'], queryFn: () => api<Me>('/me', { noTenant: true }), retry: false, staleTime: 30_000 });
}

export function OpsShell({ active, title, subtitle, actions, children }: {
  active: NavKey | keyof typeof LEGACY; title: string; subtitle?: ReactNode; icon?: string; actions?: ReactNode; children: ReactNode;
}) {
  const key = (LEGACY[active as string] ?? active) as NavKey;
  const session = loadSession();
  const me = useMe();
  const navigate = useNavigate();
  const qc = useQueryClient();
  const [more, setMore] = useState(false);
  useEffect(() => { document.title = `${title} · Tabula`; }, [title]);
  const signOut = async () => {
    try { await api('/auth/logout', { method: 'POST', noTenant: true }); } catch { /* already signed out */ }
    saveSession(null); qc.clear(); navigate('/signin');
  };
  return (
    <div className="min-h-screen bg-[#F7F3EE] font-[Plus_Jakarta_Sans,system-ui,sans-serif] text-[#16232B] [font-feature-settings:'tnum']">
      <aside className="fixed inset-y-0 left-0 z-30 hidden w-[236px] flex-col border-r border-[#E8E0D8] bg-white lg:flex">
        <Link to="/app" className="flex items-center gap-2 px-5 pb-4 pt-5"><Logo /></Link>
        <StoreSwitcher />
        <nav className="mt-3 flex flex-col gap-0.5 px-3">
          {NAV.map((n) => (
            <NavLink key={n.key} to={n.to} end={n.to === '/app'}
              className={cn('flex items-center gap-3 rounded-[10px] px-3 py-2 text-[14px] font-medium transition-colors',
                key === n.key ? 'bg-[#FCE9E3] text-[#B23F27]' : 'text-[#41525C] hover:bg-[#F7F3EE]')}>
              <SymbolIcon icon={n.icon} family="rounded" className="text-[20px]" />{n.label}
            </NavLink>
          ))}
        </nav>
        <div className="mt-auto px-5 pb-5 text-[12px] text-[#5E6E78]">
          <div className="mb-3 rounded-[10px] bg-[#F7F3EE] p-3 leading-snug"><b className="text-[#16232B]">Test mode.</b> Approved orders are kept in Tabula and not emailed to suppliers.</div>
          <div className="truncate">{me.data?.email ?? session?.user ?? ''}</div>
          <button className="mt-1 underline" onClick={signOut}>Sign out</button>
        </div>
      </aside>

      <header className="sticky top-0 z-20 flex items-center justify-between gap-3 border-b border-[#E8E0D8] bg-white/95 px-4 py-3 backdrop-blur lg:hidden">
        <Link to="/app"><Logo /></Link>
        <Link to="/app/stores" className="max-w-[55%] truncate text-[13px] font-medium text-[#41525C]">{session?.tenantName ?? 'Choose store'}</Link>
      </header>

      <main className="pb-24 lg:pb-10 lg:pl-[236px]">
        {session?.isSample && (
          <div className="flex flex-wrap items-center justify-center gap-2 bg-[#1F3A4A] px-4 py-2 text-center text-[13px] text-white">
            <SymbolIcon icon="science" family="rounded" className="text-[18px]" />
            Sample store — fictional products, suppliers and sales. Your real store's data is kept separately.
            <Link to="/app/stores" className="underline">Switch store</Link>
          </div>
        )}
        <div className="mx-auto w-full max-w-[1180px] px-4 pt-5 md:px-8 md:pt-8">
          <div className="mb-5 flex flex-wrap items-end justify-between gap-3">
            <div className="min-w-0">
              <h1 className="text-[24px] font-bold tracking-[-0.01em] md:text-[28px]">{title}</h1>
              {subtitle && <div className="mt-1 text-[14px] text-[#5E6E78]">{subtitle}</div>}
            </div>
            {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
          </div>
          <div className="flex flex-col gap-5">{children}</div>
        </div>
      </main>

      <nav className="fixed inset-x-0 bottom-0 z-30 grid grid-cols-5 border-t border-[#E8E0D8] bg-white pb-[env(safe-area-inset-bottom)] lg:hidden">
        {MOBILE.map((k) => {
          const n = NAV.find((x) => x.key === k)!;
          return (
            <NavLink key={k} to={n.to} end={n.to === '/app'} className={cn('flex flex-col items-center gap-0.5 py-2 text-[11px] font-medium',
              key === k ? 'text-[#B23F27]' : 'text-[#5E6E78]')}>
              {k === 'scan' ? <span className="-mt-5 flex h-12 w-12 items-center justify-center rounded-full bg-[#E25C3F] text-white shadow-lg"><SymbolIcon icon={n.icon} family="rounded" className="text-[24px]" /></span>
                : <SymbolIcon icon={n.icon} family="rounded" className="text-[22px]" />}
              {n.label}
            </NavLink>
          );
        })}
        <button onClick={() => setMore((m) => !m)} className={cn('flex flex-col items-center gap-0.5 py-2 text-[11px] font-medium', more ? 'text-[#B23F27]' : 'text-[#5E6E78]')}>
          <SymbolIcon icon="menu" family="rounded" className="text-[22px]" />More
        </button>
        {more && (
          <div className="absolute bottom-full right-2 mb-2 w-[220px] rounded-[14px] border border-[#E8E0D8] bg-white p-2 shadow-xl">
            {NAV.filter((n) => !MOBILE.includes(n.key)).map((n) => (
              <Link key={n.key} to={n.to} onClick={() => setMore(false)} className="flex items-center gap-3 rounded-[10px] px-3 py-2 text-[14px] hover:bg-[#F7F3EE]">
                <SymbolIcon icon={n.icon} family="rounded" className="text-[20px]" />{n.label}
              </Link>
            ))}
            <button className="flex w-full items-center gap-3 rounded-[10px] px-3 py-2 text-[14px] hover:bg-[#F7F3EE]" onClick={signOut}>
              <SymbolIcon icon="logout" family="rounded" className="text-[20px]" />Sign out
            </button>
          </div>
        )}
      </nav>
    </div>
  );
}

export function Logo({ light = false }: { light?: boolean }) {
  return (
    <span className="flex items-center gap-2">
      <span className="flex h-8 w-8 items-center justify-center rounded-[9px] bg-[#E25C3F] text-[17px] font-extrabold text-white">T</span>
      <span className={cn('text-[18px] font-extrabold tracking-[-0.02em]', light ? 'text-white' : 'text-[#16232B]')}>Tabula</span>
    </span>
  );
}

function StoreSwitcher() {
  const session = loadSession();
  return (
    <Link to="/app/stores" className="mx-3 flex items-center justify-between gap-2 rounded-[12px] border border-[#E8E0D8] px-3 py-2.5 hover:bg-[#F7F3EE]">
      <span className="min-w-0">
        <span className="block text-[11px] font-medium uppercase tracking-wide text-[#5E6E78]">{session?.isSample ? 'Sample store' : 'Store'}</span>
        <span className="block truncate text-[14px] font-semibold">{session?.tenantName ?? 'Choose a store'}</span>
      </span>
      <SymbolIcon icon="unfold_more" family="rounded" className="text-[18px] text-[#5E6E78]" />
    </Link>
  );
}

/** Signed in + a store chosen; otherwise send the person where they need to go. */
export function RequireSession({ children, needLocation = true }: { children: ReactNode; needLocation?: boolean }) {
  const me = useMe();
  const navigate = useNavigate();
  const loc = useLocation();
  const session = loadSession();
  useEffect(() => {
    if (me.error instanceof ApiError && me.error.status === 401) navigate(`/signin?next=${encodeURIComponent(loc.pathname)}`, { replace: true });
    else if (me.data && !session?.tenantId) navigate('/app/stores', { replace: true });
  }, [me.error, me.data, session?.tenantId, navigate, loc.pathname]);
  if (me.isLoading) return <Loading label="Opening your store…" />;
  if (me.error && !(me.error instanceof ApiError && me.error.status === 401)) return <ErrorBox error={me.error} onRetry={() => me.refetch()} />;
  if (!me.data || !session?.tenantId) return null;
  if (needLocation && !session.locationId) return <LocationGate />;
  return <>{children}</>;
}

function LocationGate() {
  const session = loadSession()!;
  const locations = useQuery({ queryKey: ['locations', session.tenantId], queryFn: () => api<{ id: string; name: string }[]>('/locations') });
  const navigate = useNavigate();
  useEffect(() => {
    if (locations.data?.length === 1) { saveSession({ ...session, locationId: locations.data[0].id }); navigate(0); }
  }, [locations.data]); // eslint-disable-line react-hooks/exhaustive-deps
  if (locations.isLoading || locations.data?.length === 1) return <Loading />;
  return (
    <Panel title="Which location?">
      <div className="flex flex-col gap-2">
        {locations.data?.map((l) => <Button key={l.id} variant="secondary" onClick={() => { saveSession({ ...session, locationId: l.id }); navigate(0); }}>{l.name}</Button>)}
        {locations.data?.length === 0 && <EmptyState icon="location_off" title="This store has no location yet" body="Add one in Settings." />}
      </div>
    </Panel>
  );
}

export function Panel({ children, className, title, aside, padded = true }: { children: ReactNode; className?: string; title?: ReactNode; aside?: ReactNode; padded?: boolean }) {
  return (
    <section className={cn('rounded-[18px] border border-[#E8E0D8] bg-white', padded && 'p-5 md:p-6', className)}>
      {(title || aside) && (
        <div className={cn('mb-4 flex flex-wrap items-center justify-between gap-2', !padded && 'px-5 pt-5 md:px-6')}>
          {title && <h2 className="text-[16px] font-semibold">{title}</h2>}
          {aside}
        </div>
      )}
      {children}
    </section>
  );
}

const TONES = {
  neutral: 'bg-[#F1EEEA] text-[#41525C]', good: 'bg-[#E3F3EA] text-[#1E7F55]', warn: 'bg-[#FBF0DC] text-[#8A5A0E]',
  bad: 'bg-[#FBE5E1] text-[#B93A26]', info: 'bg-[#E4EEF8] text-[#2C64A0]', brand: 'bg-[#FCE9E3] text-[#B23F27]',
};
const STATUS: Record<string, { label: string; tone: keyof typeof TONES; icon: string }> = {
  draft: { label: 'Draft', tone: 'neutral', icon: 'edit_note' },
  awaiting_approval: { label: 'Waiting for approval', tone: 'warn', icon: 'hourglass_top' },
  queued: { label: 'Sending…', tone: 'info', icon: 'schedule_send' },
  test_sent: { label: 'Sent (test mode) — waiting for supplier', tone: 'info', icon: 'mark_email_read' },
  delivery_unknown: { label: 'Not sure the supplier got it', tone: 'bad', icon: 'help' },
  failed: { label: 'Not sent', tone: 'bad', icon: 'error' },
  cancelled: { label: 'Cancelled', tone: 'neutral', icon: 'block' },
  supplier_confirmed: { label: 'Confirmed by supplier', tone: 'good', icon: 'verified' },
  changes_proposed: { label: 'Supplier proposed changes', tone: 'warn', icon: 'change_circle' },
  partially_received: { label: 'Partly received', tone: 'info', icon: 'inventory_2' },
  received: { label: 'Received — issues open', tone: 'warn', icon: 'inventory_2' },
  closed: { label: 'Complete', tone: 'neutral', icon: 'task_alt' },
  order: { label: 'Order', tone: 'brand', icon: 'add_shopping_cart' },
  on_hold: { label: 'On hold — already ordered', tone: 'warn', icon: 'pause_circle' },
  covered: { label: 'Covered by incoming order', tone: 'info', icon: 'local_shipping' },
  no_order: { label: 'Enough stock', tone: 'good', icon: 'check_circle' },
  no_supplier: { label: 'No supplier', tone: 'bad', icon: 'link_off' },
  insufficient_data: { label: 'Not enough data', tone: 'neutral', icon: 'help' },
  excluded: { label: 'Not tracked', tone: 'neutral', icon: 'do_not_disturb_on' },
  uploaded: { label: 'Needs review', tone: 'warn', icon: 'rule' },
  confirmed: { label: 'Importing…', tone: 'info', icon: 'sync' },
  applying: { label: 'Importing…', tone: 'info', icon: 'sync' },
  applied: { label: 'Imported', tone: 'good', icon: 'task_alt' },
  rejected: { label: 'Discarded', tone: 'neutral', icon: 'delete' },
  pending_review: { label: 'Needs review', tone: 'warn', icon: 'rule' },
  dismissed: { label: 'Dismissed', tone: 'neutral', icon: 'block' },
  stale: { label: 'Older than the reply used', tone: 'neutral', icon: 'history' },
  open: { label: 'Open', tone: 'warn', icon: 'report' },
  replacement_confirmed: { label: 'Replacement confirmed', tone: 'good', icon: 'autorenew' },
  credit_confirmed: { label: 'Credit confirmed', tone: 'good', icon: 'payments' },
  written_off: { label: 'Written off', tone: 'neutral', icon: 'delete' },
  ack_pending: { label: 'No answer yet', tone: 'warn', icon: 'hourglass_top' },
  ack_accepted: { label: 'Accepted', tone: 'good', icon: 'verified' },
  ack_partially_accepted: { label: 'Partly accepted', tone: 'info', icon: 'rule' },
  ack_counteroffer: { label: 'Proposed changes', tone: 'warn', icon: 'change_circle' },
  ack_rejected: { label: 'Cannot supply', tone: 'bad', icon: 'block' },
  out_of_stock: { label: 'Out of stock', tone: 'bad', icon: 'remove_shopping_cart' },
  at_risk: { label: 'Runs out soon', tone: 'warn', icon: 'warning' },
  ok: { label: 'In stock', tone: 'good', icon: 'check_circle' },
  no_sales_data: { label: 'No sales data', tone: 'neutral', icon: 'query_stats' },
  no_stock_data: { label: 'Not counted yet', tone: 'neutral', icon: 'help' },
};

export function StatusChip({ status }: { status: string }) {
  const s = STATUS[status] ?? { label: status.replace(/_/g, ' '), tone: 'neutral' as const, icon: 'info' };
  return (
    <span className={cn('inline-flex items-center gap-1 whitespace-nowrap rounded-full px-2.5 py-1 text-[12px] font-semibold', TONES[s.tone])}>
      <SymbolIcon icon={s.icon} className="text-[15px]" family="rounded" />{s.label}
    </span>
  );
}

export function Badge({ tone = 'neutral', children }: { tone?: keyof typeof TONES; children: ReactNode }) {
  return <span className={cn('inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[12px] font-semibold', TONES[tone])}>{children}</span>;
}

export function Button({ children, onClick, disabled, loading, variant = 'primary', type = 'button', title, size = 'md' }: {
  children: ReactNode; onClick?: () => void; disabled?: boolean; loading?: boolean;
  variant?: 'primary' | 'secondary' | 'danger' | 'ghost'; type?: 'button' | 'submit'; title?: string; size?: 'sm' | 'md' | 'lg';
}) {
  const styles = {
    primary: 'bg-[#E25C3F] text-white hover:bg-[#C94C31] disabled:bg-[#E25C3F]/50',
    secondary: 'border border-[#DCD2C8] bg-white text-[#16232B] hover:bg-[#F7F3EE] disabled:text-[#A3AFB6]',
    danger: 'border border-[#F0C5BC] bg-white text-[#B93A26] hover:bg-[#FBE5E1] disabled:text-[#D9A69B]',
    ghost: 'text-[#41525C] hover:bg-[#F1EEEA] disabled:text-[#A3AFB6]',
  };
  const sizes = { sm: 'min-h-[32px] px-3 text-[13px]', md: 'min-h-[40px] px-4 text-[14px]', lg: 'min-h-[48px] px-5 text-[15px]' };
  return (
    <button type={type} title={title} onClick={onClick} disabled={disabled || loading} aria-busy={loading || undefined}
      className={cn('inline-flex items-center justify-center gap-2 rounded-[10px] font-semibold transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-[#E25C3F]/50 disabled:cursor-not-allowed', styles[variant], sizes[size])}>
      {loading && <span className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-current border-t-transparent" aria-hidden="true" />}
      {children}
    </button>
  );
}

export function Field({ label, hint, children }: { label: ReactNode; hint?: ReactNode; children: ReactNode }) {
  return (
    <label className="flex flex-col gap-1.5 text-[13px] font-semibold text-[#2A3A43]">
      {label}{children}{hint && <span className="text-[12px] font-normal text-[#5E6E78]">{hint}</span>}
    </label>
  );
}

export const inputCls = 'min-h-[42px] rounded-[10px] border border-[#DCD2C8] bg-white px-3 text-[15px] font-normal text-[#16232B] outline-none placeholder:text-[#9AA6AD] focus:border-[#E25C3F] focus:ring-2 focus:ring-[#E25C3F]/20';

export function Loading({ label = 'Loading…' }: { label?: string }) {
  return (
    <div role="status" className="flex items-center gap-3 py-10 text-[14px] text-[#5E6E78]">
      <span className="h-4 w-4 animate-spin rounded-full border-2 border-[#E25C3F] border-t-transparent" aria-hidden="true" />{label}
    </div>
  );
}

export function Skeleton({ rows = 4 }: { rows?: number }) {
  return <div className="flex flex-col gap-2">{Array.from({ length: rows }, (_, i) => <div key={i} className="h-10 animate-pulse rounded-[10px] bg-[#F1EEEA]" />)}</div>;
}

export function EmptyState({ icon, title, body, children }: { icon: string; title: string; body?: ReactNode; children?: ReactNode }) {
  return (
    <div className="flex flex-col items-center gap-2 px-4 py-10 text-center">
      <span className="flex h-12 w-12 items-center justify-center rounded-full bg-[#F7F3EE]"><SymbolIcon icon={icon} className="text-[26px] text-[#8C7B6E]" family="rounded" /></span>
      <div className="text-[16px] font-semibold">{title}</div>
      {body && <p className="max-w-[480px] text-[14px] text-[#5E6E78]">{body}</p>}
      {children && <div className="mt-2 flex flex-wrap justify-center gap-2">{children}</div>}
    </div>
  );
}

export function ErrorBox({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  if (!error) return null;
  const e = error as ApiError;
  const details = e.details as Record<string, unknown> | undefined;
  const list = details && (['blockers', 'problems', 'pending', 'changed', 'errors'] as const).flatMap((k) => {
    const v = details[k];
    return Array.isArray(v) ? v.map((x: any) => (typeof x === 'string' ? x.replace(/_/g, ' ') : x?.sku ? `${x.sku}: was ${x.was}, now ${x.now}` : JSON.stringify(x))) : [];
  });
  return (
    <div role="alert" className="rounded-[12px] border border-[#F0C5BC] bg-[#FDF2EF] px-4 py-3 text-[14px] text-[#8E2B1B]">
      <div className="font-semibold">{e.message || 'Something went wrong'}</div>
      {list && list.length > 0 && <ul className="mt-1 list-disc pl-5 text-[13px]">{list.map((x, i) => <li key={i}>{x}</li>)}</ul>}
      {onRetry && <button className="mt-2 text-[13px] font-semibold underline" onClick={onRetry}>Try again</button>}
    </div>
  );
}

export function Notice({ tone = 'warn', children }: { tone?: 'warn' | 'info' | 'ok'; children: ReactNode }) {
  const tones = { warn: 'border-[#F1D9AE] bg-[#FDF6E9] text-[#6E4A0B]', info: 'border-[#CADBEE] bg-[#F1F6FC] text-[#24507F]', ok: 'border-[#BFE3CF] bg-[#EFF8F3] text-[#1A6646]' };
  return <div className={cn('rounded-[12px] border px-4 py-3 text-[14px] leading-relaxed', tones[tone])}>{children}</div>;
}

export function Stat({ label, value, sub, tone, to }: { label: string; value: ReactNode; sub?: ReactNode; tone?: 'bad' | 'warn' | 'good'; to?: string }) {
  const body = (
    <div className={cn('h-full rounded-[16px] border border-[#E8E0D8] bg-white px-5 py-4', to && 'transition-colors hover:border-[#D3C5B8]')}>
      <div className="text-[13px] font-medium text-[#5E6E78]">{label}</div>
      <div className={cn('mt-1 text-[28px] font-bold tracking-[-0.02em]', tone === 'bad' && 'text-[#B93A26]', tone === 'warn' && 'text-[#A86A12]', tone === 'good' && 'text-[#1E7F55]')}>{value}</div>
      {sub && <div className="mt-0.5 text-[12px] text-[#5E6E78]">{sub}</div>}
    </div>
  );
  return to ? <Link to={to}>{body}</Link> : body;
}

export function Tabs<T extends string>({ value, onChange, items }: { value: T; onChange: (v: T) => void; items: { value: T; label: ReactNode }[] }) {
  return (
    <div className="inline-flex rounded-[12px] bg-[#EFE9E2] p-1">
      {items.map((i) => (
        <button key={i.value} onClick={() => onChange(i.value)} className={cn('rounded-[9px] px-3 py-1.5 text-[13px] font-semibold',
          value === i.value ? 'bg-white text-[#16232B] shadow-sm' : 'text-[#5E6E78]')}>{i.label}</button>
      ))}
    </div>
  );
}

/** How fresh a number is, in words — stock is never shown as live when it is an estimate from an old count. */
export function Freshness({ at, stale, estimated, source, counted = true }: { at: string | null | undefined; stale?: boolean; estimated?: boolean; source?: string | null; counted?: boolean }) {
  if (!at) return <span className="text-[12px] text-[#5E6E78]">never counted</span>;
  if (!counted) return <span className="text-[12px] font-semibold text-[#A86A12]" title="The level comes from scans and adjustments only. Count it once to know what's really there.">not counted yet</span>;
  return (
    <span className={cn('text-[12px]', stale ? 'font-semibold text-[#A86A12]' : 'text-[#5E6E78]')} title={`${source ?? ''} ${when(at)}`}>
      {estimated ? 'estimated from count ' : 'counted '}{ago(at)}{stale ? ' · old' : ''}
    </span>
  );
}

export function ago(iso: string): string {
  const s = (Date.now() - new Date(iso).getTime()) / 1000;
  if (s < 90) return 'just now';
  if (s < 3600) return `${Math.round(s / 60)} min ago`;
  if (s < 86400) return `${Math.round(s / 3600)} h ago`;
  return `${Math.round(s / 86400)} days ago`;
}

export const num = (v: string | number | null | undefined) => (v == null || v === '' ? '—' : Number(v).toLocaleString('en-US', { maximumFractionDigits: 2 }));
export const money = (v: string | number | null | undefined, ccy?: string | null) =>
  v == null ? '—' : Number(v).toLocaleString('en-US', { style: 'currency', currency: ccy || 'USD', minimumFractionDigits: 2 });
export const when = (v: string | null | undefined) => (v ? new Date(v).toLocaleString([], { dateStyle: 'medium', timeStyle: 'short' }) : '—');
export const day = (v: string | null | undefined) => (v ? new Date(`${v.slice(0, 10)}T12:00:00`).toLocaleDateString([], { month: 'short', day: 'numeric' }) : '—');
/** An end-of-period timestamp (exclusive) as the last day it covers. */
export const through = (v: string | null | undefined) => (v ? new Date(new Date(v).getTime() - 1000).toLocaleDateString([], { month: 'short', day: 'numeric' }) : '—');
