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
  result: AnalyzeResult | CompareResult | DriversResult | null;
}

export interface SeriesPoint {
  date: string;
  value: number;
  anomaly: number;
}

export interface AnalyzeResult {
  variable: { key: string; name: string; units: string; definition: string; source: string };
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
    significant: boolean;
    verdict: string;
  };
  series?: SeriesPoint[];
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
  correlation: { r: number; lag_months: number; p_value: number; n: number };
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
