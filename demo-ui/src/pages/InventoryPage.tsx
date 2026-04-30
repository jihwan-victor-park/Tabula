import { useEffect, useRef, useState } from 'react';
import { AppShell, Badge, Sidebar, SymbolIcon } from '../components/ui';
import { platformSidebar } from '../data';

const SCANNER_URL_KEY = 'clawbot_scanner_url';
const DEFAULT_SCANNER_URL = 'http://localhost:8004/scanner';

function ScanQRModal({ onClose }: { onClose: () => void }) {
  const [url, setUrl] = useState(
    () => localStorage.getItem(SCANNER_URL_KEY) ?? DEFAULT_SCANNER_URL,
  );

  function save(val: string) {
    setUrl(val);
    localStorage.setItem(SCANNER_URL_KEY, val);
  }

  const qrSrc = `https://api.qrserver.com/v1/create-qr-code/?size=220x220&margin=12&data=${encodeURIComponent(url)}`;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm"
      onClick={onClose}
    >
      <div
        className="relative w-[340px] rounded-[20px] border border-[#E8D4C6] bg-white p-6 shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Close */}
        <button
          type="button"
          onClick={onClose}
          className="absolute right-4 top-4 flex h-7 w-7 items-center justify-center rounded-full text-[#5C7A8A] hover:bg-[#FDF5EF]"
        >
          <SymbolIcon icon="close" className="text-[18px]" />
        </button>

        <div className="flex items-center gap-2 mb-4">
          <SymbolIcon icon="qr_code_scanner" className="text-[22px] text-[#E8654A]" />
          <h2 className="text-[16px] font-semibold text-[#1B3A4B]">Scan with your phone</h2>
        </div>

        {/* QR Code */}
        <div className="flex justify-center mb-4">
          <div className="rounded-[12px] border border-[#E8D4C6] bg-[#FDF5EF] p-2">
            <img src={qrSrc} alt="Scanner QR code" className="h-[220px] w-[220px] rounded-[8px]" />
          </div>
        </div>

        <p className="mb-3 text-center text-[13px] text-[#5C7A8A]">
          Point your phone camera at this code to open the barcode scanner.
        </p>

        {/* Editable URL */}
        <div>
          <label className="mb-1 block text-[11px] font-medium uppercase tracking-wide text-[#9AAFBC]">
            Scanner URL (paste ngrok URL for iPhone)
          </label>
          <input
            className="w-full rounded-[8px] border border-[#E8D4C6] bg-[#FDF5EF] px-3 py-2 font-mono text-[12px] text-[#1B3A4B] outline-none focus:border-[#E8654A]"
            value={url}
            onChange={(e) => save(e.target.value)}
            spellCheck={false}
          />
        </div>
      </div>
    </div>
  );
}

type InventoryItem = {
  id: string;
  name: string;
  brand: string | null;
  category: string | null;
  quantity: number;
  reorder_point: number;
  cost_price: number | null;
  sell_price: number | null;
  currency: string;
  last_updated: string | null;
};

function stockTone(qty: number, reorder: number): 'green' | 'yellow' | 'red' {
  if (qty === 0) return 'red';
  if (qty <= reorder) return 'yellow';
  return 'green';
}

function stockLabel(qty: number, reorder: number) {
  if (qty === 0) return 'Out of stock';
  if (qty <= reorder) return 'Low stock';
  return 'In stock';
}

function StockBar({ qty, reorder }: { qty: number; reorder: number }) {
  const max = Math.max(reorder * 3, qty, 1);
  const pct = Math.min(100, (qty / max) * 100);
  const color =
    qty === 0 ? '#D14D4D' : qty <= reorder ? '#D4870E' : '#2D8A6E';
  return (
    <div className="flex items-center gap-2">
      <span
        className="w-8 text-right font-mono text-[13px] font-semibold"
        style={{ color }}
      >
        {qty}
      </span>
      <div className="h-[5px] w-[72px] overflow-hidden rounded-full bg-[#F5E0CF]">
        <div
          className="h-full rounded-full transition-all duration-500"
          style={{ width: `${pct}%`, background: color }}
        />
      </div>
    </div>
  );
}

function LiveDot() {
  return (
    <span className="relative inline-flex h-2 w-2">
      <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-[#2D8A6E] opacity-60" />
      <span className="relative inline-flex h-2 w-2 rounded-full bg-[#2D8A6E]" />
    </span>
  );
}

export function InventoryPage() {
  const sidebar = platformSidebar('inventory');
  const [items, setItems] = useState<InventoryItem[]>([]);
  const [query, setQuery] = useState('');
  const [loading, setLoading] = useState(true);
  const [lastRefresh, setLastRefresh] = useState<Date | null>(null);
  const [showQR, setShowQR] = useState(false);
  const prevQtys = useRef<Record<string, number>>({});
  const [flashIds, setFlashIds] = useState<Set<string>>(new Set());

  async function fetchInventory() {
    try {
      const res = await fetch('/api/db/inventory');
      if (!res.ok) return;
      const data: InventoryItem[] = await res.json();

      // Detect quantity changes for flash animation
      const changed = new Set<string>();
      data.forEach((item) => {
        if (prevQtys.current[item.id] !== undefined && prevQtys.current[item.id] !== item.quantity) {
          changed.add(item.id);
        }
        prevQtys.current[item.id] = item.quantity;
      });
      if (changed.size > 0) {
        setFlashIds(changed);
        setTimeout(() => setFlashIds(new Set()), 1500);
      }

      // Sort: out of stock → low stock → in stock, then by name
      data.sort((a, b) => {
        const score = (i: InventoryItem) =>
          i.quantity === 0 ? 0 : i.quantity <= i.reorder_point ? 1 : 2;
        return score(a) - score(b) || a.name.localeCompare(b.name);
      });

      setItems(data);
      setLastRefresh(new Date());
    } catch {
      // API not available — keep existing data
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    fetchInventory();
    const id = setInterval(fetchInventory, 5000);
    return () => clearInterval(id);
  }, []);

  const filtered = items.filter((item) => {
    if (!query) return true;
    const q = query.toLowerCase();
    return (
      item.name.toLowerCase().includes(q) ||
      (item.brand ?? '').toLowerCase().includes(q) ||
      (item.category ?? '').toLowerCase().includes(q) ||
      item.id.includes(q)
    );
  });

  const totalItems = items.length;
  const inStock = items.filter((i) => i.quantity > i.reorder_point).length;
  const lowStock = items.filter((i) => i.quantity > 0 && i.quantity <= i.reorder_point).length;
  const outOfStock = items.filter((i) => i.quantity === 0).length;
  const totalValue = items.reduce((s, i) => s + i.quantity * (i.sell_price ?? 0), 0);

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
      {showQR && <ScanQRModal onClose={() => setShowQR(false)} />}

      <div className="flex h-full flex-col overflow-hidden">

        {/* ── Header ── */}
        <header className="flex min-h-[72px] shrink-0 flex-col gap-4 border-b border-[#E8D4C6] bg-white px-8 py-4 xl:flex-row xl:items-center xl:justify-between xl:py-0">
          <div className="flex items-center gap-3">
            <SymbolIcon icon="inventory_2" className="text-[28px] text-[#E8654A]" />
            <div>
              <h1 className="text-[20px] font-semibold text-[#1B3A4B]">Inventory</h1>
              <div className="flex items-center gap-1.5 text-[12px] text-[#5C7A8A]">
                <LiveDot />
                <span>MongoDB Atlas · live</span>
                {lastRefresh && (
                  <span className="text-[#9AAFBC]">
                    · updated {lastRefresh.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })}
                  </span>
                )}
              </div>
            </div>
          </div>

          <div className="flex flex-wrap items-center gap-3">
            {/* Search */}
            <div className="flex h-10 w-[240px] items-center gap-2 rounded-[8px] border border-[#E8D4C6] bg-white px-3 text-[#9AAFBC]">
              <SymbolIcon icon="search" className="text-base" />
              <input
                className="flex-1 bg-transparent text-[14px] text-[#1B3A4B] placeholder-[#9AAFBC] outline-none"
                placeholder="Search items…"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
              />
            </div>

            {/* Refresh */}
            <button
              type="button"
              onClick={fetchInventory}
              className="inline-flex items-center gap-1.5 rounded-[999px] border border-[#E8D4C6] bg-white px-4 py-2 text-[13px] font-medium text-[#5C7A8A] transition-colors hover:bg-[#FDF5EF]"
            >
              <SymbolIcon icon="refresh" className="text-[18px]" />
              Refresh
            </button>

            {/* Scan button → shows QR code modal for phone */}
            <button
              type="button"
              onClick={() => setShowQR(true)}
              className="inline-flex items-center gap-1.5 rounded-[999px] border border-transparent bg-[#1B3A4B] px-4 py-2 text-[13px] font-medium text-white transition-colors hover:bg-[#2A5060]"
            >
              <SymbolIcon icon="qr_code_scanner" className="text-[18px]" />
              Scan Items
            </button>
          </div>
        </header>

        {/* ── Stat cards ── */}
        <div className="shrink-0 px-8 py-4">
          <div className="grid grid-cols-2 gap-3 xl:grid-cols-5">
            <div className="rounded-[12px] border border-[#E8D4C6] bg-white px-5 py-4 shadow-sm">
              <div className="text-[12px] font-medium text-[#5C7A8A]">Total items</div>
              <div className="mt-1 font-mono text-[22px] font-bold text-[#1B3A4B]">
                {loading ? '—' : totalItems}
              </div>
            </div>
            <div className="rounded-[12px] border border-[#E8D4C6] bg-white px-5 py-4 shadow-sm">
              <div className="text-[12px] font-medium text-[#5C7A8A]">In stock</div>
              <div className="mt-1 font-mono text-[22px] font-bold text-[#2D8A6E]">
                {loading ? '—' : inStock}
              </div>
            </div>
            <div className="rounded-[12px] border border-[#E8D4C6] bg-white px-5 py-4 shadow-sm">
              <div className="text-[12px] font-medium text-[#5C7A8A]">Low stock</div>
              <div className="mt-1 font-mono text-[22px] font-bold text-[#D4870E]">
                {loading ? '—' : lowStock}
              </div>
            </div>
            <div className="rounded-[12px] border border-[#E8D4C6] bg-white px-5 py-4 shadow-sm">
              <div className="text-[12px] font-medium text-[#5C7A8A]">Out of stock</div>
              <div className="mt-1 font-mono text-[22px] font-bold text-[#D14D4D]">
                {loading ? '—' : outOfStock}
              </div>
            </div>
            <div className="rounded-[12px] border border-[#E8D4C6] bg-white px-5 py-4 shadow-sm">
              <div className="text-[12px] font-medium text-[#5C7A8A]">Inventory value</div>
              <div className="mt-1 font-mono text-[22px] font-bold text-[#1B3A4B]">
                {loading ? '—' : `$${totalValue.toFixed(0)}`}
              </div>
            </div>
          </div>
        </div>

        {/* ── Table ── */}
        <div className="min-h-0 flex-1 overflow-y-auto px-8 pb-6">
          <div className="overflow-hidden rounded-[12px] border border-[#E8D4C6] bg-white shadow-sm">

            {/* Column headers */}
            <div className="grid grid-cols-[1fr_140px_160px_130px_100px_80px] items-center border-b border-[#E8D4C6] bg-[#FDF5EF] px-5 text-[12px] font-semibold uppercase tracking-wide text-[#5C7A8A]">
              <div className="py-3">Product</div>
              <div className="py-3">Category</div>
              <div className="py-3">Qty / Level</div>
              <div className="py-3">Reorder at</div>
              <div className="py-3">Price</div>
              <div className="py-3">Status</div>
            </div>

            {/* Loading state */}
            {loading && (
              <div className="flex items-center justify-center gap-2 py-16 text-[14px] text-[#5C7A8A]">
                <svg className="h-4 w-4 animate-spin text-[#E8654A]" viewBox="0 0 24 24" fill="none">
                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                  <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8z" />
                </svg>
                Connecting to MongoDB Atlas…
              </div>
            )}

            {/* Rows */}
            {!loading && filtered.map((item) => {
              const isFlashing = flashIds.has(item.id);
              return (
                <div
                  key={item.id}
                  className={`grid grid-cols-[1fr_140px_160px_130px_100px_80px] items-center border-b border-[#E8D4C6] px-5 last:border-b-0 transition-colors duration-700 ${
                    isFlashing ? 'bg-[#2D8A6E0F]' : 'bg-white hover:bg-[#FDFAF8]'
                  }`}
                >
                  {/* Product */}
                  <div className="py-3">
                    <div className="text-[14px] font-medium text-[#1B3A4B]">{item.name}</div>
                    <div className="mt-0.5 flex items-center gap-2">
                      {item.brand && (
                        <span className="text-[12px] text-[#5C7A8A]">{item.brand}</span>
                      )}
                      <span className="font-mono text-[11px] text-[#9AAFBC]">{item.id}</span>
                    </div>
                  </div>

                  {/* Category */}
                  <div className="py-3">
                    {item.category ? (
                      <Badge label={item.category} tone="blue" mono={false} />
                    ) : (
                      <span className="text-[13px] text-[#9AAFBC]">—</span>
                    )}
                  </div>

                  {/* Qty + bar */}
                  <div className="py-3">
                    <StockBar qty={item.quantity} reorder={item.reorder_point} />
                  </div>

                  {/* Reorder point */}
                  <div className="py-3 font-mono text-[13px] text-[#5C7A8A]">
                    {item.reorder_point} units
                  </div>

                  {/* Price */}
                  <div className="py-3 font-mono text-[13px] text-[#1B3A4B]">
                    {item.sell_price != null ? `$${item.sell_price.toFixed(2)}` : '—'}
                  </div>

                  {/* Status badge */}
                  <div className="py-3">
                    <Badge
                      label={stockLabel(item.quantity, item.reorder_point)}
                      tone={stockTone(item.quantity, item.reorder_point)}
                      dot
                      mono={false}
                    />
                  </div>
                </div>
              );
            })}

            {/* Empty state */}
            {!loading && filtered.length === 0 && (
              <div className="py-16 text-center text-[14px] text-[#5C7A8A]">
                {query ? `No items match "${query}"` : 'No inventory items found.'}
              </div>
            )}

            {/* Footer */}
            {!loading && (
              <div className="flex items-center justify-between border-t border-[#E8D4C6] bg-[#FDF5EF] px-5 py-3">
                <span className="text-[13px] text-[#5C7A8A]">
                  Showing {filtered.length} of {totalItems} items · auto-refreshes every 5 s
                </span>
                <div className="flex items-center gap-1.5 text-[12px] text-[#2D8A6E]">
                  <LiveDot />
                  <span>MongoDB Atlas</span>
                </div>
              </div>
            )}
          </div>
        </div>
      </div>
    </AppShell>
  );
}
