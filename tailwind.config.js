/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    "./templates/**/*.html",
    "./static/js/**/*.js",
  ],
  theme: {
    extend: {
      colors: {
        'brand-midnight': '#0A0F1E',
        'brand-amber': '#C8922A',
        'brand-gold': '#E8B84B',
      },
      fontFamily: {
        'display': ['"DM Serif Display"', 'Georgia', 'serif'],
        'mono': ['"DM Mono"', 'monospace'],
        'sans': ['"DM Sans"', 'sans-serif'],
      },
    },
  },
  plugins: [],
}
