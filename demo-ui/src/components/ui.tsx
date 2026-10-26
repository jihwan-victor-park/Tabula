import { NavLink, useLocation } from 'react-router-dom';
import type { ReactNode } from 'react';
import { SettingsMenu, useAppTheme } from '../app/theme';
import '../app/app.css';

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
  style,
}: {
  icon: string;
  className?: string;
  family?: 'sharp' | 'rounded';
  style?: React.CSSProperties;
}) {
  return (
    <span
      className={cn(
        'material-symbols inline-flex shrink-0 select-none items-center justify-center leading-none',
        family === 'sharp' ? 'material-symbols-sharp' : 'material-symbols-rounded',
        className,
      )}
      style={style}
      aria-hidden="true"
    >
      {icon}
    </span>
  );
}

export function Sidebar({ widthClass, sections, footerName, footerEmail }: SidebarProps) {
  const initials = footerName
    .split(' ')
    .map((word) => word[0])
    .join('');

  return (
    <aside className={cn('app-side', widthClass)}>
      <NavLink className="app-brand" to="/">
        <span className="app-mark" aria-hidden="true">
          <span />
          <span />
          <span />
          <span />
        </span>
        <strong>Tabula</strong>
        <em>AI</em>
      </NavLink>
      <div className="app-nav">
        {sections.map((section) => (
          <div key={section.title}>
            <div className="app-nav-label">{section.title}</div>
            {section.items.map((item) => {
              const content = (
                <>
                  <SymbolIcon icon={item.icon} className="text-[19px]" />
                  <span className="truncate text-[14px] leading-6">{item.label}</span>
                </>
              );

              if (item.href) {
                return (
                  <NavLink
                    key={item.label}
                    to={item.href}
                    className={({ isActive }) => cn('app-nav-link', (item.active || isActive) && 'is-active')}
                  >
                    {content}
                  </NavLink>
                );
              }

              return (
                <div key={item.label} className="app-nav-link">
                  {content}
                </div>
              );
            })}
          </div>
        ))}
      </div>
      <div className="app-user">
        <div className="app-user-mark">{initials}</div>
        <div className="min-w-0">
          <strong>{footerName}</strong>
          <span>{footerEmail}</span>
        </div>
      </div>
      <button className="app-logout" type="button">
        <SymbolIcon icon="logout" className="text-[18px]" />
        Log out
      </button>
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
  const { pathname } = useLocation();
  const { theme, setMode, setAccent } = useAppTheme();

  return (
    <div className="app-root" data-mode={theme.mode}>
      <div className="app-frame">
        {sidebar}
        <main className="app-main">
          <SettingsMenu mode={theme.mode} accent={theme.accent} onMode={setMode} onAccent={setAccent} />
          <div className="app-page" key={pathname}>
            {children}
          </div>
        </main>
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
  return <section className={cn('app-card', className)}>{children}</section>;
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
    <div className="app-stat">
      <span>{label}</span>
      <strong className={valueColor}>{value}</strong>
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
    blue: 'app-tone-accent',
    green: 'app-tone-success',
    yellow: 'app-tone-warning',
    red: 'app-tone-danger',
    cream: 'app-tone-neutral',
  };

  return (
    <span className={cn('app-badge', mono ? 'font-mono' : 'font-sans', tones[tone])}>
      {dot ? <i /> : null}
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
    green: 'app-tone-success',
    blue: 'app-tone-accent',
    red: 'app-tone-danger',
  };

  return (
    <span className={cn('app-chip', tones[tone])}>
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
    <button type="button" className={cn('app-tool', active && 'is-on')}>
      <SymbolIcon icon={icon} className="text-[18px]" />
      {label}
    </button>
  );
}

export function SearchField({ placeholder, dark = true }: { placeholder: string; dark?: boolean }) {
  return (
    <div className={cn('app-search', !dark && 'border-transparent bg-transparent')}>
      <SymbolIcon icon="search" className="text-base" />
      <span className="text-[14px] leading-5">{placeholder}</span>
    </div>
  );
}
