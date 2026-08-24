import type { Config } from "tailwindcss";

/**
 * Colours are declared as CSS variables in globals.css and referenced here, so
 * a single token definition drives both themes. `<alpha-value>` keeps Tailwind's
 * opacity modifiers (`bg-surface/60`) working against a variable.
 */
const config: Config = {
  darkMode: "class",
  content: ["./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        canvas: "rgb(var(--canvas) / <alpha-value>)",
        surface: "rgb(var(--surface) / <alpha-value>)",
        raised: "rgb(var(--raised) / <alpha-value>)",
        line: "rgb(var(--line) / <alpha-value>)",
        "line-strong": "rgb(var(--line-strong) / <alpha-value>)",
        ink: "rgb(var(--ink) / <alpha-value>)",
        "ink-muted": "rgb(var(--ink-muted) / <alpha-value>)",
        "ink-faint": "rgb(var(--ink-faint) / <alpha-value>)",
        accent: "rgb(var(--accent) / <alpha-value>)",
        "accent-ink": "rgb(var(--accent-ink) / <alpha-value>)",
        live: "rgb(var(--live) / <alpha-value>)",
        pass: "rgb(var(--pass) / <alpha-value>)",
        warn: "rgb(var(--warn) / <alpha-value>)",
        fail: "rgb(var(--fail) / <alpha-value>)",
      },
      fontFamily: {
        sans: ["var(--font-sans)"],
        mono: ["var(--font-mono)"],
      },
      fontSize: {
        // A deliberate floor: the previous design used 9–10px for primary data.
        "2xs": ["0.6875rem", { lineHeight: "1rem" }],
      },
      borderRadius: {
        sm: "4px",
        DEFAULT: "6px",
        md: "8px",
        lg: "10px",
      },
      boxShadow: {
        overlay: "0 16px 48px -12px rgb(0 0 0 / 0.45)",
      },
      keyframes: {
        "fade-up": {
          from: { opacity: "0", transform: "translateY(4px)" },
          to: { opacity: "1", transform: "translateY(0)" },
        },
        breathe: {
          "0%, 100%": { opacity: "1" },
          "50%": { opacity: "0.35" },
        },
        sweep: {
          from: { transform: "translateX(-100%)" },
          to: { transform: "translateX(200%)" },
        },
      },
      animation: {
        "fade-up": "fade-up 160ms ease-out",
        breathe: "breathe 1.8s ease-in-out infinite",
        sweep: "sweep 1.4s ease-in-out infinite",
      },
    },
  },
  plugins: [],
};

export default config;
