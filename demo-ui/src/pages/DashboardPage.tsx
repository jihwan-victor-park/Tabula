import { useEffect, useRef, useState } from 'react';
import { AppShell, Badge, CardPanel, Sidebar, SymbolIcon } from '../components/ui';
import {
  createInitials,
  dashboardSidebar,
  debateMessages,
  ecosystemHealth,
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

/* ── Live Agent Chat — replays debate_log.json from Nous Hermes pipeline ── */

type DebateMessage = {
  round: number;
  store_id: string;
  store_name: string;
  argument: string;
  timestamp: string;
};

const STORE_COLORS: Record<string, { color: string; bg: string }> = {
  store_a: { color: 'text-[#E8654A]', bg: 'bg-[#E8654A]' },
  store_b: { color: 'text-[#2D8A6E]', bg: 'bg-[#2D8A6E]' },
  store_c: { color: 'text-[#D4870E]', bg: 'bg-[#D4870E]' },
  store_d: { color: 'text-[#7B68B0]', bg: 'bg-[#7B68B0]' },
  store_e: { color: 'text-[#3B82F6]', bg: 'bg-[#3B82F6]' },
};

const FALLBACK_DEBATE: DebateMessage[] = [
  { round: 0, store_id: 'store_a', store_name: 'College Convenience & Deli', argument: 'Yale finals week is coming — energy drinks and grab-and-go meals always spike when students are cramming at Bass Library.', timestamp: '' },
  { round: 0, store_id: 'store_b', store_name: 'Grails', argument: 'Agreed. Every Yale semester end we see streetwear resale pick up — students want fresh fits before heading home for summer.', timestamp: '' },
  { round: 0, store_id: 'store_c', store_name: 'Edible Arrangements', argument: 'Yale commencement is the real driver for us. Parents flood New Haven for graduation — gift basket demand goes through the roof.', timestamp: '' },
  { round: 0, store_id: 'store_d', store_name: 'Tinaliah Designs', argument: 'Custom Yale-themed jewelry is trending for graduation gifts. Personalized class rings and "Y" pendants are our hottest items right now.', timestamp: '' },
  { round: 0, store_id: 'store_e', store_name: 'The Marketa', argument: 'Winter stock is still sitting. With Yale spring events ramping up, we should clear old inventory and pivot to graduation and Bulldog Days traffic.', timestamp: '' },
  { round: 1, store_id: 'store_a', store_name: 'College Convenience & Deli', argument: 'Good call on pivoting. But Yale students stress-eat through April — I\'m keeping comfort food stocked until reading period ends.', timestamp: '' },
  { round: 1, store_id: 'store_b', store_name: 'Grails', argument: 'I\'m with The Marketa. If it didn\'t sell during Yale\'s winter semester, it won\'t move now. Time to make room for spring drops.', timestamp: '' },
  { round: 1, store_id: 'store_c', store_name: 'Edible Arrangements', argument: 'The aggregated signal shows gifts trending up across all of us near Yale. Strong consensus — lean into graduation gifting hard.', timestamp: '' },
  { round: 1, store_id: 'store_d', store_name: 'Tinaliah Designs', argument: 'True, but foot traffic varies block by block. Chapel Street near Yale gets way more walk-ins than Audubon — the data might smooth that out.', timestamp: '' },
  { round: 1, store_id: 'store_e', store_name: 'The Marketa', argument: 'Exactly. Use the shared New Haven trends for big-picture calls, but trust your own street-level data for the specifics.', timestamp: '' },
  { round: 2, store_id: 'store_a', store_name: 'College Convenience & Deli', argument: 'Consensus: stock up for Yale finals and commencement, clear winter leftovers, and trust local signals for block-by-block decisions.', timestamp: '' },
  { round: 2, store_id: 'store_b', store_name: 'Grails', argument: 'Works for me. The privacy-preserving aggregation showed us the New Haven macro trend without anyone revealing their actual numbers.', timestamp: '' },
  { round: 2, store_id: 'store_c', store_name: 'Edible Arrangements', argument: 'Yale graduation gifting is the signal I needed. Placing bulk fruit orders this week — families are already booking hotels in New Haven.', timestamp: '' },
  { round: 2, store_id: 'store_d', store_name: 'Tinaliah Designs', argument: 'Great debate. I\'ll push Yale-themed custom pieces and scale back winter lines. Five stores sharing insights makes us all smarter.', timestamp: '' },
  { round: 2, store_id: 'store_e', store_name: 'The Marketa', argument: 'This is what makes the Yale/New Haven small business ecosystem work — we compete on products but collaborate on intelligence. Next cycle!', timestamp: '' },
];

function getInitials(name: string): string {
  return name.split(' ').map(w => w[0]).join('').slice(0, 2).toUpperCase();
}

function AgentChat() {
  const [messages, setMessages] = useState<{ id: number; storeId: string; storeName: string; text: string; round: number; time: string }[]>([]);
  const debateData = debateMessages.length > 0 ? debateMessages : FALLBACK_DEBATE;
  const nextIdx = useRef(0);
  const nextId = useRef(0);
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    nextIdx.current = 0;
    nextId.current = 0;
    setMessages([]);

    const now = () => new Date().toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit' });

    const batch: typeof messages = [];
    for (let i = 0; i < Math.min(3, debateData.length); i++) {
      const msg = debateData[i]!;
      batch.push({ id: nextId.current++, storeId: msg.store_id, storeName: msg.store_name, text: msg.argument, round: msg.round, time: now() });
      nextIdx.current++;
    }
    setMessages(batch);

    const id = window.setInterval(() => {
      if (nextIdx.current >= debateData.length) {
        nextIdx.current = 0;
      }
      const msg = debateData[nextIdx.current]!;
      nextIdx.current++;
      setMessages(prev => [
        ...prev.slice(-25),
        { id: nextId.current++, storeId: msg.store_id, storeName: msg.store_name, text: msg.argument, round: msg.round, time: now() },
      ]);
    }, 2800);

    return () => window.clearInterval(id);
  }, []);

  useEffect(() => {
    const el = scrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [messages]);

  const currentRound = messages.length > 0 ? messages[messages.length - 1]!.round + 1 : 0;

  return (
    <div className="flex flex-1 flex-col overflow-hidden">
      {/* Round indicator */}
      <div className="flex items-center gap-2 border-b border-[#E8D4C6] px-4 py-2">
        <span className="font-mono text-[10px] uppercase tracking-wider text-[#9AAFBC]">Debate Round {currentRound}</span>
        <span className="font-mono text-[10px] text-[#5C7A8A]">· Powered by Nous Hermes</span>
      </div>

      <div ref={scrollRef} className="flex-1 space-y-3 overflow-y-auto px-4 pb-4 pt-2">
        {messages.map((msg, i) => {
          const colors = STORE_COLORS[msg.storeId] || { color: 'text-[#5C7A8A]', bg: 'bg-[#5C7A8A]' };
          const isLeft = i % 2 === 0;

          return (
            <div key={msg.id} className={`flex items-end gap-2 ${isLeft ? 'justify-start' : 'justify-end'}`}>
              {isLeft && (
                <div className={`flex h-7 w-7 shrink-0 items-center justify-center rounded-full text-[10px] font-bold text-white ${colors.bg}`}>
                  {getInitials(msg.storeName)}
                </div>
              )}
              <div className="max-w-[75%] text-left">
                <div className={`mb-1 text-[10px] font-semibold ${colors.color}`}>
                  {msg.storeName}
                </div>
                <div
                  className={[
                    'rounded-[14px] bg-[#FDF5EF] px-3.5 py-2.5 text-left text-[12.5px] leading-[1.5] text-[#1B3A4B]',
                    isLeft ? 'rounded-bl-[4px]' : 'rounded-br-[4px]',
                  ].join(' ')}
                >
                  {msg.text}
                </div>
                <div className={`mt-1 font-mono text-[9px] text-[#9AAFBC] ${isLeft ? '' : 'text-right'}`}>{msg.time}</div>
              </div>
              {!isLeft && (
                <div className={`flex h-7 w-7 shrink-0 items-center justify-center rounded-full text-[10px] font-bold text-white ${colors.bg}`}>
                  {getInitials(msg.storeName)}
                </div>
              )}
            </div>
          );
        })}
      </div>
      <div className="flex items-center gap-2 border-t border-[#E8D4C6] px-4 py-3">
        <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-[#2D8A6E]" />
        <span className="text-[11px] text-[#9AAFBC]">
          {debateData.length} debate messages · {new Set(debateData.map(m => m.store_name)).size} agents · Nous Hermes 4
        </span>
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

            <div className="mt-8 px-4">
              <SalesChart />
            </div>

            <div className="border-t border-[#E8D4C6] px-6 py-3">
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
            <div className="border-t border-[#E8D4C6] px-6 py-2">
              <div className="flex items-center justify-between">
                <span className="text-[11px] font-semibold uppercase tracking-[0.06em] text-[#9AAFBC]">Hex Analytics</span>
                <div className="flex items-center gap-2">
                  <span className="font-mono text-[11px] text-[#9AAFBC]">ecosystem</span>
                  <span className="font-mono text-[11px] font-semibold text-[#2D8A6E]">{Math.round(ecosystemHealth.overall_health)}/100</span>
                </div>
              </div>
            </div>
            <div className="border-t border-[#E8D4C6] px-6 py-3">
              <div className="mb-2 text-[11px] font-semibold uppercase tracking-[0.06em] text-[#9AAFBC]">Suggested Actions</div>
              <div className="space-y-1.5">
                <div className="flex items-start gap-2">
                  <span className="mt-0.5 text-[11px] text-[#2D8A6E]">•</span>
                  <span className="text-[12px] text-[#5C7A8A]">Stock up on grab-and-go meals and energy drinks before Yale finals week hits</span>
                </div>
                <div className="flex items-start gap-2">
                  <span className="mt-0.5 text-[11px] text-[#D4870E]">•</span>
                  <span className="text-[12px] text-[#5C7A8A]">Clear winter inventory now — redirect shelf space toward graduation gifting</span>
                </div>
                <div className="flex items-start gap-2">
                  <span className="mt-0.5 text-[11px] text-[#E8654A]">•</span>
                  <span className="text-[12px] text-[#5C7A8A]">Partner with nearby stores on a Yale commencement bundle deal</span>
                </div>
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
