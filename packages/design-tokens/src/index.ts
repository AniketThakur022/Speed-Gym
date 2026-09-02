/** Exam Arena design tokens — lime-on-black identity from the shipped APK. */

export const colors = {
  brand: {
    lime: "#C8FF5A",
    black: "#050505",
  },
  surface: {
    base: "#050505",
    raised: "#111111",
    overlay: "#1A1A1A",
  },
  text: {
    primary: "#F5F5F5",
    secondary: "#A3A3A3",
    inverse: "#050505",
    accent: "#C8FF5A",
  },
  state: {
    fluid: "#C8FF5A",
    fragile: "#FFB020",
    fractured: "#FF4D4D",
  },
} as const;

export const radii = { sm: "6px", md: "10px", lg: "16px", pill: "999px" } as const;

export const spacing = { xs: "4px", sm: "8px", md: "16px", lg: "24px", xl: "40px" } as const;

export const fonts = {
  body: "system-ui, -apple-system, 'Segoe UI', sans-serif",
  mono: "'SF Mono', ui-monospace, monospace",
} as const;
