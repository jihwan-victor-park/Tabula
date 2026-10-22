// Tabula design system + app shell. A calm work tool: neutral background, white work areas,
// dark text, one blue accent. Colour carries meaning only (out of stock, runs out soon, problems).
// Four places to work — Overview, Inventory, Orders, Insights — and Settings for data and the store.

import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useEffect, type ReactNode } from 'react';
import { Link, NavLink, useLocation, useNavigate } from 'react-router-dom';
import { SymbolIcon, cn } from '../components/ui';
import { ApiError, api, loadSession, saveSession, type Me } from './api';

export const C = {
  ink: '#14181D', ink2: '#3B444D', muted: '#66707A', faint: '#9AA3AC', line: '#E2E5E9', divider: '#EDEFF2', bg: '#F4F5F7',
  accent: '#2457C5', accentSoft: '#EAF0FB', good: '#1F7A4D', warn: '#A15C07', bad: '#B42318',
};

type NavKey = 'overview' | 'inventory' | 'orders' | 'insights' | 'settings';
// Older screen names map onto the four places they now live in.
const ALIAS: Record<string, NavKey> = {
  home: 'overview', today: 'orders', scan: 'inventory', suppliers: 'orders', receiving: 'orders',
  data: 'settings', imports: 'settings', connections: 'settings', setup: 'settings',
};
const NAV: { key: NavKey; label: string; icon: string; to: string }[] = [
  { key: 'overview', label: 'Overview', icon: 'space_dashboard', to: '/app' },
  { key: 'inventory', label: 'Inventory', icon: 'inventory_2', to: '/app/inventory' },
  { key: 'orders', label: 'Orders', icon: 'local_shipping', to: '/app/orders' },
  { key: 'insights', label: 'Insights', icon: 'monitoring', to: '/app/insights' },
];

export function useMe() {
  return useQuery({ queryKey: ['me'], queryFn: () => api<Me>('/me', { noTenant: true }), retry: false, staleTime: 30_000 });
}

export function OpsShell({ active, title, subtitle, actions, children, tabs }: {
  active: string; title: ReactNode; subtitle?: ReactNode; icon?: string; actions?: ReactNode; children: ReactNode; tabs?: ReactNode;
}) {
  const key = (ALIAS[active] ?? active) as NavKey;
  const session = loadSession();
  const me = useMe();
  const navigate = useNavigate();
  const qc = useQueryClient();
  useEffect(() => { document.title = `${typeof title === 'string' ? title : 'Tabula'} · Tabula`; }, [title]);
  const signOut = async () => {
    try { await api('/auth/logout', { method: 'POST', noTenant: true }); } catch { /* already signed out */ }
    saveSession(null); qc.clear(); navigate('/signin');
  };
  return (
    <div className="min-h-screen bg-[#F4F5F7] font-[Inter,system-ui,sans-serif] text-[14px] text-[#14181D] antialiased [font-feature-settings:'tnum','cv11']">
      <aside className="fixed inset-y-0 left-0 z-30 hidden w-[216px] flex-col border-r border-[#E2E5E9] bg-white lg:flex">
        <Link to="/app" className="px-4 pb-3 pt-4"><Logo /></Link>
        <StoreSwitcher />
        <nav className="mt-2 flex flex-col gap-px px-2">
          {NAV.map((n) => <NavItem key={n.key} n={n} active={key === n.key} />)}
        </nav>
        <div className="mt-auto flex flex-col gap-px px-2 pb-2">
          <NavItem n={{ label: 'Settings', icon: 'settings', to: '/app/settings' }} active={key === 'settings'} />
        </div>
        <div className="border-t border-[#EDEFF2] px-4 py-3 text-[12px] text-[#66707A]">
          <TestModeTag />
          <div className="mt-2 truncate">{me.data?.email ?? session?.user ?? ''}</div>
          <button className="mt-0.5 hover:text-[#14181D] hover:underline" onClick={signOut}>Sign out</button>
        </div>
      </aside>

      <header className="sticky top-0 z-20 flex items-center justify-between gap-3 border-b border-[#E2E5E9] bg-white px-4 py-2.5 lg:hidden">
        <Link to="/app"><Logo compact /></Link>
        <Link to="/app/stores" className="min-w-0 flex-1 truncate text-center text-[13px] font-semibold">{session?.tenantName ?? 'Choose store'}</Link>
        <Link to="/app/settings" aria-label="Settings" className={cn('flex h-9 w-9 items-center justify-center rounded-[6px]', key === 'settings' ? 'bg-[#EAF0FB] text-[#2457C5]' : 'text-[#3B444D]')}>
          <SymbolIcon icon="settings" family="rounded" className="text-[22px]" /></Link>
      </header>

      <main className="pb-24 lg:pb-12 lg:pl-[216px]">
        {session?.isSample && (
          <p className="border-b border-[#E2E5E9] bg-[#F8F9FA] px-4 py-1.5 text-center text-[12px] text-[#3B444D]">
            <b>Sample store</b> — fictional products, suppliers and sales. <Link to="/app/stores" className="font-medium text-[#2457C5] hover:underline">Switch store</Link>
          </p>
        )}
        <div className="mx-auto w-full max-w-[1240px] px-4 pt-5 md:px-8 md:pt-7">
          <div className="mb-5 flex flex-wrap items-start justify-between gap-x-4 gap-y-3">
            <div className="min-w-0">
              <h1 className="text-[22px] font-semibold leading-tight tracking-[-0.01em]">{title}</h1>
              {subtitle && <div className="mt-1 text-[13px] text-[#66707A]">{subtitle}</div>}
            </div>
            {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
          </div>
          {tabs && <div className="mb-5">{tabs}</div>}
          <div className="flex flex-col gap-5">{children}</div>
        </div>
      </main>

      <nav className="fixed inset-x-0 bottom-0 z-30 grid grid-cols-4 border-t border-[#E2E5E9] bg-white pb-[env(safe-area-inset-bottom)] lg:hidden">
        {NAV.map((n) => (
          <NavLink key={n.key} to={n.to} end={n.to === '/app'} className={cn('flex flex-col items-center gap-0.5 py-2 text-[11px] font-medium',
            key === n.key ? 'text-[#2457C5]' : 'text-[#66707A]')}>
            <SymbolIcon icon={n.icon} family="rounded" className="text-[22px]" />{n.label}
          </NavLink>
        ))}
      </nav>
    </div>
  );
}

function NavItem({ n, active }: { n: { label: string; icon: string; to: string }; active: boolean }) {
  return (
    <NavLink to={n.to} end={n.to === '/app'}
      className={cn('flex items-center gap-2.5 rounded-[6px] px-2.5 py-[7px] text-[14px] font-medium',
        active ? 'bg-[#EAF0FB] text-[#1F4FB3]' : 'text-[#3B444D] hover:bg-[#F4F5F7]')}>
      <SymbolIcon icon={n.icon} family="rounded" className="text-[19px]" />{n.label}
    </NavLink>
  );
}

/** The one place test mode is always visible; order screens say it again only where it changes a decision. */
export function TestModeTag() {
  return (
    <span className="inline-flex items-center gap-1.5 rounded-[4px] border border-[#E2E5E9] px-1.5 py-0.5 text-[11px] font-semibold text-[#3B444D]"
      title="Approved orders are kept in Tabula and not emailed to suppliers. No payments are made.">
      <span className="h-1.5 w-1.5 rounded-full bg-[#A15C07]" />Test mode — not emailed
    </span>
  );
}

export function Logo({ light = false, compact = false }: { light?: boolean; compact?: boolean }) {
  return (
    <span className="flex items-center gap-2">
      <span className="flex h-7 w-7 items-center justify-center rounded-[6px] bg-[#14181D] text-[14px] font-bold text-white">T</span>
      {!compact && <span className={cn('text-[16px] font-semibold tracking-[-0.01em]', light ? 'text-white' : 'text-[#14181D]')}>Tabula</span>}
    </span>
  );
}

function StoreSwitcher() {
  const session = loadSession();
  return (
    <Link to="/app/stores" className="mx-2 flex items-center justify-between gap-2 rounded-[6px] px-2.5 py-2 hover:bg-[#F4F5F7]">
      <span className="min-w-0">
        <span className="block truncate text-[13px] font-semibold">{session?.tenantName ?? 'Choose a store'}</span>
        <span className="block text-[11px] text-[#66707A]">{session?.isSample ? 'Sample store' : 'Switch store'}</span>
      </span>
      <SymbolIcon icon="unfold_more" family="rounded" className="text-[18px] text-[#9AA3AC]" />
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

/** A white work area. Title row is part of the panel; content decides its own padding when `padded` is false. */
export function Panel({ children, className, title, aside, padded = true, sub, id }: {
  children: ReactNode; className?: string; title?: ReactNode; aside?: ReactNode; padded?: boolean; sub?: ReactNode; id?: string;
}) {
  return (
    <section id={id} className={cn('scroll-mt-4 rounded-[8px] border border-[#E2E5E9] bg-white', className)}>
      {(title || aside) && (
        <div className={cn('flex flex-wrap items-center justify-between gap-2 px-4 pt-3.5 md:px-5', padded ? 'pb-0' : 'pb-3')}>
          <div className="min-w-0">
            {title && <h2 className="text-[15px] font-semibold">{title}</h2>}
            {sub && <div className="text-[12px] text-[#66707A]">{sub}</div>}
          </div>
          {aside}
        </div>
      )}
      <div className={cn(padded && 'p-4 md:px-5')}>{children}</div>
    </section>
  );
}

// Tones: colour only where the state means something to act on.
const TONES = {
  neutral: 'text-[#3B444D]', good: 'text-[#1F7A4D]', warn: 'text-[#A15C07]', bad: 'text-[#B42318]', info: 'text-[#1F4FB3]', brand: 'text-[#1F4FB3]',
};
const DOT = { neutral: 'bg-[#9AA3AC]', good: 'bg-[#1F7A4D]', warn: 'bg-[#D08A1E]', bad: 'bg-[#B42318]', info: 'bg-[#2457C5]', brand: 'bg-[#2457C5]' };
const FILL = {
  neutral: 'bg-[#F0F2F4] text-[#3B444D]', good: 'bg-[#E8F5EE] text-[#1F7A4D]', warn: 'bg-[#FEF4E2] text-[#8A4E05]',
  bad: 'bg-[#FDECEA] text-[#B42318]', info: 'bg-[#EAF0FB] text-[#1F4FB3]', brand: 'bg-[#EAF0FB] text-[#1F4FB3]',
};
type Tone = keyof typeof TONES;
const STATUS: Record<string, { label: string; tone: Tone }> = {
  draft: { label: 'Draft', tone: 'neutral' },
  awaiting_approval: { label: 'Waiting for approval', tone: 'warn' },
  queued: { label: 'Sending…', tone: 'info' },
  test_sent: { label: 'Sent (test mode)', tone: 'info' },
  delivery_unknown: { label: 'Not sure the supplier got it', tone: 'bad' },
  failed: { label: 'Not sent', tone: 'bad' },
  cancelled: { label: 'Cancelled', tone: 'neutral' },
  supplier_confirmed: { label: 'Confirmed by supplier', tone: 'good' },
  changes_proposed: { label: 'Supplier proposed changes', tone: 'warn' },
  partially_received: { label: 'Partly received', tone: 'info' },
  received: { label: 'Received — issues open', tone: 'warn' },
  closed: { label: 'Complete', tone: 'neutral' },
  order: { label: 'Order', tone: 'brand' },
  on_hold: { label: 'On hold — already ordered', tone: 'warn' },
  covered: { label: 'Covered by incoming order', tone: 'info' },
  no_order: { label: 'Enough stock', tone: 'good' },
  no_supplier: { label: 'No supplier', tone: 'bad' },
  insufficient_data: { label: 'Not enough data', tone: 'neutral' },
  excluded: { label: 'Not tracked', tone: 'neutral' },
  uploaded: { label: 'Needs review', tone: 'warn' },
  confirmed: { label: 'Importing…', tone: 'info' },
  applying: { label: 'Importing…', tone: 'info' },
  applied: { label: 'Imported', tone: 'good' },
  rejected: { label: 'Discarded', tone: 'neutral' },
  pending_review: { label: 'Needs review', tone: 'warn' },
  dismissed: { label: 'Dismissed', tone: 'neutral' },
  stale: { label: 'Older than the reply used', tone: 'neutral' },
  open: { label: 'Open', tone: 'warn' },
  replacement_confirmed: { label: 'Replacement confirmed', tone: 'good' },
  credit_confirmed: { label: 'Credit confirmed', tone: 'good' },
  written_off: { label: 'Written off', tone: 'neutral' },
  ack_pending: { label: 'No answer yet', tone: 'warn' },
  ack_accepted: { label: 'Accepted', tone: 'good' },
  ack_partially_accepted: { label: 'Partly accepted', tone: 'info' },
  ack_counteroffer: { label: 'Proposed changes', tone: 'warn' },
  ack_rejected: { label: 'Cannot supply', tone: 'bad' },
  out_of_stock: { label: 'Out of stock', tone: 'bad' },
  at_risk: { label: 'Runs out soon', tone: 'warn' },
  ok: { label: 'In stock', tone: 'neutral' },
  no_sales_data: { label: 'No sales data', tone: 'neutral' },
  no_stock_data: { label: 'Not counted yet', tone: 'neutral' },
};

/** A state in words with a small dot; the word is coloured only for good/warn/bad. */
export function StatusChip({ status, label }: { status: string; label?: string }) {
  const s = STATUS[status] ?? { label: status.replace(/_/g, ' '), tone: 'neutral' as const };
  return (
    <span className={cn('inline-flex items-center gap-1.5 whitespace-nowrap text-[13px] font-medium', TONES[s.tone])}>
      <span className={cn('h-1.5 w-1.5 shrink-0 rounded-full', DOT[s.tone])} />{label ?? s.label}
    </span>
  );
}

export function Badge({ tone = 'neutral', children }: { tone?: Tone; children: ReactNode }) {
  return <span className={cn('inline-flex items-center gap-1 whitespace-nowrap rounded-[4px] px-1.5 py-px text-[12px] font-semibold', FILL[tone])}>{children}</span>;
}

export function Button({ children, onClick, disabled, loading, variant = 'primary', type = 'button', title, size = 'md' }: {
  children: ReactNode; onClick?: () => void; disabled?: boolean; loading?: boolean;
  variant?: 'primary' | 'secondary' | 'danger' | 'ghost'; type?: 'button' | 'submit'; title?: string; size?: 'sm' | 'md' | 'lg';
}) {
  const styles = {
    primary: 'bg-[#2457C5] text-white hover:bg-[#1D47A3] disabled:bg-[#2457C5]/45',
    secondary: 'border border-[#D5DAE0] bg-white text-[#14181D] hover:bg-[#F4F5F7] disabled:text-[#9AA3AC]',
    danger: 'border border-[#F1C4BE] bg-white text-[#B42318] hover:bg-[#FDECEA] disabled:text-[#D9A69B]',
    ghost: 'text-[#3B444D] hover:bg-[#F0F2F4] disabled:text-[#9AA3AC]',
  };
  const sizes = { sm: 'min-h-[30px] px-2.5 text-[13px]', md: 'min-h-[36px] px-3.5 text-[14px]', lg: 'min-h-[42px] px-4 text-[14px]' };
  return (
    <button type={type} title={title} onClick={onClick} disabled={disabled || loading} aria-busy={loading || undefined}
      className={cn('inline-flex items-center justify-center gap-1.5 whitespace-nowrap rounded-[6px] font-semibold transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-[#2457C5]/40 disabled:cursor-not-allowed', styles[variant], sizes[size])}>
      {loading && <span className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-current border-t-transparent" aria-hidden="true" />}
      {children}
    </button>
  );
}

/** A link styled as a button (navigation, not an action). */
export function ButtonLink({ to, children, variant = 'primary', size = 'md' }: { to: string; children: ReactNode; variant?: 'primary' | 'secondary' | 'ghost'; size?: 'sm' | 'md' | 'lg' }) {
  const styles = { primary: 'bg-[#2457C5] text-white hover:bg-[#1D47A3]', secondary: 'border border-[#D5DAE0] bg-white text-[#14181D] hover:bg-[#F4F5F7]', ghost: 'text-[#3B444D] hover:bg-[#F0F2F4]' };
  const sizes = { sm: 'min-h-[30px] px-2.5 text-[13px]', md: 'min-h-[36px] px-3.5 text-[14px]', lg: 'min-h-[42px] px-4 text-[14px]' };
  const cls = cn('inline-flex items-center justify-center gap-1.5 whitespace-nowrap rounded-[6px] font-semibold', styles[variant], sizes[size]);
  // In-page anchors (#section) scroll; everything else is a route.
  return to.startsWith('#') ? <a href={to} className={cls}>{children}</a> : <Link to={to} className={cls}>{children}</Link>;
}

export function Field({ label, hint, children }: { label: ReactNode; hint?: ReactNode; children: ReactNode }) {
  return (
    <label className="flex flex-col gap-1 text-[13px] font-medium text-[#3B444D]">
      {label}{children}{hint && <span className="text-[12px] font-normal text-[#66707A]">{hint}</span>}
    </label>
  );
}

export const inputCls = 'min-h-[36px] rounded-[6px] border border-[#D5DAE0] bg-white px-2.5 text-[14px] font-normal text-[#14181D] outline-none placeholder:text-[#9AA3AC] focus:border-[#2457C5] focus:ring-2 focus:ring-[#2457C5]/15';

export function Loading({ label = 'Loading…' }: { label?: string }) {
  return (
    <div role="status" className="flex items-center gap-3 py-8 text-[14px] text-[#66707A]">
      <span className="h-4 w-4 animate-spin rounded-full border-2 border-[#2457C5] border-t-transparent" aria-hidden="true" />{label}
    </div>
  );
}

export function Skeleton({ rows = 4 }: { rows?: number }) {
  return <div className="flex flex-col gap-2">{Array.from({ length: rows }, (_, i) => <div key={i} className="h-9 animate-pulse rounded-[6px] bg-[#F0F2F4]" />)}</div>;
}

export function EmptyState({ icon, title, body, children, compact = false }: { icon: string; title: string; body?: ReactNode; children?: ReactNode; compact?: boolean }) {
  return (
    <div className={cn('flex flex-col items-center gap-1.5 px-4 text-center', compact ? 'py-6' : 'py-10')}>
      <SymbolIcon icon={icon} className="text-[26px] text-[#9AA3AC]" family="rounded" />
      <div className="text-[15px] font-semibold">{title}</div>
      {body && <p className="max-w-[460px] text-[13px] text-[#66707A]">{body}</p>}
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
    <div role="alert" className="rounded-[6px] border border-[#F1C4BE] bg-[#FDF3F2] px-3.5 py-2.5 text-[13px] text-[#912018]">
      <div className="font-semibold">{e.message || 'Something went wrong'}</div>
      {list && list.length > 0 && <ul className="mt-1 list-disc pl-5">{list.map((x, i) => <li key={i}>{x}</li>)}</ul>}
      {onRetry && <button className="mt-1 font-semibold underline" onClick={onRetry}>Try again</button>}
    </div>
  );
}

/** A one-line note in the flow of the page. Amber = needs attention; blue = good to know; green = done. */
export function Notice({ tone = 'warn', children }: { tone?: 'warn' | 'info' | 'ok'; children: ReactNode }) {
  const tones = { warn: 'border-l-[#D08A1E] bg-[#FEF8EC] text-[#5C3A06]', info: 'border-l-[#2457C5] bg-[#F3F6FC] text-[#1B3566]', ok: 'border-l-[#1F7A4D] bg-[#F0F8F3] text-[#164E33]' };
  return <div className={cn('rounded-[6px] border-l-[3px] px-3.5 py-2.5 text-[13px] leading-relaxed', tones[tone])}>{children}</div>;
}

/** One number in a summary strip. Kept small: the lists below carry the work. */
export function Stat({ label, value, sub, tone, to }: { label: string; value: ReactNode; sub?: ReactNode; tone?: 'bad' | 'warn' | 'good'; to?: string }) {
  const body = (
    <div className={cn('h-full px-4 py-3', to && 'hover:bg-[#F8F9FA]')}>
      <div className="text-[12px] font-medium text-[#66707A]">{label}</div>
      <div className={cn('mt-0.5 text-[22px] font-semibold tabular-nums leading-tight', tone === 'bad' && 'text-[#B42318]', tone === 'warn' && 'text-[#A15C07]', tone === 'good' && 'text-[#1F7A4D]')}>{value}</div>
      {sub && <div className="mt-0.5 hidden text-[12px] text-[#66707A] sm:block">{sub}</div>}
    </div>
  );
  return to ? <Link to={to} className="block h-full">{body}</Link> : body;
}

/** Several Stats in one bordered strip, separated by hairlines. */
export function StatStrip({ children, cols = 3 }: { children: ReactNode; cols?: 2 | 3 | 4 }) {
  const grid = { 2: 'grid-cols-2', 3: 'grid-cols-3', 4: 'grid-cols-2 md:grid-cols-4' }[cols];
  return <div className={cn('grid divide-x divide-[#EDEFF2] overflow-hidden rounded-[8px] border border-[#E2E5E9] bg-white', grid)}>{children}</div>;
}

/** A small segmented control for options within a panel. */
export function Tabs<T extends string>({ value, onChange, items }: { value: T; onChange: (v: T) => void; items: { value: T; label: ReactNode }[] }) {
  return (
    <div className="inline-flex rounded-[6px] border border-[#D5DAE0] bg-white p-0.5">
      {items.map((i) => (
        <button key={i.value} onClick={() => onChange(i.value)} className={cn('rounded-[4px] px-2.5 py-1 text-[13px] font-medium',
          value === i.value ? 'bg-[#14181D] text-white' : 'text-[#3B444D] hover:bg-[#F4F5F7]')}>{i.label}</button>
      ))}
    </div>
  );
}

/** Page-level sections (Orders, Settings): underlined links, with an optional count. */
export function PageTabs({ items, active }: { items: { key: string; label: string; to: string; count?: number }[]; active: string }) {
  return (
    <nav className="-mx-4 flex gap-5 overflow-x-auto border-b border-[#E2E5E9] px-4 md:mx-0 md:px-0">
      {items.map((t) => (
        <Link key={t.key} to={t.to} className={cn('-mb-px flex items-center gap-1.5 whitespace-nowrap border-b-2 pb-2.5 text-[14px] font-medium',
          active === t.key ? 'border-[#2457C5] text-[#14181D]' : 'border-transparent text-[#66707A] hover:text-[#14181D]')}>
          {t.label}{t.count != null && t.count > 0 && <span className={cn('rounded-[4px] px-1.5 text-[12px] font-semibold', active === t.key ? 'bg-[#EAF0FB] text-[#1F4FB3]' : 'bg-[#F0F2F4] text-[#3B444D]')}>{t.count}</span>}
        </Link>
      ))}
    </nav>
  );
}

/** Supporting detail (calculation, original text, audit) — closed until asked for. */
export function Disclosure({ title, sub, children, defaultOpen = false }: { title: ReactNode; sub?: ReactNode; children: ReactNode; defaultOpen?: boolean }) {
  return (
    <details open={defaultOpen} className="group rounded-[8px] border border-[#E2E5E9] bg-white">
      <summary className="flex cursor-pointer list-none items-center justify-between gap-3 px-4 py-3 md:px-5 [&::-webkit-details-marker]:hidden">
        <span><span className="text-[14px] font-semibold">{title}</span>{sub && <span className="ml-2 text-[12px] text-[#66707A]">{sub}</span>}</span>
        <SymbolIcon icon="expand_more" family="rounded" className="text-[20px] text-[#66707A] transition-transform group-open:rotate-180" />
      </summary>
      <div className="border-t border-[#EDEFF2] px-4 py-3 md:px-5">{children}</div>
    </details>
  );
}

/** Table header cell / numeric cell helpers so every table lines up the same way. */
export const th = 'px-3 py-2 text-left text-[12px] font-medium text-[#66707A] first:pl-4 last:pr-4 md:first:pl-5 md:last:pr-5';
export const thNum = `${th} text-right`;
export const td = 'px-3 py-2.5 align-middle first:pl-4 last:pr-4 md:first:pl-5 md:last:pr-5';
export const tdNum = `${td} text-right tabular-nums`;

/** How fresh a number is, in words — stock is never shown as live when it is an estimate from an old count. */
export function Freshness({ at, stale, estimated, source, counted = true }: { at: string | null | undefined; stale?: boolean; estimated?: boolean; source?: string | null; counted?: boolean }) {
  if (!at) return <span className="text-[12px] text-[#66707A]">never counted</span>;
  if (!counted) return <span className="text-[12px] font-medium text-[#A15C07]" title="The level comes from scans and adjustments only. Count it once to know what's really there.">not counted yet</span>;
  return (
    <span className={cn('text-[12px]', stale ? 'font-medium text-[#A15C07]' : 'text-[#66707A]')} title={`${source ?? ''} ${when(at)}`}>
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
/** Days from today (store's local date) to an ISO date: 0 = today. */
export const daysUntil = (v: string | null | undefined) => {
  if (!v) return null;
  const t = new Date(); t.setHours(12, 0, 0, 0);
  return Math.round((new Date(`${v.slice(0, 10)}T12:00:00`).getTime() - t.getTime()) / 86400000);
};
