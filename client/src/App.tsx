import { useEffect, useRef, useState } from "react";
import { api, type AnalyzeResult, type CompareResult, type Job } from "./api";
import type { VariableInfo } from "./api";
import MapPanel, { type MapHandle } from "./components/MapPanel";
import Results from "./components/Results";
import CompareResults from "./components/CompareResults";
import DriversPanel from "./components/DriversPanel";
import avatar from "./assets/142555154.jpg";
import { MAX_REGIONS, SLOT_LETTERS, slotVar, type MapRegion } from "./regions";

const EXAMPLE_LABELS: Record<string, string> = {
  barents_sea: "Barents Sea",
  lake_mead: "Lake Mead",
  amazon_rondonia: "Rondônia (Amazon)",
};

const thisMonth = new Date().toISOString().slice(0, 7);
const message = (err: unknown) => (err instanceof Error ? err.message : String(err));

type Output =
  | { kind: "single"; result: AnalyzeResult; request: { region: GeoJSON.Feature; name: string; start: string; end: string } }
  | { kind: "compare"; result: CompareResult; slots: Record<string, number> };

interface Progress {
  estimatedSeconds: number;
  job: Job | null;
}

export default function App() {
  const mapRef = useRef<MapHandle>(null);
  const [variables, setVariables] = useState<VariableInfo[]>([]);
  const [examples, setExamples] = useState<string[]>([]);
  const [variable, setVariable] = useState("t2m");
  const [start, setStart] = useState("2001-01");
  // 2001-2024 matches the example regions saved on the server, so the demos load instantly.
  const [end, setEnd] = useState("2024-12");
  const [regions, setRegions] = useState<MapRegion[]>([]);

  const [busy, setBusy] = useState(false);
  const [progress, setProgress] = useState<Progress | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [output, setOutput] = useState<Output | null>(null);
  const pollRef = useRef<number | null>(null);

  const selected = variables.find((v) => v.key === variable);
  const comparing = regions.length >= 2;

  useEffect(() => {
    api.variables().then(setVariables).catch((e) => setError(message(e)));
    api.examples().then(setExamples).catch(() => {});
    return () => stopPolling();
  }, []);

  function stopPolling() {
    if (pollRef.current) window.clearInterval(pollRef.current);
    pollRef.current = null;
  }

  /** Poll a background job until it finishes, showing progress meanwhile. */
  function follow<T>(job: Job, estimatedSeconds: number, onDone: (result: T) => void) {
    setProgress({ estimatedSeconds, job });
    pollRef.current = window.setInterval(async () => {
      try {
        const j = await api.job(job.id);
        setProgress({ estimatedSeconds, job: j });
        if (j.status !== "done" && j.status !== "error") return;
        stopPolling();
        setProgress(null);
        setBusy(false);
        if (j.status === "done" && j.result) onDone(j.result as T);
        else setError(j.error ?? "Analysis failed");
      } catch (err) {
        stopPolling();
        setProgress(null);
        setBusy(false);
        setError(message(err));
      }
    }, 1000);
  }

  async function onAnalyze() {
    setError(null);
    if (regions.length === 0) return setError("Draw a region on the map first (polygon or rectangle tool, top left).");
    if (start > end) return setError("The start month must be before the end month.");
    const names = regions.map((r) => r.name.trim());
    if (names.some((n) => !n)) return setError("Every region needs a name.");
    if (new Set(names).size !== names.length) return setError("Region names must be different.");

    setBusy(true);
    setOutput(null);
    stopPolling();
    try {
      if (!comparing) {
        const body = { variable, region: regions[0].feature, start, end };
        const request = { region: regions[0].feature, name: regions[0].name.trim(), start, end };
        const plan = await api.plan(body);
        if (plan.source !== "cloud") {
          setOutput({ kind: "single", result: await api.analyze(body), request });
          setBusy(false);
          return;
        }
        const { job } = await api.analyzeJob(body);
        follow<AnalyzeResult>(job, plan.estimated_seconds, (result) => setOutput({ kind: "single", result, request }));
      } else {
        const slots = Object.fromEntries(regions.map((r) => [r.name.trim(), r.slot]));
        const body = { variable, start, end, regions: regions.map((r) => ({ name: r.name.trim(), region: r.feature })) };
        const plan = await api.comparePlan(body);
        if (plan.source !== "cloud") {
          setOutput({ kind: "compare", result: await api.compare(body), slots });
          setBusy(false);
          return;
        }
        const { job } = await api.compareJob(body);
        follow<CompareResult>(job, plan.estimated_seconds, (result) => setOutput({ kind: "compare", result, slots }));
      }
    } catch (err) {
      setError(message(err));
      setBusy(false);
    }
  }

  async function onExample(name: string) {
    try {
      const feature = await api.example(name);
      const base = EXAMPLE_LABELS[name] ?? name;
      const taken = new Set(regions.map((r) => r.name));
      let label = base;
      for (let i = 2; taken.has(label); i++) label = `${base} ${i}`;
      mapRef.current?.addFeature(feature, label);
    } catch (err) {
      setError(message(err));
    }
  }

  return (
    <div className="app">
      <aside className="sidebar">
        <header>
          <h1>Trend Detective</h1>
          <p className="muted">Draw a region, pick a NASA dataset, and find out if it's really changing.</p>
        </header>

        <section className="step">
          <h2><span className="step-num">1</span> Choose regions</h2>
          <p className="small muted">
            Draw with the polygon or rectangle tool (top left of the map), or add an example. Add up to{" "}
            {MAX_REGIONS} regions to compare them.
          </p>
          <div className="chips">
            {examples.map((name) => (
              <button key={name} type="button" className="chip" onClick={() => onExample(name)}>
                + {EXAMPLE_LABELS[name] ?? name}
              </button>
            ))}
          </div>

          {regions.length === 0 ? (
            <p className="small region-status">No regions yet</p>
          ) : (
            <ul className="region-list">
              {regions.map((r) => (
                <li key={r.id}>
                  <span className="swatch" style={{ background: slotVar(r.slot) }} aria-hidden />
                  <span className="region-letter" aria-hidden>{SLOT_LETTERS[r.slot]}</span>
                  <input
                    aria-label={`Name of region ${SLOT_LETTERS[r.slot]}`}
                    value={r.name}
                    maxLength={60}
                    onChange={(e) => mapRef.current?.rename(r.id, e.target.value)}
                  />
                  <button
                    type="button"
                    className="icon-btn"
                    aria-label={`Remove ${r.name}`}
                    onClick={() => mapRef.current?.remove(r.id)}
                  >
                    ✕
                  </button>
                </li>
              ))}
            </ul>
          )}
          {regions.length > 0 && (
            <div className="region-actions">
              <span className="small muted">
                {comparing ? `Comparing ${regions.length} regions` : "Add another region to compare"}
              </span>
              <button type="button" className="ghost small" onClick={() => mapRef.current?.clear()}>
                Clear all
              </button>
            </div>
          )}
        </section>

        <section className="step">
          <h2><span className="step-num">2</span> Choose what to investigate</h2>
          <label className="field">
            <span>Dataset</span>
            <select
              value={variable}
              onChange={(e) => {
                setVariable(e.target.value);
                setOutput(null); // old results are for a different dataset
              }}
            >
              {[...new Set(variables.map((v) => v.category))].map((cat) => (
                <optgroup key={cat} label={cat}>
                  {variables
                    .filter((v) => v.category === cat)
                    .map((v) => (
                      <option key={v.key} value={v.key}>
                        {v.name} ({v.units})
                      </option>
                    ))}
                </optgroup>
              ))}
            </select>
          </label>
          {selected && (
            <div className="var-info">
              <p>{selected.definition}</p>
              <p className="small muted">
                Data {selected.data_ends ? `from ${selected.data_starts} to ${selected.data_ends}` : `from ${selected.data_starts} onward`} ·{" "}
                {selected.source}
              </p>
            </div>
          )}
        </section>

        <section className="step">
          <h2><span className="step-num">3</span> Choose when</h2>
          <div className="row">
            <label className="field">
              <span>From</span>
              <input type="month" value={start} min={selected?.data_starts} max={selected?.data_ends ?? thisMonth} onChange={(e) => setStart(e.target.value)} />
            </label>
            <label className="field">
              <span>To</span>
              <input type="month" value={end} min={selected?.data_starts} max={selected?.data_ends ?? thisMonth} onChange={(e) => setEnd(e.target.value)} />
            </label>
          </div>
          <p className="small muted">Longer periods find trends more reliably. Aim for 10+ years.</p>
        </section>

        <button type="button" className="primary big" onClick={onAnalyze} disabled={busy}>
          {busy ? "Working…" : comparing ? `Compare ${regions.length} regions` : "Analyze trend"}
        </button>

        <p className="small muted">
          Example regions are stored on this computer and load instantly. Other regions stream straight from NASA
          Earthdata Cloud (about 30 seconds per region for 24 years), and repeat analyses come from a cache.
        </p>

        {error && (
          <p className="callout error" role="alert">
            <span aria-hidden>✕</span> {error}
          </p>
        )}

        <footer className="sidebar-footer small muted">
          <img className="avatar" src={avatar} alt="Caden McArthur" width={40} height={40} />
          <div className="footer-links">
            <span>Built by Caden McArthur</span>
            <span>
              <a href="https://github.com/cmac2112/Trend-Detective" target="_blank" rel="noopener noreferrer">
                GitHub
              </a>
              {" · "}
              <a href="https://www.linkedin.com/in/cadenmcarthur/" target="_blank" rel="noopener noreferrer">
                LinkedIn
              </a>
              {" · "}
              <a href="https://www.cadenmcarthur.net" target="_blank" rel="noopener noreferrer">
                Website
              </a>
            </span>
          </div>
        </footer>
      </aside>

      <main className="main">
        <div className="map-wrap">
          <MapPanel
            ref={mapRef}
            onChange={(list) => {
              setRegions(list);
              setOutput(null); // old results are for different regions
            }}
            onLimit={() => setError(`You can compare up to ${MAX_REGIONS} regions. Remove one to add another.`)}
          />
        </div>

        {progress && (
          <div className="progress-card" aria-live="polite">
            <div className="progress-head">
              <span className="source-pill cloud">☁ NASA Earthdata Cloud</span>
              <span className="small muted">about {progress.estimatedSeconds} s</span>
            </div>
            <div className="small">{progress.job?.message ?? "Starting…"}</div>
            <progress max={1} value={progress.job?.progress ?? undefined} />
          </div>
        )}

        {output?.kind === "single" && (
          <>
            <Results result={output.result} />
            <DriversPanel
              key={`${output.result.variable.key}|${output.request.start}|${output.request.end}|${JSON.stringify(output.request.region.geometry)}`}
              variable={output.result.variable.key}
              variableName={output.result.variable.name}
              region={output.request.region}
              regionName={output.request.name}
              start={output.request.start}
              end={output.request.end}
            />
          </>
        )}
        {output?.kind === "compare" && <CompareResults result={output.result} slots={output.slots} />}
        {!output && !busy && (
          <div className="empty muted">Results will appear here after you analyze a region.</div>
        )}
      </main>
    </div>
  );
}
