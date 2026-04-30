import { ActionChip, AppShell, Badge, HeaderButton, Sidebar, SymbolIcon } from '../components/ui';
import { actionQueueRows, actionTone, highPriorityCount, platformSidebar, totalRecommendations } from '../data';

export function OrdersPage() {
  const sidebar = platformSidebar('orders', false);
  const increaseCount = actionQueueRows.filter((row) => row.action === 'increase_stock').length;
  const reduceCount = actionQueueRows.filter(
    (row) => row.action === 'reduce_stock' || row.action === 'discontinue',
  ).length;

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
        <header className="flex h-[72px] items-center justify-between border-b border-[#E8D4C6] px-8">
          <div className="flex items-center gap-3">
            <SymbolIcon icon="shopping_cart" className="text-[28px] text-[#E8654A]" />
            <h1 className="text-[20px] font-semibold text-[#1B3A4B]">Action Queue</h1>
          </div>
          <div className="flex items-center gap-3">
            <HeaderButton icon="filter_list" label="Filter" />
            <HeaderButton icon="download" label="Export" />
          </div>
        </header>

        <div className="flex flex-1 flex-col gap-5 p-6">
          <div className="grid gap-3 xl:grid-cols-4">
            <div className="rounded-[12px] border border-[#E8D4C6] bg-white px-5 py-4 shadow-sm">
              <div className="text-[12px] font-medium text-[#5C7A8A]">Queued actions</div>
              <div className="mt-2 font-mono text-[28px] font-semibold text-[#1B3A4B]">{totalRecommendations}</div>
            </div>
            <div className="rounded-[12px] border border-[#E8D4C6] bg-white px-5 py-4 shadow-sm">
              <div className="text-[12px] font-medium text-[#5C7A8A]">Ready to act</div>
              <div className="mt-2 font-mono text-[28px] font-semibold text-[#2D8A6E]">{highPriorityCount}</div>
            </div>
            <div className="rounded-[12px] border border-[#E8D4C6] bg-white px-5 py-4 shadow-sm">
              <div className="text-[12px] font-medium text-[#5C7A8A]">Increase stock</div>
              <div className="mt-2 font-mono text-[28px] font-semibold text-[#1B3A4B]">{increaseCount}</div>
            </div>
            <div className="rounded-[12px] border border-[#E8D4C6] bg-white px-5 py-4 shadow-sm">
              <div className="text-[12px] font-medium text-[#5C7A8A]">Reduce exposure</div>
              <div className="mt-2 font-mono text-[28px] font-semibold text-[#D14D4D]">{reduceCount}</div>
            </div>
          </div>

          <div className="rounded-[12px] border border-[#E8D4C6] bg-[#FFF8F0] p-3">
            <div className="flex flex-col gap-2 md:flex-row md:items-center md:justify-between">
              <div className="font-mono text-[14px] font-medium text-[#1B3A4B]">Action workflow</div>
              <Badge label="Confidence-ranked" tone="cream" mono />
            </div>
            <p className="mt-2 text-[13px] leading-[1.4] text-[#5C7A8A]">
              High-priority recommendations surface first, while medium and low-priority moves stay in weekly review and watchlist queues.
            </p>
          </div>

          <div className="min-h-0 overflow-hidden rounded-[12px] border border-[#E8D4C6] bg-white shadow-sm">
            <div className="grid grid-cols-[170px_150px_160px_110px_140px_minmax(260px,1fr)_150px] items-center border-b border-[#E8D4C6] bg-[#FDF5EF] px-4 py-3 font-mono text-[12px] font-medium text-[#9AAFBC]">
              <div>Store</div>
              <div>Category</div>
              <div>Action</div>
              <div>Priority</div>
              <div>Status</div>
              <div>Reasoning</div>
              <div>Actions</div>
            </div>
            <div className="max-h-[540px] overflow-y-auto">
              {actionQueueRows.map((row) => (
                <div
                  key={row.id}
                  className="grid grid-cols-[170px_150px_160px_110px_140px_minmax(260px,1fr)_150px] items-center border-b border-[#E8D4C6] px-4 py-3 text-[13px] last:border-b-0"
                >
                  <div className="text-[#1B3A4B]">{row.storeName}</div>
                  <div className="text-[#5C7A8A]">{row.categoryLabel}</div>
                  <div>
                    <Badge label={row.actionLabel} tone={actionTone(row.action)} mono={false} />
                  </div>
                  <div className="font-mono text-[#1B3A4B]">{row.priorityLabel}</div>
                  <div>
                    <Badge label={row.status.label} tone={row.status.tone} mono={false} />
                  </div>
                  <div className="text-[#5C7A8A]">{row.shortReasoning}</div>
                  <div className="flex flex-wrap gap-1.5">
                    <ActionChip icon="visibility" label="Review" tone="blue" />
                    {row.priority === 'high' ? (
                      <ActionChip icon="check_circle" label="Approve" tone="green" />
                    ) : (
                      <ActionChip icon="schedule" label="Monitor" tone="blue" />
                    )}
                  </div>
                </div>
              ))}
            </div>
            <div className="flex items-center justify-between border-t border-[#E8D4C6] bg-[#FDF5EF] px-4 py-3">
              <span className="text-[13px] text-[#9AAFBC]">
                Showing {actionQueueRows.length} recommendation-driven actions
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
