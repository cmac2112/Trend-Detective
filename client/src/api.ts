// Typed client for the Trend Detective API (TrendApi/).

export const API_URL: string = import.meta.env.VITE_API_URL ?? "http://127.0.0.1:8000";

export type GeoJSONRegion = GeoJSON.Feature | GeoJSON.Polygon | GeoJSON.MultiPolygon | GeoJSON.FeatureCollection;

export interface VariableInfo {
  key: string;
  name: string;
  units: string;
  definition: string;
  source: string;
  related: string[];
  available: boolean;
  start: string | null;
  end: string | null;
  n_months: number;
  data_starts: string;
  mb_per_month: number;
}

export interface Coverage {
  variable: string;
  start: string;
  end: string;
  requested_months: number;
  available_months: number;
  missing_months: number;
  missing_first: string | null;
  missing_last: string | null;
  download_months: number;
  estimated_mb: number;
  limit_mb: number;
  within_limit: boolean;
  data_starts: string;
}

export interface Job {
  id: string;
  variable: string;
  start: string;
  end: string;
  status: "queued" | "downloading" | "building" | "done" | "error";
  message: string;
  done: number;
  total: number;
  progress: number | null;
  error: string | null;
}

export interface FetchResponse {
  job: Job | null;
  message: string;
  coverage: Coverage;
}

export interface SeriesPoint {
  date: string;
  value: number;
  anomaly: number;
}

export interface AnalyzeResult {
  variable: { key: string; name: string; units: string; definition: string; source: string };
  region: { grid_cells: number; cells_with_data: number; grid_resolution_deg: number[]; bounds: number[] };
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
    throw new ApiError(0, `Can't reach the API at ${API_URL}. Is it running?`);
  }
  const body = await res.json().catch(() => null);
  if (!res.ok) {
    const detail = body?.detail;
    const msg = typeof detail === "string" ? detail : Array.isArray(detail) ? detail.map((d) => d.msg).join("; ") : res.statusText;
    throw new ApiError(res.status, msg);
  }
  return body as T;
}

export const api = {
  variables: () => request<VariableInfo[]>("/variables"),
  examples: () => request<string[]>("/examples"),
  example: (name: string) => request<GeoJSON.Feature>(`/examples/${encodeURIComponent(name)}`),
  coverage: (key: string, start: string, end: string) =>
    request<Coverage>(`/variables/${key}/coverage?start=${start}&end=${end}`),
  fetchData: (key: string, start: string, end: string) =>
    request<FetchResponse>(`/variables/${key}/fetch`, { method: "POST", body: JSON.stringify({ start, end }) }),
  job: (id: string) => request<Job>(`/jobs/${id}`),
  analyze: (variable: string, region: GeoJSONRegion, start: string, end: string) =>
    request<AnalyzeResult>("/analyze", {
      method: "POST",
      body: JSON.stringify({ variable, region, start, end, include_series: true }),
    }),
};
