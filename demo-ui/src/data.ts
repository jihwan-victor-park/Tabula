import groupChatData from '../../output/group_chat.json';
import resultsData from '../../output/results.json';
import debateLogRaw from '../../output/debate_log.json';
import ecosystemHealthRaw from '../../output/ecosystem_health.json';
import type { NavSection } from './components/ui';

export const debateMessages: Array<{ round: number; store_id: string; store_name: string; argument: string; timestamp: string }> =
  (debateLogRaw as any)?.messages ?? [];

export const ecosystemHealth = ecosystemHealthRaw as {
  overall_health: number;
  consensus_strength: number;
  signal_diversity: number;
  anomaly_count: number;
  anomalous_signals: Array<{ signal_id: string; category: string; intensity: number; z_score: number; category_mean: number; flag: string }>;
  collaboration_value: number;
  category_alignment: Record<string, number>;
  participation_rate: number;
  hex_enabled: boolean;
  hex_run_id: string | null;
  hex_run_url: string | null;
};

type MarketTrend = (typeof resultsData.market_trends)[number];
type StoreResult = (typeof resultsData.store_results)[number];
type Recommendation = StoreResult['recommendations'][number];
type GroupChatMessage = {
  kind: 'message';
  phase: string;
  sender: string;
  text: string;
  timestamp: string;
};

type Tone = 'blue' | 'green' | 'yellow' | 'red';

const timeFormatter = new Intl.DateTimeFormat('en-US', {
  month: 'short',
  day: 'numeric',
  hour: 'numeric',
  minute: '2-digit',
});

const shortTimeFormatter = new Intl.DateTimeFormat('en-US', {
  hour: 'numeric',
  minute: '2-digit',
});

const storeNameById = Object.fromEntries(
  resultsData.store_results.map((store) => [store.store_id, store.store_name]),
);

const directionOrder: Record<MarketTrend['direction'], number> = {
  rising: 0,
  stable: 1,
  falling: 2,
};

export function formatCategory(category: string) {
  return category
    .split('_')
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(' ');
}

export function formatAction(action: string) {
  return action
    .split('_')
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(' ');
}

export function formatTimestamp(timestamp: string) {
  return timeFormatter.format(new Date(timestamp));
}

export function formatShortTime(timestamp: string) {
  return shortTimeFormatter.format(new Date(timestamp));
}

export function createInitials(name: string) {
  return name
    .split(/\s+/)
    .slice(0, 2)
    .map((part) => part.charAt(0).toUpperCase())
    .join('');
}

export function confidenceLabel(confidence: number) {
  return `${Math.round(confidence * 100)}%`;
}

export function directionTone(direction: MarketTrend['direction']): Tone {
  if (direction === 'rising') return 'green';
  if (direction === 'falling') return 'red';
  return 'blue';
}

export function priorityTone(priority: Recommendation['priority']): Tone {
  if (priority === 'high') return 'green';
  if (priority === 'medium') return 'yellow';
  return 'blue';
}

export function actionTone(action: Recommendation['action']): Tone {
  if (action === 'increase_stock' || action === 'promote') return 'green';
  if (action === 'reduce_stock' || action === 'discontinue') return 'red';
  return 'blue';
}

function trimReason(reasoning: string) {
  const [firstSentence] = reasoning.split('. ');
  return firstSentence.endsWith('.') ? firstSentence : `${firstSentence}.`;
}

function toneForSender(sender: string) {
  if (sender === 'coordinator') return 'blue' as const;
  if (sender === 'privacy_shield') return 'green' as const;
  return 'dark' as const;
}

export const cycleId = resultsData.cycle_id;
export const scenario = resultsData.scenario;
export const generatedAt = resultsData.generated_at;
export const formattedGeneratedAt = formatTimestamp(resultsData.generated_at);
export const storeCount = resultsData.store_results.length;
export const categoryCount = resultsData.market_trends.length;

export const marketTrends = [...resultsData.market_trends].sort((left, right) => {
  if (directionOrder[left.direction] !== directionOrder[right.direction]) {
    return directionOrder[left.direction] - directionOrder[right.direction];
  }

  return right.strength - left.strength;
});

export const storeResults = resultsData.store_results;
export const featuredStore = storeResults[0];
export const featuredRecommendation = featuredStore.recommendations[0];
export const risingTrendCount = marketTrends.filter((trend) => trend.direction === 'rising').length;

export const recommendationRows = storeResults.flatMap((store) =>
  store.recommendations.map((recommendation, index) => {
    const relatedTrend =
      marketTrends.find((trend) => trend.category === recommendation.category) ?? marketTrends[0];

    return {
      id: `${store.store_id}-${recommendation.category}-${index}`,
      storeId: store.store_id,
      storeName: store.store_name,
      category: recommendation.category,
      categoryLabel: formatCategory(recommendation.category),
      action: recommendation.action,
      actionLabel: formatAction(recommendation.action),
      reasoning: recommendation.reasoning,
      shortReasoning: trimReason(recommendation.reasoning),
      confidence: recommendation.confidence,
      confidenceLabel: confidenceLabel(recommendation.confidence),
      priority: recommendation.priority,
      priorityLabel:
        recommendation.priority.charAt(0).toUpperCase() + recommendation.priority.slice(1),
      trendDirection: relatedTrend.direction,
      trendDirectionLabel:
        relatedTrend.direction.charAt(0).toUpperCase() + relatedTrend.direction.slice(1),
      trendStrength: relatedTrend.strength,
      consensus: relatedTrend.consensus,
      updatedAt: store.generated_at,
      updatedLabel: formatTimestamp(store.generated_at),
    };
  }),
);

export const totalRecommendations = recommendationRows.length;
export const highPriorityCount = recommendationRows.filter(
  (row) => row.priority === 'high',
).length;
export const averageConfidence = Math.round(
  recommendationRows.reduce((sum, row) => sum + row.confidence, 0) /
    recommendationRows.length *
    100,
);

export const trendCards = marketTrends.map((trend) => ({
  ...trend,
  categoryLabel: formatCategory(trend.category),
  strengthLabel: `${Math.round(trend.strength * 100)}%`,
  directionLabel: trend.direction.charAt(0).toUpperCase() + trend.direction.slice(1),
  blurb:
    trend.direction === 'rising'
      ? `${formatCategory(trend.category)} is climbing across ${trend.signal_count} store signals with ${trend.consensus} consensus.`
      : trend.direction === 'falling'
        ? `${formatCategory(trend.category)} is softening, so stores are shifting spend toward stronger categories.`
        : `${formatCategory(trend.category)} is holding steady with ${trend.consensus} agreement across the network.`,
  impactedStores: recommendationRows.filter((row) => row.category === trend.category).length,
}));

export const featuredTrend = trendCards[0];
export const featuredTrendRecommendations = recommendationRows
  .filter((row) => row.category === featuredTrend.category)
  .sort((left, right) => right.confidence - left.confidence)
  .slice(0, 5);

export const conversationMessages = (groupChatData.entries as Array<GroupChatMessage | { kind: string }>)
  .filter((entry): entry is GroupChatMessage => entry.kind === 'message')
  .map((entry) => ({
    id: `${entry.sender}-${entry.timestamp}`,
    senderId: entry.sender,
    senderName:
      entry.sender === 'coordinator'
        ? 'Coordinator'
        : entry.sender === 'privacy_shield'
          ? 'Privacy Shield'
          : storeNameById[entry.sender] ?? formatCategory(entry.sender),
    body: entry.text,
    align: entry.sender === 'coordinator' ? ('right' as const) : ('left' as const),
    tone: toneForSender(entry.sender),
    time: formatShortTime(entry.timestamp),
    phase: entry.phase,
  }));

export const recentActivity = [...conversationMessages]
  .slice(-5)
  .reverse()
  .map((message) => ({
    ...message,
    icon:
      message.senderId === 'coordinator'
        ? 'insights'
        : message.senderId === 'privacy_shield'
          ? 'shield_lock'
          : 'forum',
  }));

const privacyEntry = conversationMessages.find((message) => message.senderId === 'privacy_shield');
const finalCoordinatorMessage = [...conversationMessages]
  .reverse()
  .find((message) => message.senderId === 'coordinator');

export const agentStatuses = [
  {
    name: 'Coordinator',
    status: finalCoordinatorMessage?.body.split('\n')[0] ?? 'Shared the nightly summary with every store.',
    time: finalCoordinatorMessage?.time ?? formatShortTime(resultsData.generated_at),
    tone: 'green' as const,
  },
  {
    name: 'Privacy Shield',
    status: privacyEntry?.body.split('\n')[0] ?? 'Anonymized store-level signals before aggregation.',
    time: privacyEntry?.time ?? formatShortTime(resultsData.generated_at),
    tone: 'green' as const,
  },
  {
    name: 'Trend Analyst',
    status: `Top signals: ${marketTrends
      .filter((trend) => trend.direction === 'rising')
      .slice(0, 3)
      .map((trend) => formatCategory(trend.category))
      .join(', ')}.`,
    time: formatShortTime(resultsData.generated_at),
    tone: 'green' as const,
  },
  {
    name: 'Recommendation Engine',
    status: `Delivered ${totalRecommendations} store-specific actions with ${averageConfidence}% average confidence.`,
    time: formatShortTime(resultsData.generated_at),
    tone: 'yellow' as const,
  },
];

export const inventoryRows = recommendationRows
  .slice()
  .sort((left, right) => {
    if (left.priority !== right.priority) {
      return left.priority === 'high' ? -1 : right.priority === 'high' ? 1 : 0;
    }

    return right.confidence - left.confidence;
  });

export const actionQueueRows = recommendationRows
  .slice()
  .sort((left, right) => right.confidence - left.confidence)
  .map((row) => ({
    ...row,
    status:
      row.priority === 'high'
        ? { label: 'Ready to act', tone: 'green' as const }
        : row.priority === 'medium'
          ? { label: 'Review this week', tone: 'yellow' as const }
          : { label: 'Watchlist', tone: 'blue' as const },
  }));

export const signalLedgerRows = marketTrends.map((trend) => ({
  ...trend,
  categoryLabel: formatCategory(trend.category),
  strengthLabel: `${Math.round(trend.strength * 100)}%`,
  directionLabel: trend.direction.charAt(0).toUpperCase() + trend.direction.slice(1),
  recommendedStoreCount: recommendationRows.filter((row) => row.category === trend.category).length,
}));

export const dashboardSidebar: {
  widthClass: string;
  sections: NavSection[];
  footerName: string;
  footerEmail: string;
} = {
  widthClass: 'w-full lg:w-[240px]',
  sections: [
    {
      title: 'Overview',
      items: [
        { label: 'Dashboard', icon: 'dashboard', href: '/dashboard', active: true },
        { label: 'Inventory', icon: 'inventory_2', href: '/inventory' },
        { label: 'Agentic Simulation', icon: 'smart_toy', href: '/agentic-simulation' },
        { label: 'Orders', icon: 'shopping_cart', href: '/orders' },
      ],
    },
    {
      title: 'Insights',
      items: [
        { label: 'Price Scout', icon: 'price_check', href: '/price-scout' },
        { label: 'Trends', icon: 'trending_up', href: '/trends' },
        { label: 'Settings', icon: 'settings' },
      ],
    },
  ],
  footerName: 'Sarah Chen',
  footerEmail: 'sarah@brightpens.com',
};

export const platformSidebar = (
  active:
    | 'dashboard'
    | 'agentic-simulation'
    | 'inventory'
    | 'orders'
    | 'price-scout'
    | 'trends'
    | 'sales-history',
  includeAgents = true,
): { widthClass: string; sections: NavSection[]; footerName: string; footerEmail: string } => {
  const items = [
    { label: 'Dashboard', icon: 'dashboard', href: '/dashboard', active: active === 'dashboard' },
    ...(includeAgents
      ? [
          {
            label: 'Agentic Simulation',
            icon: 'smart_toy',
            href: '/agentic-simulation',
            active: active === 'agentic-simulation',
          },
        ]
      : []),
    { label: 'Inventory', icon: 'inventory_2', href: '/inventory', active: active === 'inventory' },
    { label: 'Orders', icon: 'shopping_cart', href: '/orders', active: active === 'orders' },
    { label: 'Price Scout', icon: 'price_check', href: '/price-scout', active: active === 'price-scout' },
    { label: 'Trends', icon: 'trending_up', href: '/trends', active: active === 'trends' },
    {
      label: 'Sales History',
      icon: 'receipt_long',
      href: '/sales-history',
      active: active === 'sales-history',
    },
  ];

  return {
    widthClass: 'w-full lg:w-[240px]',
    sections: [{ title: 'Platform', items }],
    footerName: 'Sarah Chen',
    footerEmail: 'sarah@brightpens.com',
  };
};
