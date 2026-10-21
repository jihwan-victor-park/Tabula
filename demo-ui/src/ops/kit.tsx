// Shared pieces for the operations screens: shell, status chips, buttons with
// loading/disabled states, and loading / empty / error panels.

import type { ReactNode } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { AppShell, Sidebar, SymbolIcon, cn } from '../components/ui';
import { ApiError, loadSession, saveSession } from './api';

export function OpsShell({ active, title, icon, actions, children }: {
  active: 'today' | 'imports' | 'orders' | 'setup';
  title: string; icon: string; actions?: ReactNode; children: ReactNode;
}) {
  const session = loadSession();
  const navigate = useNavigate();
  const item = (label: string, ic: string, href: string, key: typeof active) => ({ label, icon: ic, href, active: active === key });
  return (
    <AppShell
      sidebar={
        <Sidebar
          widthClass="w-full lg:w-[248px]"
          sections={[
            { title: 'Operations', items: [
              item('Today', 'today', '/ops/today', 'today'),
              item('Data imports', 'upload_file', '/ops/imports', 'imports'),
              item('Purchase orders', 'receipt_long', '/ops/orders', 'orders'),
              item('Workspace', 'storefront', '/ops/setup', 'setup'),
            ] },
            { title: 'Legacy demo', items: [{ label: 'Hackathon dashboard', icon: 'history', href: '/dashboard' }] },
          ]}
          footerName={session?.tenantName ?? 'Not signed in'}
          footerEmail={session?.user ?? 'local dev sign-in'}
        />
      }
    >
      <div className="flex min-h-full flex-col">
        <header className="flex min-h-[72px] flex-wrap items-center justify-between gap-3 border-b border-[#E8D4C6] px-6 py-3">
          <div className="flex items-center gap-3">
            <SymbolIcon icon={icon} className="text-[26px] text-[#E8654A]" />
            <h1 className="text-[20px] font-semibold">{title}</h1>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            {actions}
            {session && (
              <button className="text-[12px] text-[#5C7A8A] underline" onClick={() => { saveSession(null); navigate('/ops/setup'); }}>
                Switch workspace
              </button>
            )}
          </div>
        </header>
        <div className="mx-auto flex w-full max-w-[1180px] flex-1 flex-col gap-5 p-4 md:p-6">{children}</div>
      </div>
    </AppShell>
  );
}

export function RequireSession({ children }: { children: ReactNode }) {
  if (!loadSession()?.tenantId) {
    return (
      <Panel>
        <EmptyState icon="login" title="Choose a workspace first" body="Sign in locally and pick or create a store workspace.">
          <Link className="text-[#E8654A] underline" to="/ops/setup">Go to Workspace</Link>
        </EmptyState>
      </Panel>
    );
  }
  return <>{children}</>;
}

export function Panel({ children, className, title, aside }: { children: ReactNode; className?: string; title?: string; aside?: ReactNode }) {
  return (
    <section className={cn('rounded-[16px] border border-[#E8D4C6] bg-white p-5 shadow-sm', className)}>
      {(title || aside) && (
        <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
          {title && <h2 className="text-[15px] font-semibold">{title}</h2>}
          {aside}
        </div>
      )}
      {children}
    </section>
  );
}

const STATUS: Record<string, { label: string; tone: string; icon: string }> = {
  draft: { label: 'Draft', tone: 'bg-[#FDF5EF] text-[#1B3A4B] border-[#E8D4C6]', icon: 'edit_note' },
  awaiting_approval: { label: 'Awaiting approval', tone: 'bg-[#FEF3C7] text-[#8A5A00] border-[#F5D58A]', icon: 'hourglass_top' },
  queued: { label: 'Queued', tone: 'bg-[#E0ECFF] text-[#1D4ED8] border-[#B8CFFB]', icon: 'schedule_send' },
  test_sent: { label: 'Test sent (captured)', tone: 'bg-[#D1FAE5] text-[#065F46] border-[#9BE3C3]', icon: 'mark_email_read' },
  failed: { label: 'Failed', tone: 'bg-[#FEE2E2] text-[#991B1B] border-[#F7B4B4]', icon: 'error' },
  cancelled: { label: 'Cancelled', tone: 'bg-[#F1F1F1] text-[#555] border-[#DDD]', icon: 'block' },
  order: { label: 'Order', tone: 'bg-[#E8654A14] text-[#B4462F] border-[#F2B6A7]', icon: 'add_shopping_cart' },
  on_hold: { label: 'On hold', tone: 'bg-[#FEF3C7] text-[#8A5A00] border-[#F5D58A]', icon: 'pause_circle' },
  no_order: { label: 'Enough stock', tone: 'bg-[#D1FAE5] text-[#065F46] border-[#9BE3C3]', icon: 'check_circle' },
  no_supplier: { label: 'No supplier', tone: 'bg-[#FEE2E2] text-[#991B1B] border-[#F7B4B4]', icon: 'link_off' },
  insufficient_data: { label: 'Not enough data', tone: 'bg-[#F1F1F1] text-[#555] border-[#DDD]', icon: 'help' },
  excluded: { label: 'Excluded', tone: 'bg-[#F1F1F1] text-[#555] border-[#DDD]', icon: 'do_not_disturb_on' },
  uploaded: { label: 'Needs review', tone: 'bg-[#FEF3C7] text-[#8A5A00] border-[#F5D58A]', icon: 'rule' },
  confirmed: { label: 'Applying…', tone: 'bg-[#E0ECFF] text-[#1D4ED8] border-[#B8CFFB]', icon: 'sync' },
  applying: { label: 'Applying…', tone: 'bg-[#E0ECFF] text-[#1D4ED8] border-[#B8CFFB]', icon: 'sync' },
  applied: { label: 'Applied', tone: 'bg-[#D1FAE5] text-[#065F46] border-[#9BE3C3]', icon: 'task_alt' },
  rejected: { label: 'Discarded', tone: 'bg-[#F1F1F1] text-[#555] border-[#DDD]', icon: 'delete' },
};

export function StatusChip({ status }: { status: string }) {
  const s = STATUS[status] ?? { label: status, tone: 'bg-[#F1F1F1] text-[#555] border-[#DDD]', icon: 'info' };
  return (
    <span className={cn('inline-flex items-center gap-1 whitespace-nowrap rounded-full border px-2.5 py-0.5 text-[12px] font-medium', s.tone)}>
      <SymbolIcon icon={s.icon} className="text-[15px]" family="rounded" />
      {s.label}
    </span>
  );
}

export function Button({ children, onClick, disabled, loading, variant = 'primary', type = 'button', title }: {
  children: ReactNode; onClick?: () => void; disabled?: boolean; loading?: boolean;
  variant?: 'primary' | 'secondary' | 'danger'; type?: 'button' | 'submit'; title?: string;
}) {
  const styles = {
    primary: 'bg-[#E8654A] text-white hover:bg-[#D5563C] disabled:bg-[#E8654A80]',
    secondary: 'border border-[#E8D4C6] bg-white text-[#1B3A4B] hover:bg-[#FDF5EF] disabled:text-[#9AB0BC]',
    danger: 'border border-[#F7B4B4] bg-white text-[#991B1B] hover:bg-[#FEE2E2] disabled:text-[#C99]',
  };
  return (
    <button
      type={type}
      title={title}
      onClick={onClick}
      disabled={disabled || loading}
      aria-busy={loading || undefined}
      className={cn('inline-flex min-h-[38px] items-center justify-center gap-2 rounded-full px-4 text-[14px] font-medium transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-[#E8654A] disabled:cursor-not-allowed', styles[variant])}
    >
      {loading && <span className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-current border-t-transparent" aria-hidden="true" />}
      {children}
    </button>
  );
}

export function Loading({ label = 'Loading…' }: { label?: string }) {
  return (
    <div role="status" className="flex items-center gap-3 py-8 text-[14px] text-[#5C7A8A]">
      <span className="h-4 w-4 animate-spin rounded-full border-2 border-[#E8654A] border-t-transparent" aria-hidden="true" />
      {label}
    </div>
  );
}

export function EmptyState({ icon, title, body, children }: { icon: string; title: string; body?: string; children?: ReactNode }) {
  return (
    <div className="flex flex-col items-center gap-2 py-10 text-center">
      <SymbolIcon icon={icon} className="text-[36px] text-[#C9A893]" family="rounded" />
      <div className="text-[15px] font-semibold">{title}</div>
      {body && <p className="max-w-[460px] text-[13px] text-[#5C7A8A]">{body}</p>}
      {children}
    </div>
  );
}

export function ErrorBox({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  if (!error) return null;
  const e = error as ApiError;
  const details = e.details as Record<string, unknown> | undefined;
  const list = details && (['blockers', 'problems', 'pending', 'changed', 'errors'] as const).flatMap((k) => {
    const v = details[k];
    return Array.isArray(v) ? v.map((x) => (typeof x === 'string' ? x : JSON.stringify(x))) : [];
  });
  return (
    <div role="alert" className="rounded-[12px] border border-[#F7B4B4] bg-[#FEE2E2] px-4 py-3 text-[13px] text-[#7F1D1D]">
      <div className="font-semibold">{e.status ? `${e.status} — ` : ''}{e.message || 'Something went wrong'}</div>
      {list && list.length > 0 && <ul className="mt-1 list-disc pl-5">{list.map((x, i) => <li key={i}>{x}</li>)}</ul>}
      {onRetry && <button className="mt-2 underline" onClick={onRetry}>Try again</button>}
    </div>
  );
}

export function Notice({ tone = 'warn', children }: { tone?: 'warn' | 'info' | 'ok'; children: ReactNode }) {
  const tones = { warn: 'border-[#F5D58A] bg-[#FFF8E1] text-[#6B4A00]', info: 'border-[#B8CFFB] bg-[#EEF4FF] text-[#1E3A8A]', ok: 'border-[#9BE3C3] bg-[#ECFDF5] text-[#065F46]' };
  return <div className={cn('rounded-[12px] border px-4 py-3 text-[13px]', tones[tone])}>{children}</div>;
}

export const num = (v: string | null | undefined) => (v == null || v === '' ? '—' : Number(v).toLocaleString('en-US', { maximumFractionDigits: 4 }));
export const money = (v: string | null | undefined, ccy?: string | null) =>
  v == null ? '—' : `${Number(v).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}${ccy ? ` ${ccy}` : ''}`;
export const when = (v: string | null | undefined) => (v ? new Date(v).toLocaleString() : '—');
