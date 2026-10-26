import { useEffect, useState } from 'react';
import { AppShell, CardPanel, Sidebar, SymbolIcon } from '../components/ui';
import { platformSidebar } from '../data';

function BrowserbaseLiveView() {
  const [session, setSession] = useState<{
    session_id: string | null;
    live_view_url: string | null;
    embed_url?: string | null;
    active?: boolean;
  }>({ session_id: null, live_view_url: null, embed_url: null });

  useEffect(() => {
    const poll = async () => {
      try {
        const res = await fetch('http://localhost:8000/live-session');
        const data = await res.json();
        setSession(data);
      } catch {
        // backend not available
      }
    };
    poll();
    const id = window.setInterval(poll, 1000);
    return () => window.clearInterval(id);
  }, []);

  const isActive = session.session_id && session.active !== false;

  return (
    <CardPanel className="flex flex-col">
      <div className="flex items-center justify-between px-6 py-5">
        <h2 className="text-[16px] font-semibold leading-[1.4] text-[var(--app-ink)]">Browser Live View</h2>
        <div className="flex items-center gap-1.5">
          {isActive ? (
            <>
              <span className="h-2 w-2 animate-pulse rounded-full bg-[var(--app-accent)]" />
              <span className="text-[12px] text-[var(--app-accent)]">Scanning</span>
            </>
          ) : session.session_id ? (
            <>
              <span className="h-2 w-2 rounded-full bg-[var(--app-warning)]" />
              <span className="text-[12px] text-[var(--app-warning)]">Scan complete</span>
            </>
          ) : (
            <>
              <span className="h-2 w-2 rounded-full bg-[var(--app-quiet)]" />
              <span className="text-[12px] text-[var(--app-quiet)]">Idle</span>
            </>
          )}
        </div>
      </div>

      {session.session_id && session.live_view_url ? (
        <div className="flex flex-col gap-3 px-6 pb-6 pt-2">
          <div className="flex w-full items-center gap-3 rounded-[10px] border border-[var(--app-line)] bg-[var(--app-surface-muted)] px-4 py-2.5">
            <SymbolIcon icon="travel_explore" family="rounded" className="text-[20px] text-[var(--app-accent)]" />
            <div className="min-w-0 flex-1">
              <div className="text-[12px] font-semibold text-[var(--app-ink)]">
                {isActive ? 'Browserbase scanning now' : 'Last scan session'}
              </div>
              <div className="truncate font-mono text-[10px] text-[var(--app-quiet)]">{session.session_id}</div>
            </div>
            <a
              href={session.live_view_url}
              target="_blank"
              rel="noreferrer"
              className="shrink-0 rounded-[8px] bg-[var(--app-ink)] px-3 py-1.5 text-[12px] font-semibold text-[var(--app-inverse-ink)] hover:bg-[var(--app-inverse-hover)]"
            >
              Full screen ↗
            </a>
          </div>

          {session.embed_url ? (
            <div className="overflow-hidden rounded-[10px] border border-[var(--app-line)]" style={{ height: 520 }}>
              <iframe
                src={session.embed_url}
                title="Browserbase live view"
                className="h-full w-full border-0"
                allow="clipboard-read; clipboard-write"
              />
            </div>
          ) : (
            <div className="text-center text-[11px] text-[var(--app-quiet)]">
              Live embed unavailable — use Full screen link above
            </div>
          )}
        </div>
      ) : (
        <div className="flex flex-1 flex-col items-center justify-center gap-3 px-6 pb-12 pt-4">
          <SymbolIcon icon="travel_explore" family="rounded" className="text-[48px] text-[var(--app-line)]" />
          <div className="text-center">
            <div className="text-[14px] font-semibold text-[var(--app-ink)]">No active scan</div>
            <div className="mt-1 text-[12px] text-[var(--app-quiet)]">
              Text your agent "check prices" to kick off a live price scan
            </div>
          </div>
        </div>
      )}
    </CardPanel>
  );
}

export function PriceScoutPage() {
  return (
    <AppShell
      sidebar={
        <Sidebar
          widthClass={platformSidebar('price-scout').widthClass}
          sections={platformSidebar('price-scout').sections}
          footerName={platformSidebar('price-scout').footerName}
          footerEmail={platformSidebar('price-scout').footerEmail}
        />
      }
    >
      <div className="flex h-full flex-col gap-6 px-8 py-7">
        <header>
          <h1 className="text-[36px] font-semibold leading-[1.05] tracking-[-0.04em] text-[var(--app-ink)]">
            Price Scout
          </h1>
          <p className="mt-1 text-[14px] text-[var(--app-muted)]">
            Live browser sessions scanning wholesale suppliers for the best prices
          </p>
        </header>

        <BrowserbaseLiveView />
      </div>
    </AppShell>
  );
}
