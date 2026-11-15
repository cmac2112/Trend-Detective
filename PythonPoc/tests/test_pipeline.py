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


def test_local_tile_preferred_else_cloud(tmp_path, monkeypatch):
    from earthtrends import analyze as A, data, local, catalog, cloud
    monkeypatch.setattr(data, "DATA_DIR", tmp_path)
    monkeypatch.setattr(data, "CUBE_DIR", tmp_path / "cubes")
    var = catalog.get("t2m")
    cube = make_cube(0.05)
    tile = cube.sel(lat=slice(34, 38), lon=slice(-116, -112), time=slice("2001-01", "2024-12"))
    local.save_tile(tile, var, "test_region")

    calls = []
    def fake_cloud(var, geom, start, end, progress=None):
        calls.append((start, end))
        return cube.sel(time=slice(start, end))
    monkeypatch.setattr(cloud, "open_region", fake_cloud)

    # inside the saved tile and period -> local, no cloud call
    res = A.analyze("t2m", POLY, start="2001-01", end="2024-12")
    assert res["data_source"]["type"] == "local" and calls == []
    assert A.plan("t2m", POLY, "2001-01", "2024-12")["source"] == "cache"  # just analyzed
    from earthtrends import cache
    cache.RESULTS.clear()
    assert A.plan("t2m", POLY, "2001-01", "2024-12")["source"] == "local"
    # region outside the tile -> cloud
    far = {"type": "Polygon", "coordinates": [[[10, 50], [12, 50], [12, 52], [10, 52], [10, 50]]]}
    res = A.analyze("t2m", far, start="2001-01", end="2024-12")
    assert res["data_source"]["type"] == "cloud" and calls == [("2001-01", "2024-12")]
    # period beyond the tile -> cloud
    p = A.plan("t2m", POLY, "1995-01", "2024-12")
    assert p["source"] == "cloud" and p["estimated_seconds"] > 10
    # local-only request that local can't satisfy -> clear error
    # (a cached result would be fine: "local" means no network, and the cache is in memory)
    cache.RESULTS.clear()
    with pytest.raises(Exception, match="No local"):
        A.analyze("t2m", far, start="2001-01", end="2024-12", source="local")
    assert local.tile_covers(var, "test_region", load_polygon(POLY), "2001-01", "2024-12")


@pytest.fixture
def fake_cloud(tmp_path, monkeypatch):
    """Point data at an empty folder and replace NASA with a synthetic cube."""
    from earthtrends import cloud, data
    monkeypatch.setattr(data, "DATA_DIR", tmp_path)
    monkeypatch.setattr(data, "CUBE_DIR", tmp_path / "cubes")
    cube = make_cube(0.05)
    calls = []
    def fake(var, geom, start, end, progress=None):
        calls.append(geom.bounds)
        if progress:
            progress(1, 1)
        sel = cube.sel(time=slice(start, end))
        return sel.where(False) if geom.bounds[1] >= 70 else sel  # north of 70 = "ocean", no data
    monkeypatch.setattr(cloud, "open_region", fake)
    return calls


def test_cache_makes_repeat_instant_and_matches(fake_cloud):
    from earthtrends import analyze as A
    first = A.analyze("t2m", POLY, start="2001-01", end="2024-12")
    assert first["data_source"] == {"type": "cloud", "description": "streamed from NASA Earthdata Cloud", "cached": False}
    assert A.plan("t2m", POLY, "2001-01", "2024-12")["source"] == "cache"
    # same shape sent again with tiny float noise and a different start vertex -> still a hit
    noisy = {"type": "Polygon", "coordinates": [[[-113, 35.000001], [-113, 37], [-115, 37], [-115, 35], [-113, 35.000001]]]}
    second = A.analyze("t2m", noisy, start="2001-01", end="2024-12")
    assert second["data_source"]["cached"] is True and len(fake_cloud) == 1
    assert second["stats"] == first["stats"] and second["series"] == first["series"]
    # different period -> miss; source="cloud" -> bypass
    A.analyze("t2m", POLY, start="2005-01", end="2024-12")
    A.analyze("t2m", POLY, start="2001-01", end="2024-12", source="cloud")
    assert len(fake_cloud) == 3


def test_cache_is_bounded():
    from earthtrends.cache import ResultCache
    c = ResultCache(max_entries=2)
    for k in "abc":
        c.put(k, {"data_source": {"type": "cloud"}})
    assert not c.contains("a") and c.contains("b") and c.contains("c")


def test_compare_regions(fake_cloud):
    from earthtrends import analyze as A
    ocean_only = {"type": "Polygon", "coordinates": [[[0, 70], [10, 70], [10, 80], [0, 80], [0, 70]]]}  # NaN zone
    progress = []
    res = A.compare("t2m", [
        {"name": "A", "region": POLY},
        {"name": "B", "region": {"type": "Polygon", "coordinates": [[[10, 40], [12, 40], [12, 42], [10, 42], [10, 40]]]}},
        {"name": "C", "region": ocean_only},
    ], start="2001-01", end="2024-12", progress=lambda d, t: progress.append((d, t)))
    assert [r["name"] for r in res["regions"]] == ["A", "B", "C"]
    assert "error" in res["regions"][2] and res["summary"]["analyzed"] == 2
    assert set(res["summary"]["significant"]) == {"A", "B"}
    assert progress[-1][0] == progress[-1][1] == 3 * 288  # progress spans all cloud regions
    with pytest.raises(ValueError):
        A.compare("t2m", [{"name": "A", "region": POLY}])


@pytest.mark.parametrize("name,expected", [
    ("AIRS.2003.12.01.L3.RetStd_IR031.v7.0.3.0.G20218141731.hdf", "2003-12"),   # AIRS dotted date
    ("MOD13C2.A2010182.061.2021169014610.hdf", "2010-07"),                      # MODIS day-of-year
    ("MOD13C2.A2012183.061.2021169014610.hdf", "2012-07"),                      # leap year
])
def test_more_filename_dates(name, expected):
    assert month_from_filename(Path(name)).strftime("%Y-%m") == expected


def test_read_field_mean_and_paths(tmp_path):
    """AIRS-style: day/night components in different groups, averaged, ignoring a missing pass."""
    import netCDF4
    from earthtrends import catalog, cloud
    f = tmp_path / "airs.nc"
    with netCDF4.Dataset(f, "w") as nc:
        for grp, name, vals in [("ascending", "SurfAirTemp_A", [[280.0, -9999.0]]),
                                ("descending", "SurfAirTemp_D", [[270.0, 290.0]])]:
            g = nc.createGroup(grp).createGroup("Data_Fields")
            g.createDimension("y", 1); g.createDimension("x", 2)
            v = g.createVariable(name, "f4", ("y", "x"), fill_value=-9999.0)
            v[:] = np.array(vals, dtype="f4")
    with netCDF4.Dataset(f) as nc:
        out = cloud._read_field(nc, catalog.get("airs_surface_temp"))
    assert out[0, 0] == pytest.approx(275 - 273.15, abs=1e-3)  # mean of day and night (float32)
    assert out[0, 1] == pytest.approx(290 - 273.15, abs=1e-3)  # day missing -> night only


def test_single_file_dataset(tmp_path, monkeypatch):
    """OMI-style: whole record in one file with 'Oct2004'-style month labels."""
    import netCDF4
    from earthtrends import catalog, cloud, data
    monkeypatch.setattr(data, "DATA_DIR", tmp_path)
    folder = tmp_path / "datasets" / "TrCO3_Monthly_OMIMLS"
    folder.mkdir(parents=True)
    months = ["Oct2004", "Nov2004", "Dec2004", "Jan2005"]
    with netCDF4.Dataset(folder / "tco.nc", "w") as nc:
        nc.createDimension("Longitude", 360); nc.createDimension("Latitude", 180); nc.createDimension("Time", 4)
        nc.createVariable("Longitude", "f4", ("Longitude",))[:] = np.arange(-179.5, 180, 1.0)
        nc.createVariable("Latitude", "f4", ("Latitude",))[:] = np.arange(-89.5, 90, 1.0)
        t = nc.createVariable("Time", str, ("Time",))
        for i, m in enumerate(months):
            t[i] = m
        o3 = nc.createVariable("TropoO3", "f4", ("Time", "Latitude", "Longitude"))
        o3[:] = np.stack([np.full((180, 360), 30.0 + i, dtype="f4") for i in range(4)])
    geom = load_polygon(POLY)
    cube = cloud.open_region(catalog.get("tropospheric_ozone"), geom, "2004-11", "2005-01")
    assert [pd.Timestamp(t).strftime("%Y-%m") for t in cube.time.values] == ["2004-11", "2004-12", "2005-01"]
    series, _ = polygon_mean(cube, geom)
    assert list(series.round(3)) == [31.0, 32.0, 33.0]


def test_discontinued_record_months():
    """Datasets that stopped (e.g. OCO-2 GEOS CO2, 2015-01..2022-02) clamp both ends."""
    from earthtrends import catalog
    from earthtrends.analyze import default_range, plan
    co2 = catalog.get("co2")
    months = co2.available_months("2001-01", "2024-12")
    assert months[0].strftime("%Y-%m") == "2015-01" and months[-1].strftime("%Y-%m") == "2022-02"
    assert len(months) == 86
    assert default_range(co2) == ("2015-01", "2022-02")
    assert co2.available_months("2023-01", "2024-12") == []
    with pytest.raises(ValueError, match="only has data from 2015-01 to 2022-02"):
        plan("co2", POLY, "2023-01", "2024-12")


def _fake_jwt(exp: int) -> str:
    import base64, json
    enc = lambda d: base64.urlsafe_b64encode(json.dumps(d).encode()).decode().rstrip("=")
    return f"{enc({'alg': 'RS256'})}.{enc({'exp': exp})}.signature"


def test_earthdata_token_login_rules(monkeypatch, tmp_path):
    import time
    from earthtrends import data

    monkeypatch.setattr(Path, "home", lambda: tmp_path)  # no _netrc here
    for k in ("EARTHDATA_TOKEN", "EARTHDATA_USERNAME", "EARTHDATA_PASSWORD"):
        monkeypatch.delenv(k, raising=False)

    # a valid token: expiry read from the token, never echoed back
    tok = _fake_jwt(int(time.time()) + 30 * 86400)
    monkeypatch.setenv("EARTHDATA_TOKEN", tok)
    s = data.token_status()
    assert s["configured"] and not s["expired"] and s["days_left"] in (29, 30)
    assert tok not in str(s)
    assert data.have_credentials()

    # an expired token is refused with a clear message, before contacting NASA
    monkeypatch.setenv("EARTHDATA_TOKEN", _fake_jwt(int(time.time()) - 86400))
    assert not data.have_credentials()
    with pytest.raises(data.DataError, match="expired"):
        data._login(interactive=False)

    # token-only mode (the API's default) ignores username/password and _netrc
    monkeypatch.delenv("EARTHDATA_TOKEN")
    monkeypatch.setenv("EARTHDATA_USERNAME", "someone")
    monkeypatch.setenv("EARTHDATA_PASSWORD", "secret")
    monkeypatch.setenv("EARTHDATA_ALLOW_PASSWORD", "0")
    (tmp_path / "_netrc").write_text("machine urs.earthdata.nasa.gov login x password y")
    assert not data.have_credentials()
    with pytest.raises(data.DataError, match="EARTHDATA_TOKEN"):
        data._login(interactive=True)
    monkeypatch.setenv("EARTHDATA_ALLOW_PASSWORD", "1")
    assert data.have_credentials()
