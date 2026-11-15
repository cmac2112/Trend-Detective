"""Where inside a region is it changing? A trend for every grid cell.

The region-average trend (stats.py) answers "is this region changing?", but averaging can
hide the most interesting answer: one part of the region rising while another falls. This
module fits the same trend to every grid cell inside the polygon, vectorised over the
whole (time, lat, lon) cube so hundreds of cells take milliseconds:

  1. remove each cell's own seasonal cycle (monthly climatology)
  2. least-squares slope per cell, with the same autocorrelation-adjusted t-test as the
     region average (Santer et al. 2000 effective sample size)
  3. control the false discovery rate across cells (Benjamini-Hochberg). Testing 500 cells
     at p < 0.05 would flag ~25 "significant" cells from pure noise; the FDR step keeps
     the expected share of false alarms among flagged cells at 5% (Wilks 2016,
     "The stippling shows statistically significant grid points").

Mann-Kendall is not run per cell (it is ~1000x slower than the vectorised t-test); the
region-average verdict still requires both tests.

Very large regions are averaged into coarser blocks first so the map stays at most
MAX_CELLS cells (the browser draws one rectangle per cell).
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd
import shapely
import xarray as xr
from scipy import stats as st
from shapely.geometry.base import BaseGeometry

from .stats import ALPHA, decimal_years

MAX_CELLS = 2500
MIN_MONTHS = 24


def _subset(da: xr.DataArray, geom: BaseGeometry) -> xr.DataArray:
    """The cells around the polygon's bounding box (same selection as region.polygon_mean)."""
    from .region import _index_range

    lat, lon = da["lat"].values, da["lon"].values
    dlat = float(np.abs(np.diff(lat)).mean()) if lat.size > 1 else 0.0
    dlon = float(np.abs(np.diff(lon)).mean()) if lon.size > 1 else 0.0
    minx, miny, maxx, maxy = geom.bounds
    return da.isel(lat=_index_range(lat, miny - dlat, maxy + dlat),
                   lon=_index_range(lon, minx - dlon, maxx + dlon))


def _inside(geom: BaseGeometry, lat: np.ndarray, lon: np.ndarray) -> np.ndarray:
    lon2d, lat2d = np.meshgrid(lon, lat)
    inside = shapely.contains_xy(geom, lon2d, lat2d)
    if not inside.any():  # tiny polygon: the nearest cell, as polygon_mean does
        c = geom.centroid
        d = (lat2d - c.y) ** 2 + (lon2d - c.x) ** 2
        inside = d == d.min()
    return inside


def _block_mean(values: np.ndarray, f: int) -> np.ndarray:
    """Average (time, ny, nx) into f x f blocks, ignoring NaN; edges padded with NaN."""
    nt, ny, nx = values.shape
    py, px = -ny % f, -nx % f
    v = np.pad(values, ((0, 0), (0, py), (0, px)), constant_values=np.nan)
    v = v.reshape(nt, (ny + py) // f, f, (nx + px) // f, f)
    with np.errstate(invalid="ignore", divide="ignore"):  # all-NaN blocks stay NaN
        return np.nansum(v, axis=(2, 4)) / np.isfinite(v).sum(axis=(2, 4))


def _block_coord(coord: np.ndarray, f: int) -> np.ndarray:
    step = float(np.mean(np.diff(coord))) if coord.size > 1 else 0.0
    n = math.ceil(coord.size / f)
    return coord[0] + (np.arange(n) * f + (f - 1) / 2) * step


def benjamini_hochberg(p: np.ndarray, alpha: float = ALPHA) -> np.ndarray:
    """True where a p-value is significant after controlling the false discovery rate.
    NaN p-values are never significant."""
    flat = p.ravel()
    ok = np.isfinite(flat)
    out = np.zeros(flat.shape, dtype=bool)
    m = int(ok.sum())
    if m == 0:
        return out.reshape(p.shape)
    idx = np.flatnonzero(ok)
    order = idx[np.argsort(flat[idx])]
    thresh = alpha * np.arange(1, m + 1) / m
    below = flat[order] <= thresh
    if below.any():
        k = int(np.max(np.nonzero(below)[0]))
        out[order[: k + 1]] = True
    return out.reshape(p.shape)


def cell_trends(values: np.ndarray, times: pd.DatetimeIndex) -> dict[str, np.ndarray]:
    """Vectorised trend test for every cell of a (time, ny, nx) array (NaN = missing).

    Returns arrays of shape (ny, nx): slope_per_year, p_value, n (valid months).
    Cells with fewer than MIN_MONTHS valid months get NaN slope and p-value."""
    y = values.astype("float64")
    valid = np.isfinite(y)
    months = times.month.to_numpy()

    # 1. per-cell seasonal cycle
    # (sums rather than np.nanmean: all-NaN cells would warn, and silencing warnings with
    # warnings.catch_warnings isn't thread-safe; scans run many analyses in threads)
    anom = np.full_like(y, np.nan)
    with np.errstate(invalid="ignore", divide="ignore"):
        for m in range(1, 13):
            sel = months == m
            if sel.any():
                clim = np.nansum(y[sel], axis=0) / valid[sel].sum(axis=0)
                anom[sel] = y[sel] - clim

    # 2. least squares with missing values
    t = decimal_years(times)[:, None, None]
    w = valid.astype("float64")
    n = w.sum(axis=0)
    with np.errstate(invalid="ignore", divide="ignore"):
        tbar = (w * t).sum(axis=0) / n
        a = np.where(valid, anom, 0.0)
        ybar = a.sum(axis=0) / n
        dt = np.where(valid, t - tbar, 0.0)
        sxx = (dt ** 2).sum(axis=0)
        slope = (dt * (a - ybar)).sum(axis=0) / sxx
        resid = np.where(valid, a - ybar - slope * dt, 0.0)
        sse = (resid ** 2).sum(axis=0)
        se = np.sqrt(sse / (n - 2) / sxx)

        # lag-1 autocorrelation of residuals (neighbouring months both present)
        pair = valid[:-1] & valid[1:]
        r0, r1_ = np.where(pair, resid[:-1], 0.0), np.where(pair, resid[1:], 0.0)
        r1 = (r0 * r1_).sum(axis=0) / np.sqrt((r0 ** 2).sum(axis=0) * (r1_ ** 2).sum(axis=0))
        r1 = np.clip(np.nan_to_num(r1, nan=0.0), 0.0, None)

        n_eff = np.maximum(n * (1 - r1) / (1 + r1), 3.0)
        se_adj = se * np.sqrt((n - 2) / (n_eff - 2))
        tstat = np.where(se_adj > 0, slope / se_adj, 0.0)
        p = 2 * st.t.sf(np.abs(tstat), n_eff - 2)

    enough = n >= MIN_MONTHS
    slope = np.where(enough, slope, np.nan)
    p = np.where(enough & np.isfinite(p), p, np.nan)
    return {"slope_per_year": slope, "p_value": p, "n": n}


def _round(a: np.ndarray, digits: int = 4) -> list:
    """2-D array -> nested lists with NaN as None, rounded to `digits` significant figures."""
    def r(v: float):
        if not math.isfinite(v):
            return None
        return float(f"{v:.{digits}g}")
    return [[r(float(v)) for v in row] for row in a]


def trend_map(da: xr.DataArray, geom: BaseGeometry, units: str = "") -> dict:
    """Per-cell trend over the polygon, as JSON-ready grid + summary.

    Grid arrays are indexed [lat][lon]; cells outside the polygon or with too little data
    are null."""
    sub = _subset(da, geom)
    lat = sub["lat"].values.astype("float64")
    lon = sub["lon"].values.astype("float64")
    times = pd.to_datetime(sub["time"].values)
    values = np.asarray(sub.values, dtype="float32")
    inside = _inside(geom, lat, lon)
    values = np.where(inside[None], values, np.nan)

    res_lat = float(np.abs(np.diff(lat)).mean()) if lat.size > 1 else 0.0
    res_lon = float(np.abs(np.diff(lon)).mean()) if lon.size > 1 else 0.0
    factor = 1
    if inside.sum() > MAX_CELLS:
        factor = math.ceil(math.sqrt(inside.sum() / MAX_CELLS))
        values = _block_mean(values, factor)
        inside = _block_mean(inside[None].astype("float32"), factor)[0] > 0
        lat, lon = _block_coord(lat, factor), _block_coord(lon, factor)
        res_lat, res_lon = res_lat * factor, res_lon * factor

    tr = cell_trends(values, times)
    slope_dec = np.where(inside, tr["slope_per_year"] * 10, np.nan)
    p = np.where(inside, tr["p_value"], np.nan)
    sig = benjamini_hochberg(p)
    sig_raw = np.isfinite(p) & (p < ALPHA)

    have = np.isfinite(slope_dec)
    n_have = int(have.sum())
    s = slope_dec[have]
    up = int((sig & (slope_dec > 0)).sum())
    down = int((sig & (slope_dec < 0)).sum())
    color_limit = float(np.percentile(np.abs(s), 98)) if n_have else 0.0
    summary = {
        "cells": int(inside.sum()),
        "cells_with_trend": n_have,
        "share_increasing": float((s > 0).mean()) if n_have else None,
        "significant_up": up,
        "significant_down": down,
        "significant_uncorrected": int(sig_raw.sum()),
        "mixed": up > 0 and down > 0,
        "slope_min": float(s.min()) if n_have else None,
        "slope_max": float(s.max()) if n_have else None,
        "color_limit": color_limit,
    }
    summary["description"] = describe(summary)
    return {
        "units": units,
        "lat": [round(float(v), 4) for v in lat],
        "lon": [round(float(v), 4) for v in lon],
        "resolution_deg": [round(res_lat, 4), round(res_lon, 4)],
        "coarsened_by": factor,
        "slope_per_decade": _round(slope_dec),
        "p_value": _round(p, 3),
        "significant": [[bool(v) for v in row] for row in sig],
        "method": ("Per-cell least-squares trend on seasonal anomalies, autocorrelation-adjusted "
                   "t-test, significance controlled for false discoveries across cells "
                   "(Benjamini-Hochberg, 5%)."),
        "summary": summary,
    }


def describe(s: dict) -> str:
    n = s["cells_with_trend"]
    if not n:
        return "No grid cell in this region has enough data for a trend map."
    if n == 1:
        return "This region covers a single grid cell, so the map can't show differences inside it."
    pct_up = round(100 * s["share_increasing"])
    parts = [f"{pct_up}% of the {n} grid cells are increasing and {100 - pct_up}% decreasing."]
    up, down = s["significant_up"], s["significant_down"]
    if s["mixed"]:
        parts.append(f"Opposite trends inside this region: {up} cells rise and {down} fall significantly, "
                     "so the regional average hides part of the story.")
    elif up or down:
        which, k = ("increase", up) if up else ("decrease", down)
        parts.append(f"{k} cells ({round(100 * k / n)}%) show a significant {which}.")
    else:
        parts.append("No individual cell's trend is significant once we allow for testing "
                     "many cells at once.")
    return " ".join(parts)
