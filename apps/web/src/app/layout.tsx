import type { Metadata, Viewport } from "next";
import type { ReactNode } from "react";

import "katex/dist/katex.min.css";
import "./globals.css";
import { CapacitorInit } from "./capacitor-init";
import { AppEntry } from "@/components/ui/app-entry";
import { OnlineProvider } from "@/providers/online-provider";
import { QueryProvider } from "@/providers/query-provider";
import { ThemeProvider } from "@/providers/theme-provider";

export const metadata: Metadata = {
  title: "Exam Arena — Competitive Learning Platform",
  description:
    "Not a coaching platform. A competitive battlefield where India's sharpest minds fight, rank, and rise.",
  manifest: "/manifest.webmanifest",
};

export const viewport: Viewport = {
  themeColor: "#050505",
  width: "device-width",
  initialScale: 1,
  viewportFit: "cover",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en" className="loading">
      <body>
        <QueryProvider>
          <ThemeProvider>
            <OnlineProvider>
              <CapacitorInit />
              <AppEntry>{children}</AppEntry>
            </OnlineProvider>
          </ThemeProvider>
        </QueryProvider>
      </body>
    </html>
  );
}
