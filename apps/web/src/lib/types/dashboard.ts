/**
 * Dashboard view types.
 *
 * RECONSTRUCTED during the 2026-09-03 reseed: this module was imported by the
 * recovered sources but was not among the 25 files the APK dev-build chunks
 * leaked. Every shape here is derived from actual usage in
 * `lib/mock/dashboard.ts`, `services/dashboard.ts` and
 * `hooks/queries/use-dashboard.ts`, so the mock data and the `/api/v1/dashboard/*`
 * responses both type-check against it.
 */
import type { LucideIcon } from "lucide-react";

export type NavItem = {
  label: string;
  href: string;
  icon: LucideIcon;
  section?: string;
};

export type Topic = {
  name: string;
  value: number; // mastery percentage, 0–100
  color: string;
};

export type RadarAxis = {
  label: string;
  value: number; // 0–1
};

export type Metric = {
  label: string;
  value: string; // pre-formatted for display ("142ms", "89%")
  icon: string; // lucide icon name, resolved by the renderer
};

export type DashboardStats = {
  accuracy: number;
  questions: number;
  percentile: number;
  speed: number;
};

export type StreakData = {
  current: number;
  xp: number;
  days: boolean[];
  labels: string[];
};

export type UpcomingEvent = {
  title: string;
  time: string;
  tag: string; // "LIVE" | "MOCK" | "GROUP"
};

export type LeaderboardEntry = {
  rank: number;
  name: string;
  xp: number;
  me?: boolean;
};

export type HomeRecentActivityItem = {
  label: string;
  score: string;
  time: string;
};
