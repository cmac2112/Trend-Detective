import type { AnalyzeResult } from "./api";

export type TrendLevel = "significant" | "possible" | "none";

/** Same rule as the API: significant when both tests agree, borderline when only one does. */
export function trendLevel(r: AnalyzeResult): TrendLevel {
  const t = r.stats.linear.p_value < 0.05;
  const mk = r.stats.mann_kendall.p_value < 0.05;
  return t && mk ? "significant" : t || mk ? "possible" : "none";
}
