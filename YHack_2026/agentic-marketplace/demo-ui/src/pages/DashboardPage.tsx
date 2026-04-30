import { useEffect, useRef, useState } from 'react';
import { AppShell, Badge, CardPanel, Sidebar, SymbolIcon } from '../components/ui';
import {
  createInitials,
  dashboardSidebar,
  featuredRecommendation,
  featuredStore,
  formatCategory,
} from '../data';

/* ── Dolls sales trend data (past 14 days) ── */

const DOLLS_SALES = [
  { day: 'Mar 15', sales: 12 },
  { day: 'Mar 16', sales: 14 },
  { day: 'Mar 17', sales: 11 },
  { day: 'Mar 18', sales: 18 },
  { day: 'Mar 19', sales: 16 },
  { day: 'Mar 20', sales: 22 },
  { day: 'Mar 21', sales: 19 },
  { day: 'Mar 22', sales: 25 },
  { day: 'Mar 23', sales: 28 },
  { day: 'Mar 24', sales: 24 },
  { day: 'Mar 25', sales: 31 },
  { day: 'Mar 26', sales: 29 },
  { day: 'Mar 27', sales: 35 },
  { day: 'Mar 28', sales: 38 },
];

const OTHER_ITEMS = [
  { name: 'Action Figures', units: 142, trend: +12 },
  { name: 'Board Games', units: 95, trend: +4 },
  { name: 'Educational Toys', units: 64, trend: +18 },
  { name: 'Craft Kits', units: 22, trend: -3 },
  { name: 'Outdoor Toys', units: 110, trend: +8 },
];

function SalesChart() {
  const W = 420;
  const H = 160;
  const padX = 36;
  const padTop = 10;
  const padBot = 24;
  const chartW = W - padX * 2;
  const chartH = H - padTop - padBot;

  const max = Math.max(...DOLLS_SALES.map((d) => d.sales));
  const min = Math.min(...DOLLS_SALES.map((d) => d.sales));
  const range = max - min || 1;

  const points = DOLLS_SALES.map((d, i) => ({
    x: padX + (i / (DOLLS_SALES.length - 1)) * chartW,
    y: padTop + chartH - ((d.sales - min) / range) * chartH,
    ...d,
  }));

  const linePath = points.map((p, i) => `${i === 0 ? 'M' : 'L'} ${p.x} ${p.y}`).join(' ');
  const areaPath = `${linePath} L ${points[points.length - 1]!.x} ${padTop + chartH} L ${points[0]!.x} ${padTop + chartH} Z`;

  const gridLines = [0, 0.25, 0.5, 0.75, 1].map((t) => {
    const y = padTop + chartH - t * chartH;
    const val = Math.round(min + t * range);
    return { y, val };
  });

  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="w-full" style={{ maxHeight: 180 }}>
      <defs>
        <linearGradient id="areaGrad" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="#2D8A6E" stopOpacity="0.18" />
          <stop offset="100%" stopColor="#2D8A6E" stopOpacity="0.02" />
        </linearGradient>
      </defs>

      {gridLines.map((g) => (
        <g key={g.val}>
          <line x1={padX} y1={g.y} x2={W - padX} y2={g.y} stroke="#E8D4C6" strokeWidth="0.5" />
          <text x={padX - 6} y={g.y + 3.5} textAnchor="end" fill="#9AAFBC" fontSize="8" fontFamily="'JetBrains Mono', monospace">
            {g.val}
          </text>
        </g>
      ))}

      <path d={areaPath} fill="url(#areaGrad)" />
      <path d={linePath} fill="none" stroke="#2D8A6E" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />

      {points.map((p, i) => (
        <g key={i}>
          <circle cx={p.x} cy={p.y} r="3.5" fill="#FFFFFF" stroke="#2D8A6E" strokeWidth="1.5" />
          {i % 3 === 0 || i === points.length - 1 ? (
            <text x={p.x} y={H - 4} textAnchor="middle" fill="#9AAFBC" fontSize="7" fontFamily="'JetBrains Mono', monospace">
              {p.day.slice(4)}
            </text>
          ) : null}
        </g>
      ))}

      <rect x={points[points.length - 1]!.x - 14} y={points[points.length - 1]!.y - 18} width="28" height="14" rx="4" fill="#2D8A6E" />
      <text
        x={points[points.length - 1]!.x}
        y={points[points.length - 1]!.y - 9}
        textAnchor="middle"
        fill="#FFFFFF"
        fontSize="8"
        fontWeight="700"
        fontFamily="'JetBrains Mono', monospace"
      >
        {points[points.length - 1]!.sales}
      </text>
    </svg>
  );
}

/* ── Agent chat scripts (30 messages cycling) ── */

type AgentId = 'procurement' | 'price_discovery' | 'trend' | 'universal';

const AGENT_META: Record<AgentId, { label: string; initials: string; color: string; bg: string; side: 'left' | 'right' }> = {
  trend:           { label: 'Trend Agent',           initials: 'TA', color: 'text-[#E8654A]', bg: 'bg-[#E8654A]', side: 'left' },
  procurement:     { label: 'Procurement Agent',     initials: 'PA', color: 'text-[#2D8A6E]', bg: 'bg-[#2D8A6E]', side: 'right' },
  price_discovery: { label: 'Price Discovery Agent', initials: 'PD', color: 'text-[#D4870E]', bg: 'bg-[#D4870E]', side: 'left' },
  universal:       { label: 'Universal Agent',       initials: 'UA', color: 'text-[#7B68B0]', bg: 'bg-[#7B68B0]', side: 'right' },
};

const CHAT_SCRIPTS: { agent: AgentId; text: string }[] = [
  { agent: 'trend', text: 'Dolls demand spiked +27% this week across 3 regional clusters.' },
  { agent: 'procurement', text: 'Checking supplier lead times for doll SKUs... average 4.2 days.' },
  { agent: 'price_discovery', text: 'Wholesale price for "Classic Baby Doll 12in" dropped to $8.40 — 6% below last month.' },
  { agent: 'universal', text: 'Store #a31d reports dolls are their #2 mover this week. Confirming cross-network signal.' },
  { agent: 'procurement', text: 'MOQ for top doll supplier is 50 units. Current stock: 38. Recommending reorder of 80.' },
  { agent: 'trend', text: 'Action figures holding steady at +12%. No restock urgency detected.' },
  { agent: 'price_discovery', text: 'Found 3 alternative suppliers for craft kits — best margin at 42% vs current 31%.' },
  { agent: 'universal', text: 'Network consensus: educational toys rising in 4/5 stores. Moderate confidence.' },
  { agent: 'procurement', text: 'Craft kit inventory critically low (22 units). Flagging for emergency reorder.' },
  { agent: 'trend', text: 'Board games seasonal trend detected — expect +15% by end of month.' },
  { agent: 'price_discovery', text: 'Bulk discount available: 100+ doll units at $7.90 each (save $0.50/unit).' },
  { agent: 'universal', text: 'Agent #b84e asking about outdoor toy supplier — sharing our verified contact.' },
  { agent: 'procurement', text: 'PO #4821 submitted for 80 dolls. Estimated arrival: April 2.' },
  { agent: 'trend', text: 'Craft kits demand is softening slightly (-3%). Monitor before large reorder.' },
  { agent: 'price_discovery', text: 'Educational toy margins improved to 38% after renegotiation.' },
  { agent: 'universal', text: 'Encrypted market signal received: plush toys trending in adjacent market.' },
  { agent: 'procurement', text: 'Outdoor toys fully stocked (110/160). No action needed this cycle.' },
  { agent: 'trend', text: 'Weekend demand forecast: +1.4× baseline for dolls and action figures.' },
  { agent: 'price_discovery', text: 'Comparing 12 suppliers for board games... best landed cost is $11.20.' },
  { agent: 'universal', text: 'Aggregated model update: craft kits consensus is "moderate" across network.' },
  { agent: 'procurement', text: 'Supplier reliability score for DollCo Inc: 9.2/10 (98% on-time delivery).' },
  { agent: 'trend', text: 'New signal: "collectible dolls" search volume up 34% in our region.' },
  { agent: 'price_discovery', text: 'Shipping cost alert: FedEx ground rate increasing 3% next week.' },
  { agent: 'universal', text: 'Privacy-preserved insight: 3/5 stores plan to increase doll stock this cycle.' },
  { agent: 'procurement', text: 'Auto-reorder triggered for educational toys (threshold: 50 units).' },
  { agent: 'trend', text: 'Historical pattern: doll sales peak in 6 weeks. Recommend front-loading inventory.' },
  { agent: 'price_discovery', text: 'New wholesale listing: "Eco-Friendly Rag Doll Set" at $6.80 — 4.8★ rating.' },
  { agent: 'universal', text: 'Cross-store intelligence: outdoor toy demand correlating with weather forecast data.' },
  { agent: 'procurement', text: 'Budget utilization this cycle: 67%. $2,400 remaining for discretionary orders.' },
  { agent: 'trend', text: 'Summary: top movers → Dolls (+27%), Educational (+18%), Action Figures (+12%).' },
];

function AgentChat() {
  const [messages, setMessages] = useState<{ id: number; agent: AgentId; text: string; time: string }[]>([]);
  const nextIdx = useRef(0);
  const nextId = useRef(0);
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const now = () => {
      const d = new Date();
      return d.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit' });
    };

    const addInitial = () => {
      const batch: typeof messages = [];
      for (let i = 0; i < 4; i++) {
        const script = CHAT_SCRIPTS[nextIdx.current % CHAT_SCRIPTS.length]!;
        nextIdx.current++;
        batch.push({ id: nextId.current++, agent: script.agent, text: script.text, time: now() });
      }
      setMessages(batch);
    };
    addInitial();

    const id = window.setInterval(() => {
      const script = CHAT_SCRIPTS[nextIdx.current % CHAT_SCRIPTS.length]!;
      nextIdx.current++;
      setMessages((prev) => [
        ...prev.slice(-30),
        { id: nextId.current++, agent: script.agent, text: script.text, time: now() },
      ]);
    }, 3200);

    return () => window.clearInterval(id);
  }, []);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  return (
    <div className="flex flex-1 flex-col overflow-hidden">
      <div className="flex-1 space-y-3 overflow-y-auto px-4 pb-4 pt-2">
        {messages.map((msg) => {
          const meta = AGENT_META[msg.agent];
          const isLeft = meta.side === 'left';

          return (
            <div key={msg.id} className={`flex items-end gap-2 ${isLeft ? 'justify-start' : 'justify-end'}`}>
              {isLeft && (
                <div className={`flex h-7 w-7 shrink-0 items-center justify-center rounded-full text-[10px] font-bold text-white ${meta.bg}`}>
                  {meta.initials}
                </div>
              )}
              <div className={`max-w-[75%] ${isLeft ? '' : 'text-right'}`}>
                <div className={`mb-1 text-[10px] font-semibold ${meta.color}`}>
                  {meta.label}
                </div>
                <div
                  className={[
                    'rounded-[14px] bg-[#FDF5EF] px-3.5 py-2.5 text-[12.5px] leading-[1.5] text-[#1B3A4B]',
                    isLeft ? 'rounded-bl-[4px]' : 'rounded-br-[4px]',
                  ].join(' ')}
                >
                  {msg.text}
                </div>
                <div className={`mt-1 font-mono text-[9px] text-[#9AAFBC] ${isLeft ? '' : 'text-right'}`}>{msg.time}</div>
              </div>
              {!isLeft && (
                <div className={`flex h-7 w-7 shrink-0 items-center justify-center rounded-full text-[10px] font-bold text-white ${meta.bg}`}>
                  {meta.initials}
                </div>
              )}
            </div>
          );
        })}
        <div ref={bottomRef} />
      </div>
      <div className="flex items-center gap-2 border-t border-[#E8D4C6] px-4 py-3">
        <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-[#2D8A6E]" />
        <span className="text-[11px] text-[#9AAFBC]">4 agents active · auto-cycling</span>
      </div>
    </div>
  );
}

/* ── Main Dashboard ── */

export function DashboardPage() {
  return (
    <AppShell
      sidebar={
        <Sidebar
          widthClass={dashboardSidebar.widthClass}
          sections={dashboardSidebar.sections}
          footerName={dashboardSidebar.footerName}
          footerEmail={dashboardSidebar.footerEmail}
        />
      }
    >
      <div className="flex h-full flex-col gap-6 px-8 py-7">
        <header className="flex flex-col gap-6 xl:flex-row xl:items-start xl:justify-between">
          <div className="flex-1">
            <h1 className="text-[42px] font-bold leading-[1.15] text-[#1B3A4B]" style={{ fontFamily: "'Plus Jakarta Sans', sans-serif" }}>Hi Sarah, Welcome to Tabula</h1>
          </div>
          <div className="flex items-center gap-3">
            <div className="flex h-9 w-9 items-center justify-center rounded-full bg-[#1B3A4B] font-mono text-[13px] font-semibold text-white">
              {createInitials(featuredStore.store_name)}
            </div>
          </div>
        </header>

        {/* ── Featured recommendation — compact purchase card ── */}
        <div className="flex w-full items-center gap-3 rounded-[12px] border border-[#E8D4C6] bg-white px-4 py-3 shadow-sm">
          <img
            src="/doll.png"
            alt="Craft Kits"
            className="h-12 w-12 shrink-0 rounded-[10px] border border-[#E8D4C6] object-cover"
          />
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2">
              <span className="text-[14px] font-semibold text-[#1B3A4B]">{formatCategory(featuredRecommendation.category)}</span>
              <Badge label={`${Math.round(featuredRecommendation.confidence * 100)}%`} tone="green" />
            </div>
            <div className="mt-0.5 text-[12px] text-[#5C7A8A]">
              {featuredRecommendation.reasoning}
            </div>
          </div>
          <button className="inline-flex shrink-0 items-center gap-1.5 rounded-[8px] bg-[#E8654A] px-4 py-2 text-[12px] font-semibold text-white transition-colors hover:bg-[#D4573E]">
            <SymbolIcon icon="shopping_cart" family="rounded" className="text-[16px]" />
            Purchase
          </button>
        </div>


        {/* ── Bottom panels ── */}
        <div className="grid min-h-0 flex-1 gap-4 xl:grid-cols-2">

          {/* ── Inventory Health — Dolls trend chart ── */}
          <CardPanel className="flex min-h-[420px] flex-col">
            <div className="flex items-center justify-between px-6 py-5">
              <h2 className="text-[16px] font-semibold leading-[1.4] text-[#1B3A4B]">Inventory Health</h2>
              <Badge label="14-day view" tone="blue" />
            </div>

            <div className="mx-6 mb-3 flex items-end justify-between">
              <div>
                <div className="text-[11px] font-semibold uppercase tracking-[0.06em] text-[#D4870E]">Trending Item</div>
                <div className="mt-0.5 text-[18px] font-semibold text-[#1B3A4B]">Dolls — Daily Sales</div>
              </div>
              <div className="text-right">
                <span className="font-mono text-[24px] font-bold text-[#2D8A6E]">+27%</span>
                <div className="text-[10px] text-[#9AAFBC]">vs. prior 14 days</div>
              </div>
            </div>

            <div className="px-4">
              <SalesChart />
            </div>

            <div className="mt-auto border-t border-[#E8D4C6] px-6 py-3">
              <div className="mb-2 text-[11px] font-semibold uppercase tracking-[0.06em] text-[#9AAFBC]">Other categories</div>
              <div className="grid grid-cols-2 gap-x-6 gap-y-1">
                {OTHER_ITEMS.map((item) => (
                  <div key={item.name} className="flex items-center justify-between py-1">
                    <span className="text-[12px] text-[#5C7A8A]">{item.name}</span>
                    <div className="flex items-center gap-2">
                      <span className="font-mono text-[11px] text-[#9AAFBC]">{item.units}u</span>
                      <span className={`font-mono text-[11px] font-semibold ${item.trend >= 0 ? 'text-[#2D8A6E]' : 'text-[#D14D4D]'}`}>
                        {item.trend >= 0 ? '+' : ''}{item.trend}%
                      </span>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </CardPanel>

          {/* ── Live Agent Chat ── */}
          <CardPanel className="flex min-h-[420px] flex-col">
            <div className="flex items-center justify-between px-6 py-5">
              <h2 className="text-[16px] font-semibold leading-[1.4] text-[#1B3A4B]">Live Agent Chat</h2>
              <div className="flex items-center gap-1.5">
                <span className="h-2 w-2 animate-pulse rounded-full bg-[#2D8A6E]" />
                <span className="text-[12px] text-[#2D8A6E]">Live</span>
              </div>
            </div>
            <AgentChat />
          </CardPanel>
        </div>
      </div>
    </AppShell>
  );
}
