"""Tests on synthetic data with a known trend, so no NASA download is needed."""
import numpy as np
import pandas as pd
import pytest
import xarray as xr

from earthtrends.analyze import analyze
from earthtrends.data import month_from_filename
from earthtrends.region import load_polygon, polygon_mean
from pathlib import Path

POLY = {"type": "Polygon", "coordinates": [[[-115, 35], [-113, 35], [-113, 37], [-115, 37], [-115, 35]]]}


def make_cube(trend_per_year: float, noise: float = 0.3, years: int = 24, seed: int = 0) -> xr.DataArray:
    rng = np.random.default_rng(seed)
    time = pd.date_range("2001-01-01", periods=years * 12, freq="MS")
    lat = np.arange(-89.75, 90, 0.5)
    lon = np.arange(-179.75, 180, 0.5)
    t = np.arange(len(time)) / 12
    signal = 15 + trend_per_year * t + 8 * np.sin(2 * np.pi * (time.month.to_numpy() - 4) / 12)
    data = signal[:, None, None] + rng.normal(0, noise, (len(time), lat.size, lon.size))
    return xr.DataArray(data.astype("float32"), coords={"time": time, "lat": lat, "lon": lon},
                        dims=("time", "lat", "lon"), name="t2m")


def test_recovers_known_trend():
    res = analyze("t2m", POLY, da=make_cube(trend_per_year=0.05))
    lin = res["stats"]["linear"]
    assert lin["slope_per_decade"] == pytest.approx(0.5, abs=0.05)
    assert lin["ci95_per_decade"][0] < 0.5 < lin["ci95_per_decade"][1]
    assert res["stats"]["significant"]
    assert res["stats"]["mann_kendall"]["trend"] == "increasing"
    assert res["region"]["grid_cells"] == 16  # 4 x 4 half-degree cells


def test_no_trend_not_significant():
    res = analyze("t2m", POLY, da=make_cube(trend_per_year=0.0, noise=1.0, seed=3))
    assert not res["stats"]["significant"]
    assert "No significant" in res["stats"]["verdict"] or "Possible" in res["stats"]["verdict"]


def test_tiny_polygon_uses_nearest_cell():
    tiny = {"type": "Polygon", "coordinates": [[[-114.1, 36.1], [-114.0, 36.1], [-114.0, 36.2], [-114.1, 36.1]]]}
    _, info = polygon_mean(make_cube(0.0, years=2), load_polygon(tiny))
    assert info["grid_cells"] == 1


def test_nan_cells_ignored():
    da = make_cube(0.05)
    da = da.where(da.lon < -114)  # half the polygon is "ocean"
    series, info = polygon_mean(da, load_polygon(POLY))
    assert info["cells_with_data"] == 8
    assert series.notna().all()


@pytest.mark.parametrize("name,expected", [
    ("3B-MO.MS.MRG.3IMERG.20010101-S000000-E235959.01.V07B.HDF5", "2001-01"),
    ("MERRA2_400.tavgM_2d_slv_Nx.202309.nc4", "2023-09"),
    ("GLDAS_NOAH025_M.A201512.021.nc4", "2015-12"),
])
def test_month_from_filename(name, expected):
    assert month_from_filename(Path(name)).strftime("%Y-%m") == expected
