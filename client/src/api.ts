// Typed client for the Trend Detective API (TrendApi/).

export const API_URL: string = import.meta.env.VITE_API_URL ?? "http://127.0.0.1:8000";

export type GeoJSONRegion = GeoJSON.Feature | GeoJSON.Polygon | GeoJSON.MultiPolygon | GeoJSON.FeatureCollection;

export interface VariableInfo {
  key: string;
  name: string;
  units: string;
  definition: string;
  category: string;
  source: string;
  related: string[];
  /** Non-empty when the variable's trend is about the same everywhere on Earth (e.g. CO2). */
  global_note: string;
  data_starts: string;
  /** Last month of a discontinued record, or null if the dataset is still updated. */
  data_ends: string | null;
  /** Global data stored on the server, if any. */
  local_global: { start: string; end: string; n_months: number } | null;
  /** Example regions stored on the server for this variable. */
  local_examples: string[];
}

export type DataSource = "local" | "cloud";

export interface Plan {
  /** "cache": analyzed recently, instant. "local": stored on the server. "cloud": streams from NASA. */
  source: DataSource | "cache";
  description: string;
  start: string;
  end: string;
  months: number;
  estimated_seconds: number;
}

export interface Job {
  id: string;
  variable: string;
  start: string | null;
  end: string | null;
  status: "queued" | "running" | "done" | "error";
  message: string;
  done: number;
  total: number;
  progress: number | null;
  error: string | null;
  result: AnalyzeResult | CompareResult | DriversResult | ScanResult | null;
}

export interface SeriesPoint {
  date: string;
  value: number;
  anomaly: number;
}

/** Per-grid-cell trend inside the region. Grids are indexed [lat][lon]; null = outside the
 *  polygon or too little data. */
export interface TrendMap {
  units: string;
  lat: number[];
  lon: number[];
  resolution_deg: [number, number];
  coarsened_by: number;
  slope_per_decade: (number | null)[][];
  p_value: (number | null)[][];
  /** Significant after controlling the false discovery rate across cells. */
  significant: boolean[][];
  method: string;
  summary: {
    cells: number;
    cells_with_trend: number;
    share_increasing: number | null;
    significant_up: number;
    significant_down: number;
    significant_uncorrected: number;
    mixed: boolean;
    slope_min: number | null;
    slope_max: number | null;
    color_limit: number;
    description: string;
  };
}

export interface AnalyzeResult {
  variable: { key: string; name: string; units: string; definition: string; source: string; global_note?: string };
  region: { grid_cells: number; cells_with_data: number; grid_resolution_deg: number[]; bounds: number[] };
  data_source: { type: DataSource | "provided"; description: string; cached?: boolean };
  stats: {
    n_months: number;
    start: string;
    end: string;
    years: number;
    units: string;
    mean: number;
    linear: {
      slope_per_decade: number;
      ci95_per_decade: [number | null, number | null];
      total_change: number;
      percent_of_mean_per_decade: number | null;
      r_squared: number;
      p_value: number;
      p_value_naive: number;
      lag1_autocorrelation: number;
      effective_n: number;
      intercept: number;
      slope_per_year: number;
    };
    mann_kendall: { trend: string; p_value: number; tau: number; sen_slope_per_decade: number };
    seasonal_mann_kendall: { trend: string; p_value: number; sen_slope_per_decade: number };
    climatology: Record<string, number>;
    /** Weatherhead et al. (1998): years of data needed to detect a trend this size. */
    detection: { years_needed: number | null; more_years: number | null; method: string };
    significant: boolean;
    /** Compare only: still significant after correcting for testing several regions. */
    significant_after_correction?: boolean;
    verdict: string;
  };
  series?: SeriesPoint[];
  trend_map?: TrendMap | { error: string };
}

export const hasMap = (m: AnalyzeResult["trend_map"]): m is TrendMap => !!m && !("error" in m);

export interface ScanItem {
  key: string;
  name: string;
  category: string;
  units: string;
  definition: string;
  start: string;
  end: string;
  n_months: number;
  level: "significant" | "possible" | "none";
  slope_per_decade: number;
  ci95_per_decade: [number | null, number | null];
  percent_of_mean_per_decade: number | null;
  change_in_sd_per_decade: number | null;
  p_value: number;
  mk_p_value: number;
  passes_fdr: boolean;
  mixed_inside_region: boolean;
  global_note: string;
  data_source: DataSource | "provided";
  rank: number;
}

export interface ScanResult {
  start: string | null;
  end: string | null;
  variables: ScanItem[];
  skipped: Record<string, string>;
  summary: { analyzed: number; significant: number; passes_fdr: number; strongest: string | null; description: string };
}

export interface ScanPlan {
  source: "local" | "cloud";
  estimated_seconds: number;
  variables: (Plan & { key: string })[];
  skipped: Record<string, string>;
}

/** One region inside a comparison: an analysis result without `variable`, or an error. */
export type CompareItem =
  | ({ name: string; error?: undefined } & Omit<AnalyzeResult, "variable">)
  | { name: string; error: string };

export interface CompareResult {
  variable: AnalyzeResult["variable"];
  start: string;
  end: string;
  regions: CompareItem[];
  summary: {
    analyzed: number;
    significant: string[];
    significant_after_correction: string[];
    fastest_change: { name: string; slope_per_decade: number };
  };
}

export interface ComparePlan {
  source: "local" | "cloud";
  estimated_seconds: number;
  regions: (Plan & { name: string })[];
}

export interface DriverEvidence {
  key: string;
  name: string;
  units: string;
  definition: string;
  rank: number;
  evidence: "strong" | "moderate" | "weak";
  trend: { slope_per_decade: number; p_value: number; significant: boolean; verdict: string };
  /** p_value is corrected for the number of lags tried; p_value_single_lag is the raw one. */
  correlation: { r: number; lag_months: number; p_value: number; p_value_single_lag: number; lags_tried: number; n: number };
  regression: {
    coef_per_unit: number | null;
    standardized_coef: number | null;
    trend_contribution_per_decade: number | null;
    share_of_target_trend: number | null;
  };
  ml_importance_share: number | null;
  physical_link: { likely_direction: "driver->target" | "target->driver" | "both" | "unknown"; mechanism: string };
}

export interface AiCause {
  cause: string;
  shown_by_data: boolean;
  explanation: string;
  confidence: "strong" | "moderate" | "weak" | "speculative";
}

export type AiExplanation =
  | {
      available: true;
      model: string;
      cached: boolean;
      headline: string;
      summary: string;
      likely_causes: AiCause[];
      other_possible_factors: string[];
      caveats: string[];
      investigate_next: string[];
    }
  | { available: false; reason: string };

export interface DriversResult {
  variable: AnalyzeResult["variable"];
  start: string;
  end: string;
  target: { stats: AnalyzeResult["stats"]; region: AnalyzeResult["region"]; data_source: AnalyzeResult["data_source"] };
  drivers: DriverEvidence[];
  models: {
    regression: { r_squared: number; n_months: number } | null;
    random_forest: { available: boolean; cv_r2?: number; has_skill?: boolean; reason?: string };
  };
  region_context: Record<string, unknown>;
  skipped: Record<string, string>;
  caveats: string[];
  explanation: AiExplanation;
}

/** Error carrying the HTTP status and the API's `detail` message. */
export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${API_URL}${path}`, {
      ...init,
      headers: { "Content-Type": "application/json", ...init?.headers },
    });
  } catch {
    // API_URL is "" when the API is served from the same address as this page (Azure).
    throw new ApiError(0, `Can't reach the API at ${API_URL || window.location.origin}. Is it running?`);
  }
  const body = await res.json().catch(() => null);
  if (!res.ok) {
    const detail = body?.detail;
    const msg = typeof detail === "string" ? detail : Array.isArray(detail) ? detail.map((d) => d.msg).join("; ") : res.statusText;
    throw new ApiError(res.status, msg);
  }
  return body as T;
}

interface AnalyzeBody {
  variable: string;
  region: GeoJSONRegion;
  start: string;
  end: string;
}

interface CompareBody {
  variable: string;
  regions: { name: string; region: GeoJSONRegion }[];
  start: string;
  end: string;
}

export const api = {
  variables: () => request<VariableInfo[]>("/variables"),
  examples: () => request<string[]>("/examples"),
  example: (name: string) => request<GeoJSON.Feature>(`/examples/${encodeURIComponent(name)}`),
  /** Where the data would come from (local or NASA cloud) and roughly how long it takes. */
  plan: (body: AnalyzeBody) => request<Plan>("/plan", { method: "POST", body: JSON.stringify(body) }),
  /** Run and wait (used for local data, which is instant). */
  analyze: (body: AnalyzeBody) =>
    request<AnalyzeResult>("/analyze", { method: "POST", body: JSON.stringify({ ...body, include_series: true }) }),
  /** Run in the background (used for NASA cloud streaming); poll job() for progress. */
  analyzeJob: (body: AnalyzeBody) =>
    request<{ job: Job; plan: Plan }>("/analyze/jobs", {
      method: "POST",
      body: JSON.stringify({ ...body, include_series: true }),
    }),
  job: (id: string) => request<Job>(`/jobs/${id}`),

  driversJob: (body: AnalyzeBody & { region_name?: string }) =>
    request<{ job: Job; plan: Plan }>("/drivers/jobs", { method: "POST", body: JSON.stringify(body) }),

  scanPlan: (body: Omit<AnalyzeBody, "variable">) =>
    request<ScanPlan>("/scan/plan", { method: "POST", body: JSON.stringify(body) }),
  scanJob: (body: Omit<AnalyzeBody, "variable">) =>
    request<{ job: Job; plan: ScanPlan }>("/scan/jobs", { method: "POST", body: JSON.stringify(body) }),

  comparePlan: (body: CompareBody) =>
    request<ComparePlan>("/compare/plan", { method: "POST", body: JSON.stringify(body) }),
  compare: (body: CompareBody) =>
    request<CompareResult>("/compare", { method: "POST", body: JSON.stringify({ ...body, include_series: true }) }),
  compareJob: (body: CompareBody) =>
    request<{ job: Job; plan: ComparePlan }>("/compare/jobs", {
      method: "POST",
      body: JSON.stringify({ ...body, include_series: true }),
    }),
};
