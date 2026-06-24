/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        brand: {
          50: "#eef6ff",
          100: "#d9eaff",
          300: "#9ec6f3",
          400: "#5e98e6",
          500: "#2f7ce0",
          600: "#1f63c4",
          700: "#1a4f9c",
        },
      },
    },
  },
  plugins: [require("@tailwindcss/forms")],
};
