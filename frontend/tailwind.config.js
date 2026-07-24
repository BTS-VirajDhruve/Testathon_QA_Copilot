/** @type {import('tailwindcss').Config} */
module.exports = {
  content: ["./src/**/*.{js,ts,jsx,tsx,mdx}"],
  theme: {
    extend: {
      colors: {
        ink: {
          950: "#0c1210",
          900: "#121a17",
          800: "#1a2621",
          700: "#24332c",
          600: "#33463c",
        },
        mist: {
          50: "#f4f7f5",
          100: "#e8efeb",
          200: "#d2ddd6",
          300: "#b3c4ba",
        },
        brass: {
          400: "#c4a574",
          500: "#b08d55",
          600: "#8f7040",
        },
        pine: {
          500: "#2f6b57",
          600: "#245445",
          700: "#1b4034",
        },
        signal: {
          high: "#b54a3c",
          med: "#b08d55",
          low: "#2f6b57",
        },
      },
      fontFamily: {
        display: ["var(--font-display)", "Georgia", "serif"],
        sans: ["var(--font-sans)", "Helvetica Neue", "Arial", "sans-serif"],
        mono: ["var(--font-mono)", "ui-monospace", "monospace"],
      },
      boxShadow: {
        soft: "0 18px 50px rgba(12, 18, 16, 0.08)",
      },
      backgroundImage: {
        "grid-mist":
          "linear-gradient(to right, rgba(36,51,44,0.04) 1px, transparent 1px), linear-gradient(to bottom, rgba(36,51,44,0.04) 1px, transparent 1px)",
        "hero-wash":
          "radial-gradient(1200px 500px at 10% -10%, rgba(176,141,85,0.18), transparent 55%), radial-gradient(900px 400px at 90% 0%, rgba(47,107,87,0.16), transparent 50%), linear-gradient(180deg, #f4f7f5 0%, #e8efeb 100%)",
      },
    },
  },
  plugins: [],
};