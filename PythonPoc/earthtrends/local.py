"""Data kept on this machine, used before going to NASA's cloud.

Two kinds of local data, both stored as Zarr (time, lat, lon):
  data/cubes/<var>.zarr          global cubes from `earthtrends fetch` (optional, large)
  data/tiles/<var>/<name>.zarr   small clipped copies made by `earthtrends prepare-examples`
                                 (the demo regions, so the presentation runs offline)

`find()` returns local data that fully covers a polygon and every requested month,
or None, in which case the caller reads from NASA's cloud instead.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import xarray as xr
from shapely.geometry.base import BaseGeometry

from . import data
from .catalog import Variable


def tile_dir(var: Variable) -> Path:
    return data.DATA_DIR / "tiles" / var.key


def _requested_months(var: Variable, start: str, end: str) -> list[pd.Timestamp]:
    return var.available_months(start, end)


def _covers(da: xr.DataArray, geom: BaseGeometry, months: list[pd.Timestamp]) -> bool:
    have = set(pd.to_datetime(da.time.values))
    if not months or any(m not in have for m in months):
        return False
    lat, lon = da["lat"].values, da["lon"].values
    dlat = float(abs(lat[1] - lat[0])) if lat.size > 1 else 0.0
    dlon = float(abs(lon[1] - lon[0])) if lon.size > 1 else 0.0
    minx, miny, maxx, maxy = geom.bounds
    return (lon.min() - dlon <= minx and maxx <= lon.max() + dlon and
            lat.min() - dlat <= miny and maxy <= lat.max() + dlat)


def find(var: Variable, geom: BaseGeometry, start: str, end: str) -> tuple[xr.DataArray, str] | None:
    """(data, description) from local storage if it covers the request, else None."""
    months = _requested_months(var, start, end)
    candidates: list[tuple[Path, str]] = []
    if data.cube_path(var).exists():
        candidates.append((data.cube_path(var), "local global data"))
    if tile_dir(var).exists():
        candidates += [(p, f"local copy of '{p.stem}'") for p in sorted(tile_dir(var).glob("*.zarr"))]
    for path, label in candidates:
        da = xr.open_zarr(path, consolidated=False)[var.key]
        if _covers(da, geom, months):
            return da, label
    return None


def tile_covers(var: Variable, name: str, geom: BaseGeometry, start: str, end: str) -> bool:
    """True if the saved copy `name` already covers this region and period."""
    path = tile_dir(var) / f"{name}.zarr"
    if not path.exists():
        return False
    return _covers(xr.open_zarr(path, consolidated=False)[var.key], geom, _requested_months(var, start, end))


def save_tile(da: xr.DataArray, var: Variable, name: str) -> Path:
    path = tile_dir(var) / f"{name}.zarr"
    path.parent.mkdir(parents=True, exist_ok=True)
    da.to_dataset(name=var.key).to_zarr(path, mode="w", consolidated=False)
    return path
