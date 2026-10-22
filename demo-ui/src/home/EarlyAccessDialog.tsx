import { useEffect, useId, useRef, useState, type FormEvent } from 'react';

const STORAGE_KEY = 'tabula.earlyAccess';

const VERTICALS = ['Pet supply', 'Hardware', 'Specialty retail', 'Other'] as const;

type EarlyAccessRequest = {
  name: string;
  store: string;
  email: string;
  vertical: string;
  savedAt: string;
};

type Fields = {
  name: string;
  store: string;
  email: string;
  vertical: string;
};

type Errors = Partial<Record<keyof Fields, string>>;

const EMPTY: Fields = {
  name: '',
  store: '',
  email: '',
  vertical: '',
};

function readRequest(): EarlyAccessRequest | null {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as Partial<EarlyAccessRequest>;
    if (!parsed.email || !parsed.store || !parsed.name) return null;
    return {
      name: parsed.name,
      store: parsed.store,
      email: parsed.email,
      vertical: parsed.vertical ?? '',
      savedAt: parsed.savedAt ?? '',
    };
  } catch {
    return null;
  }
}

function writeRequest(request: EarlyAccessRequest) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(request));
  } catch {
    return;
  }
}

export function EarlyAccessDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const titleId = useId();
  const panelRef = useRef<HTMLDivElement>(null);
  const [saved, setSaved] = useState<EarlyAccessRequest | null>(null);
  const [fields, setFields] = useState<Fields>(EMPTY);
  const [errors, setErrors] = useState<Errors>({});

  useEffect(() => {
    if (!open) return undefined;
    setSaved(readRequest());
    setErrors({});
    const panel = panelRef.current;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';

    const focusable = () =>
      [...(panel?.querySelectorAll<HTMLElement>('button, input, select, a[href]') ?? [])].filter(
        (node) => !node.hasAttribute('disabled'),
      );

    window.setTimeout(() => {
      const field = panel?.querySelector<HTMLElement>('input, select');
      (field ?? focusable()[0])?.focus();
    }, 40);

    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        onClose();
        return;
      }
      if (event.key !== 'Tab') return;
      const nodes = focusable();
      const first = nodes[0];
      const last = nodes[nodes.length - 1];
      if (!first || !last) return;
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };

    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('keydown', onKey);
      document.body.style.overflow = previousOverflow;
    };
  }, [open, onClose]);

  if (!open) return null;

  const update = (key: keyof Fields, value: string) => {
    setFields((current) => ({ ...current, [key]: value }));
    setErrors((current) => ({ ...current, [key]: undefined }));
  };

  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const next: Errors = {};
    if (fields.name.trim().length < 2) next.name = 'Add your name.';
    if (fields.store.trim().length < 2) next.store = 'Add the store name.';
    if (!/^\S+@\S+\.\S+$/.test(fields.email.trim())) next.email = 'Add a valid email.';
    if (!fields.vertical) next.vertical = 'Choose what you sell.';
    setErrors(next);
    if (Object.keys(next).length > 0) return;

    const request: EarlyAccessRequest = {
      name: fields.name.trim(),
      store: fields.store.trim(),
      email: fields.email.trim(),
      vertical: fields.vertical,
      savedAt: new Date().toISOString(),
    };
    writeRequest(request);
    setSaved(request);
  };

  const edit = () => {
    localStorage.removeItem(STORAGE_KEY);
    if (saved) {
      setFields({
        name: saved.name,
        store: saved.store,
        email: saved.email,
        vertical: saved.vertical,
      });
    }
    setSaved(null);
  };

  return (
    <div className="dialog">
      <button className="dialog__backdrop" type="button" aria-label="Close early access" onClick={onClose} />
      <div
        className="dialog__panel"
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        ref={panelRef}
      >
        <button className="dialog__close" type="button" aria-label="Close" onClick={onClose}>
          <svg viewBox="0 0 16 16" aria-hidden="true">
            <path d="M4 4l8 8M12 4l-8 8" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
          </svg>
        </button>
        <p className="kicker">Early access</p>
        <h2 className="display" id={titleId}>
          {saved ? 'Request received.' : 'Get early access to Tabula.'}
        </h2>
        {saved ? (
          <div className="received" role="status">
            <svg className="received__mark" viewBox="0 0 16 16" aria-hidden="true">
              <circle cx="8" cy="8" r="6.2" pathLength={1} />
              <path d="M4.8 8.2 7 10.3 11.3 5.8" pathLength={1} />
            </svg>
            <p>
              {saved.store} is noted. We&apos;ll use {saved.email} when early access opens.
            </p>
            <button className="text-link" type="button" onClick={edit}>
              Edit request
            </button>
          </div>
        ) : (
          <>
            <p className="dialog__lede">
              Join the early-access program and help shape a product designed around the way your
              business actually operates.
            </p>
            <form className="access-form" onSubmit={submit} noValidate>
              <label className={errors.name ? 'control is-invalid' : 'control'}>
                <span>Name</span>
                <input
                  name="name"
                  autoComplete="name"
                  value={fields.name}
                  onChange={(event) => update('name', event.target.value)}
                />
                {errors.name ? <small>{errors.name}</small> : null}
              </label>
              <label className={errors.store ? 'control is-invalid' : 'control'}>
                <span>Store</span>
                <input
                  name="organization"
                  autoComplete="organization"
                  value={fields.store}
                  onChange={(event) => update('store', event.target.value)}
                />
                {errors.store ? <small>{errors.store}</small> : null}
              </label>
              <label className={errors.email ? 'control is-invalid' : 'control'}>
                <span>Email</span>
                <input
                  name="email"
                  type="email"
                  autoComplete="email"
                  inputMode="email"
                  value={fields.email}
                  onChange={(event) => update('email', event.target.value)}
                />
                {errors.email ? <small>{errors.email}</small> : null}
              </label>
              <label className={errors.vertical ? 'control is-invalid' : 'control'}>
                <span>What you sell</span>
                <select
                  name="vertical"
                  value={fields.vertical}
                  onChange={(event) => update('vertical', event.target.value)}
                >
                  <option value="">Select</option>
                  {VERTICALS.map((vertical) => (
                    <option key={vertical} value={vertical}>
                      {vertical}
                    </option>
                  ))}
                </select>
                {errors.vertical ? <small>{errors.vertical}</small> : null}
              </label>
              <button className="btn btn--ink" type="submit">
                <span className="btn__fill" aria-hidden="true" />
                <span className="btn__label">Request Early Access</span>
              </button>
            </form>
          </>
        )}
      </div>
    </div>
  );
}
