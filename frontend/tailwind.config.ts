import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}"],
  theme: {
    extend: {
      fontFamily: { sans: ["Inter", "system-ui", "sans-serif"] },
      colors: {
        brand: { DEFAULT: "#6366f1", dark: "#4f46e5" },
      },
    },
  },
  plugins: [],
};

export default config;
