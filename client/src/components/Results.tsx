import { hasMap, type AnalyzeResult } from "../api";
import TrendCharts from "./TrendCharts";
import { downloadSeries, downloadTrendMap } from "../download";
import { trendLevel } from "../trend";

const BADGE = {
  significant: { icon: "✓", label: "Significant trend", cls: "good" },
  possible: { icon: "!", label: "Borderline trend", cls: "warning" },
  none: { icon: "–", label: "No significant trend", cls: "neutral" },
} as const;

const num = (v: number | null | undefined, digits = 3) =>
  v == null ? "–" : `${v >= 0 ? "+" : ""}${v.toPrecision(digits)}`;
const p = (v: number) => (v < 0.001 ? "< 0.001" : v.toFixed(3));

interface Props {
  result: AnalyzeResult;
  regionName: string;
  /** First month the dataset has data, to offer a longer record. */
  dataStarts?: string;
  /** Re-run from an earlier start month. */
  onExtend?: (start: string) => void;
}

export default function Results({ result, regionName, dataStarts, onExtend }: Props) {
  const { stats: s, variable: v, region } = result;
  const lin = s.linear;
  const level = trendLevel(result);
  const badge = BADGE[level];
  const tmap = hasMap(result.trend_map) ? result.trend_map : null;

  return (
    <section className="results" aria-label="Results">
      <div className="verdict">
        <span className={`badge ${badge.cls}`}>
          <span aria-hidden>{badge.icon}</span> {badge.label}
        </span>
        <p>{s.verdict}</p>
      </div>

      <div className="tiles" data-tour="tiles">
        <div className="tile">
          <div className="tile-label">Change per decade</div>
          <div className="tile-value">
            {num(lin.slope_per_decade)} <span className="unit">{v.units}</span>
          </div>
          <div className="tile-sub">
            95% range {num(lin.ci95_per_decade[0])} to {num(lin.ci95_per_decade[1])}
          </div>
        </div>
        <div className="tile">
          <div className="tile-label">Total change</div>
          <div className="tile-value">
            {num(lin.total_change)} <span className="unit">{v.units}</span>
          </div>
          <div className="tile-sub">
            over {s.years.toFixed(1)} years ({s.start} to {s.end})
          </div>
        </div>
        <div className="tile">
          <div className="tile-label">t-test p-value</div>
          <div className="tile-value">{p(lin.p_value)}</div>
          <div className="tile-sub">below 0.05 = significant</div>
        </div>
        <div className="tile">
          <div className="tile-label">Mann-Kendall p-value</div>
          <div className="tile-value">{p(s.mann_kendall.p_value)}</div>
          <div className="tile-sub">trend: {s.mann_kendall.trend}</div>
        </div>
      </div>

      {level !== "significant" && s.detection?.more_years != null && (
        <div className="callout wait">
          <strong>⏳ How long until we'd know?</strong>{" "}
          {s.detection.more_years > 100
            ? "At this rate it would take over a century of data to tell this trend apart from natural ups and downs."
            : s.detection.more_years < 1
              ? "A trend this size is normally detectable with this much data, so it's probably weaker than it looks."
              : `If it carries on at this rate, about ${Math.round(s.detection.more_years)} more years of data (${Math.round(
                  s.detection.years_needed ?? 0,
                )} in total) would give a 90% chance of a significant result.`}{" "}
          <span className="small muted" title={s.detection.method}>
            (Weatherhead et al. 1998)
          </span>
          {dataStarts && onExtend && dataStarts < s.start && s.detection.more_years >= 1 && s.detection.more_years <= 100 && (
            <div className="wait-action">
              <span className="small">
                This dataset goes back to <strong>{dataStarts}</strong>, so you don't have to wait:
              </span>
              <button type="button" className="secondary small" onClick={() => onExtend(dataStarts)}>
                Re-run from {dataStarts}
              </button>
            </div>
          )}
        </div>
      )}

      {v.global_note && (
        <p className="callout">
          <strong>🌍 A worldwide trend.</strong> {v.global_note}
        </p>
      )}

      {tmap && tmap.summary.cells_with_trend > 1 && (
        <div className={`callout ${tmap.summary.mixed ? "warn" : ""}`}>
          <strong>{tmap.summary.mixed ? "↕ Where is it changing? Not everywhere the same way." : "Where is it changing?"}</strong>{" "}
          {tmap.summary.description}{" "}
          <span className="muted small">The map above colours every grid cell by its own trend.</span>
        </div>
      )}

      <TrendCharts result={result} />

      <p className="muted small">
        <span className={`source-pill ${result.data_source.type}`}>
          {result.data_source.cached
            ? "⚡ Cached result"
            : result.data_source.type === "cloud"
              ? "☁ NASA Earthdata Cloud"
              : "💾 Stored on this computer"}
        </span>{" "}
        {region.cells_with_data} grid cells averaged · {s.n_months} months · dataset {v.source}
      </p>
      <div className="downloads">
        <span className="small muted">Download CSV:</span>
        <button type="button" className="secondary small" onClick={() => downloadSeries(result, regionName)}>
          ⤓ Monthly data
        </button>
        {tmap && (
          <button type="button" className="secondary small" onClick={() => downloadTrendMap(tmap, v.key, regionName)}>
            ⤓ Trend map (one row per grid cell)
          </button>
        )}
      </div>
    </section>
  );
}
