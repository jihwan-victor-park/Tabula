/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  darkMode: ['class', '[data-mode="dark"]'],
  theme: {
    extend: {
      colors: {
        accent: 'var(--accent)',
        'accent-foreground': 'var(--accent-foreground)',
        background: 'var(--background)',
        foreground: 'var(--foreground)',
        card: 'var(--card)',
        'card-foreground': 'var(--card-foreground)',
        border: 'var(--border)',
        muted: 'var(--muted)',
        'muted-foreground': 'var(--muted-foreground)',
        primary: 'var(--primary)',
        'primary-foreground': 'var(--primary-foreground)',
        secondary: 'var(--secondary)',
        'secondary-foreground': 'var(--secondary-foreground)',
        sidebar: 'var(--sidebar)',
        'sidebar-accent': 'var(--sidebar-accent)',
        'sidebar-foreground': 'var(--sidebar-foreground)',
        info: 'var(--color-info)',
        success: 'var(--color-success)',
        warning: 'var(--color-warning)',
        error: 'var(--color-error)',
      },
      borderRadius: {
        none: 'var(--radius-none)',
        md: 'var(--radius-m)',
        pill: 'var(--radius-pill)',
      },
      fontFamily: {
        sans: ['"Geist"', 'system-ui', 'sans-serif'],
        mono: ['"JetBrains Mono"', 'monospace'],
        logo: ['"JetBrains Mono"', 'monospace'],
      },
      boxShadow: {
        panel: '0 1px 0 rgba(42, 45, 90, 1)',
        bubble: '0 2px 4px rgba(0, 0, 0, 0.2)',
      },
    },
  },
  plugins: [],
};
