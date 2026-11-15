import { useEffect, useMemo, useRef, useState } from "react";
import { api, hasMap, type AnalyzeResult, type CompareResult, type Job, type ScanItem, type ScanResult, type TrendMap } from "./api";
import type { VariableInfo } from "./api";
import MapPanel, { type MapHandle } from "./components/MapPanel";
import Results from "./components/Results";
import CompareResults from "./components/CompareResults";
import DriversPanel from "./components/DriversPanel";
import ScanResults from "./components/ScanResults";
import TrendLegend from "./components/TrendLegend";
import DetectiveQuestions from "./components/DetectiveQuestions";
import { suggest } from "./detective";
import Tour, { type TourStep } from "./components/Tour";
import avatar from "./assets/142555154.jpg";
import { MAX_REGIONS, SLOT_LETTERS, slotVar, type MapRegion } from "./regions";

const EXAMPLE_LABELS: Record<string, string> = {
  barents_sea: "Barents Sea",
  lake_mead: "Lake Mead",
  amazon_rondonia: "Rondônia (Amazon)",
};

const thisMonth = new Date().toISOString().slice(0, 7);
const message = (err: unknown) => (err instanceof Error ? err.message : String(err));

type SingleRequest = { region: GeoJSON.Feature; name: string; start: string; end: string };
type ScanOutput = { kind: "scan"; result: ScanResult; region: GeoJSON.Feature; name: string };
type Output =
  | { kind: "single"; result: AnalyzeResult; request: SingleRequest; fromScan?: boolean }
  | { kind: "compare"; result: CompareResult; slots: Record<string, number> }
  | ScanOutput;

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
  // The last scan, so "Back to scan" works after opening one of its variables.
  const [scan, setScan] = useState<ScanOutput | null>(null);
  const [openingKey, setOpeningKey] = useState<string | null>(null);
  const [showMap, setShowMap] = useState(true);
  const [place, setPlace] = useState<string | null>(null);
  const [interest, setInterest] = useState<string | null>(null);
  const [touring, setTouring] = useState(false);
  const suggested = useMemo(() => suggest(place, interest, 6).map((s) => s.key), [place, interest]);
  const pollRef = useRef<number | null>(null);

  const selected = variables.find((v) => v.key === variable);
  const comparing = regions.length >= 2;

  // Per-cell trend maps for whatever is on screen, on one shared colour scale.
  const trend = useMemo(() => {
    let maps: TrendMap[] = [];
    let units = "";
    if (output?.kind === "single") {
      units = output.result.variable.units;
      if (hasMap(output.result.trend_map)) maps = [output.result.trend_map];
    } else if (output?.kind === "compare") {
      units = output.result.variable.units;
      maps = output.result.regions.flatMap((r) => (r.error === undefined && hasMap(r.trend_map) ? [r.trend_map] : []));
    }
    maps = maps.filter((m) => m.summary.cells_with_trend > 0);
    const limit = Math.max(0, ...maps.map((m) => m.summary.color_limit));
    return { maps, units, limit, coarsened: maps.some((m) => m.coarsened_by > 1) };
  }, [output]);

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
        await runSingle(variable, { region: regions[0].feature, name: regions[0].name.trim(), start, end });
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

  /** Analyze one region: instantly when cached/local, otherwise as a background job. */
  async function runSingle(variableKey: string, request: SingleRequest, fromScan = false) {
    const body = { variable: variableKey, region: request.region, start: request.start, end: request.end };
    const plan = await api.plan(body);
    if (plan.source !== "cloud") {
      setOutput({ kind: "single", result: await api.analyze(body), request, fromScan });
      setBusy(false);
      return;
    }
    const { job } = await api.analyzeJob(body);
    follow<AnalyzeResult>(job, plan.estimated_seconds, (result) => setOutput({ kind: "single", result, request, fromScan }));
  }

  /** Re-run the current single analysis with an earlier start (a longer record). */
  async function rerunFrom(from: string) {
    if (output?.kind !== "single") return;
    const { result, request, fromScan } = output;
    setStart(from);
    setError(null);
    setBusy(true);
    stopPolling();
    try {
      await runSingle(result.variable.key, { ...request, start: from }, fromScan);
    } catch (err) {
      setError(message(err));
      setBusy(false);
    }
  }

  async function onScan(period?: { start: string; end: string }) {
    const from = period?.start ?? start;
    const to = period?.end ?? end;
    setError(null);
    if (regions.length !== 1) {
      return setError(regions.length === 0
        ? "Draw a region on the map first (polygon or rectangle tool, top left)."
        : "Scanning works on one region at a time. Remove the others first.");
    }
    if (from > to) return setError("The start month must be before the end month.");
    const r = regions[0];
    const body = { region: r.feature, start: from, end: to };
    setBusy(true);
    setOutput(null);
    stopPolling();
    try {
      const plan = await api.scanPlan(body);
      const { job } = await api.scanJob(body);
      follow<ScanResult>(job, plan.estimated_seconds, (result) => {
        const out: ScanOutput = { kind: "scan", result, region: r.feature, name: r.name.trim() || "this region" };
        setScan(out);
        setOutput(out);
      });
    } catch (err) {
      setError(message(err));
      setBusy(false);
    }
  }

  /** Open one variable from a scan: its full result is already cached on the server. */
  async function openScanItem(item: ScanItem) {
    if (!scan) return;
    setError(null);
    setOpeningKey(item.key);
    setBusy(true);
    // Show the period and variable that the scan actually used for this dataset.
    setVariable(item.key);
    setStart(item.start);
    setEnd(item.end);
    try {
      await runSingle(item.key, { region: scan.region, name: scan.name, start: item.start, end: item.end }, true);
    } catch (err) {
      setError(message(err));
      setBusy(false);
    } finally {
      setOpeningKey(null);
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

  // The guided demo: the Rondônia story, each step done live in the app.
  const DEMO = "amazon_rondonia";
  const tourSteps: TourStep[] = [
    {
      title: "Meet Rondônia, Brazil",
      text:
        "A state in the southern Amazon where large areas of rainforest have been cleared for farms and cattle " +
        "since the 1970s. We've outlined it on the map. Is anything changing here, and where?",
      target: "map",
      run: async () => {
        stopPolling();
        setOutput(null);
        setScan(null);
        mapRef.current?.clear();
        mapRef.current?.addFeature(await api.example(DEMO), EXAMPLE_LABELS[DEMO]);
      },
    },
    {
      title: "Every detective starts with questions",
      text:
        "What kind of place is this? A rainforest. The app suggests leads worth checking there, " +
        "each with a reason: greenness, rainfall, evaporation, temperature.",
      target: "detective",
      run: () => {
        setPlace("rainforest");
        setInterest("any");
      },
    },
    {
      title: "Scan all 15 NASA variables at once",
      text:
        "Instead of guessing, test every variable over 2001-2024. Each one gets the same tests, and they're " +
        "ranked by how significant the trend is and how big it is compared with normal ups and downs.",
      target: "scan-table",
      run: () => {
        setStart("2001-01");
        setEnd("2024-12");
        return onScan({ start: "2001-01", end: "2024-12" });
      },
    },
    {
      title: "A clue: the forest is losing its green",
      text:
        "Vegetation greenness (NDVI) is falling significantly, marked \"matches your answers\" and \"opposite " +
        "trends inside\". Rain, soil moisture and runoff are falling too, while air temperature rises.",
      target: "scan-row-ndvi",
    },
    {
      title: "Where is it changing? The trend map",
      text:
        "Every grid cell is coloured by its own trend: blue is losing greenness, red is gaining. Solid cells " +
        "are significant even after allowing for testing thousands of cells at once. The losses come in " +
        "patches, not everywhere, which a single regional average would hide.",
      target: "map",
      run: async () => {
        const ndvi = scan?.result.variables.find((v) => v.key === "ndvi");
        if (ndvi) await openScanItem(ndvi);
      },
    },
    {
      title: "How much, and is it real?",
      text:
        "The change per decade with its 95% confidence range, and two independent significance tests " +
        "(a t-test corrected for autocorrelation, and Mann-Kendall). We only call a trend significant " +
        "when both agree.",
      target: "tiles",
    },
    {
      title: "Why is it changing?",
      text:
        "This tests the related variables (rain, soil moisture, temperature) as possible drivers, then " +
        "Claude explains the evidence in plain language, including when it's weak. Now try your own region: " +
        "draw one with the tools at the top left of the map.",
      target: "drivers",
    },
  ];

  return (
    <div className="app">
      {touring && <Tour steps={tourSteps} busy={busy} onClose={() => setTouring(false)} />}
      <aside className="sidebar">
        <header>
          <h1>Trend Detective</h1>
          <p className="muted">Draw a region, pick a NASA dataset, and find out if it's really changing.</p>
          {examples.includes(DEMO) && (
            <button type="button" className="secondary small tour-start" onClick={() => setTouring(true)} disabled={touring}>
              ▶ Watch a guided demo
            </button>
          )}
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
          <DetectiveQuestions
            place={place}
            interest={interest}
            onPlace={setPlace}
            onInterest={setInterest}
            variables={variables}
            selected={variable}
            onPick={(key) => {
              setVariable(key);
              setOutput(null);
            }}
          />
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
        <button
          type="button"
          className="secondary"
          onClick={() => onScan()}
          data-tour="scan-btn"
          disabled={busy || comparing}
          title={comparing ? "Scanning works on one region at a time" : undefined}
        >
          🔍 Not sure what to look at? Scan all variables here
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
        <div className="map-wrap" data-tour="map">
          <MapPanel
            ref={mapRef}
            onChange={(list) => {
              setRegions(list);
              setOutput(null); // old results are for different regions
              setScan(null);
            }}
            onLimit={() => setError(`You can compare up to ${MAX_REGIONS} regions. Remove one to add another.`)}
            trendMaps={showMap ? trend.maps : []}
            trendLimit={trend.limit}
          />
          {trend.maps.length > 0 && (
            <TrendLegend
              units={trend.units}
              limit={trend.limit}
              coarsened={trend.coarsened}
              visible={showMap}
              onToggle={setShowMap}
            />
          )}
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

        {output?.kind === "scan" && (
          <ScanResults
            result={output.result}
            regionName={output.name}
            busyKey={openingKey}
            onOpen={openScanItem}
            suggested={suggested}
          />
        )}
        {output?.kind === "single" && (
          <>
            {output.fromScan && scan && (
              <button type="button" className="ghost small back-btn" onClick={() => setOutput(scan)}>
                ← Back to all variables
              </button>
            )}
            <Results
              result={output.result}
              regionName={output.request.name}
              dataStarts={variables.find((x) => x.key === output.result.variable.key)?.data_starts}
              onExtend={(from) => rerunFrom(from)}
            />
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
