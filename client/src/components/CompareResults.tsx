import { CartesianGrid, ComposedChart, Legend, Line, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import type { AnalyzeResult, CompareItem, CompareResult } from "../api";
import { slotVar } from "../regions";
import { trendLevel } from "../trend";

interface Props {
  result: CompareResult;
  /** Region name -> colour slot, so each region keeps its map colour. */
  slots: Record<string, number>;
}

type OkItem = Extract<CompareItem, { error?: undefined }>;

const BADGE = {
  significant: { icon: "✓", label: "Significant", cls: "good" },
  possible: { icon: "!", label: "Borderline", cls: "warning" },
  none: { icon: "–", label: "Not significant", cls: "neutral" },
} as const;

const signed = (v: number | null | undefined, digits = 3) =>
  v == null ? "–" : `${v >= 0 ? "+" : ""}${v.toPrecision(digits)}`;
const pval = (v: number) => (v < 0.001 ? "< 0.001" : v.toFixed(3));
const decimalYear = (date: string) => {
  const [y, m] = date.split("-").map(Number);
  return y + (m - 0.5) / 12;
};

/** Centered 12-month mean, so several noisy regions stay readable on one chart. */
function rolling12(values: number[]) {
  return values.map((_, i) => {
    if (i < 6 || i + 6 > values.length) return null;
    const win = values.slice(i - 6, i + 6);
    return win.reduce((a, b) => a + b, 0) / win.length;
  });
}

const asLevelInput = (item: OkItem) => ({ stats: item.stats }) as AnalyzeResult;

export default function CompareResults({ result, slots }: Props) {
  const { units, name: varName } = result.variable;
  const ok = result.regions.filter((r): r is OkItem => !r.error);
  const failed = result.regions.filter((r) => r.error);
  const slotOf = (name: string) => slots[name] ?? 0;

  // Merge every region's monthly series into one row per month.
  const rows = new Map<string, Record<string, number | string | null>>();
  for (const item of ok) {
    const s = slotOf(item.name);
    const series = item.series ?? [];
    const smooth = rolling12(series.map((p) => p.anomaly));
    const level = trendLevel(asLevelInput(item));
    const lin = item.stats.linear;
    series.forEach((p, i) => {
      const row = rows.get(p.date) ?? { date: p.date };
      row[`v${s}`] = p.value;
      row[`a${s}`] = smooth[i];
      row[`t${s}`] = level === "none" ? null : lin.intercept + lin.slope_per_year * decimalYear(p.date);
      rows.set(p.date, row);
    });
  }
  const data = [...rows.values()].sort((a, b) => String(a.date).localeCompare(String(b.date)));

  const fastest = result.summary.fastest_change;
  const sig = result.summary.significant;

  const axis = { stroke: "var(--axis)", tick: { fill: "var(--text-muted)", fontSize: 12 }, tickLine: false };
  const tooltip = {
    contentStyle: {
      background: "var(--surface-raised)",
      border: "1px solid var(--border)",
      borderRadius: 8,
      color: "var(--text-primary)",
      fontSize: 13,
    },
    labelStyle: { color: "var(--text-secondary)" },
    cursor: { stroke: "var(--text-muted)", strokeWidth: 1 },
    formatter: (v: number, name: string) => [`${v.toLocaleString(undefined, { maximumFractionDigits: 2 })} ${units}`, name],
  };
  const legend = (
    <Legend
      wrapperStyle={{ fontSize: 13 }}
      formatter={(label: string) => <span style={{ color: "var(--text-secondary)" }}>{label}</span>}
    />
  );

  return (
    <section className="results" aria-label="Comparison results">
      <div className="verdict">
        <span className="badge neutral">Comparing {ok.length} regions</span>
        <p>
          <strong>{varName}</strong>, {result.start} to {result.end}.{" "}
          {sig.length === 0
            ? "None of the regions shows a significant trend."
            : `Significant trend in ${sig.length === ok.length ? "all regions" : sig.join(", ")}.`}{" "}
          Fastest change: <strong>{fastest.name}</strong> ({signed(fastest.slope_per_decade)} {units} per decade).
        </p>
      </div>

      <div className="table-scroll compare-table">
        <table>
          <thead>
            <tr>
              <th>Region</th>
              <th>Change / decade ({units})</th>
              <th>95% range</th>
              <th>Total change</th>
              <th>t-test p</th>
              <th>Mann-Kendall p</th>
              <th>Trend</th>
              <th>Data</th>
            </tr>
          </thead>
          <tbody>
            {ok.map((item) => {
              const lin = item.stats.linear;
              const b = BADGE[trendLevel(asLevelInput(item))];
              return (
                <tr key={item.name}>
                  <td>
                    <span className="swatch" style={{ background: slotVar(slotOf(item.name)) }} aria-hidden />
                    {item.name}
                  </td>
                  <td>{signed(lin.slope_per_decade)}</td>
                  <td>
                    {signed(lin.ci95_per_decade[0])} to {signed(lin.ci95_per_decade[1])}
                  </td>
                  <td>{signed(lin.total_change)}</td>
                  <td>{pval(lin.p_value)}</td>
                  <td>{pval(item.stats.mann_kendall.p_value)}</td>
                  <td>
                    <span className={`badge ${b.cls}`}>
                      <span aria-hidden>{b.icon}</span> {b.label}
                    </span>
                  </td>
                  <td className="muted">
                    {item.data_source.cached ? "cached" : item.data_source.type === "cloud" ? "NASA cloud" : "stored"}
                  </td>
                </tr>
              );
            })}
            {failed.map((item) => (
              <tr key={item.name}>
                <td>
                  <span className="swatch" style={{ background: slotVar(slotOf(item.name)) }} aria-hidden />
                  {item.name}
                </td>
                <td colSpan={7} className="muted">
                  {item.error}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <figure className="chart-card">
        <figcaption>
          <strong>{varName}</strong> <span className="muted">· monthly average in each region ({units})</span>
        </figcaption>
        <ResponsiveContainer width="100%" height={260}>
          <ComposedChart data={data} margin={{ top: 8, right: 16, bottom: 0, left: 0 }}>
            <CartesianGrid stroke="var(--grid)" vertical={false} />
            <XAxis dataKey="date" {...axis} minTickGap={40} />
            <YAxis {...axis} axisLine={false} width={56} domain={["auto", "auto"]} />
            <Tooltip {...tooltip} />
            {legend}
            {ok.map((item) => (
              <Line
                key={item.name}
                name={item.name}
                dataKey={`v${slotOf(item.name)}`}
                stroke={slotVar(slotOf(item.name))}
                strokeWidth={1.5}
                dot={false}
                connectNulls
                isAnimationActive={false}
              />
            ))}
          </ComposedChart>
        </ResponsiveContainer>
      </figure>

      <figure className="chart-card">
        <figcaption>
          <strong>Trends after removing the seasonal cycle</strong>{" "}
          <span className="muted">
            · 12-month average of each region's difference from normal ({units}); thick lines are trend lines
          </span>
        </figcaption>
        <ResponsiveContainer width="100%" height={260}>
          <ComposedChart data={data} margin={{ top: 8, right: 16, bottom: 0, left: 0 }}>
            <CartesianGrid stroke="var(--grid)" vertical={false} />
            <XAxis dataKey="date" {...axis} minTickGap={40} />
            <YAxis {...axis} axisLine={false} width={56} domain={["auto", "auto"]} />
            <Tooltip {...tooltip} />
            {legend}
            {ok.map((item) => {
              const s = slotOf(item.name);
              return (
                <Line
                  key={`a-${item.name}`}
                  name={item.name}
                  dataKey={`a${s}`}
                  stroke={slotVar(s)}
                  strokeWidth={1.25}
                  strokeOpacity={0.7}
                  dot={false}
                  isAnimationActive={false}
                />
              );
            })}
            {ok.map((item) => {
              const s = slotOf(item.name);
              const level = trendLevel(asLevelInput(item));
              if (level === "none") return null;
              return (
                <Line
                  key={`t-${item.name}`}
                  name={`${item.name} trend`}
                  legendType="none"
                  type="linear"
                  dataKey={`t${s}`}
                  stroke={slotVar(s)}
                  strokeWidth={3}
                  strokeDasharray={level === "possible" ? "8 6" : undefined}
                  dot={false}
                  isAnimationActive={false}
                />
              );
            })}
          </ComposedChart>
        </ResponsiveContainer>
        <p className="muted small chart-note">
          Solid trend line = significant, dashed = borderline, none = no significant trend.
        </p>
      </figure>

      <details className="table-view">
        <summary>Show data table ({data.length} months)</summary>
        <div className="table-scroll">
          <table>
            <thead>
              <tr>
                <th>Month</th>
                {ok.map((item) => (
                  <th key={item.name}>
                    {item.name} ({units})
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {data.map((row) => (
                <tr key={String(row.date)}>
                  <td>{row.date}</td>
                  {ok.map((item) => {
                    const v = row[`v${slotOf(item.name)}`];
                    return <td key={item.name}>{typeof v === "number" ? v.toFixed(3) : "–"}</td>;
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </details>
    </section>
  );
}
