# Earth Science Trend Detective (data + stats core)

The web API (`../TrendApi`) uses this project as a library. If you want to run the POC
yourself, see below.

Draw a region → get a monthly time series of a NASA Earth science variable → find out
whether it's trending and whether that trend is statistically significant.

This folder is the Python core: getting the data, building the polygon's time series,
and the trend statistics. The API calls `earthtrends.analyze.analyze()`.

## Where the data comes from

- **Cache.** The same variable, region and period analyzed recently in this process comes
  back instantly. It's held in memory (512 results maximum) and cleared on restart.
- **NASA Earthdata Cloud (default).** For each month, NASA's cloud OPeNDAP service sends
  only the grid cells around your polygon. Everything stays in memory and nothing is
  saved. 24 years takes about 30 seconds.
- **Local copies (optional).** Saved on disk and used automatically whenever they cover
  the region and period:
  - **Example regions** (`prepare-examples`): a few MB, for offline, instant demos.
  - **Whole-world data** (`fetch`): about 2.5 GB, for fast offline analysis anywhere.

## Variables

| key | what | source | resolution | data from |
|---|---|---|---|---|
| `precip` | Precipitation (mm/day) | GPM IMERG monthly `GPM_3IMERGM` v07 (satellite) | 0.1° | 1998 |
| `t2m` | Air temperature at 2 m (°C) | MERRA-2 `M2TMNXSLV` v5.12.4 (reanalysis) | 0.5° × 0.625° | 1980 |
| `humidity` | Specific humidity at 2 m (g/kg) | MERRA-2 `M2TMNXSLV` (same file as `t2m`) | 0.5° × 0.625° | 1980 |
| `sea_level_pressure` | Sea-level pressure (hPa) | MERRA-2 `M2TMNXSLV` (same file) | 0.5° × 0.625° | 1980 |
| `soil_moisture` | Soil moisture, top 10 cm (mm) | GLDAS Noah `GLDAS_NOAH025_M` v2.1 (land model) | 0.25° | 2000 |
| `root_zone_moisture` | Root-zone soil moisture, ~1–2 m (mm) | GLDAS Noah (same files) | 0.25° | 2000 |
| `evapotranspiration` | Evapotranspiration (mm/day) | GLDAS Noah (same files) | 0.25° | 2000 |
| `runoff` | Surface + groundwater runoff (mm/day) | GLDAS Noah (same files; `Qs_acc` + `Qsb_acc`) | 0.25° | 2000 |
| `snow_water` | Snow water equivalent (mm) | GLDAS Noah (same files) | 0.25° | 2000 |
| `land_surface_temp` | Land surface (skin) temperature (°C) | GLDAS Noah (same files) | 0.25° | 2000 |
| `ndvi` | Vegetation greenness (NDVI, 0–1) | **MODIS** Terra `MOD13C2` v061 (satellite) | 0.05° | 2000-02 |
| `airs_surface_temp` | Surface air temperature, day + night (°C) | **AIRS** Aqua `AIRS3STM` v7.0 (satellite) | 1° | 2002-09 |
| `water_vapor` | Total column water vapor (mm) | **AIRS** `AIRS3STM` v7.0 | 1° | 2002-09 |
| `tropospheric_ozone` | Lower-atmosphere ozone (Dobson units) | **OMI**/MLS Aura `TrCO3_Monthly_OMIMLS` v2 (satellite) | 1°, ~60°S–60°N | 2004-10 |
| `co2` | Carbon dioxide, column average (ppm) | **OCO-2** GEOS L3 monthly `OCO2_GEOS_L3CO2_MONTH` v10r | 0.5° × 0.625° | 2015-01 to **2022-02** (record ends) |

`ndvi` and the AIRS variables are streamed from NASA's cloud only (`fetch` would mean
~100–200 MB per global file). The OMI/MLS ozone record is a single 10 MB file, downloaded
once to `data/datasets/` on first use and then read locally.

---

## Initialization

### 1. Create the environment

```powershell
cd PythonPoc
python -m venv .venv
.venv\Scripts\Activate.ps1          # prompt now starts with (.venv)
pip install -r requirements.txt
```

If PowerShell refuses to run `Activate.ps1`, run this once:
`Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`.

Check that it works without any NASA access (uses synthetic data):

```powershell
python -m pytest                     # expect: 22 passed
```

### 2. NASA Earthdata login (one time)

1. Create a free account at https://urs.earthdata.nasa.gov
2. **Authorize GES DISC** (all four datasets come from it): log in, then go to
   *Applications → Authorized Apps → Approve More Applications* and approve
   **"NASA GESDISC DATA ARCHIVE"**. Accept its EULA if asked. Without this, requests fail
   with 401/403 or `EulaNotAccepted` errors.
3. Give the tool your credentials, using **one** of these:

   **Option A: token (recommended).** Generate one under *Generate Token* on the Earthdata
   site. It expires after about 60 days and can be revoked.
   ```powershell
   [Environment]::SetEnvironmentVariable("EARTHDATA_TOKEN", "<your token>", "User")
   # open a new terminal so the variable is picked up
   ```

   **Option B: saved password.** Run any `fetch` command once. It asks for your username
   and password and saves them to `~/_netrc` (plain text, readable only by your Windows
   account):
   ```powershell
   python -m earthtrends fetch t2m --start 2024-01 --end 2024-01
   ```

### 3. First analysis (streams from NASA's cloud)

```powershell
python -m earthtrends analyze t2m examples/barents_sea.geojson --no-show
```

Expected output (takes about 30 seconds):

```
t2m from NASA cloud: 48/288 months
...
Air temperature (2 m) (M2TMNXSLV v5.12.4)
  Region: 861 grid cells, bounds [20.0, 72.0, 60.0, 80.0]
  Period: 2001-01 to 2024-12 (288 months), mean -1.51 °C
  Linear trend:   +0.7686 °C/decade  95% CI [+0.2408, +1.296]
  t-test p-value: 0.0048 (autocorrelation-adjusted; naive 0.0000)
  Mann-Kendall:   increasing, p = 0.0056, Sen's slope +0.6942 °C/decade

  Significant trend: increasing by about 0.769 °C per decade over 2001-01 to 2024-12. ...
```

The CSV, JSON and PNG chart are saved in `output/`.

### 4. Save the example regions for presentations (optional, recommended)

```powershell
python -m earthtrends prepare-examples
```

This streams every example region × variable for 2001–2024 once and keeps a small local
copy (about 15–25 minutes, a few MB on disk). After that, the examples analyze instantly
with no internet connection. It's safe to re-run: copies that already exist are skipped.

```powershell
python -m earthtrends list           # shows which examples are stored locally per variable
python -m earthtrends analyze t2m examples/barents_sea.geojson --source local   # proves it's offline
```

Other forms:

```powershell
python -m earthtrends prepare-examples --var precip                         # one variable only
python -m earthtrends prepare-examples --start 1998-01 --end 2024-12        # a longer period
```

To add your own presentation region, put a GeoJSON file in `examples/` (see step 5) and
run `prepare-examples` again.

### 5. Analyze your own region

Regions are GeoJSON Polygons with coordinates in **[longitude, latitude]** order. The
first and last points must be the same. The easiest way to make one:
- draw it at https://geojson.io and save it, or
- copy a file from `examples/` and edit the numbers.

Or create one from PowerShell:

```powershell
@'
{
  "type": "Polygon",
  "coordinates": [[[-122.5, 37.0], [-121.5, 37.0], [-121.5, 38.0], [-122.5, 38.0], [-122.5, 37.0]]]
}
'@ | Set-Content -Encoding utf8 my_region.geojson

python -m earthtrends analyze precip my_region.geojson
```

### 6. Optional: whole-world local data

Only needed if you want **any** region to work offline. It downloads global files and
builds a local copy:

```powershell
python -m earthtrends fetch t2m                                  # ~190 MB, 2001-2024
python -m earthtrends fetch soil_moisture --start 2015-01        # also prepares evapotranspiration
python -m earthtrends fetch all                                  # ~2.5 GB total, mostly precipitation
```

Re-running `fetch` skips files you already have, so an interrupted download can be
resumed. If you later want the space back, delete `data/cubes/` and `data/raw/`. The
example copies in `data/tiles/` are separate and keep working.

---

## Command reference

```powershell
python -m earthtrends list                                   # variables, definitions, what's stored locally

python -m earthtrends analyze <var|all> <region.geojson> [options]
    --start YYYY-MM          first month             (default 2001-01)
    --end YYYY-MM            last month              (default December of last year)
    --source auto|local|cloud
                             auto (default): local copy if it covers the request, else NASA cloud
                             local: fail instead of using the network
                             cloud: always stream, even if a local copy exists
    --out DIR                where to save CSV/JSON/PNG  (default output/)
    --no-show                don't open the interactive chart window

python -m earthtrends prepare-examples [--var KEY|all] [--start YYYY-MM] [--end YYYY-MM]
python -m earthtrends fetch <var|all> [--start YYYY-MM] [--end YYYY-MM] [--threads N]
python -m earthtrends build <var|all>                        # rebuild global data from downloaded files
```

More analyze examples:

```powershell
# every variable for one region
python -m earthtrends analyze all examples/amazon_rondonia.geojson --no-show

# a shorter period: 2010s only
python -m earthtrends analyze soil_moisture examples/lake_mead.geojson --start 2010-01 --end 2019-12

# force fresh data from NASA even though a local copy exists
python -m earthtrends analyze t2m examples/barents_sea.geojson --source cloud
```

Without `--no-show`, an interactive chart window opens. Close it to finish the command.
The trend line appears only when there is a trend: solid red if significant, dashed orange
if borderline.

## Using it from Python

```python
from earthtrends.analyze import analyze, plan

region = "examples/lake_mead.geojson"      # or a GeoJSON dict / string

print(plan("precip", region, "2001-01", "2024-12"))
# {'source': 'local', 'description': "local copy of 'lake_mead'", ..., 'estimated_seconds': 1}

result = analyze("precip", region, start="2001-01", end="2024-12",
                 progress=lambda done, total: print(f"{done}/{total}"))
print(result["data_source"])               # {'type': 'local' or 'cloud', 'description': ...}
print(result["stats"]["verdict"])
print(result["stats"]["linear"]["slope_per_decade"], result["variable"]["units"])
series = result["series"]                  # [{'date': '2001-01', 'value': ..., 'anomaly': ...}, ...]
```

Compare one variable across 2–5 regions for the same period:

```python
from earthtrends.analyze import compare

res = compare("t2m", [
    {"name": "Arctic", "region": "examples/barents_sea.geojson"},
    {"name": "Amazon", "region": "examples/amazon_rondonia.geojson"},
], start="2001-01", end="2024-12")
for r in res["regions"]:
    print(r["name"], r.get("error") or r["stats"]["linear"]["slope_per_decade"])
print(res["summary"])   # which are significant, which changes fastest
```

Cause analysis (correlation, regression, random forest) and the optional AI explanation:

```python
from earthtrends.drivers import analyze_drivers
from earthtrends.narrative import explain

res = analyze_drivers("t2m", "examples/amazon_rondonia.geojson", "2001-01", "2024-12")
for d in res["drivers"]:
    print(d["rank"], d["name"], d["evidence"], round(d["correlation"]["r"], 2),
          d["regression"]["share_of_target_trend"], d["physical_link"]["likely_direction"])

# needs ANTHROPIC_API_KEY in the environment; otherwise returns {"available": False, ...}
print(explain(res, region_name="Rondônia (Amazon)"))
```

Lower-level pieces:

```python
from earthtrends import catalog, cloud, region, stats

var = catalog.get("t2m")
geom = region.load_polygon("examples/barents_sea.geojson")
cube = cloud.open_region(var, geom, "2015-01", "2024-12")   # (time, lat, lon), in memory
series, info = region.polygon_mean(cube, geom)              # one value per month
print(stats.trend_stats(series, units=var.units)["verdict"])
```

## Where things are stored

| Path | What | Size | Safe to delete? |
|---|---|---|---|
| `data/tiles/<var>/<example>.zarr` | Example-region copies (`prepare-examples`) | a few MB | Yes; the examples then stream from NASA |
| `data/grids/` | Each dataset's grid coordinates, fetched once | KB | Yes; re-fetched automatically |
| `data/cubes/<var>.zarr` | Whole-world data (`fetch`) | up to ~2.5 GB | Yes |
| `data/raw/` | Downloaded files used to build `cubes/` | up to ~2.5 GB | Yes, once `cubes/` is built |
| `output/` | CSV/JSON/PNG from `analyze` | small | Yes |

Set `EARTHTRENDS_DATA_DIR` to keep `data/` somewhere else.

## How it works

1. **Data** (`earthtrends/cache.py`, `cloud.py`, `local.py`, `data.py`):
   - The in-memory result cache is checked first, then local copies.
   - Otherwise `earthaccess` lists the monthly files, and NASA's cloud OPeNDAP service
     returns just the bounding-box cells for each month, 16 requests in parallel.
   - The values are identical to downloading the full files.
2. **Polygon mean** (`earthtrends/region.py`):
   - Picks the grid cells whose centers fall in the polygon.
   - Averages them weighted by cos(latitude), because cells get smaller toward the poles.
   - Skips cells with no data, such as ocean for GLDAS.
   - If the polygon is smaller than one grid cell, uses the nearest cell.
3. **Statistics** (`earthtrends/stats.py`):
   - Removes the seasonal cycle (anomaly = value − that calendar month's average).
   - Runs a linear regression on the anomalies: slope per decade, 95% CI, t-test p-value.
   - The t-test is **adjusted for autocorrelation**: neighbouring months are similar, so
     there are fewer independent data points than months (effective sample size,
     Santer et al. 2000).
   - Runs a Mann-Kendall test (Hamed-Rao autocorrelation correction) with Sen's slope,
     plus a seasonal Mann-Kendall on the raw data.
   - The verdict is **significant** when both the t-test and Mann-Kendall have p < 0.05.

## Troubleshooting

| Problem | Fix |
|---|---|
| `ModuleNotFoundError: No module named 'pandas'` | The virtual environment isn't active. Run `.venv\Scripts\Activate.ps1` |
| `EulaNotAccepted` or 401/403 | Approve "NASA GESDISC DATA ARCHIVE" in your Earthdata profile (step 2) |
| `No Earthdata credentials on this machine` | Set `EARTHDATA_TOKEN` or create `~/_netrc` (step 2) |
| `No local ... data covers this region and period` | You used `--source local` for a region or period that isn't saved. Drop the flag, or run `prepare-examples` |
| `No ... data inside this region` | Land-only variables (soil moisture, evapotranspiration) have no data over the ocean |
| `Need at least 24 months of data` | Choose a longer period |
