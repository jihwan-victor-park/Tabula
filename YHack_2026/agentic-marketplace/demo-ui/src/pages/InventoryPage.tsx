import { AppShell, Badge, HeaderButton, SearchField, Sidebar, SymbolIcon } from '../components/ui';
import {
  categoryCount,
  directionTone,
  highPriorityCount,
  inventoryRows,
  platformSidebar,
  storeCount,
  totalRecommendations,
} from '../data';

export function InventoryPage() {
  const sidebar = platformSidebar('inventory');

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
            <SymbolIcon icon="inventory_2" className="text-[28px] text-[#E8654A]" />
            <h1 className="text-[20px] font-semibold text-[#1B3A4B]">Store Playbook</h1>
          </div>
          <div className="flex flex-wrap items-center gap-3">
            <div className="w-[220px]">
              <SearchField placeholder="Search stores or categories..." />
            </div>
            <HeaderButton icon="bolt" label="Prioritize" />
            <HeaderButton icon="download" label="Export actions" active />
          </div>
        </header>

        <div className="px-8 py-4">
          <div className="grid gap-4 xl:grid-cols-4">
            <div className="rounded-[12px] border border-[#E8D4C6] bg-white px-5 py-4 shadow-sm">
              <div className="text-[13px] font-medium text-[#5C7A8A]">Stores tracked</div>
              <div className="mt-2 font-mono text-[24px] font-bold text-[#1B3A4B]">{storeCount}</div>
            </div>
            <div className="rounded-[12px] border border-[#E8D4C6] bg-white px-5 py-4 shadow-sm">
              <div className="flex items-center gap-2 text-[13px] font-medium text-[#5C7A8A]">
                High priority
                <span className="h-2 w-2 rounded-full bg-[#2D8A6E]" />
              </div>
              <div className="mt-2 font-mono text-[24px] font-bold text-[#2D8A6E]">{highPriorityCount}</div>
            </div>
            <div className="rounded-[12px] border border-[#E8D4C6] bg-white px-5 py-4 shadow-sm">
              <div className="text-[13px] font-medium text-[#5C7A8A]">Total recommendations</div>
              <div className="mt-2 font-mono text-[24px] font-bold text-[#1B3A4B]">{totalRecommendations}</div>
            </div>
            <div className="rounded-[12px] border border-[#E8D4C6] bg-white px-5 py-4 shadow-sm">
              <div className="text-[13px] font-medium text-[#5C7A8A]">Categories in cycle</div>
              <div className="mt-2 font-mono text-[24px] font-bold text-[#1B3A4B]">{categoryCount}</div>
            </div>
          </div>
        </div>

        <div className="flex-1 px-8 pb-4">
          <div className="overflow-hidden rounded-[12px] border border-[#E8D4C6] bg-white shadow-sm">
            <div className="grid grid-cols-[180px_160px_150px_130px_110px_110px_170px] items-center bg-[#FDF5EF] px-4 text-[13px] font-semibold text-[#5C7A8A]">
              <div className="py-3">Store</div>
              <div className="py-3">Category</div>
              <div className="py-3">Recommendation</div>
              <div className="py-3">Priority</div>
              <div className="py-3">Confidence</div>
              <div className="py-3">Trend</div>
              <div className="py-3">Updated</div>
            </div>
            {inventoryRows.map((row) => (
              <div
                key={row.id}
                className="grid grid-cols-[180px_160px_150px_130px_110px_110px_170px] items-center border-b border-[#E8D4C6] px-4 last:border-b-0"
              >
                <div className="py-3 text-[14px] text-[#1B3A4B]">{row.storeName}</div>
                <div className="py-3 text-[13px] text-[#5C7A8A]">{row.categoryLabel}</div>
                <div className="py-3 font-mono text-[13px] text-[#3D5A6E]">{row.actionLabel}</div>
                <div className="py-3">
                  <Badge label={row.priorityLabel} tone={row.priority === 'high' ? 'green' : row.priority === 'medium' ? 'yellow' : 'blue'} mono={false} />
                </div>
                <div className="py-3 font-mono text-[13px] text-[#1B3A4B]">{row.confidenceLabel}</div>
                <div className="py-3">
                  <Badge label={row.trendDirectionLabel} tone={directionTone(row.trendDirection)} mono={false} />
                </div>
                <div className="py-3 font-mono text-[13px] text-[#5C7A8A]">{row.updatedLabel}</div>
              </div>
            ))}
            <div className="flex items-center justify-between border-t border-[#E8D4C6] px-4 py-3">
              <span className="text-[13px] text-[#5C7A8A]">
                Showing {inventoryRows.length} recommendations from the latest cycle
              </span>
              <div className="flex items-center gap-1">
                <button className="flex h-8 w-8 items-center justify-center rounded-[6px] border border-[#E8D4C6] bg-white text-[#5C7A8A]">
                  <SymbolIcon icon="chevron_left" className="text-base" />
                </button>
                <button className="h-8 w-8 rounded-[6px] bg-[#E8654A] text-[13px] font-semibold text-white">1</button>
                <button className="flex h-8 w-8 items-center justify-center rounded-[6px] border border-[#E8D4C6] bg-white text-[#5C7A8A]">
                  <SymbolIcon icon="chevron_right" className="text-base" />
                </button>
              </div>
            </div>
          </div>
        </div>
      </div>
    </AppShell>
  );
}
