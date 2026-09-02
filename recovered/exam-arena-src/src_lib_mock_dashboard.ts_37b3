import type { NavItem, Topic, RadarAxis, Metric, DashboardStats, StreakData, UpcomingEvent, LeaderboardEntry, HomeRecentActivityItem } from "@/lib/types/dashboard";
import {
  Home,
  Zap,
  LineChart,
  User,
  Settings,
  LayoutGrid,
  Trophy,
  Award,
  Bell,
  HelpCircle,
  Clock,
  BookOpen,
  Calendar,
  Swords,
  Library,
  CreditCard,
  Users,
  FileText,
  GraduationCap,
  Gamepad2,
  Sparkles,
  Target,
} from "lucide-react";

export const NAV_ITEMS: NavItem[] = [
  { label: "Dashboard", href: "/dashboard", icon: Home, section: "Main" },
  { label: "Sprints", href: "/dashboard/configure-sprint", icon: Zap, section: "Training" },
  { label: "History", href: "/dashboard/history", icon: Clock, section: "Training" },
  { label: "Practice", href: "/dashboard/practice", icon: BookOpen, section: "Training" },
  { label: "Analytics", href: "/dashboard/analytics", icon: LineChart, section: "Training" },
  { label: "Leaderboard", href: "/dashboard/leaderboard", icon: Trophy, section: "Training" },
  { label: "Profile", href: "/dashboard/profile", icon: User, section: "Account" },
  { label: "Achievements", href: "/dashboard/achievements", icon: Award, section: "Account" },
  { label: "Duel", href: "/dashboard/duel", icon: Swords, section: "Account" },
  { label: "Settings", href: "/dashboard/settings", icon: Settings, section: "Account" },
  { label: "Friends", href: "/dashboard/friends", icon: Users, section: "Account" },
  { label: "Planner", href: "/dashboard/planner", icon: Calendar, section: "Support" },
  { label: "Reports", href: "/dashboard/reports", icon: FileText, section: "Support" },
  { label: "Notifications", href: "/dashboard/notifications", icon: Bell, section: "Support" },
  { label: "Help & About", href: "/dashboard/help", icon: HelpCircle, section: "Support" },
  { label: "Question Bank", href: "/dashboard/questions", icon: Library, section: "Resources" },
  { label: "Flashcards", href: "/dashboard/flashcards", icon: CreditCard, section: "Resources" },
];

export const MOBILE_NAV: NavItem[] = [
  { label: "Home", href: "/dashboard", icon: Home },
  { label: "Learn", href: "/dashboard/learn", icon: BookOpen },
  { label: "Play", href: "/dashboard/play", icon: Zap },
  { label: "Setting", href: "/dashboard/settings", icon: Settings },
];

const RADAR_AXES: RadarAxis[] = [
  { label: "Speed", value: 0.9 },
  { label: "Logic", value: 0.75 },
  { label: "Stamina", value: 0.7 },
  { label: "Focus", value: 0.8 },
  { label: "Memory", value: 0.72 },
  { label: "Reflex", value: 0.85 },
];

const METRICS: Metric[] = [
  { label: "Action Delay", value: "142ms", icon: "Zap" },
  { label: "Focus Density", value: "89%", icon: "TrendingUp" },
];

const DASHBOARD_DATA_BY_DOMAIN: Record<string, {
  topics: Topic[];
  stats: DashboardStats;
  upcoming: UpcomingEvent[];
  recent: HomeRecentActivityItem[];
}> = {
  "vedic-math": {
    topics: [
      { name: "Addition", value: 92, color: "primary" },
      { name: "Subtraction", value: 78, color: "primary" },
      { name: "Multiplication", value: 64, color: "primary" },
      { name: "Division", value: 85, color: "primary" },
      { name: "Squares", value: 41, color: "primary" },
    ],
    stats: { accuracy: 87, questions: 1247, percentile: 64, speed: 47 },
    upcoming: [
      { title: "Sprint Duel", time: "Today, 8PM", tag: "LIVE" },
      { title: "Vedic Math Challenge", time: "Thu, 10AM", tag: "MOCK" },
      { title: "Group Challenge", time: "Sat, 3PM", tag: "GROUP" },
    ],
    recent: [
      { label: "Speed Mult. Sprint", score: "22/25", time: "2h ago" },
      { label: "Division Set #14", score: "18/20", time: "Yesterday" },
      { label: "Full Vedic Mock", score: "142/200", time: "2d ago" },
    ],
  },
  gmat: {
    topics: [
      { name: "Problem Solving", value: 85, color: "primary" },
      { name: "Data Sufficiency", value: 72, color: "primary" },
      { name: "Sentence Correction", value: 68, color: "primary" },
      { name: "Critical Reasoning", value: 79, color: "primary" },
      { name: "Reading Comprehension", value: 60, color: "primary" },
    ],
    stats: { accuracy: 82, questions: 890, percentile: 71, speed: 95 },
    upcoming: [
      { title: "GMAT Quant Sprint", time: "Today, 7PM", tag: "LIVE" },
      { title: "Mock GMAT #3", time: "Sat, 9AM", tag: "MOCK" },
      { title: "Verbal Drill", time: "Mon, 6PM", tag: "GROUP" },
    ],
    recent: [
      { label: "DS Practice Set", score: "14/20", time: "3h ago" },
      { label: "SC Timed Drill", score: "16/18", time: "Yesterday" },
      { label: "CR Passage Set", score: "10/12", time: "2d ago" },
    ],
  },
  cat: {
    topics: [
      { name: "Quantitative Aptitude", value: 92, color: "primary" },
      { name: "Logical Reasoning", value: 78, color: "primary" },
      { name: "Data Interpretation", value: 85, color: "primary" },
      { name: "Verbal Ability", value: 64, color: "primary" },
      { name: "General Knowledge", value: 41, color: "primary" },
    ],
    stats: { accuracy: 85, questions: 2100, percentile: 68, speed: 72 },
    upcoming: [
      { title: "LRDI Sprint", time: "Today, 8PM", tag: "LIVE" },
      { title: "Mock CAT #7", time: "Thu, 10AM", tag: "MOCK" },
      { title: "VA Sectional", time: "Sat, 3PM", tag: "GROUP" },
    ],
    recent: [
      { label: "LR Sprint", score: "22/25", time: "2h ago" },
      { label: "Quant Set #14", score: "18/20", time: "Yesterday" },
      { label: "Full CAT Mock", score: "142/300", time: "2d ago" },
    ],
  },
  gre: {
    topics: [
      { name: "Quantitative Reasoning", value: 88, color: "primary" },
      { name: "Verbal Reasoning", value: 72, color: "primary" },
      { name: "Text Completion", value: 65, color: "primary" },
      { name: "Sentence Equivalence", value: 70, color: "primary" },
      { name: "Reading Comprehension", value: 75, color: "primary" },
    ],
    stats: { accuracy: 80, questions: 760, percentile: 74, speed: 88 },
    upcoming: [
      { title: "Quant Comparison", time: "Today, 6PM", tag: "LIVE" },
      { title: "Verbal Drill #4", time: "Fri, 11AM", tag: "MOCK" },
      { title: "Practice Test", time: "Sun, 9AM", tag: "GROUP" },
    ],
    recent: [
      { label: "QC Practice", score: "15/18", time: "1h ago" },
      { label: "TC Passage Set", score: "11/14", time: "Yesterday" },
      { label: "SE Timed Quiz", score: "16/20", time: "3d ago" },
    ],
  },
  banking: {
    topics: [
      { name: "Numerical Ability", value: 86, color: "primary" },
      { name: "Reasoning Ability", value: 74, color: "primary" },
      { name: "English Language", value: 70, color: "primary" },
      { name: "General Awareness", value: 55, color: "primary" },
      { name: "Computer Knowledge", value: 62, color: "primary" },
    ],
    stats: { accuracy: 78, questions: 1560, percentile: 72, speed: 55 },
    upcoming: [
      { title: "Reasoning Sprint", time: "Today, 7PM", tag: "LIVE" },
      { title: "Mock Bank Exam", time: "Sat, 10AM", tag: "MOCK" },
      { title: "GA Weekly Quiz", time: "Mon, 8PM", tag: "GROUP" },
    ],
    recent: [
      { label: "Numerical Speed Run", score: "20/25", time: "3h ago" },
      { label: "Reasoning Puzzle Set", score: "14/16", time: "Yesterday" },
      { label: "English RC Passages", score: "17/20", time: "2d ago" },
    ],
  },
};

export function getDashboardData(domain: string) {
  const data = DASHBOARD_DATA_BY_DOMAIN[domain] ?? DASHBOARD_DATA_BY_DOMAIN["cat"];
  return {
    topics: data.topics,
    radarAxes: RADAR_AXES,
    metrics: METRICS,
    stats: data.stats,
    streak: {
      current: 6,
      xp: 2340,
      days: [true, true, true, false, true, true, false],
      labels: ["M", "T", "W", "T", "F", "S", "S"],
    } as StreakData,
    upcoming: data.upcoming,
    leaderboard: [
      { rank: 1, name: "Priya S.", xp: 4820 },
      { rank: 2, name: "Arjun M.", xp: 4310 },
      { rank: 3, name: "Rohan K.", xp: 3990 },
      { rank: 47, name: "You", xp: 2340, me: true },
    ] as LeaderboardEntry[],
    recent: data.recent,
  };
}
