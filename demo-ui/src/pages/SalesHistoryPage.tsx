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
        <header className="flex min-h-[72px] flex-col gap-4 border-b border-[#E8D4C6] px-8 py-4 xl:flex-row xl:items-center xl:justify-between xl:py-0">
          <div className="flex items-center gap-3">
            <SymbolIcon icon="receipt_long" className="text-[28px] text-[#E8654A]" />
            <h1 className="text-[20px] font-semibold text-[#1B3A4B]">Signal Ledger</h1>
          </div>
          <div className="flex items-center gap-3">
            <HeaderButton icon="calendar_today" label="Latest nightly cycle" />
            <HeaderButton icon="download" label="Export CSV" />
          </div>
        </header>

        <div className="flex flex-1 flex-col gap-5 p-6">
          <div className="grid gap-3 xl:grid-cols-4">
            <div className="rounded-[12px] border border-[#E8D4C6] bg-white px-5 py-4 shadow-sm">
              <div className="text-[12px] font-medium text-[#5C7A8A]">Rising signals</div>
              <div className="mt-2 font-mono text-[28px] font-semibold text-[#2D8A6E]">
                {marketTrends.filter((trend) => trend.direction === 'rising').length}
              </div>
            </div>
            <div className="rounded-[12px] border border-[#E8D4C6] bg-white px-5 py-4 shadow-sm">
              <div className="text-[12px] font-medium text-[#5C7A8A]">Stable signals</div>
              <div className="mt-2 font-mono text-[28px] font-semibold text-[#1B3A4B]">{stableCount}</div>
            </div>
            <div className="rounded-[12px] border border-[#E8D4C6] bg-white px-5 py-4 shadow-sm">
              <div className="text-[12px] font-medium text-[#5C7A8A]">Falling signals</div>
              <div className="mt-2 font-mono text-[28px] font-semibold text-[#D14D4D]">{fallingCount}</div>
            </div>
            <div className="rounded-[12px] border border-[#E8D4C6] bg-white px-5 py-4 shadow-sm">
              <div className="text-[12px] font-medium text-[#5C7A8A]">Strongest signal</div>
              <div className="mt-2 text-[20px] font-semibold text-[#E8654A]">{featuredTrend.categoryLabel}</div>
              <div className="mt-1 font-mono text-[11px] text-[#9AAFBC]">{featuredTrend.strengthLabel} confidence-weighted strength</div>
            </div>
          </div>

          <div className="min-h-0 overflow-hidden rounded-[12px] border border-[#E8D4C6] bg-white shadow-sm">
            <div className="grid grid-cols-[200px_110px_110px_120px_120px_160px] items-center border-b border-[#E8D4C6] bg-[#FDF5EF] px-4 py-3 font-mono text-[12px] font-medium text-[#9AAFBC]">
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
                  className="grid grid-cols-[200px_110px_110px_120px_120px_160px] items-center border-b border-[#E8D4C6] px-4 py-3 text-[13px] last:border-b-0"
                >
                  <div className="text-[#1B3A4B]">{row.categoryLabel}</div>
                  <div>
                    <Badge
                      label={row.directionLabel}
                      tone={row.direction === 'rising' ? 'green' : row.direction === 'falling' ? 'red' : 'blue'}
                      mono={false}
                    />
                  </div>
                  <div className="font-mono font-medium text-[#1B3A4B]">{row.strengthLabel}</div>
                  <div className="font-mono capitalize text-[#5C7A8A]">{row.consensus}</div>
                  <div className="font-mono text-[#5C7A8A]">{row.signal_count}</div>
                  <div className="font-mono text-[#E8654A]">{row.recommendedStoreCount}</div>
                </div>
              ))}
            </div>
            <div className="flex items-center justify-between border-t border-[#E8D4C6] bg-[#FDF5EF] px-4 py-3">
              <span className="text-[13px] text-[#9AAFBC]">
                Showing {signalLedgerRows.length} categories from the latest aggregated run
              </span>
              <div className="flex items-center gap-1">
                <button className="h-8 w-8 rounded-[8px] bg-[#E8654A] text-[13px] font-semibold text-white">1</button>
              </div>
            </div>
          </div>
        </div>
      </div>
    </AppShell>
  );
}
