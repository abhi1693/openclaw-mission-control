/** @type {import('tailwindcss').Config} */
module.exports = {
  darkMode: ["class"],
  content: ["./src/**/*.{ts,tsx}", "./app/**/*.{ts,tsx}"],
  theme: {
    extend: {
      fontFamily: {
        heading: ["var(--font-heading)", "sans-serif"],
        body: ["var(--font-body)", "sans-serif"],
        display: ["var(--font-display)", "serif"],
        pixel: ["'Courier New'", "Courier", "monospace"],
      },
      animation: {
        'pixel-blink': 'pixel-blink 0.8s infinite',
        'pixel-bounce': 'pixel-bounce 0.6s infinite',
        'pixel-flicker': 'pixel-flicker 3s infinite',
        'pixel-slide-in': 'pixel-slide-in 0.3s ease-out',
        'gradient-shift': 'gradient-shift 3s ease infinite',
        'pulse-expand': 'pulse-expand 1.5s infinite',
      },
      keyframes: {
        pixel_blink: {
          '0%, 100%': { opacity: '1' },
          '50%': { opacity: '0' },
        },
        pixel_bounce: {
          '0%, 100%': { transform: 'translateY(0)' },
          '50%': { transform: 'translateY(-4px)' },
        },
        pixel_flicker: {
          '0%, 19%, 21%, 23%, 25%, 54%, 56%, 100%': { opacity: '1' },
          '20%, 24%, 55%': { opacity: '0.4' },
        },
        pixel_slide_in: {
          'from': { opacity: '0', transform: 'translateX(-10px)' },
          'to': { opacity: '1', transform: 'translateX(0)' },
        },
        gradient_shift: {
          '0%': { backgroundPosition: '0% 50%' },
          '50%': { backgroundPosition: '100% 50%' },
          '100%': { backgroundPosition: '0% 50%' },
        },
        pulse_expand: {
          '0%': { transform: 'scale(1)', opacity: '0.8' },
          '100%': { transform: 'scale(2)', opacity: '0' },
        },
      },
      boxShadow: {
        'pixel': '4px 4px 0 0 var(--surface-muted)',
        'pixel-hover': '6px 6px 0 0 var(--surface-muted)',
        'neon': '0 0 5px var(--accent), 0 0 10px var(--accent), 0 0 20px rgba(37, 99, 235, 0.3)',
        'neon-success': '0 0 5px var(--success), 0 0 10px var(--success), 0 0 20px rgba(22, 163, 74, 0.3)',
        'neon-warning': '0 0 5px var(--warning), 0 0 10px var(--warning), 0 0 20px rgba(217, 119, 6, 0.3)',
        'neon-danger': '0 0 5px var(--danger), 0 0 10px var(--danger), 0 0 20px rgba(220, 38, 38, 0.3)',
      },
    },
  },
  plugins: [require("tailwindcss-animate")],
};
