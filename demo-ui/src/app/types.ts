export type StockRow = {
  variant_id: string; sku: string; name: string; barcode: string | null; status: string;
  on_hand: string | null; incoming_confirmed: string; incoming_unconfirmed: string; daily_demand: string | null;
  days_of_cover: string | null; stockout_date: string | null; state: 'out_of_stock' | 'at_risk' | 'ok' | 'no_sales_data' | 'no_stock_data';
  plan_status: string; stock_as_of: string | null; stock_source: string | null; stock_age_hours: string | null;
  stale: boolean; estimated: boolean; stock_counted: boolean; sales_through: string | null; history_days: number;
};
export type Overview = { location_id: string; stock_owner: string; today: string; computed_at: string; counts: Record<string, number>; items: StockRow[] };

export type History = {
  sales: { date: string; units: string | null; covered: boolean }[];
  movements: { id: string; at: string; reason: string; delta: string; source: string; note: string | null; by: string | null; undo_of: string | null }[];
  pos_readings: { at: string; qty: string; source: string }[];
  orders: { po_id: string; number: string; status: string; ordered: string; outstanding: string; unconfirmed: string; unit: string; eta: string | null }[];
  projection: { day: number; date: string; start: string; demand: string; short: string; arriving: string }[];
};

type Period = { from: string; to: string; days: number; days_with_data: number; units: string | null; revenue: string | null; sales_without_price: number };
type ItemSales = { variant_id: string; sku: string; name: string; units: string; previous_units: string; on_hand: string | null };
export type Analytics = {
  days: number; current: Period; previous: Period; daily: { date: string; units: string | null }[]; has_data: boolean;
  top_sellers: ItemSales[]; slow_movers: ItemSales[]; stockouts_ahead: StockRow[]; sales_through: string | null;
};

export type Readiness = {
  facts: { products: number; stock_readings: number; sales_days: number; approved_suppliers: number; priced_items: number; ship_to_address: boolean };
  features: { key: string; label: string; ready: boolean; missing: { what: string; how: string }[]; partial: string | null }[];
};

export type Lookup = {
  found: boolean; code: string; variant_id?: string; sku?: string; name?: string; barcode?: string | null; status?: string; version?: number;
  stock?: StockRow | null; stock_owner?: string; expected_orders?: { po_id: string; number: string; line_no: number; expected: string; unit: string }[];
};

export type StockAction = { id: string; at: string; sku: string; name: string; delta: string; reason: string; note: string | null; by: string | null; is_undo: boolean; undone: boolean };
