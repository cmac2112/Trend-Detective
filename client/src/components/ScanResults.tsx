import type { ScanItem, ScanResult } from "../api";
import { downloadScan } from "../download";

const BADGE = {
  significant: { icon: "✓", label: "Significant", cls: "good" },
  possible: { icon: "!", label: "Borderline", cls: "warning" },
  none: { icon: "–", label: "No trend", cls: "neutral" },
} as const;

const signed = (v: number | null | undefined, digits = 3) =>
  v == null ? "–" : `${v >= 0 ? "+" : ""}${v.toPrecision(digits)}`;
const p = (v: number) => (v < 0.001 ? "< 0.001" : v.toFixed(3));

interface Props {
  result: ScanResult;
  regionName: string;
  busyKey: string | null;
  onOpen: (item: ScanItem) => void;
  /** Variables the detective questions pointed to, tagged in the table. */
  suggested?: string[];
}

/** "What's changing here?" Every variable for one region, most clearly trending first. */
export default function ScanResults({ result, regionName, busyKey, onOpen, suggested = [] }: Props) {
  const skipped = Object.entries(result.skipped);
  return (
    <section className="results" aria-label="Scan results">
      <div className="verdict">
        <span className="badge neutral">What's changing in {regionName}?</span>
        <p>{result.summary.description}</p>
      </div>

      <div className="table-scroll compare-table scan-table" data-tour="scan-table">
        <table>
          <caption className="small muted">
            Ranked by significance, then by how big the change is compared with normal year-to-year ups and downs.
            Click a variable to see its charts and map.
          </caption>
          <thead>
            <tr>
              <th>Variable</th>
              <th>Trend</th>
              <th>Change per decade</th>
              <th title="Change per decade divided by the typical size of month-to-month anomalies">
                vs. normal variation
              </th>
              <th>t-test p</th>
              <th>Mann-Kendall p</th>
              <th>Period</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {result.variables.map((v) => {
              const b = BADGE[v.level];
              return (
                <tr key={v.key} data-tour={`scan-row-${v.key}`}>
                  <td>
                    <div className="scan-name">{v.name}</div>
                    <div className="small muted">{v.category}</div>
                    {suggested.includes(v.key) && <div className="small idea-tag">💡 matches your answers</div>}
                  </td>
                  <td>
                    <span className={`badge ${b.cls}`}>
                      <span aria-hidden>{b.icon}</span> {b.label}
                    </span>
                    {v.level === "significant" && !v.passes_fdr && (
                      <div className="small muted" title="Could be a fluke of testing many variables at once">
                        may be chance
                      </div>
                    )}
                    {v.global_note && (
                      <div className="small muted" title={v.global_note}>
                        🌍 worldwide trend
                      </div>
                    )}
                    {v.mixed_inside_region && (
                      <div className="small muted" title="Some grid cells rise significantly while others fall">
                        ↕ opposite trends inside
                      </div>
                    )}
                  </td>
                  <td>
                    {signed(v.slope_per_decade)} {v.units}
                    {v.percent_of_mean_per_decade != null && (
                      <div className="small muted">{signed(v.percent_of_mean_per_decade, 2)}% of average</div>
                    )}
                  </td>
                  <td>{v.change_in_sd_per_decade == null ? "–" : `${signed(v.change_in_sd_per_decade, 2)}×`}</td>
                  <td>{p(v.p_value)}</td>
                  <td>{p(v.mk_p_value)}</td>
                  <td className="muted">
                    {v.start} to {v.end}
                  </td>
                  <td>
                    <button
                      type="button"
                      className="secondary small"
                      onClick={() => onOpen(v)}
                      disabled={busyKey !== null}
                      aria-label={`Open ${v.name}`}
                    >
                      {busyKey === v.key ? "Opening…" : "Open"}
                    </button>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      <div className="downloads">
        <span className="small muted">Download CSV:</span>
        <button type="button" className="secondary small" onClick={() => downloadScan(result, regionName)}>
          ⤓ This table
        </button>
      </div>

      {skipped.length > 0 && (
        <details className="table-view">
          <summary>
            {skipped.length} {skipped.length === 1 ? "variable" : "variables"} couldn't be analyzed here
          </summary>
          <ul className="small muted">
            {skipped.map(([key, why]) => (
              <li key={key}>
                <strong>{key}</strong>: {why}
              </li>
            ))}
          </ul>
        </details>
      )}
    </section>
  );
}
