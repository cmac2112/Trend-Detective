# Trend Detective client

React + TypeScript + Vite frontend. Draw a region on the map, pick a NASA dataset and a
date range, and see whether it's trending. If data is missing, the app asks before the
server downloads it, and refuses downloads over the server's size limit.

## Run

The API must be running first (see `../TrendApi/README.md`):

```powershell
cd ..\TrendApi; .venv\Scripts\Activate.ps1; uvicorn app.main:app --reload
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

1. **Region**: draw with the polygon or rectangle tool (top-left of the map), or click
   an example. One region at a time; you can edit, drag or delete it.
2. **Dataset and dates**: the dropdown shows each dataset's plain-language definition
   and what's already on the server.
3. **Analyze**: the app first asks the API what's missing
   (`GET /variables/{key}/coverage`).
   - Everything is there: it runs `POST /analyze` straight away.
   - Something is missing: a dialog shows how many months are missing and the
     estimated download size.
     - Within the server limit (default 500 MB): **Download and analyze** starts
       `POST /variables/{key}/fetch`, shows progress by polling `GET /jobs/{id}`, then
       analyzes automatically.
     - Over the limit: the download button is hidden and the dialog suggests a shorter
       range.
     - If at least 24 months are already available, you can analyze those instead.
4. **Results**:
   - verdict badge and summary tiles
   - a chart of the raw monthly values
   - a chart of the anomalies with the trend line (solid if significant, dashed if
     borderline, hidden if no trend)
   - an expandable data table

## Files

| File | Purpose |
|---|---|
| `src/api.ts` | Typed API client |
| `src/App.tsx` | Page layout and the analyze → coverage → fetch → analyze flow |
| `src/components/MapPanel.tsx` | Leaflet map and Geoman drawing tools |
| `src/components/FetchDialog.tsx` | "Data isn't downloaded" dialog and progress |
| `src/components/Results.tsx` | Verdict and stat tiles |
| `src/components/TrendCharts.tsx` | Recharts charts and data table |
| `src/trend.ts` | Significant / borderline / none rule, matching the API |
| `src/index.css` | Styles; follows the system light/dark theme |
