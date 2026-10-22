import { useEffect, useRef, useState, type CSSProperties } from 'react';

const PHASES = [
  {
    id: 'connect',
    index: '01',
    label: 'Connect',
    caption: 'Catalog, sales, stock, and suppliers, brought into one plan.',
  },
  {
    id: 'review',
    index: '02',
    label: 'Review',
    caption: 'Quantities from demand, stock on hand, incoming orders, and supplier constraints.',
  },
  {
    id: 'prepare',
    index: '03',
    label: 'Prepare',
    caption: 'A purchase order with quantities ready to adjust and approve.',
  },
  {
    id: 'receive',
    index: '04',
    label: 'Track',
    caption: 'Received units set against what was ordered. Short lines are flagged.',
  },
] as const;

const LINES = [
  {
    sku: 'Coastal kibble, 20 lb',
    hand: 6,
    sold: 41,
    order: 24,
    received: 24,
    supplier: 'Northline',
    spark: 'M1 16 L12 14 L24 15 L36 9 L48 11 L60 5 L71 4',
  },
  {
    sku: 'Nylon leash, 6 ft',
    hand: 2,
    sold: 18,
    order: 12,
    received: 9,
    supplier: 'Northline',
    spark: 'M1 8 L12 10 L24 7 L36 12 L48 9 L60 14 L71 16',
  },
  {
    sku: 'Galvanized hinge, 3 in',
    hand: 14,
    sold: 9,
    order: 0,
    received: 0,
    supplier: 'Harbor',
    spark: 'M1 12 L12 13 L24 11 L36 12 L48 14 L60 13 L71 12',
  },
  {
    sku: 'Ceramic bowl, large',
    hand: 0,
    sold: 11,
    order: 8,
    received: 8,
    supplier: 'Kiln & Co',
    spark: 'M1 18 L12 16 L24 17 L36 12 L48 8 L60 6 L71 3',
  },
] as const;

const SOURCES = [
  { name: 'Product catalog', detail: 'Items and pack sizes' },
  { name: 'Sales history', detail: 'Last 28 days' },
  { name: 'Current stock', detail: 'On hand now' },
  { name: 'Suppliers', detail: 'Lead times and constraints' },
] as const;

function readDuration(name: string, fallback: number) {
  const raw = getComputedStyle(document.documentElement).getPropertyValue(name);
  const value = Number.parseFloat(raw);
  return Number.isFinite(value) ? value : fallback;
}

function useCount(target: number) {
  const [value, setValue] = useState(0);

  useEffect(() => {
    if (target === 0) {
      setValue(0);
      return undefined;
    }
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
      setValue(target);
      return undefined;
    }

    let frame = 0;
    const start = performance.now();
    const duration = 480;
    const tick = (now: number) => {
      const t = Math.min(1, (now - start) / duration);
      const eased = t < 0.5 ? 2 * t * t : 1 - ((-2 * t + 2) ** 2) / 2;
      setValue(Math.round(target * eased));
      if (t < 1) frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [target]);

  return value;
}

function Tick({ index }: { index: number }) {
  return (
    <svg className="tick" viewBox="0 0 16 16" aria-hidden="true" style={{ '--i': index } as CSSProperties}>
      <circle cx="8" cy="8" r="6.2" pathLength={1} />
      <path d="M4.8 8.2 7 10.3 11.3 5.8" pathLength={1} />
    </svg>
  );
}

function Spark({ d, index }: { d: string; index: number }) {
  return (
    <svg className="spark" viewBox="0 0 72 24" aria-hidden="true" style={{ '--i': index } as CSSProperties}>
      <path d={d} pathLength={1} />
    </svg>
  );
}

function OrderFigure({ value }: { value: number }) {
  const shown = useCount(value);
  if (value === 0) return <span className="qty qty--hold">Hold</span>;
  return <span className="qty">{shown}</span>;
}

function ConnectSheet() {
  return (
    <div className="sources">
      {SOURCES.map((source, index) => (
        <article className="source" key={source.name}>
          <Tick index={index} />
          <strong>{source.name}</strong>
          <em>{source.detail}</em>
        </article>
      ))}
    </div>
  );
}

function ReviewSheet() {
  return (
    <div className="sheet-table">
      <div className="sheet-head">
        <span>Item</span>
        <span>On hand</span>
        <span>28d</span>
        <span>Order</span>
      </div>
      {LINES.map((line, index) => (
        <div className="sheet-row" key={line.sku}>
          <div className="item">
            <strong>{line.sku}</strong>
            <Spark d={line.spark} index={index} />
          </div>
          <span>{line.hand}</span>
          <span>{line.sold}</span>
          <OrderFigure value={line.order} />
        </div>
      ))}
    </div>
  );
}

function PrepareSheet() {
  const lines = LINES.filter((line) => line.supplier === 'Northline');
  return (
    <div className="po">
      <div className="po__back" aria-hidden="true">
        <span>Kiln &amp; Co · next</span>
      </div>
      <article className="po__front">
        <p className="po__kicker">PO-184</p>
        <h3>Northline</h3>
        <span className="stamp">Ready</span>
        {lines.map((line) => (
          <div className="po__line" key={line.sku}>
            <span>{line.sku}</span>
            <b>{line.order}</b>
          </div>
        ))}
      </article>
    </div>
  );
}

function ReceiveSheet() {
  const lines = LINES.filter((line) => line.supplier === 'Northline');
  return (
    <div className="receive">
      <div className="receive__top">
        <span>PO-184 · Northline</span>
        <span>Delivery</span>
      </div>
      {lines.map((line) => {
        const short = line.received < line.order;
        const fill = Math.round((line.received / line.order) * 100);
        return (
          <article className={short ? 'receipt is-short' : 'receipt'} key={line.sku}>
            <header>
              <b>{line.sku}</b>
              <span>{short ? `Short ${line.order - line.received}` : 'Matched'}</span>
            </header>
            <div className="bar" aria-hidden="true">
              <span style={{ '--fill': fill } as CSSProperties} />
            </div>
            <footer>
              <span>Ordered {line.order}</span>
              <span>Received {line.received}</span>
            </footer>
          </article>
        );
      })}
    </div>
  );
}

export function PlanStage() {
  const [index, setIndex] = useState(0);
  const [paused, setPaused] = useState(false);
  const [reduce, setReduce] = useState(false);
  const skipSwap = useRef(true);
  const [swap, setSwap] = useState(false);
  const phase = PHASES[index];

  useEffect(() => {
    const media = window.matchMedia('(prefers-reduced-motion: reduce)');
    const apply = () => setReduce(media.matches);
    apply();
    media.addEventListener('change', apply);
    return () => media.removeEventListener('change', apply);
  }, []);

  useEffect(() => {
    if (skipSwap.current) {
      skipSwap.current = false;
      return undefined;
    }
    setSwap(true);
    return undefined;
  }, [index]);

  useEffect(() => {
    if (paused || reduce) return undefined;
    const delay = readDuration('--hf-duration-phase', 3600);
    const id = window.setInterval(() => {
      setIndex((current) => (current + 1) % PHASES.length);
    }, delay);
    return () => window.clearInterval(id);
  }, [paused, reduce]);

  const stageClass = ['stage', paused ? 'is-paused' : '', reduce ? 'is-still' : ''].filter(Boolean).join(' ');

  return (
    <aside
      className={stageClass}
      style={{ '--phase': index } as CSSProperties}
      aria-label="Sample purchasing plan"
      onMouseEnter={() => setPaused(true)}
      onMouseLeave={() => setPaused(false)}
      onFocus={() => setPaused(true)}
      onBlur={(event) => {
        const next = event.relatedTarget;
        if (!(next instanceof Node) || !event.currentTarget.contains(next)) setPaused(false);
      }}
    >
      <div className="stage__top">
        <span className="stage__id">
          <span className="logo__mark" aria-hidden="true">
            <span />
            <span />
            <span />
            <span />
          </span>
          Purchasing plan
        </span>
        <span className="stage__sample">Sample</span>
      </div>

      <div className="rail" role="tablist" aria-label="Plan stages">
        <span className="rail__indicator" />
        {PHASES.map((item, itemIndex) => (
          <button
            key={item.id}
            type="button"
            role="tab"
            aria-selected={itemIndex === index}
            onClick={() => setIndex(itemIndex)}
          >
            <span>{item.index}</span>
            {item.label}
          </button>
        ))}
      </div>

      <div className="meter" aria-hidden="true">
        <span key={phase.id} />
      </div>

      <div className="stage__body">
        <span className="stage__scan" key={`scan-${phase.id}`} aria-hidden="true" />
        <div key={phase.id} className={swap ? 'sheet is-swap' : 'sheet'}>
          {phase.id === 'connect' ? <ConnectSheet /> : null}
          {phase.id === 'review' ? <ReviewSheet /> : null}
          {phase.id === 'prepare' ? <PrepareSheet /> : null}
          {phase.id === 'receive' ? <ReceiveSheet /> : null}
        </div>
      </div>

      <p className="stage__caption">{phase.caption}</p>
    </aside>
  );
}
