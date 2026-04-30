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
        <header className="flex min-h-[72px] flex-col gap-4 border-b border-[#E8D4C6] px-6 py-4 xl:flex-row xl:items-center xl:justify-between xl:py-0">
          <div>
            <h1 className="text-[24px] font-semibold leading-[1.2] text-[#1B3A4B]">Trends Marketplace</h1>
            <p className="mt-1 text-[13px] leading-[1.3] text-[#5C7A8A]">
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
          <div className="flex min-h-[174px] flex-col justify-between rounded-[16px] bg-gradient-to-l from-[#E8654A] to-[#F58900] px-6 py-5 lg:flex-row lg:items-center">
            <div className="max-w-[560px]">
              <h2 className="max-w-[520px] text-[38px] font-bold leading-[0.98] tracking-[-0.03em] text-white md:text-[40px]">
                Trending for your store
                <br />
                right now
              </h2>
              <p className="mt-3 max-w-[520px] text-[14px] leading-[1.35] text-[#FFE7CC]">
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
                    <div className="text-[14px] font-semibold leading-[1.3] text-[#1B3A4B]">
                      {product.name}
                    </div>
                    <div className="text-[12px] leading-[1.35] text-[#5C7A8A]">{product.blurb}</div>
                    <div className="flex items-center justify-between gap-2">
                      <div className="font-mono text-[16px] font-semibold text-[#1B3A4B]">
                        {product.price}
                      </div>
                      <div className="flex items-center gap-2">
                        <span className="rounded-[8px] bg-[#1B3A4B10] px-[10px] py-[6px] font-mono text-[11px] font-semibold text-[#1B3A4B]">
                          View Details
                        </span>
                        <span className="rounded-[8px] bg-[#2D8A6E12] px-[10px] py-[6px] font-mono text-[11px] font-semibold text-[#2D8A6E]">
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
                <div className="text-[13px] font-medium text-[#5C7A8A]">Selected product</div>
                <div className="mt-1 font-mono text-[17px] font-semibold text-[#1B3A4B]">
                  Bio-Collagen Night Repair Serum · 30ml
                </div>
              </div>
              <div className="flex items-center justify-between rounded-[8px] border border-[#E8D4C6] bg-[#FDF5EF] px-[10px] py-2">
                <div>
                  <div className="text-[11px] font-medium text-[#5C7A8A]">Unit Cost</div>
                  <div className="font-mono text-[20px] font-bold text-[#1B3A4B]">$31.90</div>
                  <div className="text-[11px] text-[#9AAFBC]">MOQ 50 · 2.9d ship</div>
                </div>
                <Badge label="In stock" tone="green" mono={false} />
              </div>
              <img
                className="h-[100px] w-full rounded-[12px] border border-[#E8D4C6] object-cover"
                src="https://images.unsplash.com/photo-1700151573695-d1ba457e0ef2?crop=entropy&cs=tinysrgb&fit=max&fm=jpg&q=80&w=1080"
                alt="Selected product"
              />
              <div className="rounded-[10px] border border-[#E8D4C6] bg-[#FDF5EF] p-3">
                <div className="text-[12px] font-semibold text-[#5C7A8A]">Trust & Fulfillment</div>
                <div className="mt-3 flex flex-wrap gap-2">
                  <span className="rounded-full bg-[#D1FAE5] px-2 py-1 text-[11px] font-medium text-[#065F46]">
                    Verified
                  </span>
                  <span className="rounded-full bg-[#E8D4C6] px-2 py-1 text-[11px] font-medium text-[#1B3A4B]">
                    4.8 rating
                  </span>
                  <span className="rounded-full bg-[#FFF0E5] px-2 py-1 text-[11px] font-medium text-[#92400E]">
                    2.9d ship
                  </span>
                </div>
              </div>
              <div className="rounded-[10px] border border-[#E8D4C6] bg-[#FDF5EF] p-3">
                <div className="text-[11px] font-semibold text-[#5C7A8A]">AI highlights</div>
                <div className="mt-2 text-[11px] leading-[1.5] text-[#3D5A6E]">
                  • Overnight-repair messaging is rising in short-form beauty content.
                </div>
                <div className="mt-1 text-[11px] leading-[1.5] text-[#3D5A6E]">
                  • Repeat purchase intent peaks among ages 25-34.
                </div>
              </div>
              <div className="rounded-[10px] border border-[#D4C0B0] bg-[#FDF5EF] p-2">
                <button className="w-full rounded-[12px] bg-[#E8654A] px-4 py-3 font-mono text-[14px] font-bold text-white">
                  Place order
                </button>
                <p className="mt-2 text-[10px] leading-[1.35] text-[#9AAFBC]">
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
