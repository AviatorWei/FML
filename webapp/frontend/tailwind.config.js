/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,jsx}"],
  theme: {
    extend: {
      colors: {
        pitch: {
          50: "#effdf5",
          100: "#d8fbe8",
          200: "#b3f5d1",
          300: "#75e9af",
          400: "#36d486",
          500: "#10b968",
          600: "#059553",
          700: "#067544",
          800: "#0a5c39",
          900: "#0a4c31",
        },
        ink: {
          800: "#13261f",
          900: "#0b1a14",
        },
      },
      fontFamily: {
        sans: ["Inter", "system-ui", "Segoe UI", "Roboto", "sans-serif"],
      },
      boxShadow: {
        card: "0 1px 2px rgba(16,40,30,0.06), 0 8px 24px rgba(16,40,30,0.08)",
      },
    },
  },
  plugins: [],
};
