# Trend Detective API

FastAPI service that wraps the `earthtrends` core library (in `../PythonPoc`).

**Where the data comes from** (checked in this order):
- **Cache**: the same variable, region shape and period analyzed recently. Instant. Held in
  memory (up to 512 results, least recently used dropped first) and cleared on restart.
- **Stored on this computer** when a local copy covers the region and period. The demo
  regions are saved with `python -m earthtrends prepare-examples` (a few MB), so
  presentations work offline and instantly.
- **Otherwise, streamed from NASA Earthdata Cloud** for that one analysis and never saved.
  NASA's cloud OPeNDAP service cuts out just the cells around the polygon, so 24 years
  takes about 30 seconds and a few MB of network traffic. Disk use doesn't grow no matter
  how many people use the app.

Streaming needs a **NASA Earthdata token** on the server (`EARTHDATA_TOKEN`). The API
never uses a username/password or `~/_netrc`, so a hosted copy holds only a token that
expires and can be revoked. Local data works without it.

**AI explanations** (part of the cause analysis) need an Anthropic API key. Everything else
works without one.

Both secrets go in `TrendApi/.env` on a dev machine:
1. Copy `TrendApi/.env.example` to `TrendApi/.env`.
2. Earthdata token: log in at https://urs.earthdata.nasa.gov/users/tokens, click
   **Generate Token**, and paste it after `EARTHDATA_TOKEN=`.
3. Claude key: paste it after `ANTHROPIC_API_KEY=`.
4. Restart the API: stop uvicorn and start it again, because `--reload` doesn't watch `.env`.

`.env` is git-ignored, and an environment variable that's already set takes priority over
the file, so on a host such as Azure you set them as app settings instead. Check
`GET /health`: `cloud_enabled` and `ai_enabled` should be `true`, and `earthdata_token`
shows when the token expires (Earthdata tokens last 60 days; the token itself is never shown).

## Setup

```powershell
cd TrendApi
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt     # also installs ../PythonPoc as an editable library
```

Local data lives in `../PythonPoc/data` by default; set `EARTHTRENDS_DATA_DIR` to change it.
To save the demo regions locally (once, about 5 minutes):

```powershell
cd ..\PythonPoc
python -m earthtrends prepare-examples
```

## Run

```powershell
uvicorn app.main:app --reload --reload-dir app --reload-dir ../PythonPoc/earthtrends
```

Plain `--reload` only watches the `TrendApi/` folder. Most of the science lives in
`../PythonPoc/earthtrends`, so without the second `--reload-dir`, changes there (for
example new variables in `catalog.py`) don't reach the running server until you restart it.

- API: http://127.0.0.1:8000
- Interactive docs (try requests in the browser): http://127.0.0.1:8000/docs

## Endpoints

| Method | Path | What it does |
|---|---|---|
| GET | `/health` | Checks the server is running |
| GET | `/variables` | Lists every variable the tool knows about |
| GET | `/variables/{key}` | Details for one variable |
| GET | `/examples` | Lists the ready-made demo regions |
| GET | `/examples/{name}` | Returns one demo region's polygon |
| POST | `/plan` | Says whether an analysis would use local data or NASA's cloud, and roughly how long it takes |
| POST | `/analyze` | **The main endpoint**: time series + trend analysis for a variable over a polygon (waits for the result) |
| POST | `/analyze/jobs` | The same analysis in the background, for slow cloud requests |
| POST | `/compare/plan` | Like `/plan`, for 2–5 regions at once |
| POST | `/compare` | Analyze one variable over 2–5 regions for the same period (waits for the result) |
| POST | `/compare/jobs` | The same comparison in the background |
| GET | `/jobs/{id}` | Progress of a background analysis or comparison, and its result when done |
| POST | `/drivers` | **Why is it changing?** Compares the variable with its related variables and has Claude explain the evidence |
| POST | `/drivers/jobs` | The same cause analysis in the background, with progress |
| POST | `/cache/clear` | Forget cached results (e.g. to show a live NASA stream in a demo). Admin only |

A typical frontend flow:
1. Call `GET /variables` to fill the variable picker.
2. The user draws a polygon on the map, or picks a demo region from `GET /examples/{name}`.
3. `POST /plan`:
   - if `source` is `"cache"` or `"local"`, call `POST /analyze` (instant)
   - if it's `"cloud"`, call `POST /analyze/jobs`, then poll `GET /jobs/{id}` every second
     to show progress
4. Chart the `series` and show the `stats`.

For Postman or curl, `POST /analyze` works for both. A cloud request just takes about 30
seconds to respond.

---

### GET /health

Confirms the API is up, and shows:
- which data folder it reads local data from
- whether it can reach NASA's cloud (`cloud_enabled` is `false` when the server has no
  Earthdata credentials)
- cache statistics

```json
{ "status": "ok", "data_dir": "C:\\...\\Trend-Detective\\PythonPoc\\data", "cloud_enabled": true,
  "cache": { "entries": 3, "max_entries": 512, "hits": 5, "misses": 3 } }
```

---

### GET /variables

Returns every variable with:
- a plain-language definition, to show to users
- its units and NASA data source
- what's stored locally

Every variable can be analyzed anywhere: anything not stored locally streams from NASA.

```json
[
  {
    "key": "t2m",
    "name": "Air temperature (2 m)",
    "units": "°C",
    "definition": "The temperature of the air about 2 meters above the ground, the height a weather station thermometer sits at. From the MERRA-2 reanalysis model.",
    "source": "M2TMNXSLV v5.12.4",
    "related": ["precip", "soil_moisture", "evapotranspiration"],
    "data_starts": "1980-01",
    "local_global": { "start": "1999-01", "end": "2024-12", "n_months": 312 },
    "local_examples": ["amazon_rondonia", "barents_sea", "lake_mead"]
  },
  ...
]
```

| Field | Meaning |
|---|---|
| `key` | ID to send as `variable` in `/analyze` |
| `related` | Variables physically linked to this one (planned use: cause analysis) |
| `data_starts` | First month NASA has data for |
| `local_global` | Whole-world data stored locally (from the optional `earthtrends fetch` command), or `null` |
| `local_examples` | Demo regions stored locally for this variable |

### GET /variables/{key}

The same information for a single variable, e.g. `GET /variables/t2m`. Returns 404 for an unknown key.

---

### GET /examples

Names of the built-in demo regions:

```json
["amazon_rondonia", "barents_sea", "lake_mead"]
```

| Name | Region | What to try |
|---|---|---|
| `barents_sea` | Arctic Ocean north of Norway | `t2m`: strong, significant warming |
| `lake_mead` | Lake Mead, Nevada/Arizona | `soil_moisture`, `precip`: Southwest drought |
| `amazon_rondonia` | Rondônia, Brazil | `evapotranspiration`, `precip`: deforestation frontier |

### GET /examples/{name}

Returns the demo region as a GeoJSON Feature. Paste it straight into the `region` field
of `/analyze`, or draw it on the map.

```json
{
  "type": "Feature",
  "properties": { "name": "Barents Sea (Arctic, fast warming as sea ice retreats)" },
  "geometry": { "type": "Polygon", "coordinates": [[[20.0, 72.0], [55.0, 72.0], ...]] }
}
```

---

### POST /analyze

The core of the tool. Given a variable and a region, it:
1. Averages the variable over every grid cell inside the polygon, giving one value per month.
2. Removes the seasonal cycle, so that, for example, summer being warmer than winter doesn't
   look like a trend.
3. Fits a trend line and runs two significance tests (t-test and Mann-Kendall).
4. Returns the numbers, a plain-English verdict, and the monthly data for charting.

**Request**

```json
{
  "variable": "t2m",
  "region": { "type": "Polygon", "coordinates": [[[20,72],[55,72],[55,80],[20,80],[20,72]]] },
  "start": "2001-01",
  "end": "2024-12",
  "source": "auto",
  "include_series": true
}
```

| Field | Required | Meaning |
|---|---|---|
| `variable` | yes | A `key` from `/variables` |
| `region` | yes | GeoJSON Polygon or MultiPolygon, a Feature, or a FeatureCollection. Coordinates are **[longitude, latitude]**, which is the GeoJSON standard (note: Leaflet uses lat/lng) |
| `start`, `end` | no | The period, as `YYYY-MM`. Defaults: `2001-01` to December of last year |
| `source` | no | `auto` (default): cache, then local data, then NASA cloud. `local`: never use the network (cache or stored data only; 409 if neither covers it). `cloud`: always stream fresh data from NASA |
| `include_series` | no | Default `true`. Set it to `false` to get only the statistics, a much smaller response |

**Response** (real result for the Barents Sea; numbers rounded, lists shortened)

```json
{
  "variable": {
    "key": "t2m", "name": "Air temperature (2 m)", "units": "°C",
    "definition": "The temperature of the air about 2 meters above the ground, ...",
    "source": "M2TMNXSLV v5.12.4"
  },
  "region": {
    "grid_cells": 861,
    "cells_with_data": 861,
    "grid_resolution_deg": [0.5, 0.625],
    "bounds": [20.0, 72.0, 60.0, 80.0]
  },
  "data_source": { "type": "local", "description": "local copy of 'barents_sea'" },
  "stats": {
    "n_months": 288, "start": "2001-01", "end": "2024-12", "years": 23.92,
    "units": "°C",
    "mean": -1.51,
    "linear": {
      "slope_per_decade": 0.769,
      "ci95_per_decade": [0.241, 1.296],
      "total_change": 1.838,
      "percent_of_mean_per_decade": null,
      "r_squared": 0.082,
      "p_value": 0.0048,
      "p_value_naive": 0.0000007,
      "lag1_autocorrelation": 0.50,
      "effective_n": 95.2,
      "slope_per_year": 0.0769,
      "intercept": -154.72
    },
    "mann_kendall": {
      "trend": "increasing", "p_value": 0.0056, "tau": 0.188, "sen_slope_per_decade": 0.694
    },
    "seasonal_mann_kendall": {
      "trend": "increasing", "p_value": 0.00000006, "sen_slope_per_decade": 0.671
    },
    "climatology": { "1": -5.81, "2": -6.00, "...": "..." },
    "significant": true,
    "verdict": "Significant trend: increasing by about 0.769 °C per decade over 2001-01 to 2024-12. Both the t-test (p = 0.005) and Mann-Kendall test (p = 0.006) say this is unlikely to be random variation."
  },
  "series": [
    { "date": "2001-01", "value": -5.82, "anomaly": -0.003 },
    { "date": "2001-02", "value": -5.65, "anomaly": 0.350 },
    "..."
  ]
}
```

**What the fields mean**

`region`: what the polygon covered.

| Field | Meaning |
|---|---|
| `grid_cells` | Number of data grid squares inside the polygon |
| `cells_with_data` | Cells that actually have values; lower when part of the polygon is ocean for a land-only variable |
| `grid_resolution_deg` | Size of one grid square in degrees (lat, lon) |
| `bounds` | Polygon bounding box: [west, south, east, north] |

`data_source.type` is `"local"` or `"cloud"`. `description` says which local copy was used.
`data_source.cached` is `true` when the result came from the cache.

`stats.linear`: the straight-line trend, fitted to the anomalies.

| Field | Meaning |
|---|---|
| `slope_per_decade` | **The headline number**: how much the variable changes per 10 years, in `units` |
| `ci95_per_decade` | 95% confidence interval for the slope. If it doesn't include 0, the trend is significant |
| `total_change` | Slope × years: how much it changed over the whole period |
| `percent_of_mean_per_decade` | Slope as a % of the average. `null` for temperature, where a percentage is meaningless |
| `p_value` | t-test p-value, **adjusted for autocorrelation**. Below 0.05 means significant |
| `p_value_naive` | Unadjusted p-value, kept for comparison. It's usually too optimistic |
| `r_squared` | Share of the month-to-month variation the trend line explains. It's often small even for real trends, because monthly data is noisy |
| `lag1_autocorrelation`, `effective_n` | How similar each month is to the previous one, and how many truly independent data points that leaves |
| `slope_per_year`, `intercept` | Trend line equation for drawing it on a chart: anomaly = intercept + slope_per_year × decimal year |

Mann-Kendall tests: a second, independent check that doesn't assume a straight line or bell-curve noise.

| Field | Meaning |
|---|---|
| `mann_kendall.trend` | `"increasing"`, `"decreasing"` or `"no trend"` |
| `mann_kendall.p_value` | Below 0.05 means significant (adjusted for autocorrelation) |
| `mann_kendall.tau` | Strength of the trend, from −1 to +1 |
| `mann_kendall.sen_slope_per_decade` | A robust slope estimate that outliers barely affect |
| `seasonal_mann_kendall` | Compares each month only with the same month in other years (January with January, and so on) |

Summary fields:

| Field | Meaning |
|---|---|
| `climatology` | Average value for each calendar month (`"1"` = January). This is the seasonal cycle that was removed |
| `significant` | `true` only when **both** the t-test and Mann-Kendall have p < 0.05 |
| `verdict` | One- or two-sentence plain-English summary to show to users |

`series`: one entry per month.

| Field | Meaning |
|---|---|
| `date` | `YYYY-MM` |
| `value` | The actual monthly average over the region; chart this to show the raw data |
| `anomaly` | The value minus that month's normal; chart this with the trend line |

**Errors**

| Code | When | Example `detail` |
|---|---|---|
| 404 | Unknown variable | `Unknown variable 'temp'. Options: precip, t2m, ...` |
| 409 | `source: "local"` but no local data covers the request | `No local data covers this region and period.` |
| 422 | Bad GeoJSON, bad or out-of-order dates, a region with no data (e.g. ocean for soil moisture), fewer than 24 months of data, or a NASA request that failed | `Invalid region GeoJSON: ...` |
| 503 | The request needs NASA's cloud, but the server has no Earthdata credentials | `This needs NASA's cloud, but ...` |

### POST /plan

Same body as `/analyze`. Answers "where would the data come from, and how long?" without
running anything. The frontend uses it to choose between `/analyze` and `/analyze/jobs`.

`source` is `"cache"`, `"local"` or `"cloud"`.

```json
{ "source": "cloud", "description": "streamed from NASA Earthdata Cloud",
  "start": "2001-01", "end": "2024-12", "months": 288, "estimated_seconds": 32 }
```

### POST /analyze/jobs

Same body as `/analyze`. Starts the analysis in the background and returns right away (202):

```json
{ "job": { "id": "3f2a9c1b7d4e", "status": "queued", "...": "..." },
  "plan": { "source": "cloud", "...": "..." } }
```

### POST /compare

Analyze **one variable over 2–5 regions for the same period**: for example, warming in the
Arctic vs the Amazon. Each region is analyzed exactly like `/analyze`, using the cache,
local data or NASA cloud as available.

**Request**

```json
{
  "variable": "t2m",
  "start": "2001-01",
  "end": "2024-12",
  "regions": [
    { "name": "Barents Sea", "region": { "type": "Polygon", "coordinates": [[[20,72],[55,72],[55,80],[20,80],[20,72]]] } },
    { "name": "Lake Mead",   "region": { "type": "Polygon", "coordinates": [[[-115.3,35.7],[-113.7,35.7],[-113.7,36.8],[-115.3,36.8],[-115.3,35.7]]] } }
  ],
  "include_series": true
}
```

Region names must be unique; they identify each region in the response. `source` works
like `/analyze`.

**Response** (shortened)

```json
{
  "variable": { "key": "t2m", "name": "Air temperature (2 m)", "units": "°C", "...": "..." },
  "start": "2001-01", "end": "2024-12",
  "regions": [
    { "name": "Barents Sea", "region": { "...": "..." }, "data_source": { "type": "local", "cached": false, "...": "..." },
      "stats": { "linear": { "slope_per_decade": 0.769, "...": "..." }, "significant": true, "...": "..." },
      "series": [ { "date": "2001-01", "value": -5.82, "anomaly": -0.003 }, "..." ] },
    { "name": "Lake Mead", "...": "same shape as /analyze, without `variable`" }
  ],
  "summary": {
    "analyzed": 2,
    "significant": ["Barents Sea", "Lake Mead"],
    "fastest_change": { "name": "Barents Sea", "slope_per_decade": 0.769 }
  }
}
```

- If one region can't be analyzed (for example ocean for soil moisture), its entry is
  `{ "name": ..., "error": "..." }` and the other regions still come back.
- Only if **none** can be analyzed is the response a 422.
- Regions are analyzed at the same time. All NASA requests share one limit for the whole
  server (`EARTHTRENDS_NASA_CONCURRENCY`, default 24), so this doesn't overload NASA.
  Measured: 3 cloud regions over 10 years take about 15 s, against 40 s one after another.

### POST /compare/plan and POST /compare/jobs

Same body as `/compare`.

`/compare/plan` returns each region's plan and the total estimated time. `source` is
`"cloud"` if any region needs NASA, otherwise `"local"`:

```json
{ "source": "cloud", "estimated_seconds": 33,
  "regions": [ { "name": "Barents Sea", "source": "local", "...": "..." },
               { "name": "Europe", "source": "cloud", "...": "..." } ] }
```

`/compare/jobs` starts the comparison in the background. Its progress counts months
across all cloud regions together, and `result` holds the `/compare` response when done.

### POST /drivers (cause analysis)

Same body as `/analyze`, plus two optional fields:
- `region_name`: helps the AI explanation, e.g. `"Rondônia (Amazon)"`.
- `explain`: default `true`. Set it to `false` to skip Claude.

What it does:
1. Analyzes the target and each of its `related` variables for the same region and period,
   using the cache, local data or NASA cloud.
2. **Correlation:** compares the target's anomalies (seasonal cycle removed) with each
   driver's, with the driver leading by 0–3 months. P-values are adjusted for
   autocorrelation.
3. **Regression:** fits the target on all drivers, then converts each coefficient into
   "how much of the target's trend this driver's own trend implies" (`share_of_target_trend`).
4. **Machine learning:** a random forest on the lagged drivers, giving permutation importance
   per driver. Time-ordered cross-validation reports whether the model predicts anything
   at all (`has_skill`).
5. Labels each driver's **evidence** as `strong`, `moderate` or `weak`, and adds the known
   **physical link**, including which way the effect usually runs (rain drives soil
   moisture, not the reverse).
6. **Claude** (`claude-haiku-5-5`, structured output) writes a plain-language explanation
   grounded in those numbers. It separates what the data shows from outside knowledge (such
   as deforestation) and lists caveats.

**Response** (real Rondônia temperature result, shortened)

```json
{
  "variable": { "key": "t2m", "...": "..." }, "start": "2001-01", "end": "2024-12",
  "target": { "stats": { "...": "same as /analyze" }, "region": { "...": "..." }, "data_source": { "...": "..." } },
  "drivers": [
    { "rank": 1, "key": "soil_moisture", "name": "Soil moisture (top 10 cm)", "evidence": "strong",
      "trend": { "slope_per_decade": -1.417, "significant": true, "...": "..." },
      "correlation": { "r": -0.67, "lag_months": 0, "p_value": 0.0000, "n": 288 },
      "regression": { "share_of_target_trend": 0.69, "trend_contribution_per_decade": 0.56, "...": "..." },
      "ml_importance_share": 0.85,
      "physical_link": { "likely_direction": "both", "mechanism": "Drier soil evaporates less water, ..." } },
    "..."
  ],
  "models": { "regression": { "r_squared": 0.46, "n_months": 288 },
              "random_forest": { "available": true, "cv_r2": -0.03, "has_skill": false } },
  "region_context": { "centroid": { "lat": -10.7, "lon": -62.4 }, "latitude_zone": "tropical",
                      "annual_precip_mm": 1729, "mean_temp_c": 26.4, "...": "..." },
  "caveats": [ "These are statistical associations, not proof of cause. ...", "..." ],
  "explanation": {
    "available": true, "model": "claude-haiku-5-5", "cached": false,
    "headline": "...", "summary": "...",
    "likely_causes": [ { "cause": "...", "shown_by_data": true, "explanation": "...", "confidence": "strong" } ],
    "other_possible_factors": ["..."], "caveats": ["..."], "investigate_next": ["..."]
  }
}
```

Without a key, `explanation` is `{"available": false, "reason": "..."}` and everything else
is still returned. The same happens if the AI call fails or is declined, so the statistics
are never lost.

Explanations for identical evidence are cached in memory (256 maximum), so repeating a
request doesn't call Claude again. A cloud cause analysis streams up to 4 variables, so
expect about 1–2 minutes the first time; examples and cached results take a few seconds.

### POST /cache/clear

Empties the result cache and returns the cache statistics. This is handy before a demo, if
you want to show a region actually streaming from NASA.

Admin only. Send the `X-Admin-Token` header with the server's `ADMIN_TOKEN`. If no
`ADMIN_TOKEN` is set, it works only from the server itself (localhost); anyone else gets 403.

```powershell
curl.exe -X POST http://127.0.0.1:8000/cache/clear -H "X-Admin-Token: <your admin token>"
```

### GET /jobs/{id}

```json
{ "id": "3f2a9c1b7d4e", "variable": "t2m", "start": "2001-01", "end": "2024-12",
  "status": "running", "message": "Streaming from NASA Earthdata Cloud: 120 of 288 months",
  "done": 120, "total": 288, "progress": 0.417, "error": null, "result": null }
```

- `status` moves through `queued` -> `running` -> `done`, or ends at `error`, in which case
  `error` says why.
- When `done`, `result` holds the same JSON that `/analyze` (or `/compare`) returns.
- Two analyses run at once; more wait in the queue. At most 20 can be waiting or running
  (`MAX_ACTIVE_JOBS`); past that, new jobs get **503** with `Retry-After: 60`.
- Jobs are kept in memory (the newest 50) and cleared when the server restarts.

## Settings

| Environment variable | Default | Purpose |
|---|---|---|
| `EARTHTRENDS_DATA_DIR` | `../PythonPoc/data` | Where local data (example copies) is stored |
| `CORS_ORIGINS` | `http://localhost:5173,http://127.0.0.1:5173` | Comma-separated browser origins allowed to call the API (the React dev server). Postman and curl aren't affected by CORS |
| `EARTHDATA_TOKEN` | – | NASA Earthdata token for streaming from the cloud. Expires after 60 days |
| `EARTHDATA_ALLOW_PASSWORD` | `0` | `1` also allows the `~/_netrc` username/password login (dev machines only) |
| `ANTHROPIC_API_KEY` | – | Enables the AI explanation in `/drivers`. Put it in `TrendApi/.env` |
| `ADMIN_TOKEN` | – | Required in the `X-Admin-Token` header for `POST /cache/clear`. Unset: localhost only |
| `RATE_LIMIT_ENABLED` | `1` | `0` turns rate limiting off |
| `RATE_LIMIT_ANALYSIS` | `15/minute,300/day` | Per client IP: `/analyze`, `/compare` and their `/jobs` versions |
| `RATE_LIMIT_DRIVERS` | `5/minute,50/day` | Per client IP: `/drivers` and `/drivers/jobs` (these call Claude) |
| `RATE_LIMIT_POLL` | `240/minute` | Per client IP: `GET /jobs/{id}` (the client polls once a second) |
| `RATE_LIMIT_DEFAULT` | `120/minute` | Per client IP: everything else. `/health` is never limited |
| `MAX_ACTIVE_JOBS` | `20` | Background jobs waiting or running at once, for all users together |

### Rate limits

Every client IP address gets its own allowance per group of endpoints (table above). Over
the limit, the API answers **429** with a `Retry-After` header and a message such as
"Too many analyses from your address (limit: 15 per minute). Try again in 23 s.", which the
web client shows like any other error. Units: `second`, `minute`, `hour`, `day`; combine
windows with commas.

The counters are kept in memory, so they reset on restart and assume **one** API process
(the same reason jobs and the cache need one process). Behind a proxy such as Azure's
ingress, run uvicorn with `--proxy-headers` (the Dockerfile does), or every user shares the
proxy's address and one allowance.

## Try it

**curl** (in PowerShell, type `curl.exe` so you get real curl, not PowerShell's alias):

```powershell
curl.exe http://127.0.0.1:8000/variables
curl.exe -X POST http://127.0.0.1:8000/analyze -H "Content-Type: application/json" -d "@samples/barents_t2m.json"
```

**Postman**:
1. New request: `POST http://127.0.0.1:8000/analyze`
2. Open Body → raw → JSON, and paste the contents of a file from `samples/`.
3. Send.

Ready-made request bodies are in `samples/`:
- `barents_t2m.json`: Arctic warming, expect a significant trend.
- `lake_mead_soil_moisture.json`: statistics only, without the series.

## Tests

```powershell
python -m pytest
```

The tests use synthetic data with a known trend and a fake NASA cloud, so they need no
network access.
