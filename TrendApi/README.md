# Trend Detective API

FastAPI service that wraps the `earthtrends` core library (in `../PythonPoc`).
It reads the local data cubes built by the PythonPoc `fetch` command, so serving
requests needs no NASA login or network access.

## Setup

```powershell
cd TrendApi
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt     # also installs ../PythonPoc as an editable library
```

Data comes from `../PythonPoc/data` by default. To use a different folder, set the
`EARTHTRENDS_DATA_DIR` environment variable. To download data:

```powershell
cd ..\PythonPoc
python -m earthtrends fetch t2m
```

## Run

```powershell
uvicorn app.main:app --reload
```

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
| POST | `/analyze` | **The main endpoint**: time series + trend analysis for a variable over a polygon |

A typical frontend flow:
1. Call `GET /variables` to fill the variable picker.
2. The user draws a polygon on the map, or picks a demo region from `GET /examples/{name}`.
3. Send both to `POST /analyze`.
4. Chart the `series` and show the `stats`.

---

### GET /health

Confirms the API is up and shows which data folder it's reading from. Use it first when
something isn't working: if `data_dir` is wrong, every variable will show as not downloaded.

```json
{ "status": "ok", "data_dir": "C:\\...\\Trend-Detective\\PythonPoc\\data" }
```

---

### GET /variables

Returns every variable with:
- a plain-language definition, to show to users
- its units and NASA data source
- whether it has been downloaded (`available`)
- the date range you can analyze

Variables with `available: false` exist in the catalog but need `python -m earthtrends fetch <key>`
first. Calling `/analyze` with one returns a 409 error.

```json
[
  {
    "key": "t2m",
    "name": "Air temperature (2 m)",
    "units": "°C",
    "definition": "The temperature of the air about 2 meters above the ground, the height a weather station thermometer sits at. From the MERRA-2 reanalysis model.",
    "source": "M2TMNXSLV v5.12.4",
    "related": ["precip", "soil_moisture", "evapotranspiration"],
    "available": true,
    "start": "2001-01",
    "end": "2024-12",
    "n_months": 288
  },
  ...
]
```

| Field | Meaning |
|---|---|
| `key` | ID to send as `variable` in `/analyze` |
| `related` | Variables physically linked to this one (planned use: cause analysis) |
| `start`, `end`, `n_months` | Downloaded date range; `null` / `0` if not downloaded |

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
  "include_series": true
}
```

| Field | Required | Meaning |
|---|---|---|
| `variable` | yes | A `key` from `/variables` |
| `region` | yes | GeoJSON Polygon or MultiPolygon, a Feature, or a FeatureCollection. Coordinates are **[longitude, latitude]**, which is the GeoJSON standard (note: Leaflet uses lat/lng) |
| `start`, `end` | no | Limit the period, as `YYYY-MM`. Leave them out to use all downloaded data |
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
| 409 | Variable not downloaded yet | `Data for 'precip' isn't downloaded yet. In PythonPoc run: ...` |
| 422 | Bad GeoJSON, bad or out-of-order dates, a region with no data (e.g. ocean for soil moisture), or fewer than 24 months of data | `Invalid region GeoJSON: ...` |

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

The tests use synthetic data with a known trend, so no download is needed.
