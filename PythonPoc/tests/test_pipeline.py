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


def _fake_gldas(raw_dir, months):
    from earthtrends import catalog
    var = catalog.get("soil_moisture")
    d = raw_dir / var.collection
    d.mkdir(parents=True, exist_ok=True)
    lat, lon = np.arange(30.125, 40, 0.25), np.arange(-120.125, -110, 0.25)
    for m in months:
        v = np.full((1, lat.size, lon.size), float(m.year * 100 + m.month), dtype="f4")
        xr.Dataset({"SoilMoi0_10cm_inst": (("time", "lat", "lon"), v),
                    "Evap_tavg": (("time", "lat", "lon"), v * 0)},
                   coords={"time": [0.0], "lat": lat, "lon": lon}
                   ).to_netcdf(d / f"GLDAS_NOAH025_M.A{m:%Y%m}.021.nc4")
    return var


def test_build_cube_adds_older_months_and_coverage(tmp_path, monkeypatch):
    from earthtrends import data
    monkeypatch.setattr(data, "RAW_DIR", tmp_path / "raw")
    monkeypatch.setattr(data, "CUBE_DIR", tmp_path / "cubes")
    var = _fake_gldas(data.RAW_DIR, pd.date_range("2022-01", "2022-06", freq="MS"))
    data.build_cube(var)

    cov = data.coverage(var, "2021-01", "2022-06")
    assert cov["missing_months"] == 12 and cov["download_months"] == 12
    assert cov["estimated_mb"] == pytest.approx(12 * var.mb_per_month)

    _fake_gldas(data.RAW_DIR, pd.date_range("2021-01", "2021-12", freq="MS"))  # older months
    assert data.coverage(var, "2021-01", "2022-06")["download_months"] == 0  # on disk, not in cube
    data.build_cube(var)
    times = pd.to_datetime(data.open_cube(var).time.values)
    assert len(times) == 18 and times.is_monotonic_increasing
    assert data.coverage(var, "2021-01", "2022-06")["missing_months"] == 0
    assert not (data.CUBE_DIR / "soil_moisture.zarr.rebuild").exists()
