import { useEffect } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  getTopicMastery, getRadarAxes, getDashboardMetrics,
  getDashboardStats, getStreakData, getUpcomingEvents,
  getLeaderboard, getHomeRecentActivity,
} from "@/services/dashboard";
import { cacheQueryData } from "@/services/offline/sync";
import type { Topic, RadarAxis, Metric, DashboardStats, StreakData, UpcomingEvent, LeaderboardEntry, HomeRecentActivityItem } from "@/lib/types/dashboard";

type DashboardData = {
  topics: Topic[];
  radarAxes: RadarAxis[];
  metrics: Metric[];
  stats: DashboardStats;
  streak: StreakData;
  upcoming: UpcomingEvent[];
  leaderboard: LeaderboardEntry[];
  recent: HomeRecentActivityItem[];
};

async function fetchDashboardData(domain?: string): Promise<DashboardData> {
  const [topics, radarAxes, metrics, stats, streak, upcoming, leaderboard, recent] = await Promise.all([
    getTopicMastery(domain),
    getRadarAxes(domain),
    getDashboardMetrics(domain),
    getDashboardStats(domain),
    getStreakData(domain),
    getUpcomingEvents(domain),
    getLeaderboard(domain),
    getHomeRecentActivity(domain),
  ]);
  return { topics, radarAxes, metrics, stats, streak, upcoming, leaderboard, recent };
}

export function useDashboardData(domain?: string) {
  const query = useQuery<DashboardData>({
    queryKey: ["dashboard", domain],
    queryFn: () => fetchDashboardData(domain),
  });

  useEffect(() => {
    if (query.data) {
      cacheQueryData("dashboard", query.data);
    }
  }, [query.data]);

  return query;
}
