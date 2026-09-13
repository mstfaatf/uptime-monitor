import type { Config } from 'tailwindcss'

export default {
  content: ['./app/**/*.{ts,tsx}', './components/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        // Locked palette, referenced directly (plain hex custom properties — no hsl() wrapper,
        // unlike shadcn's generated default). See globals.css :root for the source of truth.
        surface: {
          base: 'var(--bg-base)',
          DEFAULT: 'var(--bg-surface)',
          raised: 'var(--bg-surface-raised)',
        },
        fg: {
          primary: 'var(--text-primary)',
          secondary: 'var(--text-secondary)',
        },
        signal: {
          up: 'var(--signal-up)',
          warning: 'var(--signal-warning)',
          down: 'var(--signal-down)',
          pending: 'var(--signal-pending)',
        },
        border: 'var(--border)',

        // shadcn/ui semantic slots — kept so every generated component (Button, Card, ...)
        // resolves to real utility classes; each one is aliased to the locked palette above
        // via globals.css, not left at shadcn's generated neutral scale.
        background: 'var(--background)',
        foreground: 'var(--foreground)',
        card: {
          DEFAULT: 'var(--card)',
          foreground: 'var(--card-foreground)',
        },
        popover: {
          DEFAULT: 'var(--popover)',
          foreground: 'var(--popover-foreground)',
        },
        primary: {
          DEFAULT: 'var(--primary)',
          foreground: 'var(--primary-foreground)',
        },
        secondary: {
          DEFAULT: 'var(--secondary)',
          foreground: 'var(--secondary-foreground)',
        },
        muted: {
          DEFAULT: 'var(--muted)',
          foreground: 'var(--muted-foreground)',
        },
        accent: {
          DEFAULT: 'var(--accent)',
          foreground: 'var(--accent-foreground)',
        },
        destructive: 'var(--destructive)',
        input: 'var(--input)',
        ring: 'var(--ring)',
      },
      borderRadius: {
        // Instrument-panel radius throughout (2-4px), not shadcn's generated 0.5rem (8px)
        // default — every radius utility a component might use tops out at 4px.
        DEFAULT: 'var(--radius)',
        sm: 'var(--radius-sm)',
        md: 'var(--radius)',
        lg: 'var(--radius)',
      },
      fontFamily: {
        // Wired to next/font/google's CSS variables in app/layout.tsx.
        sans: ['var(--font-sans)', 'system-ui', 'sans-serif'],
        mono: ['var(--font-mono)', 'ui-monospace', 'monospace'],
      },
    },
  },
  plugins: [require('tailwindcss-animate')],
} satisfies Config
