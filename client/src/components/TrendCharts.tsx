import {
  CartesianGrid,
  ComposedChart,
  Legend,
  Line,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { AnalyzeResult } from "../api";
import { trendLevel } from "../trend";

const fmt = (v: number, units: string) => `${v.toLocaleString(undefined, { maximumFractionDigits: 2 })} ${units}`;

/**
 * Two charts (never a dual axis):
 *  1. the raw monthly values the region actually had
 *  2. anomalies (seasonal cycle removed) with the trend line, drawn only when a trend shows up
 */
export default function TrendCharts({ result }: { result: AnalyzeResult }) {
  const { units } = result.variable;
  const lin = result.stats.linear;
  const level = trendLevel(result);
  const series = result.series ?? [];

  const data = series.map((p) => {
    const [y, m] = p.date.split("-").map(Number);
    const t = y + (m - 0.5) / 12; // decimal year, same as the API's trend fit
    return { ...p, trend: level === "none" ? null : lin.intercept + lin.slope_per_year * t };
  });

  const axisProps = {
    stroke: "var(--axis)",
    tick: { fill: "var(--text-muted)", fontSize: 12 },
    tickLine: false,
  };
  const tooltipProps = {
    contentStyle: {
      background: "var(--surface-raised)",
      border: "1px solid var(--border)",
      borderRadius: 8,
      color: "var(--text-primary)",
      fontSize: 13,
    },
    labelStyle: { color: "var(--text-secondary)" },
    cursor: { stroke: "var(--text-muted)", strokeWidth: 1 },
  };

  return (
    <div className="charts">
      <figure className="chart-card">
        <figcaption>
          <strong>{result.variable.name}</strong> <span className="muted">· monthly average over your region ({units})</span>
        </figcaption>
        <ResponsiveContainer width="100%" height={240}>
          <ComposedChart data={data} margin={{ top: 8, right: 16, bottom: 0, left: 0 }}>
            <CartesianGrid stroke="var(--grid)" vertical={false} />
            <XAxis dataKey="date" {...axisProps} minTickGap={40} />
            <YAxis {...axisProps} axisLine={false} width={56} domain={["auto", "auto"]} />
            <Tooltip {...tooltipProps} formatter={(v: number) => [fmt(v, units), "Monthly value"]} />
            <Line type="monotone" dataKey="value" stroke="var(--series-1)" strokeWidth={2} dot={false} isAnimationActive={false} />
          </ComposedChart>
        </ResponsiveContainer>
      </figure>

      <figure className="chart-card">
        <figcaption>
          <strong>Trend after removing the seasonal cycle</strong>{" "}
          <span className="muted">· difference from that month's normal ({units})</span>
        </figcaption>
        <ResponsiveContainer width="100%" height={240}>
          <ComposedChart data={data} margin={{ top: 8, right: 16, bottom: 0, left: 0 }}>
            <CartesianGrid stroke="var(--grid)" vertical={false} />
            <XAxis dataKey="date" {...axisProps} minTickGap={40} />
            <YAxis {...axisProps} axisLine={false} width={56} domain={["auto", "auto"]} />
            <Tooltip
              {...tooltipProps}
              formatter={(v: number, name: string) => [fmt(v, units), name]}
            />
            <Legend
              wrapperStyle={{ fontSize: 13 }}
              formatter={(label: string) => <span style={{ color: "var(--text-secondary)" }}>{label}</span>}
            />
            <Line
              name="Anomaly"
              type="monotone"
              dataKey="anomaly"
              stroke="var(--series-1)"
              strokeWidth={1.5}
              dot={false}
              isAnimationActive={false}
            />
            {level !== "none" && (
              <Line
                name={`Trend line (${lin.slope_per_decade >= 0 ? "+" : ""}${lin.slope_per_decade.toPrecision(3)} ${units}/decade${level === "possible" ? ", borderline" : ""})`}
                type="linear"
                dataKey="trend"
                stroke="var(--series-2)"
                strokeWidth={3}
                strokeDasharray={level === "possible" ? "8 6" : undefined}
                dot={false}
                isAnimationActive={false}
              />
            )}
          </ComposedChart>
        </ResponsiveContainer>
        {level === "none" && <p className="muted small chart-note">No trend line: the change isn't statistically significant.</p>}
      </figure>

      <details className="table-view">
        <summary>Show data table ({series.length} months)</summary>
        <div className="table-scroll">
          <table>
            <thead>
              <tr>
                <th>Month</th>
                <th>Value ({units})</th>
                <th>Anomaly ({units})</th>
              </tr>
            </thead>
            <tbody>
              {series.map((p) => (
                <tr key={p.date}>
                  <td>{p.date}</td>
                  <td>{p.value.toFixed(3)}</td>
                  <td>{p.anomaly.toFixed(3)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </details>
    </div>
  );
}
