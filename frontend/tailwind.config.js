/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        primary: {
          50: '#eef2ff',
          100: '#e0e7ff',
          500: '#6366f1',
          600: '#4f46e5',
          700: '#4338ca',
        },
      },
      boxShadow: {
        'primary': '0 10px 40px -10px rgba(99, 102, 241, 0.4)',
        'primary-lg': '0 20px 50px -15px rgba(99, 102, 241, 0.35)',
        'red-glow': '0 10px 40px -10px rgba(239, 68, 68, 0.35)',
      },
    },
  },
  plugins: [],
}
