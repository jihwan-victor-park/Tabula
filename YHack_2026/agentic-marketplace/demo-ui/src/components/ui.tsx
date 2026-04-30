import { NavLink } from 'react-router-dom';
import type { ReactNode } from 'react';

export type NavItem = {
  label: string;
  icon: string;
  href?: string;
  active?: boolean;
};

export type NavSection = {
  title: string;
  items: NavItem[];
};

type SidebarProps = {
  widthClass: string;
  sections: NavSection[];
  footerName: string;
  footerEmail: string;
};

export function cn(...parts: Array<string | false | null | undefined>) {
  return parts.filter(Boolean).join(' ');
}

export function SymbolIcon({
  icon,
  className,
  family = 'sharp',
}: {
  icon: string;
  className?: string;
  family?: 'sharp' | 'rounded';
}) {
  return (
    <span
      className={cn(
        'material-symbols inline-flex shrink-0 select-none items-center justify-center leading-none',
        family === 'sharp' ? 'material-symbols-sharp' : 'material-symbols-rounded',
        className,
      )}
      aria-hidden="true"
    >
      {icon}
    </span>
  );
}

export function TabulaLogo() {
  return (
    <div className="flex items-center gap-2">
      <svg className="h-7 w-7 shrink-0 text-[#E8654A]" viewBox="0 0 32 32" fill="currentColor" aria-hidden="true">
        <path d="M16 0c8.83656 0 16 7.16344 16 16 0 8.83656-7.16344 16-16 16-8.83656 0-16-7.16344-16-16 0-8.83656 7.16344-16 16-16zm1.86035 8.71777c-.66585-1.68829-3.05485-1.68829-3.7207 0l-1.21485 3.08008c-.20329.51544-.61151.92366-1.12695 1.12695l-3.08008 1.21485c-1.68829.66585-1.68829 3.05485 0 3.7207l3.08008 1.21485c.51544.20329.92366.61151 1.12695 1.12695l1.21485 3.08008c.66585 1.68829 3.05485 1.68829 3.7207 0l1.21485-3.08008c.20329-.51544.61151-.92366 1.12695-1.12695l3.08008-1.21485c1.68829-.66585 1.68829-3.05485 0-3.7207l-3.08008-1.21485c-.51544-.20329-.92366-.61151-1.12695-1.12695l-1.21485-3.08008z" />
      </svg>
      <span className="font-logo text-[17px] font-bold tracking-[0.02em] text-[#E8654A]">TABULA</span>
    </div>
  );
}

export function Sidebar({ widthClass, sections, footerName, footerEmail }: SidebarProps) {
  return (
    <aside
      className={cn(
        'flex h-full shrink-0 flex-col border-r border-[#2A5060] bg-[#1B3A4B]',
        widthClass,
      )}
    >
      <div className="flex h-[72px] items-center border-b border-[#2A5060] px-5">
        <TabulaLogo />
      </div>
      <div className="flex flex-1 flex-col gap-6 overflow-y-auto px-1 py-6">
        {sections.map((section) => (
          <div key={section.title} className="flex flex-col">
            <div className="px-5 py-3 font-mono text-[13px] uppercase leading-4 tracking-[0.06em] text-[#7A9EB0]">{section.title}</div>
            {section.items.map((item) => {
              const content = (
                <>
                  <SymbolIcon icon={item.icon} className={cn('text-[19px]', item.active ? 'text-[#E8654A]' : 'text-[#7A9EB0]')} />
                  <span className={cn('truncate text-[14px] leading-6', item.active ? 'font-medium text-white' : 'text-[#7A9EB0]')}>
                    {item.label}
                  </span>
                </>
              );

              if (item.href) {
                return (
                  <NavLink
                    key={item.label}
                    to={item.href}
                    className={({ isActive }) =>
                      cn(
                        'mx-2 flex items-center gap-4 rounded-[100px] px-5 py-3 transition-colors',
                        item.active || isActive ? 'bg-[#E8654A18]' : 'bg-transparent hover:bg-[#1F4455]',
                      )
                    }
                  >
                    {content}
                  </NavLink>
                );
              }

              return (
                <div key={item.label} className="mx-2 flex items-center gap-4 rounded-[100px] px-5 py-3">
                  {content}
                </div>
              );
            })}
          </div>
        ))}
      </div>
      <div className="shrink-0 border-t border-[#2A5060] px-3 py-4">
        <div className="mb-3 flex items-center gap-3 px-2">
          <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-[#2A5060] text-[12px] font-semibold text-white">
            {footerName.split(' ').map(w => w[0]).join('')}
          </div>
          <div className="flex min-w-0 flex-1 flex-col">
            <span className="truncate text-[13px] font-medium leading-5 text-white">{footerName}</span>
            <span className="truncate text-[11px] leading-4 text-[#7A9EB0]">{footerEmail}</span>
          </div>
        </div>
        <button
          type="button"
          className="flex w-full items-center gap-3 rounded-[100px] px-4 py-2.5 text-[13px] text-[#7A9EB0] transition-colors hover:bg-[#1F4455] hover:text-white"
        >
          <SymbolIcon icon="logout" className="text-[18px]" />
          Log out
        </button>
      </div>
    </aside>
  );
}

export function AppShell({
  sidebar,
  children,
}: {
  sidebar: ReactNode;
  children: ReactNode;
}) {
  return (
    <div className="min-h-screen bg-[#F5E0CF] text-[#1B3A4B]">
      <div className="mx-auto flex min-h-screen w-full max-w-[1440px] flex-col lg:h-screen lg:flex-row">
        <div className="lg:h-screen">{sidebar}</div>
        <main className="min-w-0 flex-1">{children}</main>
      </div>
    </div>
  );
}

export function CardPanel({
  children,
  className,
}: {
  children: ReactNode;
  className?: string;
}) {
  return <section className={cn('rounded-[16px] border border-[#E8D4C6] bg-white shadow-sm', className)}>{children}</section>;
}

export function StatCard({
  icon: _icon,
  iconColor: _iconColor,
  value,
  label,
  valueColor,
}: {
  icon: string;
  iconColor: string;
  value: string;
  label: string;
  valueColor?: string;
}) {
  void _icon;
  void _iconColor;

  return (
    <div className="flex min-w-0 flex-1 flex-col rounded-[12px] border border-[#E8D4C6] bg-white px-5 py-4 shadow-sm">
      <div className="text-[12px] font-medium leading-[1.4] text-[#5C7A8A]">{label}</div>
      <div className={cn('mt-1 text-[22px] font-bold leading-[1.2] text-[#1B3A4B]', valueColor)}>{value}</div>
    </div>
  );
}

export function Badge({
  label,
  tone,
  dot,
  mono = true,
}: {
  label: string;
  tone: 'blue' | 'green' | 'yellow' | 'red' | 'cream';
  dot?: boolean;
  mono?: boolean;
}) {
  const tones = {
    blue: 'bg-[#E8654A14] text-[#E8654A]',
    green: 'bg-[#2D8A6E14] text-[#2D8A6E]',
    yellow: 'bg-[#D4870E14] text-[#D4870E]',
    red: 'bg-[#D14D4D14] text-[#D14D4D]',
    cream: 'bg-[#FFF0E5] text-[#92400E]',
  };

  return (
    <span
      className={cn(
        'inline-flex items-center gap-1.5 rounded-[9999px] px-[10px] py-[4px] text-[11px] font-medium',
        mono ? 'font-mono' : 'font-sans',
        tones[tone],
      )}
    >
      {dot ? <span className="h-1.5 w-1.5 rounded-full bg-current" /> : null}
      {label}
    </span>
  );
}

export function ActionChip({
  icon,
  label,
  tone,
}: {
  icon: string;
  label: string;
  tone: 'green' | 'blue' | 'red';
}) {
  const tones = {
    green: 'bg-[#2D8A6E12] text-[#2D8A6E]',
    blue: 'bg-[#E8654A14] text-[#E8654A]',
    red: 'bg-[#D14D4D12] text-[#D14D4D]',
  };

  return (
    <span className={cn('inline-flex items-center gap-1 rounded-[6px] px-2 py-1 font-mono text-[10px] font-medium', tones[tone])}>
      <SymbolIcon icon={icon} className="text-[14px]" />
      {label}
    </span>
  );
}

export function HeaderButton({
  icon,
  label,
  active,
}: {
  icon: string;
  label: string;
  active?: boolean;
}) {
  return (
    <button
      type="button"
      className={cn(
        'inline-flex items-center gap-1.5 rounded-[999px] border px-4 py-2 text-[13px] font-medium transition-colors',
        active
          ? 'border-transparent bg-[#1B3A4B] text-white'
          : 'border-[#E8D4C6] bg-white text-[#5C7A8A] hover:bg-[#FDF5EF]',
      )}
    >
      <SymbolIcon icon={icon} className="text-[18px]" />
      {label}
    </button>
  );
}

export function SearchField({ placeholder, dark = true }: { placeholder: string; dark?: boolean }) {
  return (
    <div
      className={cn(
        'flex h-10 items-center gap-2 rounded-[8px] border px-2',
        dark ? 'border-[#E8D4C6] bg-white text-[#9AAFBC]' : 'border-transparent bg-transparent text-[#9AAFBC]',
      )}
    >
      <SymbolIcon icon="search" className="text-base" />
      <span className="text-[14px] leading-5">{placeholder}</span>
    </div>
  );
}
