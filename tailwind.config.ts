import type { Config } from 'tailwindcss'

export default {
  content: [
    './app/**/*.{vue,ts,js}',
    './app.vue',
  ],
  darkMode: 'class',
  theme: {
    extend: {
      colors: {
        cardiac: {
          red: '#e31b1b',
          'red-dim': '#9b1010',
          'red-glow': '#ff3333',
          blue: '#1a6fff',
          'blue-dim': '#0d3d99',
          'blue-glow': '#4d9fff',
          navy: '#030d1a',
          'navy-light': '#071428',
          'navy-card': '#0a1f3a',
          'navy-border': '#102a50',
          electric: '#00d4ff',
          pulse: '#ff6b35',
          safe: '#22c55e',
          warn: '#f59e0b',
          muted: '#94a3b8',
        },
      },
      fontFamily: {
        mono: ['JetBrains Mono', 'Fira Code', 'Consolas', 'monospace'],
        sans: ['Inter', 'system-ui', 'sans-serif'],
      },
      animation: {
        pulse: 'pulse 1s cubic-bezier(0.4, 0, 0.6, 1) infinite',
        'pulse-slow': 'pulse 2s cubic-bezier(0.4, 0, 0.6, 1) infinite',
        'ecg-draw': 'ecgDraw 2s linear infinite',
        'float-up': 'floatUp 3s ease-in-out infinite',
        'glow-red': 'glowRed 2s ease-in-out infinite',
        'glow-blue': 'glowBlue 2s ease-in-out infinite',
        'scan-line': 'scanLine 3s linear infinite',
      },
      keyframes: {
        ecgDraw: {
          '0%': { strokeDashoffset: '1000' },
          '100%': { strokeDashoffset: '0' },
        },
        floatUp: {
          '0%, 100%': { transform: 'translateY(0)' },
          '50%': { transform: 'translateY(-8px)' },
        },
        glowRed: {
          '0%, 100%': { boxShadow: '0 0 5px #e31b1b, 0 0 10px #e31b1b' },
          '50%': { boxShadow: '0 0 15px #e31b1b, 0 0 30px #e31b1b44' },
        },
        glowBlue: {
          '0%, 100%': { boxShadow: '0 0 5px #1a6fff, 0 0 10px #1a6fff' },
          '50%': { boxShadow: '0 0 15px #1a6fff, 0 0 30px #1a6fff44' },
        },
        scanLine: {
          '0%': { transform: 'translateY(-100%)' },
          '100%': { transform: 'translateY(200%)' },
        },
      },
      backgroundImage: {
        'ecg-grid': `
          linear-gradient(rgba(227,27,27,0.06) 1px, transparent 1px),
          linear-gradient(90deg, rgba(227,27,27,0.06) 1px, transparent 1px)
        `,
        'cardiac-gradient': 'linear-gradient(135deg, #030d1a 0%, #071428 50%, #030d1a 100%)',
      },
      backgroundSize: {
        'ecg-grid': '40px 40px',
      },
      backdropBlur: {
        xs: '2px',
      },
    },
  },
  plugins: [],
} satisfies Config
