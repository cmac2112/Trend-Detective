# Trend Detective client

React + TypeScript + Vite frontend. Draw one or more regions on the map, pick a NASA
dataset and a date range, and see whether each is trending. Add 2–5 regions to compare
them side by side. The example regions load instantly from data
stored on the server; any other region streams from NASA Earthdata Cloud with a progress
bar and nothing is stored.

## Run

The API must be running first (see `../TrendApi/README.md`):

```powershell
cd ..\TrendApi; .venv\Scripts\Activate.ps1
uvicorn app.main:app --reload --reload-dir app --reload-dir ../PythonPoc/earthtrends
```

Then, in a second terminal:

```powershell
cd client
npm install
npm run dev
```

Open http://localhost:5173.

Port 5173 matters: the API's CORS settings only allow `http://localhost:5173` and
`http://127.0.0.1:5173`. If Vite says 5173 is busy and picks another port, stop the other
process, or add the new origin to the API's `CORS_ORIGINS` environment variable.

The API address defaults to `http://127.0.0.1:8000`. To change it, copy `.env.example`
to `.env.local` and edit `VITE_API_URL`.

## How it works

1. **Regions**: draw with the polygon or rectangle tool (top-left of the map), or click
   **+ example**.
   - Each region gets a letter (A–E) and a colour, used on the map, in the charts and in
     the table.
   - Rename or remove regions in the sidebar list.
   - Up to 5 regions.
2. **Dataset and dates**: the dropdown shows each dataset's plain-language definition
   and what's already on the server.
3. **Analyze** (one region) or **Compare** (2–5 regions): the app first asks the API
   where the data will come from (`POST /plan` or `POST /compare/plan`).
   - **Cached or stored locally** (repeat analyses, and the example regions 2001-2024):
     it calls `POST /analyze` or `POST /compare` and the result appears instantly.
   - **NASA Earthdata Cloud** (anything else): it starts `POST /analyze/jobs` and polls
     `GET /jobs/{id}` every second, showing a progress bar (about 30 s per region for
     24 years). For comparisons it uses `POST /compare/jobs`.
4. **Results** for one region:
   - verdict badge and summary tiles
   - a chart of the raw monthly values
   - a chart of the anomalies with the trend line (solid if significant, dashed if
     borderline, hidden if no trend)
   - an expandable data table
   - a label showing where the data came from (stored, NASA cloud, or cached)

   Under a single-region result, **Why is it changing?** → **Investigate causes** runs
   the cause analysis (`POST /drivers/jobs`) and shows:
   - Claude's explanation (if the API has a key): headline, likely causes labeled
     "shown by the data" or "outside knowledge", things to try next
   - the evidence table: each driver's own trend, correlation, share of the trend, ML
     importance, evidence strength, and which way the effect usually runs
   - model quality and the limits of the analysis

   **Comparison results**:
   - a summary (which regions are significant, which is changing fastest)
   - a side-by-side table: change per decade, 95% range, p-values, verdict and data source
     for each region
   - a chart of every region's monthly values
   - a chart of each region's 12-month smoothed anomalies with its trend line
   - a data table

## Files

| File | Purpose |
|---|---|
| `src/api.ts` | Typed API client |
| `src/App.tsx` | Page layout, region list, and the plan → analyze/compare (instant) or job + progress (cloud) flow |
| `src/regions.ts` | Region slots A–E and their colours (validated categorical palette) |
| `src/components/MapPanel.tsx` | Leaflet map, Geoman drawing tools, up to 5 coloured, labeled regions |
| `src/components/CompareResults.tsx` | Comparison summary, table, multi-region charts |
| `src/components/DriversPanel.tsx` | "Why is it changing?": cause analysis evidence + AI explanation |
| `src/components/Results.tsx` | Verdict and stat tiles |
| `src/components/TrendCharts.tsx` | Recharts charts and data table |
| `src/trend.ts` | Significant / borderline / none rule, matching the API |
| `src/index.css` | Styles; follows the system light/dark theme |
