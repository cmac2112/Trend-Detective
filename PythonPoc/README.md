# Earth Science Trend Detective (data + stats core)

Draw a region → get a monthly time series of a NASA Earth science variable → find out
whether it's trending and whether that trend is statistically significant.

This folder is the Python core: downloading, polygon time series, and trend statistics.
The React + .NET web app will call `earthtrends.analyze.analyze()` through an API.

## Variables

| key | what | source | resolution |
|---|---|---|---|
| `precip` | Precipitation (mm/day) | GPM IMERG monthly `GPM_3IMERGM` v07 | 0.1° |
| `t2m` | Air temperature at 2 m (°C) | MERRA-2 `M2TMNXSLV` v5.12.4 | 0.5° × 0.625° |
| `soil_moisture` | Soil moisture, top 10 cm (mm) | GLDAS Noah `GLDAS_NOAH025_M` v2.1 | 0.25° |
| `evapotranspiration` | Evapotranspiration (mm/day) | GLDAS Noah `GLDAS_NOAH025_M` v2.1 | 0.25° |

`python -m earthtrends list` shows plain-language definitions.

## Setup

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

### NASA Earthdata login (one time)
1. Create a free account at https://urs.earthdata.nasa.gov
2. **Authorize GES DISC** (all four datasets come from it): log in to Earthdata, then go to
   *Applications → Authorized Apps → Approve More Applications* and approve
   **"NASA GESDISC DATA ARCHIVE"**. Without this, downloads fail with 401/403 errors.
3. The first `fetch` asks for your username and password and saves them to `~/_netrc`,
   so later runs log in automatically.

## Usage

```powershell
# Download 2001-2024 and build the local cube (do one first to test, then the rest)
python -m earthtrends fetch t2m          # ~190 MB
python -m earthtrends fetch all          # ~2.5 GB total; precipitation is most of it

# Analyze a region (GeoJSON polygon, lon/lat)
python -m earthtrends analyze t2m examples/lake_mead.geojson
python -m earthtrends analyze all examples/amazon_rondonia.geojson
```

Outputs go to `output/`: a CSV with the series, a JSON with all the statistics (the same
shape the API will return), and a PNG chart.

Re-running `fetch` skips files and months you already have, so it's safe to resume an
interrupted download.

## How it works

1. **Download** (`earthtrends/data.py`): `earthaccess` finds the monthly files, then NASA's
   cloud OPeNDAP service sends only the variables we use (not the whole file) into
   `data/raw/<collection>/`. Full MERRA-2 files are 61 MB; the subset is 0.5 MB.
2. **Cube**: each variable is extracted, converted to friendly units, and stored as
   `data/cubes/<var>.zarr`, chunked in space. A polygon query reads only the chunks it
   touches, so it takes seconds and makes no network calls (safe for a live demo).
3. **Polygon mean** (`earthtrends/region.py`): picks the grid cells whose centers fall in
   the polygon and averages them weighted by cos(latitude) (cells get smaller toward the
   poles). Cells with no data, such as ocean in GLDAS, are skipped. If the polygon is
   smaller than one grid cell, the nearest cell is used.
4. **Statistics** (`earthtrends/stats.py`):
   - remove the seasonal cycle (anomaly = value − that calendar month's average)
   - linear regression on the anomalies → slope per decade, 95% CI, t-test p-value
   - the t-test is **adjusted for autocorrelation**: neighbouring months are similar, so
     there are fewer independent data points than months (effective sample size,
     Santer et al. 2000)
   - Mann-Kendall test (Hamed-Rao autocorrelation correction) with Sen's slope, plus a
     seasonal Mann-Kendall on the raw data
   - verdict: **significant** when both the t-test and Mann-Kendall have p < 0.05

## Tests

```powershell
python -m pytest
```

The tests use synthetic data with a known trend, so they don't need a download.
