// Client for the Tabula product API (/v1). Everything shown in the operations
// screens comes from here — no bundled demo data.

const SESSION_KEY = 'tabula.session.v1';

export type Session = { user: string; tenantId: string; tenantName: string; locationId?: string };

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
    /* private mode: the session simply isn't remembered */
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
  const h: Record<string, string> = { ...extra };
  if (session?.user) h['X-Dev-User'] = session.user;
  if (session?.tenantId) h['X-Tenant-Id'] = session.tenantId;
  return h;
}

async function handle<T>(res: Response): Promise<T> {
  const text = await res.text();
  const body = text ? JSON.parse(text) : null;
  if (!res.ok) {
    const detail = body?.detail;
    const message = typeof detail === 'string' ? detail : Array.isArray(detail) ? detail.map((d) => d.msg).join('; ') : res.statusText;
    throw new ApiError(res.status, message, body?.details);
  }
  return body as T;
}

export async function api<T>(path: string, init: { method?: string; body?: unknown; userOverride?: string } = {}): Promise<T> {
  const session = loadSession();
  const h = headers({ 'Content-Type': 'application/json' }, init.userOverride ? { user: init.userOverride, tenantId: '', tenantName: '' } : session);
  const res = await fetch(`/v1${path}`, {
    method: init.method ?? (init.body ? 'POST' : 'GET'),
    headers: h,
    body: init.body ? JSON.stringify(init.body) : undefined,
  });
  return handle<T>(res);
}

export async function upload<T>(path: string, form: FormData): Promise<T> {
  const res = await fetch(`/v1${path}`, { method: 'POST', headers: headers(), body: form });
  return handle<T>(res);
}

// ---------------------------------------------------------------- types

export type Me = { user_id: string; email: string; memberships: { tenant_id: string; tenant_name: string; role: string }[] };
export type Location = {
  id: string; name: string; timezone: string; inventory_write_owner: string;
  address_line1: string | null; city: string | null; region: string | null; postal_code: string | null; country: string | null;
};
export type Reason = { code: string; message: string; [k: string]: unknown };
export type Step = { label: string; value: string; formula?: string };
export type ProjectionDay = { day: number; date: string; start: string; demand: string; short: string; arriving: string };
export type PlanLine = {
  variant_id: string; sku: string; status: string; needs_review: boolean;
  order_qty: string; order_uom: string | null; base_qty: string; line_cost: string | null; currency: string | null;
  supplier: string | null; supplier_item_id: string | null; on_hand: string | null; open_po: string | null;
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
};

export type ImportRecord = {
  id: string; kind: string; status: string; file_name: string; row_count: number; mapping_revision: number;
  mapping: { columns: Record<string, string>; settings: Record<string, unknown> }; header: string[];
  summary: Record<string, unknown>; failure: string | null; created_at: string; context: Record<string, string>;
};
export type Preview = {
  mapping_revision: number; blocking_issues: string[]; declared_settings: Record<string, unknown>;
  counts: { rows: number; valid: number; with_errors: number; with_warnings: number } | null;
  fields: { name: string; label: string; required: boolean }[];
  rows: { row_number: number; interpretation: string; errors: { column: string; message: string }[]; warnings: { message: string }[] }[];
};
