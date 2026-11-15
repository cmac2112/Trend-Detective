"""Per-cell trend map and the all-variable scan, on synthetic data."""
import zlib

import numpy as np
import pandas as pd
import pytest
import xarray as xr

from earthtrends import analyze as engine
from earthtrends import cloud, data, scan, stats, trendmap
from earthtrends.region import load_polygon

POLY = {"type": "Polygon", "coordinates": [[[-115, 35], [-113, 35], [-113, 37], [-115, 37], [-115, 35]]]}


def cube(trend_fn, noise=0.3, years=24, seed=0, res=0.5):
    """trend_fn(lon2d, lat2d) -> trend per year for each cell."""
    rng = np.random.default_rng(seed)
    time = pd.date_range("2001-01-01", periods=years * 12, freq="MS")
    lat = np.arange(30 + res / 2, 42, res)
    lon = np.arange(-120 + res / 2, -108, res)
    lon2d, lat2d = np.meshgrid(lon, lat)
    t = (np.arange(len(time)) / 12)[:, None, None]
    season = 8 * np.sin(2 * np.pi * time.month.to_numpy() / 12)[:, None, None]
    vals = 15 + trend_fn(lon2d, lat2d)[None] * t + season + rng.normal(0, noise, (len(time), lat.size, lon.size))
    return xr.DataArray(vals.astype("f4"), coords={"time": time, "lat": lat, "lon": lon},
                        dims=("time", "lat", "lon"), name="t2m")


def test_single_cell_matches_region_stats():
    """The vectorised per-cell test must give the same slope and p-value as trend_stats."""
    da = cube(lambda x, y: np.full_like(x, 0.02), noise=0.5)
    one = da.isel(lat=[5], lon=[5])
    tr = trendmap.cell_trends(one.values, pd.to_datetime(one.time.values))
    ref = stats.trend_stats(one.isel(lat=0, lon=0).to_series())
    assert tr["slope_per_year"][0, 0] * 10 == pytest.approx(ref["linear"]["slope_per_decade"], rel=1e-6)
    # tiny difference: np.corrcoef centres each half of the lag-1 pair, the vectorised version doesn't
    assert tr["p_value"][0, 0] == pytest.approx(ref["linear"]["p_value"], rel=1e-2)


def test_opposite_trends_inside_region_are_found():
    # west half warming, east half cooling: the region average is ~flat
    da = cube(lambda x, y: np.where(x < -114, 0.06, -0.06))
    res = engine.analyze("t2m", POLY, da=da)
    m = res["trend_map"]
    assert m["summary"]["mixed"]
    assert m["summary"]["significant_up"] == 8 and m["summary"]["significant_down"] == 8
    assert abs(res["stats"]["linear"]["slope_per_decade"]) < 0.1
    assert "Opposite trends" in m["summary"]["description"]
    lon = np.array(m["lon"])
    for row in m["slope_per_decade"]:
        for x, v in zip(lon, row):
            if v is not None:
                assert (v > 0) == (x < -114)


def test_cells_outside_polygon_are_null():
    m = engine.analyze("t2m", POLY, da=cube(lambda x, y: np.full_like(x, 0.05)))["trend_map"]
    flat = [v for row in m["slope_per_decade"] for v in row]
    assert sum(v is not None for v in flat) == 16 == m["summary"]["cells"]
    assert len(flat) > 16  # the bounding-box padding cells are present but null


def test_fdr_controls_noise():
    """Pure noise: some cells pass p < 0.05 by chance, (almost) none survive FDR."""
    big = {"type": "Polygon", "coordinates": [[[-120, 30], [-108, 30], [-108, 42], [-120, 42], [-120, 30]]]}
    m = trendmap.trend_map(cube(lambda x, y: np.zeros_like(x), noise=1.0, seed=7), load_polygon(big))
    s = m["summary"]
    assert s["cells_with_trend"] > 500
    assert s["significant_uncorrected"] > 5
    assert s["significant_up"] + s["significant_down"] <= 2


def test_benjamini_hochberg():
    p = np.array([0.001, 0.008, 0.039, 0.041, 0.6, np.nan])
    assert trendmap.benjamini_hochberg(p).tolist() == [True, True, False, False, False, False]


def test_large_region_is_coarsened(monkeypatch):
    monkeypatch.setattr(trendmap, "MAX_CELLS", 100)
    big = {"type": "Polygon", "coordinates": [[[-120, 30], [-108, 30], [-108, 42], [-120, 42], [-120, 30]]]}
    m = trendmap.trend_map(cube(lambda x, y: np.full_like(x, 0.05), years=3), load_polygon(big))
    assert m["coarsened_by"] == 3
    assert m["summary"]["cells"] <= 100
    assert m["resolution_deg"] == [1.5, 1.5]


def test_land_only_cells_skipped():
    da = cube(lambda x, y: np.full_like(x, 0.05))
    da = da.where(da.lon < -114)
    m = engine.analyze("t2m", POLY, da=da)["trend_map"]
    assert m["summary"]["cells_with_trend"] == 8


def test_scan_ranks_variables(monkeypatch, tmp_path):
    from earthtrends import cache
    monkeypatch.setattr(data, "DATA_DIR", tmp_path)
    monkeypatch.setattr(data, "CUBE_DIR", tmp_path / "cubes")
    cache.RESULTS.clear()
    trends = {"t2m": 0.08, "precip": 0.0}

    def fake_cloud(var, geom, start, end, progress=None):
        if var.key == "soil_moisture":
            raise data.DataError("no soil over the ocean")
        if var.key == "snow_water":  # no snow at all: constant zero
            return (cube(lambda x, y: np.zeros_like(x), noise=0) * 0).sel(time=slice(start, end)).rename(var.key)
        rate = trends.get(var.key, 0.0)
        return cube(lambda x, y: np.full_like(x, rate), noise=0.5, seed=zlib.crc32(var.key.encode()) % 1000).sel(
            time=slice(start, end)).rename(var.key)

    monkeypatch.setattr(cloud, "open_region", fake_cloud)
    res = scan.scan(POLY, "2001-01", "2024-12")
    keys = [v["key"] for v in res["variables"]]
    assert keys[0] == "t2m"
    top = res["variables"][0]
    assert top["level"] == "significant" and top["passes_fdr"] and top["rank"] == 1
    assert "soil_moisture" in res["skipped"]
    assert "doesn't change" in res["skipped"]["snow_water"]
    co2 = next(v for v in res["variables"] if v["key"] == "co2")
    assert co2["start"] >= "2014-01"  # clipped to OCO-2's record
    # the full result is cached under the item's own period, so opening it is instant
    assert engine.plan("t2m", POLY, top["start"], top["end"])["source"] == "cache"
    cache.RESULTS.clear()


def test_years_to_detect_matches_simulation():
    """Weatherhead's n* should give ~90% detection with our own autocorrelation-adjusted test."""
    import warnings
    warnings.simplefilter("ignore")
    rng = np.random.default_rng(1)
    slope, sd, phi = 0.05, 0.5, 0.3
    n = int(round(stats.years_to_detect(slope, sd, phi) * 12))
    hits, sims = 0, 80
    for _ in range(sims):
        e = np.zeros(n)
        w = rng.normal(0, sd * np.sqrt(1 - phi ** 2), n)
        e[0] = rng.normal(0, sd)
        for k in range(1, n):
            e[k] = phi * e[k - 1] + w[k]
        y = pd.Series(slope * np.arange(n) / 12 + e, index=pd.date_range("2000-01-01", periods=n, freq="MS"))
        hits += stats.trend_stats(y)["linear"]["p_value"] < 0.05
    assert 0.8 <= hits / sims <= 1.0


def test_not_significant_verdict_says_how_long_to_wait():
    rng = np.random.default_rng(4)
    idx = pd.date_range("2001-01-01", periods=120, freq="MS")
    y = pd.Series(0.01 * np.arange(120) / 12 + rng.normal(0, 0.5, 120), index=idx)
    r = stats.trend_stats(y)
    assert not r["significant"]
    assert r["detection"]["more_years"] > 0
    assert "more years of data" in r["verdict"] or "century" in r["verdict"]
