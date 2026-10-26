import { AppShell, Badge, CardPanel, HeaderButton, SearchField, Sidebar } from '../components/ui';
import { platformSidebar } from '../data';

const products = [
  {
    name: 'Pilot G2 Premium Gel Pen Pack (24)',
    blurb: 'AI: demand +38% WoW, low returns, stable stock.',
    price: '$21.40',
    image:
      'https://images.unsplash.com/photo-1646801089509-c152f61a1909?crop=entropy&cs=tinysrgb&fit=max&fm=jpg&q=80&w=1080',
  },
  {
    name: 'Logi Combo MK Wireless Desk Set',
    blurb: 'AI: supplier score 9.1/10, margin +27%, safe restock.',
    price: '$62.00',
    image:
      'https://images.unsplash.com/photo-1536059540012-f2ed455bc0b1?crop=entropy&cs=tinysrgb&fit=max&fm=jpg&q=80&w=1080',
  },
  {
    name: 'Moleskine Classic Notebook Set',
    blurb: 'AI: back-to-school demand strong, shipping stable, returns 2.1%.',
    price: '$34.50',
    image:
      'https://images.unsplash.com/photo-1646617747559-9b93439edcec?crop=entropy&cs=tinysrgb&fit=max&fm=jpg&q=80&w=1080',
  },
  {
    name: 'Noise-Canceling Office Headset Pro',
    blurb: 'AI: conversion up in remote-work stores, SMB review velocity strong.',
    price: '$79.00',
    image:
      'https://images.unsplash.com/photo-1752650734912-2d30401369f1?crop=entropy&cs=tinysrgb&fit=max&fm=jpg&q=80&w=1080',
  },
];

export function TrendsPage() {
  const sidebar = platformSidebar('trends');

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
        <header className="flex min-h-[72px] flex-col gap-4 border-b border-[var(--app-line)] px-6 py-4 xl:flex-row xl:items-center xl:justify-between xl:py-0">
          <div>
            <h1 className="text-[24px] font-semibold leading-[1.2] text-[var(--app-ink)]">Trends Marketplace</h1>
            <p className="mt-1 text-[13px] leading-[1.3] text-[var(--app-muted)]">
              Use filters to narrow products by demand, margin, and shipping.
            </p>
          </div>
          <div className="flex items-center gap-3">
            <div className="w-[320px]">
              <SearchField placeholder="Search..." dark={false} />
            </div>
            <HeaderButton icon="filter_list" label="Filters" active />
          </div>
        </header>

        <div className="flex flex-1 flex-col gap-4 p-5">
          <div className="flex min-h-[174px] flex-col justify-between rounded-[16px] bg-gradient-to-l from-[var(--app-accent)] to-[color-mix(in_srgb,var(--app-accent)_65%,white)] px-6 py-5 lg:flex-row lg:items-center">
            <div className="max-w-[560px]">
              <h2 className="max-w-[520px] text-[38px] font-bold leading-[0.98] tracking-[-0.03em] text-[var(--app-accent-ink)] md:text-[40px]">
                Trending for your store
                <br />
                right now
              </h2>
              <p className="mt-3 max-w-[520px] text-[14px] leading-[1.35] text-[var(--app-accent-ink)]">
                AI agents researched these products from live supplier pages and ranked them for
                demand, margin, and reliability.
              </p>
            </div>
            <img
              className="mt-4 h-[132px] w-full max-w-[344px] rounded-[14px] object-cover lg:mt-0"
              src="https://images.unsplash.com/photo-1762331237307-332757526f5b?crop=entropy&cs=tinysrgb&fit=max&fm=jpg&q=80&w=1080"
              alt="Trending feature"
            />
          </div>

          <div className="grid min-h-0 flex-1 gap-4 xl:grid-cols-[minmax(0,1fr)_360px]">
            <div className="flex min-h-0 flex-col gap-3">
              <div className="flex flex-wrap gap-2">
                <Badge label="Trending Now" tone="blue" mono />
                <Badge label="Agent Picks" tone="blue" mono />
                <Badge label="Order Again" tone="blue" mono />
                <Badge label="High Margin" tone="blue" mono />
                <Badge label="Fast Shipping" tone="blue" mono />
              </div>
              <div className="grid gap-3 md:grid-cols-2">
                {products.map((product) => (
                  <CardPanel key={product.name} className="flex flex-col gap-3 rounded-[14px] p-3">
                    <img
                      className="h-[106px] w-full rounded-[12px] object-cover"
                      src={product.image}
                      alt={product.name}
                    />
                    <div className="text-[14px] font-semibold leading-[1.3] text-[var(--app-ink)]">
                      {product.name}
                    </div>
                    <div className="text-[12px] leading-[1.35] text-[var(--app-muted)]">{product.blurb}</div>
                    <div className="flex items-center justify-between gap-2">
                      <div className="font-mono text-[16px] font-semibold text-[var(--app-ink)]">
                        {product.price}
                      </div>
                      <div className="flex items-center gap-2">
                        <span className="rounded-[8px] bg-[color-mix(in_srgb,var(--app-ink)_8%,transparent)] px-[10px] py-[6px] font-mono text-[11px] font-semibold text-[var(--app-ink)]">
                          View Details
                        </span>
                        <span className="rounded-[8px] bg-[var(--app-success-soft)] px-[10px] py-[6px] font-mono text-[11px] font-semibold text-[var(--app-success)]">
                          Quick Order
                        </span>
                      </div>
                    </div>
                  </CardPanel>
                ))}
              </div>
            </div>

            <CardPanel className="flex min-h-[620px] flex-col gap-3 rounded-[14px] p-3">
              <div>
                <div className="text-[13px] font-medium text-[var(--app-muted)]">Selected product</div>
                <div className="mt-1 font-mono text-[17px] font-semibold text-[var(--app-ink)]">
                  Bio-Collagen Night Repair Serum · 30ml
                </div>
              </div>
              <div className="flex items-center justify-between rounded-[8px] border border-[var(--app-line)] bg-[var(--app-surface-muted)] px-[10px] py-2">
                <div>
                  <div className="text-[11px] font-medium text-[var(--app-muted)]">Unit Cost</div>
                  <div className="font-mono text-[20px] font-bold text-[var(--app-ink)]">$31.90</div>
                  <div className="text-[11px] text-[var(--app-quiet)]">MOQ 50 · 2.9d ship</div>
                </div>
                <Badge label="In stock" tone="green" mono={false} />
              </div>
              <img
                className="h-[100px] w-full rounded-[12px] border border-[var(--app-line)] object-cover"
                src="https://images.unsplash.com/photo-1700151573695-d1ba457e0ef2?crop=entropy&cs=tinysrgb&fit=max&fm=jpg&q=80&w=1080"
                alt="Selected product"
              />
              <div className="rounded-[10px] border border-[var(--app-line)] bg-[var(--app-surface-muted)] p-3">
                <div className="text-[12px] font-semibold text-[var(--app-muted)]">Trust & Fulfillment</div>
                <div className="mt-3 flex flex-wrap gap-2">
                  <span className="rounded-full bg-[var(--app-success-soft)] px-2 py-1 text-[11px] font-medium text-[var(--app-success)]">
                    Verified
                  </span>
                  <span className="rounded-full bg-[var(--app-line)] px-2 py-1 text-[11px] font-medium text-[var(--app-ink)]">
                    4.8 rating
                  </span>
                  <span className="rounded-full bg-[var(--app-warning-soft)] px-2 py-1 text-[11px] font-medium text-[var(--app-warning)]">
                    2.9d ship
                  </span>
                </div>
              </div>
              <div className="rounded-[10px] border border-[var(--app-line)] bg-[var(--app-surface-muted)] p-3">
                <div className="text-[11px] font-semibold text-[var(--app-muted)]">AI highlights</div>
                <div className="mt-2 text-[11px] leading-[1.5] text-[var(--app-muted)]">
                  • Overnight-repair messaging is rising in short-form beauty content.
                </div>
                <div className="mt-1 text-[11px] leading-[1.5] text-[var(--app-muted)]">
                  • Repeat purchase intent peaks among ages 25-34.
                </div>
              </div>
              <div className="rounded-[10px] border border-[var(--app-line-strong)] bg-[var(--app-surface-muted)] p-2">
                <button className="w-full rounded-[12px] bg-[var(--app-accent)] px-4 py-3 font-mono text-[14px] font-bold text-[var(--app-accent-ink)]">
                  Place order
                </button>
                <p className="mt-2 text-[10px] leading-[1.35] text-[var(--app-quiet)]">
                  Tabula submits to suppliers, confirms terms, and tracks fulfillment end to end.
                </p>
              </div>
            </CardPanel>
          </div>
        </div>
      </div>
    </AppShell>
  );
}
