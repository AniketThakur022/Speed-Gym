import type { Config } from "tailwindcss";

/**
 * Token names mirror the class names used by the recovered Exam Arena pages
 * (see src/app/globals.css for why these were reconstructed). `fluid-*` font
 * sizes are viewport-interpolated: the app targets phones through desktop from
 * one static export.
 */
const config: Config = {
  content: ["./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        background: "hsl(var(--background))",
        foreground: "hsl(var(--foreground))",
        card: { DEFAULT: "hsl(var(--card))", foreground: "hsl(var(--card-foreground))" },
        primary: { DEFAULT: "hsl(var(--primary))", foreground: "hsl(var(--primary-foreground))" },
        muted: { DEFAULT: "hsl(var(--muted))", foreground: "hsl(var(--muted-foreground))" },
        accent: { DEFAULT: "hsl(var(--accent))", foreground: "hsl(var(--accent-foreground))" },
        border: "hsl(var(--border))",
        input: "hsl(var(--input))",
        ring: "hsl(var(--ring))",
      },
      borderRadius: {
        lg: "var(--radius)",
        md: "calc(var(--radius) - 2px)",
        sm: "calc(var(--radius) - 4px)",
      },
      fontSize: {
        "fluid-xs": "clamp(0.72rem, 0.68rem + 0.2vw, 0.8rem)",
        "fluid-sm": "clamp(0.84rem, 0.79rem + 0.25vw, 0.95rem)",
        "fluid-base": "clamp(0.95rem, 0.89rem + 0.3vw, 1.08rem)",
        "fluid-lg": "clamp(1.12rem, 1.02rem + 0.5vw, 1.35rem)",
        "fluid-xl": "clamp(1.35rem, 1.16rem + 0.9vw, 1.9rem)",
        "fluid-2xl": "clamp(1.7rem, 1.35rem + 1.6vw, 2.75rem)",
      },
    },
  },
  plugins: [],
};

export default config;
