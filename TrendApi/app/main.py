"""Trend Detective API.

Thin HTTP layer over the `earthtrends` core library (PythonPoc/). Analysis reads
the local data cubes only. Downloading missing data (POST /variables/{key}/fetch)
needs Earthdata credentials on the server and is capped at MAX_FETCH_MB per request.

Run:  uvicorn app.main:app --reload      (from the TrendApi folder)
Docs: http://127.0.0.1:8000/docs

Settings (environment variables):
  EARTHTRENDS_DATA_DIR  where data lives            (default ../PythonPoc/data)
  MAX_FETCH_MB          max download per request    (default 500)
  CORS_ORIGINS          comma-separated origins     (default the Vite dev server)
"""
from __future__ import annotations

import json
import math
import os
import re
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
POC_DIR = REPO_ROOT / "PythonPoc"
# Must be set before earthtrends.data is imported.
os.environ.setdefault("EARTHTRENDS_DATA_DIR", str(POC_DIR / "data"))

import pandas as pd  # noqa: E402
import xarray as xr  # noqa: E402
from fastapi import FastAPI, HTTPException  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from pydantic import BaseModel, Field  # noqa: E402

from earthtrends import catalog, data, region  # noqa: E402
from earthtrends.analyze import analyze  # noqa: E402

from . import jobs  # noqa: E402

EXAMPLES_DIR = POC_DIR / "examples"
MONTH = r"^\d{4}-(0[1-9]|1[0-2])$"
MAX_FETCH_MB = float(os.environ.get("MAX_FETCH_MB", "500"))
CORS_ORIGINS = [
    o.strip()
    for o in os.environ.get("CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173").split(",")
    if o.strip()
]

app = FastAPI(
    title="Trend Detective API",
    description="Draw a region, pick a NASA Earth science variable, find out if it's trending.",
    version="0.2.0",
)
# Browsers only let the listed origins (the React app) call this API.
# Postman and curl aren't browsers, so CORS doesn't affect them.
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)


# ----------------------------------------------------------------- models

class AnalyzeRequest(BaseModel):
    variable: str = Field(..., examples=["t2m"], description="Variable key from GET /variables")
    region: dict[str, Any] = Field(
        ...,
        description="GeoJSON Polygon/MultiPolygon, Feature, or FeatureCollection (lon/lat)",
        examples=[{"type": "Polygon", "coordinates": [[[20, 72], [55, 72], [55, 80], [20, 80], [20, 72]]]}],
    )
    start: str | None = Field(None, pattern=MONTH, examples=["2001-01"], description="First month, YYYY-MM")
    end: str | None = Field(None, pattern=MONTH, examples=["2024-12"], description="Last month, YYYY-MM")
    include_series: bool = Field(True, description="Include the monthly data points in the response")


class FetchRequest(BaseModel):
    start: str = Field(..., pattern=MONTH, examples=["2001-01"], description="First month, YYYY-MM")
    end: str = Field(..., pattern=MONTH, examples=["2024-12"], description="Last month, YYYY-MM")


# ----------------------------------------------------------------- helpers

def _clean(obj: Any) -> Any:
    """JSON can't carry NaN/Infinity; turn them into null."""
    if isinstance(obj, float):
        return obj if math.isfinite(obj) else None
    if isinstance(obj, dict):
        return {k: _clean(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_clean(v) for v in obj]
    return obj


def _variable_info(var: catalog.Variable) -> dict:
    info = {
        "key": var.key,
        "name": var.name,
        "units": var.units,
        "definition": var.definition,
        "source": f"{var.collection} v{var.version}",
        "related": list(var.related),
        "available": False,
        "start": None,
        "end": None,
        "n_months": 0,
        "data_starts": var.first_month,
        "mb_per_month": var.mb_per_month,
    }
    path = data.cube_path(var)
    if path.exists():
        with xr.open_zarr(path, consolidated=False) as ds:
            times = pd.to_datetime(ds.time.values)
        info.update(available=True, start=f"{times.min():%Y-%m}", end=f"{times.max():%Y-%m}",
                    n_months=len(times))
    return info


def _require_variable(key: str) -> catalog.Variable:
    var = catalog.VARIABLES.get(key)
    if var is None:
        raise HTTPException(404, f"Unknown variable '{key}'. Options: {', '.join(catalog.VARIABLES)}")
    return var


def _check_range(start: str | None, end: str | None) -> None:
    if start and end and start > end:
        raise HTTPException(422, "start must be before end")
    latest = f"{pd.Timestamp.now():%Y-%m}"
    if end and end > latest:
        raise HTTPException(422, f"end can't be in the future (latest is {latest})")


def _coverage(var: catalog.Variable, start: str, end: str) -> dict:
    cov = data.coverage(var, start, end)
    cov.update(variable=var.key, start=start, end=end, limit_mb=MAX_FETCH_MB,
               within_limit=cov["estimated_mb"] <= MAX_FETCH_MB)
    return cov


# ----------------------------------------------------------------- routes

@app.get("/health")
def health():
    return {
        "status": "ok",
        "data_dir": str(data.DATA_DIR),
        "max_fetch_mb": MAX_FETCH_MB,
        "can_fetch": data.have_credentials(),
    }


@app.get("/variables")
def list_variables():
    """All variables with plain-language definitions and whether their data is downloaded."""
    return [_variable_info(v) for v in catalog.VARIABLES.values()]


@app.get("/variables/{key}")
def get_variable(key: str):
    return _variable_info(_require_variable(key))


@app.get("/variables/{key}/coverage")
def get_coverage(key: str, start: str, end: str):
    """How much of start..end is already downloaded, and the estimated size of
    downloading the rest. Call this before /analyze to decide whether to offer a fetch."""
    var = _require_variable(key)
    for m in (start, end):
        if not re.fullmatch(MONTH, m):
            raise HTTPException(422, f"'{m}' isn't a YYYY-MM month")
    _check_range(start, end)
    return _coverage(var, start, end)


@app.post("/variables/{key}/fetch", status_code=202)
def fetch_variable(key: str, req: FetchRequest):
    """Start downloading the missing months for start..end in the background.
    Refused with 413 if the estimated download is over MAX_FETCH_MB.
    Poll GET /jobs/{id} for progress."""
    var = _require_variable(key)
    _check_range(req.start, req.end)
    cov = _coverage(var, req.start, req.end)
    if cov["missing_months"] == 0:
        return {"job": None, "message": "All requested months are already available.", "coverage": cov}
    if not cov["within_limit"]:
        raise HTTPException(
            413,
            f"That download is about {cov['estimated_mb']:.0f} MB, over the server's "
            f"{MAX_FETCH_MB:.0f} MB limit per request. Choose a shorter date range.",
        )
    if cov["download_months"] > 0 and not data.have_credentials():
        raise HTTPException(503, "The server has no NASA Earthdata credentials, so it can't download data.")
    job, created = jobs.submit(var.key, req.start, req.end)
    msg = "Download started." if created else "A download for this dataset is already running."
    return {"job": job.to_dict(), "message": msg, "coverage": cov}


@app.get("/jobs")
def list_jobs():
    return [j.to_dict() for j in jobs.all_jobs()]


@app.get("/jobs/{job_id}")
def get_job(job_id: str):
    job = jobs.get(job_id)
    if job is None:
        raise HTTPException(404, f"No job '{job_id}'")
    return job.to_dict()


@app.get("/examples")
def list_examples():
    """Ready-made demo regions."""
    return [p.stem for p in sorted(EXAMPLES_DIR.glob("*.geojson"))]


@app.get("/examples/{name}")
def get_example(name: str):
    """GeoJSON for a demo region - paste it into the `region` field of /analyze."""
    path = EXAMPLES_DIR / f"{name}.geojson"
    if not path.is_file() or path.parent != EXAMPLES_DIR:
        raise HTTPException(404, f"No example named '{name}'")
    return json.loads(path.read_text())


@app.post("/analyze")
def analyze_region(req: AnalyzeRequest):
    """Time series + trend statistics for one variable over a polygon."""
    var = _require_variable(req.variable)
    if not data.cube_path(var).exists():
        raise HTTPException(
            409, f"Data for '{var.key}' isn't downloaded yet. "
                 f"Download it with POST /variables/{var.key}/fetch.",
        )
    _check_range(req.start, req.end)
    try:
        region.load_polygon(req.region)
    except Exception as e:
        raise HTTPException(422, f"Invalid region GeoJSON: {e}")

    try:
        result = analyze(var.key, req.region, start=req.start, end=req.end)
    except data.DataError as e:
        raise HTTPException(409, str(e))
    except ValueError as e:  # too few months, no data in region, etc.
        raise HTTPException(422, str(e))

    if not req.include_series:
        result.pop("series", None)
    return _clean(result)
