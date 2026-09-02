import type { Metadata, Viewport } from "next";
import type { ReactNode } from "react";

export const metadata: Metadata = {
  title: "Exam Arena — Competitive Learning Platform",
  description:
    "Not a coaching platform. A competitive battlefield where India's sharpest minds fight, rank, and rise.",
  manifest: "/manifest.webmanifest",
};

export const viewport: Viewport = {
  themeColor: "#050505",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <body
        style={{
          margin: 0,
          background: "#050505",
          color: "#f5f5f5",
          fontFamily: "system-ui, -apple-system, sans-serif",
        }}
      >
        {children}
      </body>
    </html>
  );
}
