import { useEffect, useId, useLayoutEffect, useRef, useState, type CSSProperties } from 'react';

const STORAGE_KEY = 'tabula.appTheme';
const DEFAULT_ACCENT = '#ffffff';

export type AppMode = 'dark' | 'light';

type AppTheme = {
  mode: AppMode;
  accent: string;
};

const DEFAULT_THEME: AppTheme = {
  mode: 'dark',
  accent: DEFAULT_ACCENT,
};

function isHex(value: string) {
  return /^#([0-9a-f]{6})$/i.test(value);
}

function readTheme(): AppTheme {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return DEFAULT_THEME;
    const parsed = JSON.parse(raw) as Partial<AppTheme>;
    return {
      mode: parsed.mode === 'light' ? 'light' : 'dark',
      accent: parsed.accent && isHex(parsed.accent) ? parsed.accent.toLowerCase() : DEFAULT_ACCENT,
    };
  } catch {
    return DEFAULT_THEME;
  }
}

export function accentInk(hex: string) {
  const raw = hex.replace('#', '');
  const full = raw.length === 3 ? raw.split('').map((part) => part + part).join('') : raw;
  if (full.length !== 6) return '#101820';
  const channel = (start: number) => parseInt(full.slice(start, start + 2), 16) / 255;
  const linear = (value: number) => (value <= 0.03928 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4);
  const luminance = 0.2126 * linear(channel(0)) + 0.7152 * linear(channel(2)) + 0.0722 * linear(channel(4));
  return luminance > 0.58 ? '#101820' : '#ffffff';
}

export function useAppTheme() {
  const [theme, setTheme] = useState<AppTheme>(readTheme);

  useLayoutEffect(() => {
    const root = document.documentElement;
    const app = document.querySelector<HTMLElement>('.app-root');
    const ink = accentInk(theme.accent);
    root.dataset.app = theme.mode;
    for (const node of [root, app]) {
      node?.style.setProperty('--app-accent', theme.accent);
      node?.style.setProperty('--app-accent-ink', ink);
    }
    return () => {
      delete root.dataset.app;
      for (const node of [root, app]) {
        node?.style.removeProperty('--app-accent');
        node?.style.removeProperty('--app-accent-ink');
      }
    };
  }, [theme]);

  useEffect(() => {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(theme));
  }, [theme]);

  const setMode = (mode: AppMode) => setTheme((current) => ({ ...current, mode }));
  const setAccent = (accent: string) => {
    if (!isHex(accent)) return;
    setTheme((current) => ({ ...current, accent: accent.toLowerCase() }));
  };

  return { theme, setMode, setAccent };
}

export function SettingsMenu({
  mode,
  accent,
  onMode,
  onAccent,
}: {
  mode: AppMode;
  accent: string;
  onMode: (mode: AppMode) => void;
  onAccent: (accent: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState(accent);
  const panelId = useId();
  const rootRef = useRef<HTMLDivElement>(null);

  useEffect(() => setDraft(accent), [accent]);

  useEffect(() => {
    if (!open) return undefined;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setOpen(false);
    };
    const onPointer = (event: PointerEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener('keydown', onKey);
    document.addEventListener('pointerdown', onPointer);
    return () => {
      document.removeEventListener('keydown', onKey);
      document.removeEventListener('pointerdown', onPointer);
    };
  }, [open]);

  const commitDraft = () => {
    if (isHex(draft)) onAccent(draft);
    else setDraft(accent);
  };

  return (
    <div className="app-settings" ref={rootRef}>
      <button
        className="app-gear"
        type="button"
        aria-label="Settings"
        aria-expanded={open}
        aria-controls={panelId}
        onClick={() => setOpen((current) => !current)}
      >
        <svg viewBox="0 0 24 24" aria-hidden="true">
          <path
            d="M12 8.2a3.8 3.8 0 1 0 0 7.6 3.8 3.8 0 0 0 0-7.6Z"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.6"
          />
          <path
            d="M12 2.8v2.1M12 19.1v2.1M4.7 6.2l1.6 1.2M17.7 16.6l1.6 1.2M2.8 12h2.1M19.1 12h2.1M4.7 17.8l1.6-1.2M17.7 7.4l1.6-1.2"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.6"
            strokeLinecap="round"
          />
        </svg>
      </button>
      {open ? (
        <div className="app-panel" id={panelId} role="dialog" aria-label="Appearance">
          <p className="app-kicker">Appearance</p>
          <div className="app-rail" style={{ '--phase': mode === 'dark' ? 1 : 0 } as CSSProperties}>
            <span className="app-rail__indicator" />
            <button type="button" aria-pressed={mode === 'light'} onClick={() => onMode('light')}>
              Light
            </button>
            <button type="button" aria-pressed={mode === 'dark'} onClick={() => onMode('dark')}>
              Dark
            </button>
          </div>
          <label className="app-accent">
            <span>Accent</span>
            <span className="app-accent__control">
              <input
                className="app-accent__picker"
                type="color"
                value={isHex(draft) ? draft : accent}
                aria-label="Accent color"
                onChange={(event) => {
                  setDraft(event.target.value);
                  onAccent(event.target.value);
                }}
              />
              <input
                className="app-accent__hex"
                value={draft}
                spellCheck={false}
                aria-label="Accent hex"
                onChange={(event) => setDraft(event.target.value)}
                onBlur={commitDraft}
                onKeyDown={(event) => {
                  if (event.key === 'Enter') commitDraft();
                }}
              />
            </span>
          </label>
        </div>
      ) : null}
    </div>
  );
}
