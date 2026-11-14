import { useCallback, useEffect, useRef, useState } from "react";
import { api, ApiError, type AnalyzeResult, type Coverage, type Job, type VariableInfo } from "./api";
import MapPanel from "./components/MapPanel";
import FetchDialog from "./components/FetchDialog";
import Results from "./components/Results";

const EXAMPLE_LABELS: Record<string, string> = {
  barents_sea: "Barents Sea (Arctic)",
  lake_mead: "Lake Mead (US Southwest)",
  amazon_rondonia: "Rondônia (Amazon)",
};

const thisMonth = new Date().toISOString().slice(0, 7);

export default function App() {
  const [variables, setVariables] = useState<VariableInfo[]>([]);
  const [examples, setExamples] = useState<string[]>([]);
  const [variable, setVariable] = useState("t2m");
  const [start, setStart] = useState("2001-01");
  const [end, setEnd] = useState("2024-12");
  const [region, setRegion] = useState<GeoJSON.Feature | null>(null);
  const [loadRegion, setLoadRegion] = useState<{ id: number; feature: GeoJSON.Feature } | null>(null);

  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<AnalyzeResult | null>(null);

  const [coverage, setCoverage] = useState<Coverage | null>(null);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [job, setJob] = useState<Job | null>(null);
  const [jobError, setJobError] = useState<string | null>(null);
  const pollRef = useRef<number | null>(null);

  const selected = variables.find((v) => v.key === variable);

  const loadVariables = useCallback(async () => {
    const vs = await api.variables();
    setVariables(vs);
    return vs;
  }, []);

  useEffect(() => {
    loadVariables().catch((e) => setError(e.message));
    api.examples().then(setExamples).catch(() => {});
    return () => {
      if (pollRef.current) window.clearInterval(pollRef.current);
    };
  }, [loadVariables]);

  const runAnalysis = useCallback(
    async (s = start, e = end) => {
      if (!region) return;
      setBusy(true);
      setError(null);
      try {
        setResult(await api.analyze(variable, region, s, e));
      } catch (err) {
        setResult(null);
        setError(err instanceof Error ? err.message : String(err));
      } finally {
        setBusy(false);
      }
    },
    [region, variable, start, end],
  );

  /** Step 1: check what's downloaded. Analyze right away, or ask about downloading. */
  async function onAnalyze() {
    setError(null);
    if (!region) return setError("Draw a region on the map first (polygon or rectangle tool, top left).");
    if (start > end) return setError("The start month must be before the end month.");
    setBusy(true);
    try {
      const cov = await api.coverage(variable, start, end);
      if (cov.missing_months === 0) {
        await runAnalysis();
      } else {
        setCoverage(cov);
        setJob(null);
        setJobError(null);
        setDialogOpen(true);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  /** Step 2 (only if data is missing): start a server download and poll it. */
  async function onDownload() {
    if (!coverage) return;
    setJobError(null);
    try {
      const res = await api.fetchData(variable, coverage.start, coverage.end);
      if (!res.job) {
        setDialogOpen(false);
        await loadVariables();
        return runAnalysis();
      }
      setJob(res.job);
      pollJob(res.job.id, coverage.start, coverage.end);
    } catch (err) {
      setJobError(err instanceof ApiError ? err.message : String(err));
    }
  }

  function pollJob(id: string, s: string, e: string) {
    if (pollRef.current) window.clearInterval(pollRef.current);
    pollRef.current = window.setInterval(async () => {
      try {
        const j = await api.job(id);
        setJob(j);
        if (j.status === "done" || j.status === "error") {
          window.clearInterval(pollRef.current!);
          pollRef.current = null;
          if (j.status === "error") {
            setJobError(j.error ?? "Download failed");
            setDialogOpen(true);
          } else {
            setDialogOpen(false);
            setJob(null);
            await loadVariables();
            await runAnalysis(s, e);
          }
        }
      } catch (err) {
        setJobError(err instanceof Error ? err.message : String(err));
      }
    }, 1000);
  }

  async function onExample(name: string) {
    try {
      const feature = await api.example(name);
      setLoadRegion({ id: Date.now(), feature });
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  const jobRunning = job && job.status !== "done" && job.status !== "error";

  return (
    <div className="app">
      <aside className="sidebar">
        <header>
          <h1>Trend Detective</h1>
          <p className="muted">Draw a region, pick a NASA dataset, and find out if it's really changing.</p>
        </header>

        <section className="step">
          <h2><span className="step-num">1</span> Choose a region</h2>
          <p className="small muted">
            Use the polygon or rectangle tool on the map (top left), or start from an example:
          </p>
          <div className="chips">
            {examples.map((name) => (
              <button key={name} type="button" className="chip" onClick={() => onExample(name)}>
                {EXAMPLE_LABELS[name] ?? name}
              </button>
            ))}
          </div>
          <p className={`small region-status ${region ? "ok" : ""}`}>
            {region ? "✓ Region selected" : "No region yet"}
          </p>
        </section>

        <section className="step">
          <h2><span className="step-num">2</span> Choose what to investigate</h2>
          <label className="field">
            <span>Dataset</span>
            <select
              value={variable}
              onChange={(e) => {
                setVariable(e.target.value);
                setResult(null); // old results are for a different dataset
              }}
            >
              {variables.map((v) => (
                <option key={v.key} value={v.key}>
                  {v.name} ({v.units}){v.available ? "" : " · not downloaded"}
                </option>
              ))}
            </select>
          </label>
          {selected && (
            <div className="var-info">
              <p>{selected.definition}</p>
              <p className="small muted">
                {selected.available
                  ? `On the server: ${selected.start} to ${selected.end} (${selected.n_months} months)`
                  : "Not downloaded yet. You'll be asked before anything is downloaded."}
              </p>
            </div>
          )}
        </section>

        <section className="step">
          <h2><span className="step-num">3</span> Choose when</h2>
          <div className="row">
            <label className="field">
              <span>From</span>
              <input type="month" value={start} min={selected?.data_starts} max={thisMonth} onChange={(e) => setStart(e.target.value)} />
            </label>
            <label className="field">
              <span>To</span>
              <input type="month" value={end} min={selected?.data_starts} max={thisMonth} onChange={(e) => setEnd(e.target.value)} />
            </label>
          </div>
          <p className="small muted">Longer periods find trends more reliably. Aim for 10+ years.</p>
        </section>

        <button type="button" className="primary big" onClick={onAnalyze} disabled={busy || !!jobRunning}>
          {busy ? "Working…" : "Analyze trend"}
        </button>

        {jobRunning && !dialogOpen && (
          <button type="button" className="ghost job-pill" onClick={() => setDialogOpen(true)}>
            {job.message} · show
          </button>
        )}
        {error && (
          <p className="callout error" role="alert">
            <span aria-hidden>✕</span> {error}
          </p>
        )}
      </aside>

      <main className="main">
        <div className="map-wrap">
          <MapPanel
            onChange={(r) => {
              setRegion(r);
              setResult(null); // old results are for a different region
            }}
            loadRegion={loadRegion}
          />
        </div>
        {result ? (
          <Results result={result} />
        ) : (
          <div className="empty muted">Results will appear here after you analyze a region.</div>
        )}
      </main>

      {dialogOpen && coverage && selected && (
        <FetchDialog
          variable={selected}
          coverage={coverage}
          job={job}
          error={jobError}
          onDownload={onDownload}
          onAnalyzeAvailable={() => {
            setDialogOpen(false);
            runAnalysis();
          }}
          onCancel={() => setDialogOpen(false)}
        />
      )}
    </div>
  );
}
