import type { Config } from 'tailwindcss'

export default {
  darkMode: 'class',
  content: [
    './index.html',
    './src/**/*.{vue,ts}',
  ],
  theme: {
    extend: {
      colors: {
        // Semantic design tokens - all components reference these, never
        // raw gray-* values. Each palette defines these variables in main.css.
        bg:      'var(--color-bg)',
        sidebar: 'var(--color-sidebar)',
        surface: 'var(--color-surface)',
        'surface-raised': 'var(--color-surface-raised)',
        subtle:  'var(--color-subtle)',
        border:  { DEFAULT: 'var(--color-border)', input: 'var(--color-border-input)', strong: 'var(--color-border-strong)' },
        text:    'var(--color-text)',
        muted:   'var(--color-muted)',
        faint:   'var(--color-faint)',
        hover:   { DEFAULT: 'var(--color-hover)', subtle: 'var(--color-hover-subtle)' },
        skeleton: 'var(--color-skeleton)',
        // Accent scale: per-palette interactive color (buttons, focus rings, active states).
        accent: {
          DEFAULT: 'var(--accent)',
          hover:   'var(--accent-hover)',
          fg:      'var(--accent-fg)',
          ring:    'var(--accent-ring)',
        },
        // Gray scale kept for backwards compat and internal palette scale reference.
        gray: {
          50:  'var(--p-50)',
          100: 'var(--p-100)',
          200: 'var(--p-200)',
          300: 'var(--p-300)',
          400: 'var(--p-400)',
          500: 'var(--p-500)',
          600: 'var(--p-600)',
          700: 'var(--p-700)',
          800: 'var(--p-800)',
          850: 'var(--p-850)',
          900: 'var(--p-900)',
          950: 'var(--p-950)',
        },
      },
      borderRadius: {
        '4xl': '2rem',
      },
      boxShadow: {
        // Extends Tailwind's shadow-2xl for deep modal/panel shadows
        '3xl': '0 35px 60px -15px rgb(0 0 0 / 0.3)',
      },
      transitionProperty: {
        width: 'width',
      },
      transitionDuration: {
        fast: '150ms',
        base: '200ms',
        slow: '250ms',
      },
      fontFamily: {
        sans: ['var(--font-sans)', 'ui-sans-serif', 'system-ui', 'sans-serif'],
      },
    },
  },
  plugins: [],
} satisfies Config
