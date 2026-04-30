import { AppShell, Badge, CardPanel, Sidebar, SymbolIcon } from '../components/ui';
import {
  conversationMessages,
  featuredTrend,
  formattedGeneratedAt,
  platformSidebar,
  storeCount,
  totalRecommendations,
} from '../data';

export function AgentsPage() {
  const sidebar = platformSidebar('agentic-simulation');
  const messages = conversationMessages.slice(-12);

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
            <SymbolIcon icon="smart_toy" className="text-[28px] text-[#E8654A]" />
            <h1 className="text-[20px] font-semibold leading-[1.4] text-[#1B3A4B]">Agentic Simulation</h1>
          </div>
          <div className="inline-flex items-center gap-2 rounded-full bg-[#D1FAE5] px-3 py-1.5 font-mono text-[12px] font-medium text-[#065F46]">
            <span className="h-2 w-2 rounded-full bg-[#2D8A6E]" />
            Live nightly sync
          </div>
        </header>

        <div className="grid flex-1 gap-6 p-6 xl:grid-cols-[minmax(0,1fr)_420px]">
          <CardPanel className="flex min-h-[640px] flex-col overflow-hidden">
            <div className="flex h-14 items-center justify-between border-b border-[#E8D4C6] bg-[#FDF5EF] px-5">
              <div className="flex items-center gap-2">
                <SymbolIcon icon="forum" className="text-[22px] text-[#E8654A]" />
                <span className="text-[15px] font-semibold text-[#1B3A4B]">Marketplace Coordination Feed</span>
              </div>
              <span className="rounded-full bg-[#E8654A] px-[10px] py-1 font-mono text-[11px] font-semibold text-white">
                {messages.length} messages
              </span>
            </div>

            <div className="flex flex-1 flex-col gap-4 overflow-y-auto p-5">
              <div className="text-center font-mono text-[11px] text-[#9AAFBC]">{formattedGeneratedAt}</div>
              {messages.map((message) => (
                <div key={message.id} className={message.align === 'right' ? 'flex justify-end' : 'flex justify-start'}>
                  <div className="max-w-[380px]">
                    <div
                      className={[
                        'rounded-[12px] px-4 py-3',
                        message.tone === 'blue'
                          ? 'bg-[#E8654A] shadow-sm'
                          : message.tone === 'green'
                            ? 'border border-[#A7D8C0] bg-[#F0FAF5]'
                            : 'bg-[#FDF5EF]',
                      ].join(' ')}
                    >
                      <div
                        className={`mb-1 font-mono text-[11px] font-semibold ${
                          message.tone === 'blue'
                            ? 'text-white/80'
                            : message.tone === 'green'
                              ? 'text-[#2D8A6E]'
                              : 'text-[#E8654A]'
                        }`}
                      >
                        {message.senderName}
                      </div>
                      <div
                        className={`whitespace-pre-line text-[13px] leading-[1.5] ${
                          message.tone === 'blue' ? 'text-white' : 'text-[#3D5A6E]'
                        }`}
                      >
                        {message.body}
                      </div>
                    </div>
                    <div className="mt-1 font-mono text-[10px] text-[#9AAFBC]">{message.time}</div>
                  </div>
                </div>
              ))}
            </div>
          </CardPanel>

          <CardPanel className="flex min-h-[640px] flex-col gap-4 p-6">
            <div>
              <h2 className="text-[18px] font-semibold leading-[1.4] text-[#1B3A4B]">Transaction demo summary</h2>
              <p className="mt-3 text-[13px] leading-[1.5] text-[#5C7A8A]">
                This view is the demo for the agentic transaction flow: stores send signals, the coordinator aggregates them, privacy protection runs, and actions come back as executable recommendations.
              </p>
            </div>
            <div className="grid gap-3">
              <div className="rounded-[12px] border border-[#E8D4C6] bg-[#FDF5EF] p-4">
                <div className="text-[12px] uppercase tracking-[0.12em] text-[#5C7A8A]">Stores involved</div>
                <div className="mt-2 font-mono text-[28px] font-semibold text-[#1B3A4B]">{storeCount}</div>
              </div>
              <div className="rounded-[12px] border border-[#E8D4C6] bg-[#FDF5EF] p-4">
                <div className="text-[12px] uppercase tracking-[0.12em] text-[#5C7A8A]">Recommendations sent</div>
                <div className="mt-2 font-mono text-[28px] font-semibold text-[#1B3A4B]">{totalRecommendations}</div>
              </div>
              <div className="rounded-[12px] border border-[#E8D4C6] bg-[#FDF5EF] p-4">
                <div className="text-[12px] uppercase tracking-[0.12em] text-[#5C7A8A]">Top category discussed</div>
                <div className="mt-2 text-[20px] font-semibold text-[#2D8A6E]">{featuredTrend.categoryLabel}</div>
                <div className="mt-1 text-[12px] text-[#5C7A8A]">
                  {featuredTrend.directionLabel} with {featuredTrend.strengthLabel} strength
                </div>
              </div>
            </div>
            <Badge label="Privacy-preserved coordination" tone="blue" mono={false} />
          </CardPanel>
        </div>
      </div>
    </AppShell>
  );
}
