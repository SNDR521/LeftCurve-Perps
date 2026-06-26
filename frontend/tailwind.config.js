/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,jsx}'],
  theme: {
    extend: {
      colors: {
        bg: {
          primary:   '#111213',
          secondary: '#161718',
          card:      '#1e2024',
          elevated:  '#242629',
          border:    '#2a2c30',
          hover:     '#2e3038',
        },
        accent: {
          blue:        '#4f6ef7',
          'blue-hover':'#4060e6',
          teal:        '#00d4aa',
          'teal-hover':'#00bfa0',
        },
        text: {
          primary:   '#fcfefd',
          secondary: '#8d91a6',
          muted:     '#4e5166',
        },
        profit:      '#00d4aa',
        'profit-bg': 'rgba(0,212,170,0.08)',
        loss:        '#de576f',
        'loss-bg':   'rgba(222,87,111,0.08)',
      },
      fontFamily: {
        sans: ['"DM Sans"', 'system-ui', 'sans-serif'],
        mono: ['"JetBrains Mono"', '"Fira Code"', 'monospace'],
      },
      borderRadius: {
        card: '10px',
      },
    },
  },
  plugins: [],
}
