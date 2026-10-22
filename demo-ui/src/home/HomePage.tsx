import { useCallback, useRef, useState, type MouseEvent } from 'react';
import { Link } from 'react-router-dom';
import { EarlyAccessDialog } from './EarlyAccessDialog';
import { PlanStage } from './PlanStage';
import { useHomeMotion } from './useHomeMotion';
import './tokens.css';
import './home.css';

const CAPABILITIES = [
  {
    index: '01',
    title: 'Know what needs reordering',
    copy: 'See which products are running low, which are selling quickly, and which need attention before they become a problem.',
  },
  {
    index: '02',
    title: 'Know how much to order',
    copy: 'Get recommended quantities based on sales history, available stock, incoming orders, supplier lead times, and ordering constraints.',
  },
  {
    index: '03',
    title: 'Keep purchasing organized',
    copy: 'Prepare purchase orders, review quantities and costs, and keep track of outstanding orders.',
  },
  {
    index: '04',
    title: 'Know what actually arrived',
    copy: 'Record received quantities and identify missing or damaged items instead of assuming every order arrived as expected.',
  },
] as const;

const STEPS = [
  {
    index: '01',
    title: 'Connect your inventory data',
    copy: 'Bring together your product catalog, sales history, current stock, and supplier information from supported sources.',
  },
  {
    index: '02',
    title: 'Review your recommendations',
    copy: 'Tabula calculates replenishment needs using demand, stock levels, incoming orders, and available supplier information.',
  },
  {
    index: '03',
    title: 'Prepare your orders',
    copy: 'Review recommended quantities, make adjustments, and prepare purchase orders for approval.',
  },
  {
    index: '04',
    title: 'Track incoming stock',
    copy: 'Record deliveries, reconcile received quantities, and keep your purchasing records organized.',
  },
] as const;

const DECISIONS = [
  {
    question: 'What should I buy?',
    answer: 'Identify products that need replenishment.',
  },
  {
    question: 'How much do I need?',
    answer: 'Account for demand, stock on hand, incoming orders, and supplier constraints.',
  },
  {
    question: 'Which supplier should I use?',
    answer: 'Organize supplier pricing and purchasing information to support better decisions.',
  },
  {
    question: 'What have I already ordered?',
    answer: 'Keep outstanding purchases visible to avoid unnecessary reordering.',
  },
  {
    question: 'Did I receive everything?',
    answer: 'Compare received quantities with what was ordered and flag discrepancies.',
  },
] as const;

function Mark() {
  return (
    <span className="logo__mark" aria-hidden="true">
      <span />
      <span />
      <span />
      <span />
    </span>
  );
}

function Arrow() {
  return (
    <svg viewBox="0 0 16 16" aria-hidden="true">
      <path
        d="M3 8h10M9 4l4 4-4 4"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.4"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

export function HomePage() {
  const rootRef = useRef<HTMLDivElement>(null);
  const openerRef = useRef<HTMLButtonElement | null>(null);
  const [open, setOpen] = useState(false);
  useHomeMotion(rootRef);

  const openDialog = (event: MouseEvent<HTMLButtonElement>) => {
    openerRef.current = event.currentTarget;
    setOpen(true);
  };

  const closeDialog = useCallback(() => {
    setOpen(false);
    openerRef.current?.focus();
  }, []);

  return (
    <div className="home" ref={rootRef}>
      <a className="skip" href="#main">
        Skip to content
      </a>

      <header className="header">
        <div className="header__bar">
          <a className="logo" href="#top" data-enter="" data-i="0">
            <Mark />
            <span className="logo__name">Tabula</span>
            <span className="logo__ai">AI</span>
          </a>

          <nav className="nav" aria-label="Page" data-enter="" data-i="1">
            <a className="nav__link" href="#product">
              Product
            </a>
            <a className="nav__link" href="#method">
              Method
            </a>
            <a className="nav__link" href="#decisions">
              Decisions
            </a>
            <Link className="nav__link" to="/dashboard">
              App
            </Link>
          </nav>

          <button className="btn btn--ink header__cta" type="button" data-enter="" data-i="2" onClick={openDialog}>
            <span className="btn__fill" aria-hidden="true" />
            <span className="btn__label">Get Early Access</span>
          </button>
        </div>
      </header>

      <main id="main">
        <section className="hero" id="top">
          <div className="field" aria-hidden="true" />
          <div className="wrap hero__layout">
            <p className="kicker" data-enter="" data-i="1">
              Purchasing intelligence
            </p>
            <h1 className="display">
              <span className="line" data-enter="" data-scrub="" data-i="2">
                Know what to order.
              </span>
              <span className="line" data-enter="" data-scrub="" data-i="3">
                Spend less time figuring it out.
              </span>
            </h1>
            <div className="hero__split">
              <div>
                <p className="hero__lede" data-enter="" data-i="4">
                  Tabula turns your sales, inventory, and supplier data into a clear purchasing plan,
                  so you can spend less time managing spreadsheets and more time running your business.
                </p>
                <div className="hero__actions" data-enter="" data-i="5">
                  <button className="btn btn--ink" type="button" onClick={openDialog}>
                    <span className="btn__fill" aria-hidden="true" />
                    <span className="btn__label">Get Early Access</span>
                  </button>
                  <a className="text-link" href="#method">
                    See How It Works
                    <Arrow />
                  </a>
                </div>
                <p className="hero__note" data-enter="" data-i="6">
                  Built for independent retailers who need better purchasing decisions without
                  enterprise-level complexity.
                </p>
                <p className="hero__verticals" data-enter="" data-i="7">
                  <span>Starting with</span>
                  <span>Pet supply</span>
                  <span>Hardware</span>
                  <span>Specialty retail</span>
                </p>
              </div>
              <div data-enter="" data-i="4">
                <PlanStage />
              </div>
            </div>
          </div>
        </section>

        <section className="section" id="product" data-section="">
          <div className="wrap">
            <div className="section__intro" data-reveal="" data-i="0">
              <p className="kicker">The work</p>
              <h2 className="display" data-scrub="">
                Your inventory is telling you what to buy. Tabula helps you act on it.
              </h2>
            </div>
            <div className="cards">
              {CAPABILITIES.map((item, index) => (
                <article className="card" data-reveal="" data-scrub="" data-i={index} key={item.index}>
                  <span className="card__index">{item.index}</span>
                  <h3>{item.title}</h3>
                  <p>{item.copy}</p>
                </article>
              ))}
            </div>
          </div>
        </section>

        <section className="section" id="method" data-section="">
          <div className="wrap">
            <div className="section__intro" data-reveal="" data-i="0">
              <p className="kicker">How it works</p>
              <h2 className="display" data-scrub="">
                From scattered data to a purchasing plan.
              </h2>
            </div>
            <ol className="steps">
              {STEPS.map((step, index) => (
                <li className="step" data-reveal="" data-scrub="" data-i={index} key={step.index}>
                  <span className="step__index">{step.index}</span>
                  <h3>{step.title}</h3>
                  <p>{step.copy}</p>
                </li>
              ))}
            </ol>
          </div>
        </section>

        <section className="section" id="decisions" data-section="">
          <div className="wrap">
            <div className="section__intro" data-reveal="" data-i="0">
              <p className="kicker">Every week</p>
              <h2 className="display" data-scrub="">
                Built around the decisions retailers make every week.
              </h2>
            </div>
            <ul className="decisions">
              {DECISIONS.map((item, index) => (
                <li className="decision" data-reveal="" data-scrub="" data-i={index} key={item.question}>
                  <h3>{item.question}</h3>
                  <p>{item.answer}</p>
                </li>
              ))}
            </ul>
          </div>
        </section>

        <section className="section" id="outcome" data-section="">
          <div className="wrap outcome__grid">
            <h2 className="display" data-reveal="" data-scrub="" data-i="0">
              Better purchasing decisions. Less administrative work.
            </h2>
            <div className="outcome__copy" data-reveal="" data-i="1">
              <p>
                Spend less time calculating order quantities, searching through spreadsheets, and
                tracking what is on the way.
              </p>
              <p>
                Keep purchasing decisions organized and make them using the data your business already
                has.
              </p>
            </div>
          </div>
        </section>

        <section className="access" id="access" data-section="">
          <div className="wrap access__grid">
            <div data-reveal="" data-i="0">
              <p className="kicker">Early access</p>
              <h2 className="display" data-scrub="">
                Get early access to Tabula.
              </h2>
            </div>
            <div className="access__copy" data-reveal="" data-i="1">
              <p>We&apos;re building a simpler way for independent retailers to manage replenishment and purchasing.</p>
              <p>
                Join the early-access program and help shape a product designed around the way your
                business actually operates.
              </p>
              <button className="btn btn--paper" type="button" onClick={openDialog}>
                <span className="btn__fill" aria-hidden="true" />
                <span className="btn__label">Request Early Access</span>
              </button>
            </div>
          </div>
        </section>
      </main>

      <footer className="footer">
        <div className="wrap footer__row">
          <a className="logo" href="#top">
            <Mark />
            <span className="logo__name">Tabula</span>
            <span className="logo__ai">AI</span>
          </a>
          <p>Purchasing intelligence for independent retailers.</p>
        </div>
      </footer>

      <EarlyAccessDialog open={open} onClose={closeDialog} />
    </div>
  );
}
