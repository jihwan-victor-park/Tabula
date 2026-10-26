import { AppShell, Badge, HeaderButton, Sidebar, SymbolIcon } from '../components/ui';
import {
  featuredTrend,
  marketTrends,
  platformSidebar,
  signalLedgerRows,
} from '../data';

export function SalesHistoryPage() {
  const sidebar = platformSidebar('sales-history');
  const stableCount = marketTrends.filter((trend) => trend.direction === 'stable').length;
  const fallingCount = marketTrends.filter((trend) => trend.direction === 'falling').length;

  return (
    <AppShell
      sidebar={
        <Sidebar
          widthClass={sidebar.widthClass}
          sections={sidebar.sections}
          footerName={sidebar.footerName}
          footerEmail={sidebar.footerEmail}
        />
      }
    >
      <div className="flex h-full flex-col">
        <header className="flex min-h-[72px] flex-col gap-4 border-b border-[var(--app-line)] px-8 py-4 xl:flex-row xl:items-center xl:justify-between xl:py-0">
          <div className="flex items-center gap-3">
            <SymbolIcon icon="receipt_long" className="text-[28px] text-[var(--app-accent)]" />
            <h1 className="text-[20px] font-semibold text-[var(--app-ink)]">Signal Ledger</h1>
          </div>
          <div className="flex items-center gap-3">
            <HeaderButton icon="calendar_today" label="Latest nightly cycle" />
            <HeaderButton icon="download" label="Export CSV" />
          </div>
        </header>

        <div className="flex flex-1 flex-col gap-5 p-6">
          <div className="grid gap-3 xl:grid-cols-4">
            <div className="rounded-[12px] border border-[var(--app-line)] bg-[var(--app-surface)] px-5 py-4 shadow-sm">
              <div className="text-[12px] font-medium text-[var(--app-muted)]">Rising signals</div>
              <div className="mt-2 font-mono text-[28px] font-semibold text-[var(--app-success)]">
                {marketTrends.filter((trend) => trend.direction === 'rising').length}
              </div>
            </div>
            <div className="rounded-[12px] border border-[var(--app-line)] bg-[var(--app-surface)] px-5 py-4 shadow-sm">
              <div className="text-[12px] font-medium text-[var(--app-muted)]">Stable signals</div>
              <div className="mt-2 font-mono text-[28px] font-semibold text-[var(--app-ink)]">{stableCount}</div>
            </div>
            <div className="rounded-[12px] border border-[var(--app-line)] bg-[var(--app-surface)] px-5 py-4 shadow-sm">
              <div className="text-[12px] font-medium text-[var(--app-muted)]">Falling signals</div>
              <div className="mt-2 font-mono text-[28px] font-semibold text-[var(--app-danger)]">{fallingCount}</div>
            </div>
            <div className="rounded-[12px] border border-[var(--app-line)] bg-[var(--app-surface)] px-5 py-4 shadow-sm">
              <div className="text-[12px] font-medium text-[var(--app-muted)]">Strongest signal</div>
              <div className="mt-2 text-[20px] font-semibold text-[var(--app-accent)]">{featuredTrend.categoryLabel}</div>
              <div className="mt-1 font-mono text-[11px] text-[var(--app-quiet)]">{featuredTrend.strengthLabel} confidence-weighted strength</div>
            </div>
          </div>

          <div className="min-h-0 overflow-hidden rounded-[12px] border border-[var(--app-line)] bg-[var(--app-surface)] shadow-sm">
            <div className="grid grid-cols-[200px_110px_110px_120px_120px_160px] items-center border-b border-[var(--app-line)] bg-[var(--app-surface-muted)] px-4 py-3 font-mono text-[12px] font-medium text-[var(--app-quiet)]">
              <div>Category</div>
              <div>Direction</div>
              <div>Strength</div>
              <div>Consensus</div>
              <div>Signals</div>
              <div>Store actions</div>
            </div>
            <div className="max-h-[540px] overflow-y-auto">
              {signalLedgerRows.map((row) => (
                <div
                  key={row.category}
                  className="grid grid-cols-[200px_110px_110px_120px_120px_160px] items-center border-b border-[var(--app-line)] px-4 py-3 text-[13px] last:border-b-0"
                >
                  <div className="text-[var(--app-ink)]">{row.categoryLabel}</div>
                  <div>
                    <Badge
                      label={row.directionLabel}
                      tone={row.direction === 'rising' ? 'green' : row.direction === 'falling' ? 'red' : 'blue'}
                      mono={false}
                    />
                  </div>
                  <div className="font-mono font-medium text-[var(--app-ink)]">{row.strengthLabel}</div>
                  <div className="font-mono capitalize text-[var(--app-muted)]">{row.consensus}</div>
                  <div className="font-mono text-[var(--app-muted)]">{row.signal_count}</div>
                  <div className="font-mono text-[var(--app-accent)]">{row.recommendedStoreCount}</div>
                </div>
              ))}
            </div>
            <div className="flex items-center justify-between border-t border-[var(--app-line)] bg-[var(--app-surface-muted)] px-4 py-3">
              <span className="text-[13px] text-[var(--app-quiet)]">
                Showing {signalLedgerRows.length} categories from the latest aggregated run
              </span>
              <div className="flex items-center gap-1">
                <button className="h-8 w-8 rounded-[8px] bg-[var(--app-accent)] text-[13px] font-semibold text-[var(--app-accent-ink)]">1</button>
              </div>
            </div>
          </div>
        </div>
      </div>
    </AppShell>
  );
}
