// Where an order stands and what the store has to do next — one place, so Overview and Orders agree.

import type { PoSummary } from '../ops/api';

export type Phase = 'review' | 'progress' | 'done';

export function phase(p: PoSummary): Phase {
  if (['draft', 'awaiting_approval', 'failed', 'changes_proposed', 'delivery_unknown'].includes(p.status)) return 'review';
  if (p.status === 'received' || (p.open_issues > 0 && p.status !== 'cancelled')) return 'review';
  if (['closed', 'cancelled'].includes(p.status)) return 'done';
  return 'progress';
}

/** The next step in words, and whether only the owner can take it. */
export function nextAction(p: PoSummary, role?: string): { label: string; owner?: boolean; to?: 'receive' } | null {
  switch (p.status) {
    case 'draft': return { label: 'Review and submit' };
    case 'awaiting_approval': return role === 'owner' ? { label: 'Approve', owner: true } : { label: 'Waiting for the owner' };
    case 'failed': return { label: 'Fix and approve again' };
    case 'queued': return { label: 'Sending…' };
    case 'delivery_unknown': return { label: 'Check with the supplier' };
    case 'changes_proposed': return { label: 'Decide on the changes' };
    case 'test_sent': return p.awaiting_reply ? { label: "Record the supplier's answer" } : { label: 'Record the delivery', to: 'receive' };
    case 'supplier_confirmed':
    case 'partially_received': return { label: 'Record the delivery', to: 'receive' };
    case 'received': return { label: 'Resolve delivery issues', to: 'receive' };
    default: return p.open_issues > 0 ? { label: 'Resolve delivery issues', to: 'receive' } : null;
  }
}
