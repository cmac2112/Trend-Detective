// CSV downloads, built in the browser from results already on screen (no extra API calls).
// Plain comma-separated with one header row, so they open in Excel/Sheets/pandas and load
// into hydrology tools such as CUAHSI HydroShare.

import type { AnalyzeResult, CompareResult, ScanResult, TrendMap } from "./api";

type Cell = string | number | boolean | null | undefined;

function csv(rows: Cell[][]): string {
  const esc = (v: Cell) => {
    if (v == null || (typeof v === "number" && !Number.isFinite(v))) return "";
    const s = String(v);
    return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
  };
  return rows.map((r) => r.map(esc).join(",")).join("\r\n") + "\r\n";
}

const slug = (s: string) =>
  s
    .normalize("NFKD")
    .replace(/[̀-ͯ]/g, "")
    .replace(/[^A-Za-z0-9]+/g, "-")
    .replace(/^-|-$/g, "")
    .toLowerCase() || "region";

function save(name: string, text: string) {
  const url = URL.createObjectURL(new Blob([text], { type: "text/csv;charset=utf-8" }));
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

/** Monthly values and anomalies for one region. */
export function downloadSeries(r: AnalyzeResult, regionName: string) {
  const u = r.variable.units;
  const rows: Cell[][] = [["month", `${r.variable.key} (${u})`, `anomaly (${u})`]];
  for (const p of r.series ?? []) rows.push([p.date, p.value, p.anomaly]);
  save(`trend-detective_${r.variable.key}_${slug(regionName)}_${r.stats.start}_${r.stats.end}.csv`, csv(rows));
}

/** One row per grid cell: where it is, its trend and whether that's significant. */
export function downloadTrendMap(m: TrendMap, variableKey: string, regionName: string) {
  const rows: Cell[][] = [["lat", "lon", `slope_per_decade (${m.units})`, "p_value", "significant_fdr"]];
  m.lat.forEach((lat, i) =>
    m.lon.forEach((lon, j) => {
      const s = m.slope_per_decade[i][j];
      if (s != null) rows.push([lat, lon, s, m.p_value[i][j], m.significant[i][j]]);
    }),
  );
  save(`trend-detective_${variableKey}_${slug(regionName)}_trend-map.csv`, csv(rows));
}

/** Every region's monthly values side by side. */
export function downloadCompare(r: CompareResult) {
  const ok = r.regions.filter((x) => x.error === undefined);
  const byMonth = new Map<string, Map<string, number>>();
  for (const reg of ok) {
    if (reg.error !== undefined) continue;
    for (const p of reg.series ?? []) {
      if (!byMonth.has(p.date)) byMonth.set(p.date, new Map());
      byMonth.get(p.date)!.set(reg.name, p.value);
    }
  }
  const names = ok.map((x) => x.name);
  const rows: Cell[][] = [["month", ...names.map((n) => `${n} (${r.variable.units})`)]];
  for (const month of [...byMonth.keys()].sort()) rows.push([month, ...names.map((n) => byMonth.get(month)!.get(n))]);
  save(`trend-detective_${r.variable.key}_compare_${r.start}_${r.end}.csv`, csv(rows));
}

/** The ranked scan table. */
export function downloadScan(r: ScanResult, regionName: string) {
  const rows: Cell[][] = [[
    "rank", "variable", "name", "units", "trend", "slope_per_decade", "ci95_low", "ci95_high",
    "percent_of_mean_per_decade", "change_vs_normal_variation", "t_test_p", "mann_kendall_p",
    "significant_after_correction", "opposite_trends_inside", "worldwide_trend", "start", "end",
  ]];
  for (const v of r.variables) {
    rows.push([
      v.rank, v.key, v.name, v.units, v.level, v.slope_per_decade, v.ci95_per_decade[0], v.ci95_per_decade[1],
      v.percent_of_mean_per_decade, v.change_in_sd_per_decade, v.p_value, v.mk_p_value,
      v.passes_fdr, v.mixed_inside_region, !!v.global_note, v.start, v.end,
    ]);
  }
  save(`trend-detective_scan_${slug(regionName)}.csv`, csv(rows));
}
