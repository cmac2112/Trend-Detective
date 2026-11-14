"""Trend Detective API.

Thin HTTP layer over the `earthtrends` core library (PythonPoc/). Reads the local
data cubes only - no NASA calls or credentials are needed to serve requests.

Run:  uvicorn app.main:app --reload      (from the TrendApi folder)
Docs: http://127.0.0.1:8000/docs
"""
from __future__ import annotations

import json
import math
import os
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

EXAMPLES_DIR = POC_DIR / "examples"
MONTH = r"^\d{4}-(0[1-9]|1[0-2])$"

app = FastAPI(
    title="Trend Detective API",
    description="Draw a region, pick a NASA Earth science variable, find out if it's trending.",
    version="0.1.0",
)
app.add_middleware(  # open for local development (React dev server, Postman, etc.)
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
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


# ----------------------------------------------------------------- routes

@app.get("/health")
def health():
    return {"status": "ok", "data_dir": str(data.DATA_DIR)}


@app.get("/variables")
def list_variables():
    """All variables with plain-language definitions and whether their data is downloaded."""
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


@app.post("/analyze")
def analyze_region(req: AnalyzeRequest):
    """Time series + trend statistics for one variable over a polygon."""
    var = _require_variable(req.variable)
    if not data.cube_path(var).exists():
        raise HTTPException(
            409, f"Data for '{var.key}' isn't downloaded yet. In PythonPoc run: "
                 f"python -m earthtrends fetch {var.key}",
        )
    if req.start and req.end and req.start > req.end:
        raise HTTPException(422, "start must be before end")
    try:
        region.load_polygon(req.region)
    except Exception as e:
        raise HTTPException(422, f"Invalid region GeoJSON: {e}")

    try:
        result = analyze(var.key, req.region, start=req.start, end=req.end)
    except ValueError as e:  # too few months, no data in region, etc.
        raise HTTPException(422, str(e))

    if not req.include_series:
        result.pop("series", None)
    return _clean(result)
