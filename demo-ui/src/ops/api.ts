// Client for the Tabula product API (/v1). Everything shown in the operations
// screens comes from here — no bundled demo data.

const SESSION_KEY = 'tabula.session.v1';

// Which store this browser is working in. Who you are comes from the HttpOnly session cookie
// (email + password account); `user` is set only for the email-only demo sign-in on a developer's machine.
export type Session = { tenantId: string; tenantName: string; locationId?: string; isSample?: boolean; user?: string };

export function loadSession(): Session | null {
  try {
    const raw = localStorage.getItem(SESSION_KEY);
    return raw ? (JSON.parse(raw) as Session) : null;
  } catch {
    return null;
  }
}

export function saveSession(session: Session | null) {
  try {
    if (session) localStorage.setItem(SESSION_KEY, JSON.stringify(session));
    else localStorage.removeItem(SESSION_KEY);
  } catch {
    /* private mode: the store choice simply isn't remembered */
  }
}

export class ApiError extends Error {
  status: number;
  details: unknown;
  constructor(status: number, message: string, details?: unknown) {
    super(message);
    this.status = status;
    this.details = details;
  }
}

function headers(extra?: Record<string, string>, session = loadSession()): Record<string, string> {
  const h: Record<string, string> = { 'X-Tabula-Client': 'web', ...extra };
  if (session?.user) h['X-Dev-User'] = session.user;
  if (session?.tenantId) h['X-Tenant-Id'] = session.tenantId;
  return h;
}

async function handle<T>(res: Response): Promise<T> {
  const text = await res.text();
  let body: any = null;
  try { body = text ? JSON.parse(text) : null; } catch { body = null; }
  if (!res.ok) {
    const detail = body?.detail;
    const message = typeof detail === 'string' ? detail : Array.isArray(detail) ? detail.map((d: any) => d.msg).join('; ')
      : res.status >= 500 ? 'Something went wrong on our side. Try again in a moment.' : res.statusText;
    throw new ApiError(res.status, message, body?.details);
  }
  return body as T;
}

export async function api<T>(path: string, init: { method?: string; body?: unknown; userOverride?: string; noTenant?: boolean } = {}): Promise<T> {
  const session = loadSession();
  const h = headers(init.body !== undefined ? { 'Content-Type': 'application/json' } : {},
    init.userOverride ? { user: init.userOverride, tenantId: '', tenantName: '' } : init.noTenant ? { ...session!, tenantId: '' } as Session : session);
  const res = await fetch(`/v1${path}`, {
    method: init.method ?? (init.body !== undefined ? 'POST' : 'GET'),
    headers: h,
    credentials: 'same-origin',
    body: init.body !== undefined ? JSON.stringify(init.body) : undefined,
  });
  return handle<T>(res);
}

export async function upload<T>(path: string, form: FormData): Promise<T> {
  const res = await fetch(`/v1${path}`, { method: 'POST', headers: headers(), body: form, credentials: 'same-origin' });
  return handle<T>(res);
}

// ---------------------------------------------------------------- types

export type Membership = { tenant_id: string; tenant_name: string; role: string; business_type: string | null; currency: string; is_sample: boolean };
export type Me = { user_id: string; email: string; memberships: Membership[] };
export type Location = {
  id: string; name: string; timezone: string; inventory_write_owner: string;
  address_line1: string | null; city: string | null; region: string | null; postal_code: string | null; country: string | null;
  sales_feed: 'files' | 'square'; sales_feed_since: string | null;
};
export type Reason = { code: string; message: string; [k: string]: unknown };
export type Step = { label: string; value: string; formula?: string };
export type ProjectionDay = { day: number; date: string; start: string; demand: string; short: string; arriving: string };
export type PlanLine = {
  variant_id: string; sku: string; status: string; needs_review: boolean;
  order_qty: string; order_uom: string | null; base_qty: string; line_cost: string | null; currency: string | null;
  supplier: string | null; supplier_item_id: string | null; on_hand: string | null; open_po: string | null; pos_pending: string[];
  arrival: { order_date: string | null; delivery_date: string | null; usable_date: string | null } | null;
  daily_demand: string | null; target: string | null; position: string | null; need: string | null;
  need_before_held: string | null; held_qty: string | null;
  stockout_days: number[]; stockout_days_without_order: number[];
  reasons: Reason[]; steps: Step[]; projection: ProjectionDay[];
  data_as_of: { stock: string | null; stock_source: string | null; sales_through: string | null; price: string | null };
};
export type Plan = {
  id: string; status: string; cutoff: string; planning_date: string; computed_at: string;
  policy_version: number; engine_version: string; input_digest: string; data_version: number;
  summary: { lines: Record<string, number>; needs_review: number };
  plan_notes: Record<string, unknown>[];
  lines: PlanLine[];
};
export type Recommendations = { location_id: string; stale: boolean; stale_reasons: string[]; pending_updates?: string[]; run: Plan | null };

export type PoSummary = {
  id: string; number: string; status: string; revision: number; supplier: string; ship_to: string; currency: string;
  lines: number; estimated_total: string; needs_attention: boolean; created_at: string; updated_at: string;
  ack_status: string; sent_at: string | null; awaiting_reply: boolean; expected_lines: number; open_issues: number;
  /** Supplier's date when they gave one, otherwise the lead-time estimate. */
  expected_at: string | null; expected_source: 'supplier' | 'lead_time' | null;
};
export type PoLine = {
  line_no: number; sku: string; name: string; supplier_sku: string; order_uom: string; units_per_order_uom: string;
  order_multiple: string; min_order_qty: string; order_qty: string; base_qty: string; unit_price: string; line_total: string;
  price: { id: string; type: string; source: string | null; valid_from: string; basis: string } | null;
  recommendation: {
    order_qty?: string; on_hand?: string; stock_as_of?: string; daily_demand?: string; target?: string; position?: string;
    need?: string; need_before_held?: string; held_qty?: string; stockout_days?: number[]; steps?: Step[]; reasons?: Reason[];
    status?: string; stock_source?: string; sales_through?: string; order_date?: string | null; delivery_date?: string | null;
    usable_date?: string | null;
  };
  edited: boolean; blockers: string[];
};
export type PoDetail = PoSummary & {
  digest: string;
  content: {
    po_number: string; currency: string;
    supplier: { name: string; account_number: string | null; order_email: string | null; payment_terms: string; status: string };
    ship_to: { name: string; complete: boolean };
    address_text: string;
    lines: PoLine[];
    totals: { subtotal: string; estimated_total: string; estimate_note: string;
      shipping: { status: string; note: string | null }; tax: { status: string } };
    notices: Reason[]; blockers: string[];
  };
  data: { checked_version: number; current_version: number; changed_since_check: boolean; pending_updates: string[] };
  send_job: { status: string; attempts: number; last_error: string | null } | null;
  approvals: { revision: number; digest: string; by: string; role: string; at: string }[];
  send_attempts: { revision: number; mode: string; recipient: string | null; outcome: string; detail: string | null; at: string }[];
  captured_message: { to: string; subject: string; body: string; attachment_name: string; attachment_csv: string;
    revision: number; at: string; note: string } | null;
  revisions: { revision: number; reason: string | null; at: string; by: string; total: string }[];
  history: { action: string; by: string; at: string; reason: string | null }[];
  progress: Progress | null;
};

export type Proposal = {
  kind: 'price' | 'pack' | 'substitute' | 'qty_increase'; digest: string; reply_id: string; eta: string | null;
  unit_price?: string; units_per_order_uom?: string; substitute_sku?: string; qty?: string;
  was: { unit_price: string; units_per_order_uom: string; supplier_sku: string; ordered_qty: string };
};
export type ProgressLine = {
  line_no: number; sku: string; supplier_sku: string; order_uom: string; units_per_order_uom: string; unit_price: string;
  ordered: string; confirmed: string | null; rejected: string; cancelled: string; received: string; damaged: string;
  sellable_received: string; replacement: string; unconfirmed: string; outstanding: string; eta: string | null;
  proposal: Proposal | null; replaces_line_no: number | null; pos_pending: string[];
};
export type ReplyReading = {
  line_no: number; sku: string; supplier_sku: string; action: string; confirmed_qty: string | null; eta: string | null;
  backorder: boolean; change: { kind: string; unit_price?: string; units_per_order_uom?: string; substitute_sku?: string; qty?: string } | null;
  evidence: { line: number; text: string }[];
};
export type Reply = {
  id: string; source: string; file_name: string | null; status: string; replied_at: string; recorded_at: string; raw_text: string;
  parsed: { format: string; lines: ReplyReading[]; warnings: string[]; replied_at_source?: string };
  applied: { decisions: unknown[] } | null;
};
export type Progress = {
  sent_at: string | null; ack_status: string; last_reply_at: string | null; lines: ProgressLine[]; replies: Reply[];
  receipts: { id: string; receipt_key: string; received_at: string; notes: string | null;
    lines: { id: string; line_no: number; arrived: string; damaged: string; sellable_units: string; pos_status: string }[] }[];
  issues: { id: string; line_no: number; kind: string; qty: string; status: string; resolution_qty: string | null;
    resolution_eta: string | null; note: string | null }[];
};

export type ImportRecord = {
  id: string; kind: string; status: string; file_name: string; row_count: number; mapping_revision: number;
  mapping: { columns: Record<string, string>; settings: Record<string, unknown> }; header: string[];
  summary: Record<string, unknown>; failure: string | null; created_at: string; context: Record<string, string>;
};
export type Preview = {
  mapping_revision: number; blocking_issues: string[]; declared_settings: Record<string, unknown>;
  suggested_settings?: { period_start?: string; period_end?: string; note?: string };
  counts: { rows: number; valid: number; with_errors: number; with_warnings: number } | null;
  fields: { name: string; label: string; required: boolean }[];
  rows: { row_number: number; interpretation: string; errors: { column: string; message: string }[]; warnings: { message: string }[] }[];
};

export type AttentionItem = {
  kind: string; severity: 'high' | 'medium' | 'low'; title: string; why: string; action: string; href: string;
  ref?: string; supplier_id?: string; external_po_number?: string; candidates?: string[];
};
export type OpenOrderLinkView = {
  supplier_id: string; supplier: string | null; external_po_number: string;
  status: 'linked_exact' | 'linked_by_person' | 'separate_by_person' | 'suggested' | 'separate';
  po_number: string | null; candidates: { po_id: string; number: string; status: string }[];
  lines: { sku: string | null; outstanding: string; confirmed: boolean }[];
};
export type PosEvidence = {
  source: string; received_at: string; reported_entered_at: string | null; this_receipt_units: string;
  reading_before: { qty: string; at: string } | null; reading_after: { qty: string; at: string } | null;
  latest_reading: { qty: string; at: string } | null;
  window?: { from: string; to: string }; units_received_in_window?: string; units_sold?: string;
  refunds_restocked?: string; refunds_restock_unknown?: string; expected_after?: string; unexplained?: string;
  assessment: string; explanation: string;
};
export type ConnectorAccount = {
  id: string; provider: string; environment: string; merchant_id: string; display_name: string | null; status: string;
  token_expires_at: string | null; last_success_at: string | null; last_error: string | null;
  sync_state: { sales_synced_through?: string; token_refreshed_at?: string;
    reconciliations?: { at: string; window: string; recovered_sales_lines: number; unmapped_items: number; stock_readings: number }[] };
  locations: { external_location_id: string; location_id: string }[];
};
export type DevInfo = { environment: string; auth_mode: string; send_mode: string; square_environment: string };
export type VariantLite = { id: string; sku: string; name: string; barcode: string | null; version: number; status: string };
