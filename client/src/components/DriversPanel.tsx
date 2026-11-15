import { useEffect, useRef, useState } from "react";
import { api, type DriverEvidence, type DriversResult, type Job } from "../api";

interface Props {
  variable: string;
  variableName: string;
  region: GeoJSON.Feature;
  regionName: string;
  start: string;
  end: string;
}

const EVIDENCE = {
  strong: { label: "Strong link", cls: "good" },
  moderate: { label: "Moderate link", cls: "warning" },
  weak: { label: "Weak / none", cls: "neutral" },
} as const;

const CONFIDENCE_CLS = { strong: "good", moderate: "warning", weak: "neutral", speculative: "neutral" } as const;

const DIRECTION = {
  "driver->target": "usually the cause",
  "target->driver": "usually the effect",
  both: "works both ways",
  unknown: "",
} as const;

const signed = (v: number | null | undefined, digits = 2) =>
  v == null ? "–" : `${v >= 0 ? "+" : ""}${v.toFixed(digits)}`;
const pct = (v: number | null | undefined) => (v == null ? "–" : `${Math.round(v * 100)}%`);
const pval = (v: number) => (v < 0.001 ? "< 0.001" : v.toFixed(3));

/** "Why is it changing?" - statistical cause analysis plus Claude's explanation. */
export default function DriversPanel({ variable, variableName, region, regionName, start, end }: Props) {
  const [job, setJob] = useState<Job | null>(null);
  const [result, setResult] = useState<DriversResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const timer = useRef<number | null>(null);

  useEffect(() => () => {
    if (timer.current) window.clearInterval(timer.current);
  }, []);

  async function run() {
    setError(null);
    setResult(null);
    try {
      const { job: started } = await api.driversJob({ variable, region, start, end, region_name: regionName });
      setJob(started);
      timer.current = window.setInterval(async () => {
        try {
          const j = await api.job(started.id);
          setJob(j);
          if (j.status !== "done" && j.status !== "error") return;
          window.clearInterval(timer.current!);
          setJob(null);
          if (j.status === "done" && j.result) setResult(j.result as DriversResult);
          else setError(j.error ?? "Cause analysis failed");
        } catch (e) {
          window.clearInterval(timer.current!);
          setJob(null);
          setError(e instanceof Error ? e.message : String(e));
        }
      }, 1000);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  const running = job !== null;

  return (
    <section className="drivers" aria-label="Possible causes" data-tour="drivers">
      <div className="drivers-head">
        <div>
          <h2 className="section-title">Why is it changing?</h2>
          <p className="small muted">
            Compares {variableName.toLowerCase()} with the other datasets (rain, temperature, soil moisture,
            evaporation) in the same region, then asks Claude to explain what the evidence suggests.
          </p>
        </div>
        {!result && (
          <button type="button" className="primary" onClick={run} disabled={running}>
            {running ? "Investigating…" : "Investigate causes"}
          </button>
        )}
      </div>

      {running && (
        <div className="progress-card" aria-live="polite">
          <div className="small">{job?.message ?? "Starting…"}</div>
          <progress max={1} value={job?.progress ?? undefined} />
        </div>
      )}
      {error && (
        <p className="callout error" role="alert">
          <span aria-hidden>✕</span> {error}
        </p>
      )}

      {result && (
        <>
          <AiCard result={result} />
          <EvidenceTable drivers={result.drivers} units={result.variable.units} />
          <p className="small muted">
            Regression explains {pct(result.models.regression?.r_squared)} of the month-to-month variation.{" "}
            {result.models.random_forest.available
              ? result.models.random_forest.has_skill
                ? `The machine-learning model (random forest) predicts unseen years with R² = ${result.models.random_forest.cv_r2?.toFixed(2)}.`
                : "The machine-learning model (random forest) couldn't predict unseen years, so its importance scores are unreliable."
              : result.models.random_forest.reason}
          </p>
          <details className="table-view">
            <summary>Limits of this analysis ({result.caveats.length})</summary>
            <ul className="small">
              {result.caveats.map((c) => (
                <li key={c}>{c}</li>
              ))}
            </ul>
          </details>
        </>
      )}
    </section>
  );
}

function AiCard({ result }: { result: DriversResult }) {
  const ex = result.explanation;
  if (!ex.available) {
    return (
      <p className="callout">
        <span aria-hidden>ℹ</span> {ex.reason} The statistical evidence is below.
      </p>
    );
  }
  return (
    <div className="ai-card">
      <div className="ai-label small">
        ✦ AI explanation by Claude · grounded in the numbers below, but check it against the evidence
      </div>
      <p className="ai-headline">{ex.headline}</p>
      <p>{ex.summary}</p>
      <ol className="ai-causes">
        {ex.likely_causes.map((c) => (
          <li key={c.cause}>
            <div className="ai-cause-head">
              <strong>{c.cause}</strong>
              <span className={`badge ${CONFIDENCE_CLS[c.confidence]}`}>{c.confidence}</span>
              <span className="source-pill">{c.shown_by_data ? "shown by the data" : "outside knowledge"}</span>
            </div>
            <p>{c.explanation}</p>
          </li>
        ))}
      </ol>
      {ex.other_possible_factors.length > 0 && (
        <p className="small">
          <strong>Not measured here, but could matter:</strong> {ex.other_possible_factors.join("; ")}
        </p>
      )}
      {ex.investigate_next.length > 0 && (
        <div className="small">
          <strong>Try next:</strong>
          <ul>
            {ex.investigate_next.map((s) => (
              <li key={s}>{s}</li>
            ))}
          </ul>
        </div>
      )}
      {ex.caveats.length > 0 && (
        <p className="small muted">
          <strong>Keep in mind:</strong> {ex.caveats.join(" ")}
        </p>
      )}
    </div>
  );
}

function EvidenceTable({ drivers, units }: { drivers: DriverEvidence[]; units: string }) {
  return (
    <div className="table-scroll compare-table">
      <table>
        <caption className="small muted">The evidence: how each variable relates to the trend</caption>
        <thead>
          <tr>
            <th>Possible driver</th>
            <th>Its own trend / decade</th>
            <th>Moves together? (r)</th>
            <th>Share of trend</th>
            <th>ML importance</th>
            <th>Evidence</th>
          </tr>
        </thead>
        <tbody>
          {drivers.map((d) => {
            const e = EVIDENCE[d.evidence];
            const dir = DIRECTION[d.physical_link.likely_direction];
            return (
              <tr key={d.key}>
                <td>
                  <span title={d.physical_link.mechanism}>{d.name}</span>
                  {dir && <div className="tiny muted">{dir}</div>}
                </td>
                <td>
                  {signed(d.trend.slope_per_decade, 3)} {d.units}
                  <div className="tiny muted">{d.trend.significant ? "significant" : "not significant"}</div>
                </td>
                <td>
                  <span className="r-bar" aria-hidden>
                    <span style={{ width: `${Math.min(Math.abs(d.correlation.r), 1) * 100}%` }} />
                  </span>
                  {signed(d.correlation.r)}
                  <div className="tiny muted">
                    <span title={d.correlation.lags_tried > 1 ? `Adjusted for trying ${d.correlation.lags_tried} time lags and keeping the best one` : undefined}>
                      p {pval(d.correlation.p_value)}
                    </span>
                    {d.correlation.lag_months > 0 ? ` · ${d.correlation.lag_months}-month lead` : ""}
                  </div>
                </td>
                <td title={`Implied change in the target: ${signed(d.regression.trend_contribution_per_decade, 3)} ${units} per decade`}>
                  {pct(d.regression.share_of_target_trend)}
                </td>
                <td>{pct(d.ml_importance_share)}</td>
                <td>
                  <span className={`badge ${e.cls}`}>{e.label}</span>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
