"""Turn a gridded (time, lat, lon) cube into a single time series for a polygon."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import shapely
import xarray as xr
from shapely.geometry import shape
from shapely.geometry.base import BaseGeometry


def load_polygon(source: str | Path | dict) -> BaseGeometry:
    """Accept a GeoJSON file path, a GeoJSON string, or a GeoJSON dict
    (Feature, FeatureCollection, or bare geometry). Coordinates are lon/lat."""
    if isinstance(source, dict):
        gj = source
    else:
        text = str(source)
        gj = json.loads(text) if text.lstrip().startswith("{") else json.loads(Path(text).read_text())

    if gj.get("type") == "FeatureCollection":
        geoms = [shape(f["geometry"]) for f in gj["features"]]
        geom = shapely.union_all(geoms)
    elif gj.get("type") == "Feature":
        geom = shape(gj["geometry"])
    else:
        geom = shape(gj)
    if geom.is_empty or geom.geom_type not in ("Polygon", "MultiPolygon"):
        raise ValueError("Region must be a Polygon or MultiPolygon")
    return geom


def _index_range(coord: np.ndarray, lo: float, hi: float) -> slice:
    idx = np.where((coord >= lo) & (coord <= hi))[0]
    if idx.size == 0:  # polygon smaller than a grid cell: take nearest cell
        mid = (lo + hi) / 2
        i = int(np.abs(coord - mid).argmin())
        return slice(i, i + 1)
    return slice(int(idx.min()), int(idx.max()) + 1)


def polygon_mean(da: xr.DataArray, geom: BaseGeometry) -> tuple[pd.Series, dict]:
    """Area-weighted mean of da over the polygon for every time step.

    Returns the series and info about the grid cells used.
    """
    lat = da["lat"].values
    lon = da["lon"].values
    dlat = float(np.abs(np.diff(lat)).mean())
    dlon = float(np.abs(np.diff(lon)).mean())

    minx, miny, maxx, maxy = geom.bounds
    sub = da.isel(
        lat=_index_range(lat, miny - dlat, maxy + dlat),
        lon=_index_range(lon, minx - dlon, maxx + dlon),
    )
    lon2d, lat2d = np.meshgrid(sub["lon"].values, sub["lat"].values)
    inside = shapely.contains_xy(geom, lon2d, lat2d)
    if not inside.any():  # tiny polygon: no cell centre inside, use the nearest cell
        c = geom.centroid
        d = (lat2d - c.y) ** 2 + (lon2d - c.x) ** 2
        inside = d == d.min()

    # Grid cells shrink toward the poles; weight by cos(latitude).
    weights = np.where(inside, np.cos(np.deg2rad(lat2d)), 0.0)
    values = sub.values  # (time, lat, lon) -- only the small subset is read from disk
    valid = ~np.isnan(values) & inside[None]
    w = np.where(valid, weights[None], 0.0)
    wsum = w.sum(axis=(1, 2))
    with np.errstate(invalid="ignore"):
        mean = np.where(wsum > 0, np.nansum(np.where(valid, values, 0.0) * w, axis=(1, 2)) / wsum, np.nan)

    series = pd.Series(mean, index=pd.to_datetime(sub["time"].values), name=da.name)
    info = {
        "grid_cells": int(inside.sum()),
        "cells_with_data": int(valid.any(axis=0).sum()),
        "grid_resolution_deg": [round(dlat, 4), round(dlon, 4)],
        "bounds": [round(b, 4) for b in geom.bounds],
    }
    return series.dropna(), info
