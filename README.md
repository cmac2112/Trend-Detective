# Trend Detective

**Draw a region on a map, pick a NASA Earth-science variable, and find out whether that
place is really changing, how fast, and what might be driving it.**

Built solo for the NASA Space Apps Challenge. It uses all six data sources the challenge
names (MODIS, OMI, AIRS, GPM, MERRA-2 and GLDAS), plus NASA's OCO-2 satellite for
carbon dioxide.

| Part | Folder | What it is |
|---|---|---|
| Web client | [`client/`](client/README.md) | React + TypeScript + Vite. The map, drawing tools and charts |
| API | [`TrendApi/`](TrendApi/README.md) | Python + FastAPI. The web service the client calls (also works with curl or Postman) |
| Analysis library | [`PythonPoc/`](PythonPoc/README.md) | Python library `earthtrends`. Finds, reads, averages and tests NASA data. Also has a command line |
| Docs | [`docs/`](docs/) | [Architecture](docs/ARCHITECTURE.md) (with diagrams) and [presentation notes](docs/PRESENTATION.md) |

---

## Quick start (Windows, PowerShell)

You need **Python 3.12**, **Node.js 22** and a free
[NASA Earthdata account](https://urs.earthdata.nasa.gov).

### 1. One-time NASA setup

1. Log in at https://urs.earthdata.nasa.gov.
2. Under *Applications → Authorized Apps → Approve More Applications*, approve
   **NASA GESDISC DATA ARCHIVE** and accept its EULA. Without this, NASA answers 401/403.
3. Go to https://urs.earthdata.nasa.gov/users/tokens and click **Generate Token**. Tokens
   expire after 60 days, so make a new one when it runs out.

### 2. Install

```powershell
# API (also installs the analysis library from ../PythonPoc)
cd TrendApi
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
cd ..

# Web client
cd client
npm install
cd ..
```

If PowerShell refuses to run `Activate.ps1`, run this once:
`Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`.

### 3. Add your secrets

Copy `TrendApi/.env.example` to `TrendApi/.env` and fill it in:

```ini
EARTHDATA_TOKEN=<your Earthdata token>       # needed to stream from NASA's cloud
ANTHROPIC_API_KEY=<your Claude key>          # optional: AI explanations of causes
```

`.env` is git-ignored. The API logs in to NASA with the token only; it never uses a
username or password. On a host such as Azure, set the same names as app settings instead.

### 4. (Optional) Save the example regions locally

The three demo regions (Rondônia in the Amazon, Lake Mead, the Barents Sea) load
instantly and work offline once saved. This takes about 5 minutes and a few MB:

```powershell
cd PythonPoc
..\TrendApi\.venv\Scripts\Activate.ps1
$env:EARTHDATA_TOKEN = "<your Earthdata token>"   # this command doesn't read TrendApi/.env
python -m earthtrends prepare-examples
cd ..
```

### 5. Run

Terminal 1, the API:

```powershell
cd TrendApi
.venv\Scripts\Activate.ps1
uvicorn app.main:app --reload --reload-dir app --reload-dir ../PythonPoc/earthtrends
```

Terminal 2, the web client:

```powershell
cd client
npm run dev
```

Open **http://localhost:5173**. Check http://127.0.0.1:8000/health: `cloud_enabled`
(and `ai_enabled`, if you added a Claude key) should be `true`, and `earthdata_token`
shows when the token expires. Interactive API docs are at http://127.0.0.1:8000/docs.

**Keep the client on port 5173.** The API only accepts browser requests from that port
(set `CORS_ORIGINS` to change it). Restart uvicorn after editing `.env`, because
`--reload` doesn't watch it.

### Run the tests

No NASA access needed; they use synthetic data with a known trend.

```powershell
cd PythonPoc; ..\TrendApi\.venv\Scripts\Activate.ps1; python -m pytest   # 22 tests
cd ..\TrendApi; python -m pytest                                         # 14 tests
```

### Common problems

| Symptom | Fix |
|---|---|
| "This needs NASA's cloud, but the server has no Earthdata credentials" | Add `EARTHDATA_TOKEN` to `TrendApi/.env` and restart the API |
| "The Earthdata token expired on …" | Generate a new token and replace it in `.env` |
| NASA refused the login (HTTP 401/403) | Approve NASA GESDISC DATA ARCHIVE in your Earthdata profile, or make a new token |
| The browser shows a CORS or network error | Make sure the API is running and the client is on port 5173 |
| A new variable doesn't appear in the dropdown | Start uvicorn with both `--reload-dir` flags shown above |

---

## Project details

### What it does and how it works

Trend Detective lets anyone draw a shape on a map, pick a NASA Earth-science variable, and find out whether that place is really changing, how fast, and what might be driving it.

NASA holds decades of satellite and model data on rainfall, temperature, vegetation, soil moisture, ozone and carbon dioxide. Asking a simple question of it, like "is my watershed getting drier?", normally means finding the right product, downloading gigabytes of global files, cutting out a region and running statistics by hand. Trend Detective turns that into four steps in a web browser:

1. **Draw.** Sketch up to five regions on an interactive map, labeled A to E. A region can be a farm, a lake basin, a rainforest or a patch of the Arctic Ocean.
2. **Detect.** Choose one of 15 variables and a date range. The app builds a monthly time series for each region by averaging every NASA pixel inside the shape, weighted by area. It plots the series with a fitted trend line and reports the rate of change per decade, a confidence interval and a plain verdict: significant or not.
3. **Compare.** Plot several regions on one chart over the same period. Is the Amazon warming as fast as the Arctic? Is one basin drying while its neighbor holds steady?
4. **Explain.** Ask why the trend is happening. The app tests the other NASA variables over the same region as possible drivers and ranks them by how much of the trend each one accounts for. Claude, an AI model, then writes a short, plain-language explanation that sticks to what the evidence supports.

The variables come from all six sources the challenge names (MODIS, OMI, AIRS, GPM, MERRA-2 and GLDAS), plus NASA's OCO-2 satellite for carbon dioxide.

### Benefits

- **No expertise required.** Users don't need to know file formats, programming or which NASA product holds which variable. They draw, pick, and read the answer.
- **No downloads.** The app reads only the pixels inside the user's shape, straight from NASA's cloud. A question about one region costs megabytes, not gigabytes.
- **Answers you can trust.** Charts alone mislead: a single drought year or a seasonal cycle can look like a trend. Trend Detective removes the seasonal cycle, corrects for months that resemble their neighbors, and calls a trend significant only when two independent tests agree. Every rate comes with a confidence interval.
- **Context, not just a number.** Comparing regions side by side shows whether a change is local or global. Cause analysis points users toward a likely explanation, then suggests what to look at next.
- **Fast and reliable.** Repeat questions are answered instantly from a cache. Three example regions (the Brazilian Amazon, Lake Mead and the Barents Sea) are stored locally, so a demo or classroom lesson works even without internet.

### Intended impact

My goal is to make NASA's Earth record answer local questions for people who will never open a data file. The intended users include:

- **Local planners** checking whether rainfall or snowpack in their basin is truly declining
- **Farmers and land managers** watching soil moisture and vegetation
- **Students and teachers** learning how climate change shows up differently from place to place
- **Journalists** who want to check a claim before they publish it

The real results show why this matters. Carbon dioxide rises about 25 ppm per decade in all three example regions, because it mixes around the whole planet. Rainfall and vegetation trends, by contrast, differ sharply from place to place. In Rondônia, two independent NASA sources both show significant drying (about 0.7 to 0.95 mm per day per decade). A tool that separates global signals from local ones, and real trends from noise, helps people make better-informed decisions about water, land and health.

### Tools, languages and software

Trend Detective has three layers. Each can be used on its own.

1. **Web client (TypeScript, React, Vite).** Leaflet draws the map, Geoman handles drawing the shapes, and Recharts draws the time series and comparison charts.
2. **API (Python, FastAPI).** A small web service the client calls. It runs long requests as background jobs with live progress, caches finished results, and can also be called directly with curl or Postman.
3. **Analysis library (Python), which I call earthtrends.** It does all the science: finding data, reading it, averaging it over each shape and testing for trends.

The main libraries are:

| Job | Tools |
| --- | --- |
| NASA data access | earthaccess, NASA Earthdata login, the CMR catalog search, OPeNDAP cloud streaming |
| Reading data | xarray, netCDF4, Zarr |
| Shapes and maps | shapely |
| Statistics | NumPy, pandas, SciPy, pymannkendall |
| Machine learning | scikit-learn (random forest) |
| AI explanation | Anthropic's Claude Haiku model, through its Python SDK |
| Testing | pytest (36 automated tests) |

The key design choice is **cloud streaming**. Instead of downloading whole global files, the library asks NASA's OPeNDAP service for just the rows and columns that cover the shape. The server never stores user data, so many people can use it without the disk filling up. Example regions are stored locally as compact Zarr files for speed and offline demos.

No special hardware was needed. I built and ran everything on a single Windows laptop.

### How it is creative

- **It answers "why", not just "what".** Most Earth-data viewers stop at a chart. Trend Detective tests other variables as possible causes. It uses three methods that check each other: lagged correlation (does rainfall lead vegetation by a few months?), regression (what share of the trend does each driver account for?) and a random forest scored on held-out years. Each driver gets an evidence label from strong to weak.
- **AI with guardrails.** Claude never looks at raw data and never makes up a cause. It receives only the computed statistics plus a table of known physical mechanisms, and returns a structured explanation. If the AI is unavailable, the statistics still stand on their own.
- **Statistics that refuse to overclaim.** The app shows a verdict of "not significant" just as clearly as "significant". It admits uncertainty instead of hiding it.
- **Seven instruments as one.** Data from satellites, weather models and land models normally sits in incompatible formats. Here they share one map, one chart and one set of tests, so a user can check a satellite against a model in a single click.
- **Shape-first.** Users ask about the place they care about, drawn freehand, not a fixed grid box or a country border.

### Factors I considered

I built Trend Detective alone in 36 hours, so every choice had to count.

- **Accuracy over flash.** I checked the pipeline against real data before building the interface:
  - Values streamed from the cloud matched downloaded files exactly.
  - GLDAS rainfall, evaporation and runoff balance within 2%, which confirmed the unit conversions.
  - AIRS satellite temperatures track MERRA-2 model temperatures closely, with correlations of 0.88 to 0.997.
  - CO2 averages about 407 ppm, matching global records for 2015 to 2022.
- **Honest statistics.** Monthly climate data violates the assumptions of a basic t-test: seasons repeat and neighboring months are alike. I corrected for both, and required two independent tests to agree before calling anything significant.
- **Scale and cost.** Storing downloads for every user would fill a server quickly. Cloud streaming plus a result cache keeps storage near zero and makes repeat questions instant.
- **Messy data.** Every NASA product has its own quirks: file formats, scaling rules, date labels, day and night passes, and records that end (OCO-2 stops in February 2022). I handled them all in one catalog, so adding a variable is a single entry, not new code.
- **Security.** NASA login details and the AI key stay on the server, are never sent to the browser, and are kept out of the code repository.
- **A demo that can't fail.** Three example regions are stored locally, so the presentation works even if the venue's Wi-Fi does not.
- **Clear limits.** The app says when evidence is weak, and it states that correlation is not proof of cause.

---

## NASA data used

| Product | Variables | Dataset page |
|---|---|---|
| GPM IMERG monthly (v07) | Precipitation | [GPM_3IMERGM](https://disc.gsfc.nasa.gov/datasets/GPM_3IMERGM_07/summary) |
| MERRA-2 monthly surface (5.12.4) | Air temperature, humidity, sea-level pressure | [M2TMNXSLV](https://disc.gsfc.nasa.gov/datasets/M2TMNXSLV_5.12.4/summary) |
| GLDAS Noah 0.25° monthly (2.1) | Soil moisture (top and root zone), evapotranspiration, runoff, snow, land surface temperature | [GLDAS_NOAH025_M](https://disc.gsfc.nasa.gov/datasets/GLDAS_NOAH025_M_2.1/summary) |
| MODIS Terra vegetation (v061) | Vegetation greenness (NDVI) | [MOD13C2](https://lpdaac.usgs.gov/products/mod13c2v061/) |
| AIRS monthly (v7.0) | Surface air temperature, total water vapor | [AIRS3STM](https://disc.gsfc.nasa.gov/datasets/AIRS3STM_7.0/summary) |
| OMI/MLS monthly (v2) | Lower-atmosphere ozone | [TrCO3_Monthly_OMIMLS](https://search.earthdata.nasa.gov/search?q=TrCO3_Monthly_OMIMLS) |
| OCO-2 GEOS monthly (v10r) | Carbon dioxide (2015 to 2022) | [OCO2_GEOS_L3CO2_MONTH](https://disc.gsfc.nasa.gov/datasets/OCO2_GEOS_L3CO2_MONTH_10r/summary) |

All data comes from [NASA Earthdata](https://www.earthdata.nasa.gov) and is streamed
through NASA's cloud [OPeNDAP](https://opendap.earthdata.nasa.gov) service.
