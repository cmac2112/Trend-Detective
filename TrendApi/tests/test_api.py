"""API tests using a synthetic cube with a known trend (no downloads needed)."""
import numpy as np
import pandas as pd
import pytest
import xarray as xr
from fastapi.testclient import TestClient

from app import main
from earthtrends import analyze as analyze_mod

POLY = {"type": "Polygon", "coordinates": [[[-115, 35], [-113, 35], [-113, 37], [-115, 37], [-115, 35]]]}


def synthetic_cube(trend_per_year=0.05):
    rng = np.random.default_rng(0)
    time = pd.date_range("2001-01-01", periods=24 * 12, freq="MS")
    lat = np.arange(-89.75, 90, 0.5)
    lon = np.arange(-179.75, 180, 0.5)
    t = np.arange(len(time)) / 12
    sig = 15 + trend_per_year * t + 8 * np.sin(2 * np.pi * time.month.to_numpy() / 12)
    vals = sig[:, None, None] + rng.normal(0, 0.3, (len(time), lat.size, lon.size))
    vals[:, lat > 60, :] = np.nan  # "no data" zone for testing
    return xr.DataArray(vals.astype("f4"), coords={"time": time, "lat": lat, "lon": lon},
                        dims=("time", "lat", "lon"), name="t2m")


@pytest.fixture
def client(monkeypatch, tmp_path):
    cube = synthetic_cube()
    monkeypatch.setattr(analyze_mod.data, "open_cube", lambda var: cube)
    # pretend t2m is downloaded, nothing else
    fake = tmp_path / "t2m.zarr"
    cube.to_dataset().to_zarr(fake, consolidated=False)
    monkeypatch.setattr(main.data, "cube_path",
                        lambda var: fake if var.key == "t2m" else tmp_path / "missing.zarr")
    return TestClient(main.app)


def test_variables(client):
    r = client.get("/variables")
    assert r.status_code == 200
    by_key = {v["key"]: v for v in r.json()}
    assert by_key["t2m"]["available"] and by_key["t2m"]["start"] == "2001-01"
    assert not by_key["precip"]["available"]


def test_analyze_significant(client):
    r = client.post("/analyze", json={"variable": "t2m", "region": POLY})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["stats"]["significant"]
    assert body["stats"]["linear"]["slope_per_decade"] == pytest.approx(0.5, abs=0.05)
    assert len(body["series"]) == 288


def test_analyze_date_range_and_no_series(client):
    r = client.post("/analyze", json={"variable": "t2m", "region": POLY,
                                      "start": "2010-01", "end": "2019-12", "include_series": False})
    assert r.status_code == 200
    body = r.json()
    assert body["stats"]["n_months"] == 120 and "series" not in body


def test_errors(client):
    assert client.post("/analyze", json={"variable": "nope", "region": POLY}).status_code == 404
    assert client.post("/analyze", json={"variable": "precip", "region": POLY}).status_code == 409
    assert client.post("/analyze", json={"variable": "t2m", "region": {"type": "Point", "coordinates": [0, 0]}}).status_code == 422
    assert client.post("/analyze", json={"variable": "t2m", "region": POLY, "start": "2024-13"}).status_code == 422
    arctic = {"type": "Polygon", "coordinates": [[[0, 70], [10, 70], [10, 80], [0, 80], [0, 70]]]}
    r = client.post("/analyze", json={"variable": "t2m", "region": arctic})
    assert r.status_code == 422 and "No" in r.json()["detail"]


def test_examples(client):
    assert "barents_sea" in client.get("/examples").json()
    assert client.get("/examples/barents_sea").json()["type"] == "Feature"
    assert client.get("/examples/..%2Fsecret").status_code == 404
