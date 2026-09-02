import { getDashboardData } from "@/lib/mock/dashboard";
import type { Topic, RadarAxis, Metric, DashboardStats, StreakData, UpcomingEvent, LeaderboardEntry, HomeRecentActivityItem } from "@/lib/types/dashboard";
import { apiGet } from "./api";

const IS_MOCK = process.env.NEXT_PUBLIC_API_MOCK !== "false";

function delay(ms: number) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

export async function getTopicMastery(domain?: string): Promise<Topic[]> {
  if (IS_MOCK) {
    await delay(250);
    return getDashboardData(domain ?? "").topics;
  }
  const params = domain ? `?domain=${domain}` : "";
  return apiGet<Topic[]>(`/dashboard/topics${params}`);
}

export async function getRadarAxes(_domain?: string): Promise<RadarAxis[]> {
  if (IS_MOCK) {
    await delay(150);
    return getDashboardData("").radarAxes;
  }
  return apiGet<RadarAxis[]>("/dashboard/radar");
}

export async function getDashboardMetrics(_domain?: string): Promise<Metric[]> {
  if (IS_MOCK) {
    await delay(100);
    return getDashboardData("").metrics;
  }
  return apiGet<Metric[]>("/dashboard/metrics");
}

export async function getDashboardStats(domain?: string): Promise<DashboardStats> {
  if (IS_MOCK) {
    await delay(120);
    return getDashboardData(domain ?? "").stats;
  }
  const params = domain ? `?domain=${domain}` : "";
  return apiGet<DashboardStats>(`/dashboard/stats${params}`);
}

export async function getStreakData(_domain?: string): Promise<StreakData> {
  if (IS_MOCK) {
    await delay(80);
    return getDashboardData("").streak;
  }
  return apiGet<StreakData>("/dashboard/streak");
}

export async function getUpcomingEvents(domain?: string): Promise<UpcomingEvent[]> {
  if (IS_MOCK) {
    await delay(100);
    return getDashboardData(domain ?? "").upcoming;
  }
  const params = domain ? `?domain=${domain}` : "";
  return apiGet<UpcomingEvent[]>(`/dashboard/events${params}`);
}

export async function getLeaderboard(_domain?: string): Promise<LeaderboardEntry[]> {
  if (IS_MOCK) {
    await delay(200);
    return getDashboardData("").leaderboard;
  }
  return apiGet<LeaderboardEntry[]>("/dashboard/leaderboard");
}

export async function getHomeRecentActivity(domain?: string): Promise<HomeRecentActivityItem[]> {
  if (IS_MOCK) {
    await delay(90);
    return getDashboardData(domain ?? "").recent;
  }
  const params = domain ? `?domain=${domain}` : "";
  return apiGet<HomeRecentActivityItem[]>(`/dashboard/recent-activity${params}`);
}
