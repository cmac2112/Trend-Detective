import type { AnalyzeResult } from "../api";
import TrendCharts from "./TrendCharts";
import { trendLevel } from "../trend";

const BADGE = {
  significant: { icon: "✓", label: "Significant trend", cls: "good" },
  possible: { icon: "!", label: "Borderline trend", cls: "warning" },
  none: { icon: "–", label: "No significant trend", cls: "neutral" },
} as const;

const num = (v: number | null | undefined, digits = 3) =>
  v == null ? "–" : `${v >= 0 ? "+" : ""}${v.toPrecision(digits)}`;
const p = (v: number) => (v < 0.001 ? "< 0.001" : v.toFixed(3));

export default function Results({ result }: { result: AnalyzeResult }) {
  const { stats: s, variable: v, region } = result;
  const lin = s.linear;
  const level = trendLevel(result);
  const badge = BADGE[level];

  return (
    <section className="results" aria-label="Results">
      <div className="verdict">
        <span className={`badge ${badge.cls}`}>
          <span aria-hidden>{badge.icon}</span> {badge.label}
        </span>
        <p>{s.verdict}</p>
      </div>

      <div className="tiles">
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
    </section>
  );
}
