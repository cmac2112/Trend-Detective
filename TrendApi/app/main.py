"""Trend Detective API.

Thin HTTP layer over the `earthtrends` core library (PythonPoc/).

Where data comes from:
  * local copies on this machine when they cover the region and period
    (the example regions, saved with `python -m earthtrends prepare-examples`)
  * otherwise streamed from NASA Earthdata Cloud for that one analysis and never
    stored, so any number of users can't fill the server's disk.
Streaming needs a NASA Earthdata token on the server (EARTHDATA_TOKEN).
AI explanations need ANTHROPIC_API_KEY. Both are read from the environment, or from
TrendApi/.env on a dev machine (see .env.example).

Run:  uvicorn app.main:app --reload --reload-dir app --reload-dir ../PythonPoc/earthtrends
      (from the TrendApi folder; the two --reload-dir flags make code changes in the
      core library reload the server too, not just changes in TrendApi/)
Docs: http://127.0.0.1:8000/docs

Settings (environment variables):
  EARTHTRENDS_DATA_DIR  where local data lives      (default ../PythonPoc/data)
  CORS_ORIGINS          comma-separated origins     (default the Vite dev server)
  EARTHDATA_TOKEN       NASA Earthdata user token   (expires after 60 days)
  EARTHDATA_ALLOW_PASSWORD  1 = also allow ~/_netrc (default 0)
  ANTHROPIC_API_KEY     Claude key for explanations (optional)
"""
from __future__ import annotations

import json
import math
import os
from pathlib import Path
from typing import Any, Literal

REPO_ROOT = Path(__file__).resolve().parents[2]
POC_DIR = REPO_ROOT / "PythonPoc"
API_DIR = Path(__file__).resolve().parents[1]

from dotenv import load_dotenv  # noqa: E402

# Secrets such as ANTHROPIC_API_KEY live in TrendApi/.env (git-ignored).
# Variables already set in the environment win over the file.
load_dotenv(API_DIR / ".env", override=False)
# The server logs in to NASA with EARTHDATA_TOKEN only - never a username/password or
# ~/_netrc - so a hosted copy holds nothing but a revocable, expiring token.
# Set EARTHDATA_ALLOW_PASSWORD=1 to allow the old _netrc login on a dev machine.
os.environ.setdefault("EARTHDATA_ALLOW_PASSWORD", "0")
# Must be set before earthtrends.data is imported.
os.environ.setdefault("EARTHTRENDS_DATA_DIR", str(POC_DIR / "data"))

import pandas as pd  # noqa: E402
import xarray as xr  # noqa: E402
from fastapi import FastAPI, HTTPException  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from pydantic import BaseModel, Field  # noqa: E402

from earthtrends import analyze as engine  # noqa: E402
from earthtrends import cache, catalog, data, drivers, local, narrative, region  # noqa: E402

from . import jobs  # noqa: E402

EXAMPLES_DIR = POC_DIR / "examples"
MONTH = r"^\d{4}-(0[1-9]|1[0-2])$"
CORS_ORIGINS = [
    o.strip()
    for o in os.environ.get("CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173").split(",")
    if o.strip()
]

app = FastAPI(
    title="Trend Detective API",
    description="Draw a region, pick a NASA Earth science variable, find out if it's trending.",
    version="0.3.0",
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
    start: str | None = Field(None, pattern=MONTH, examples=["2001-01"],
                              description="First month, YYYY-MM (default 2001-01)")
    end: str | None = Field(None, pattern=MONTH, examples=["2024-12"],
                            description="Last month, YYYY-MM (default December of last year)")
    source: Literal["auto", "local", "cloud"] = Field(
        "auto", description="auto = local copy if it covers the request, otherwise NASA cloud")
    include_series: bool = Field(True, description="Include the monthly data points in the response")


class NamedRegion(BaseModel):
    name: str = Field(..., min_length=1, max_length=60, examples=["Barents Sea"])
    region: dict[str, Any] = Field(..., description="GeoJSON Polygon/MultiPolygon, Feature, or FeatureCollection")


class CompareRequest(BaseModel):
    variable: str = Field(..., examples=["t2m"])
    regions: list[NamedRegion] = Field(..., min_length=2, max_length=engine.MAX_COMPARE_REGIONS,
                                       description="2 to 5 named regions, analyzed for the same period")
    start: str | None = Field(None, pattern=MONTH, examples=["2001-01"])
    end: str | None = Field(None, pattern=MONTH, examples=["2024-12"])
    source: Literal["auto", "local", "cloud"] = "auto"
    include_series: bool = True


class DriversRequest(AnalyzeRequest):
    region_name: str | None = Field(None, max_length=60, examples=["Rondônia (Amazon)"],
                                    description="Optional place name; helps the AI explanation")
    explain: bool = Field(True, description="Ask Claude for a plain-language explanation (needs ANTHROPIC_API_KEY)")


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
        "category": var.category,
        "source": f"{var.collection} v{var.version}",
        "related": list(var.related),
        "data_starts": var.first_month,
        "data_ends": var.last_month,
        "local_global": None,
        "local_examples": [],
    }
    path = data.cube_path(var)
    if path.exists():
        with xr.open_zarr(path, consolidated=False) as ds:
            times = pd.to_datetime(ds.time.values)
        info["local_global"] = {"start": f"{times.min():%Y-%m}", "end": f"{times.max():%Y-%m}",
                                "n_months": len(times)}
    if local.tile_dir(var).exists():
        info["local_examples"] = sorted(p.stem for p in local.tile_dir(var).glob("*.zarr"))
    return info


def _require_variable(key: str) -> catalog.Variable:
    var = catalog.VARIABLES.get(key)
    if var is None:
        raise HTTPException(404, f"Unknown variable '{key}'. Options: {', '.join(catalog.VARIABLES)}")
    return var


def _validate(req: AnalyzeRequest) -> catalog.Variable:
    var = _require_variable(req.variable)
    if req.start and req.end and req.start > req.end:
        raise HTTPException(422, "start must be before end")
    latest = f"{pd.Timestamp.now():%Y-%m}"
    if req.end and req.end > latest:
        raise HTTPException(422, f"end can't be in the future (latest is {latest})")
    try:
        region.load_polygon(req.region)
    except Exception as e:
        raise HTTPException(422, f"Invalid region GeoJSON: {e}")
    return var


def _plan(req: AnalyzeRequest) -> dict:
    try:
        p = engine.plan(req.variable, req.region, req.start, req.end, source=req.source)
    except data.DataError as e:  # source="local" but nothing local covers it
        raise HTTPException(409, str(e))
    if p["source"] == "cloud" and not data.have_credentials():
        raise HTTPException(503, "This needs NASA's cloud, but the server has no Earthdata credentials.")
    return p


def _run(req: AnalyzeRequest, progress=None) -> dict:
    result = engine.analyze(req.variable, req.region, start=req.start, end=req.end,
                            source=req.source, progress=progress)
    if not req.include_series:
        result.pop("series", None)
    return _clean(result)


def _error_message(e: Exception) -> str:
    return str(e) if isinstance(e, (data.DataError, ValueError)) else f"Unexpected error: {e}"


# ----------------------------------------------------------------- routes

@app.get("/health")
def health():
    return {
        "status": "ok",
        "data_dir": str(data.DATA_DIR),
        "cloud_enabled": data.have_credentials(),
        "earthdata_token": data.token_status(),  # expiry date only, never the token
        "ai_enabled": narrative.has_api_key(),
        "cache": cache.RESULTS.stats(),
    }


@app.post("/cache/clear")
def clear_cache():
    """Forget all cached results (e.g. before a demo, to show a real NASA stream)."""
    cache.RESULTS.clear()
    return cache.RESULTS.stats()


@app.get("/variables")
def list_variables():
    """All variables, with plain-language definitions and what's stored locally."""
    return [_variable_info(v) for v in catalog.VARIABLES.values()]


@app.get("/variables/{key}")
def get_variable(key: str):
    return _variable_info(_require_variable(key))


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


@app.post("/plan")
def plan(req: AnalyzeRequest):
    """Where an analysis would get its data (local or NASA cloud) and roughly how long
    it would take, without running it."""
    _validate(req)
    return _plan(req)


@app.post("/analyze")
def analyze_region(req: AnalyzeRequest):
    """Run an analysis and wait for the result. Instant for local data; ~30 s when
    streaming 24 years from NASA's cloud (use POST /analyze/jobs to get progress)."""
    _validate(req)
    _plan(req)
    try:
        return _run(req)
    except (data.DataError, ValueError) as e:  # too few months, no data in region, NASA errors
        raise HTTPException(422, str(e))


@app.post("/analyze/jobs", status_code=202)
def analyze_job(req: AnalyzeRequest):
    """Start an analysis in the background. Poll GET /jobs/{id}: it reports progress
    while streaming from NASA, and holds the full result once `status` is `done`."""
    _validate(req)
    p = _plan(req)
    job = jobs.submit(req.variable, req.start, req.end,
                      work=lambda progress: _run(req, progress), on_error=_error_message)
    return {"job": job.to_dict(), "plan": p}


def _validate_compare(req: CompareRequest) -> list[dict]:
    names = [r.name for r in req.regions]
    if len(set(names)) != len(names):
        raise HTTPException(422, "Region names must be unique")
    for r in req.regions:
        _validate(AnalyzeRequest(variable=req.variable, region=r.region, start=req.start, end=req.end))
    return [{"name": r.name, "region": r.region} for r in req.regions]


def _compare_plan(req: CompareRequest, regions: list[dict]) -> dict:
    plans = [{"name": r["name"], **_plan(AnalyzeRequest(variable=req.variable, region=r["region"],
                                                       start=req.start, end=req.end, source=req.source))}
             for r in regions]
    seconds = sum(p["estimated_seconds"] for p in plans)
    cloud = any(p["source"] == "cloud" for p in plans)
    return {"source": "cloud" if cloud else "local", "estimated_seconds": seconds, "regions": plans}


def _run_compare(req: CompareRequest, regions: list[dict], progress=None) -> dict:
    result = engine.compare(req.variable, regions, start=req.start, end=req.end,
                            source=req.source, progress=progress)
    if not req.include_series:
        for r in result["regions"]:
            r.pop("series", None)
    return _clean(result)


@app.post("/compare/plan")
def compare_plan(req: CompareRequest):
    """Where each region's data would come from, and the total estimated time."""
    return _compare_plan(req, _validate_compare(req))


@app.post("/compare")
def compare_regions(req: CompareRequest):
    """Analyze one variable over 2-5 regions for the same period, and wait for the result."""
    regions = _validate_compare(req)
    _compare_plan(req, regions)
    try:
        return _run_compare(req, regions)
    except (data.DataError, ValueError) as e:
        raise HTTPException(422, str(e))


@app.post("/compare/jobs", status_code=202)
def compare_job(req: CompareRequest):
    """Start a comparison in the background; poll GET /jobs/{id} for progress and the result."""
    regions = _validate_compare(req)
    p = _compare_plan(req, regions)
    job = jobs.submit(req.variable, req.start, req.end,
                      work=lambda progress: _run_compare(req, regions, progress), on_error=_error_message)
    return {"job": job.to_dict(), "plan": p}


def _run_drivers(req: DriversRequest, progress=None, say=None) -> dict:
    result = drivers.analyze_drivers(req.variable, req.region, start=req.start, end=req.end,
                                     source=req.source, progress=progress)
    if req.explain:
        if say:
            say("Writing a plain-language explanation with Claude")
        result["explanation"] = narrative.explain(result, region_name=req.region_name)
    else:
        result["explanation"] = {"available": False, "reason": "Not requested."}
    return _clean(result)


@app.post("/drivers")
def explain_drivers(req: DriversRequest):
    """What might be causing the trend: the target is compared with its related variables
    (correlation, regression, random forest), then Claude explains the evidence.
    Waits for the result; use POST /drivers/jobs to get progress."""
    _validate(req)
    _plan(req)
    try:
        return _run_drivers(req)
    except (data.DataError, ValueError) as e:
        raise HTTPException(422, str(e))


@app.post("/drivers/jobs", status_code=202)
def explain_drivers_job(req: DriversRequest):
    """Start a cause analysis in the background; poll GET /jobs/{id}."""
    _validate(req)
    p = _plan(req)
    job = jobs.submit(req.variable, req.start, req.end,
                      work=lambda progress, say: _run_drivers(req, progress, say), on_error=_error_message)
    return {"job": job.to_dict(), "plan": p}


@app.get("/jobs/{job_id}")
def get_job(job_id: str):
    job = jobs.get(job_id)
    if job is None:
        raise HTTPException(404, f"No job '{job_id}' (jobs are kept in memory and cleared on restart)")
    return job.to_dict()
