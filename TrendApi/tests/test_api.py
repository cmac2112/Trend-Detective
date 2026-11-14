"""API tests with synthetic data: a local tile for one region, and a fake NASA cloud
reader everywhere else. No network access needed."""
import time

import numpy as np
import pandas as pd
import pytest
import xarray as xr
from fastapi.testclient import TestClient

from app import main
from earthtrends import catalog, cloud, data, local

POLY = {"type": "Polygon", "coordinates": [[[-115, 35], [-113, 35], [-113, 37], [-115, 37], [-115, 35]]]}
FAR = {"type": "Polygon", "coordinates": [[[10, 50], [12, 50], [12, 52], [10, 52], [10, 50]]]}


def synthetic_cube(trend_per_year=0.05):
    rng = np.random.default_rng(0)
    time_ = pd.date_range("2001-01-01", periods=24 * 12, freq="MS")
    lat = np.arange(-89.75, 90, 0.5)
    lon = np.arange(-179.75, 180, 0.5)
    t = np.arange(len(time_)) / 12
    sig = 15 + trend_per_year * t + 8 * np.sin(2 * np.pi * time_.month.to_numpy() / 12)
    vals = sig[:, None, None] + rng.normal(0, 0.3, (len(time_), lat.size, lon.size))
    vals[:, lat > 60, :] = np.nan  # "no data" zone, like ocean for a land-only variable
    return xr.DataArray(vals.astype("f4"), coords={"time": time_, "lat": lat, "lon": lon},
                        dims=("time", "lat", "lon"), name="t2m")


@pytest.fixture
def client(monkeypatch, tmp_path):
    cube = synthetic_cube()
    monkeypatch.setattr(data, "DATA_DIR", tmp_path)
    monkeypatch.setattr(data, "CUBE_DIR", tmp_path / "cubes")
    monkeypatch.setattr(data, "have_credentials", lambda: True)
    # local copy of the POLY area only
    local.save_tile(cube.sel(lat=slice(34, 38), lon=slice(-116, -112)), catalog.get("t2m"), "test_region")

    calls = []

    def fake_cloud(var, geom, start, end, progress=None):
        calls.append((var.key, start, end))
        sel = cube.sel(time=slice(start, end))
        for i in range(1, 4):
            if progress:
                progress(i, 3)
        return sel.rename(var.key)

    monkeypatch.setattr(cloud, "open_region", fake_cloud)
    c = TestClient(main.app)
    c.cloud_calls = calls
    return c


def test_variables_show_local_examples(client):
    by_key = {v["key"]: v for v in client.get("/variables").json()}
    assert by_key["t2m"]["local_examples"] == ["test_region"]
    assert by_key["precip"]["local_examples"] == [] and by_key["precip"]["local_global"] is None


def test_plan_local_vs_cloud(client):
    p = client.post("/plan", json={"variable": "t2m", "region": POLY, "start": "2001-01", "end": "2024-12"}).json()
    assert p["source"] == "local"
    p = client.post("/plan", json={"variable": "t2m", "region": FAR, "start": "2001-01", "end": "2024-12"}).json()
    assert p["source"] == "cloud" and p["estimated_seconds"] > 10 and p["months"] == 288


def test_analyze_local_is_significant_and_makes_no_cloud_calls(client):
    r = client.post("/analyze", json={"variable": "t2m", "region": POLY, "start": "2001-01", "end": "2024-12"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["data_source"]["type"] == "local"
    assert body["stats"]["significant"]
    assert body["stats"]["linear"]["slope_per_decade"] == pytest.approx(0.5, abs=0.05)
    assert client.cloud_calls == []


def test_analyze_cloud_sync(client):
    r = client.post("/analyze", json={"variable": "t2m", "region": FAR, "start": "2010-01",
                                      "end": "2019-12", "include_series": False})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["data_source"]["type"] == "cloud" and body["stats"]["n_months"] == 120
    assert "series" not in body and client.cloud_calls == [("t2m", "2010-01", "2019-12")]


def test_analyze_job_reports_progress_and_result(client):
    r = client.post("/analyze/jobs", json={"variable": "t2m", "region": FAR, "start": "2001-01", "end": "2024-12"})
    assert r.status_code == 202 and r.json()["plan"]["source"] == "cloud"
    job_id = r.json()["job"]["id"]
    for _ in range(100):
        job = client.get(f"/jobs/{job_id}").json()
        if job["status"] in ("done", "error"):
            break
        time.sleep(0.05)
    assert job["status"] == "done", job
    assert job["progress"] == 1 and job["result"]["stats"]["significant"]
    assert client.get("/jobs/nope").status_code == 404


def test_job_error_is_reported(client):
    arctic = {"type": "Polygon", "coordinates": [[[0, 70], [10, 70], [10, 80], [0, 80], [0, 70]]]}
    job_id = client.post("/analyze/jobs", json={"variable": "t2m", "region": arctic}).json()["job"]["id"]
    for _ in range(100):
        job = client.get(f"/jobs/{job_id}").json()
        if job["status"] in ("done", "error"):
            break
        time.sleep(0.05)
    assert job["status"] == "error" and "No" in job["error"]


def test_errors(client, monkeypatch):
    post = lambda body: client.post("/analyze", json=body)
    assert post({"variable": "nope", "region": POLY}).status_code == 404
    assert post({"variable": "t2m", "region": {"type": "Point", "coordinates": [0, 0]}}).status_code == 422
    assert post({"variable": "t2m", "region": POLY, "start": "2024-13"}).status_code == 422
    assert post({"variable": "t2m", "region": POLY, "start": "2020-01", "end": "2019-01"}).status_code == 422
    assert post({"variable": "t2m", "region": FAR, "source": "local"}).status_code == 409
    monkeypatch.setattr(data, "have_credentials", lambda: False)
    assert post({"variable": "t2m", "region": FAR}).status_code == 503
    # local data still works without credentials
    assert post({"variable": "t2m", "region": POLY, "start": "2001-01", "end": "2024-12"}).status_code == 200


def test_examples(client):
    assert "barents_sea" in client.get("/examples").json()
    assert client.get("/examples/barents_sea").json()["type"] == "Feature"
    assert client.get("/examples/..%2Fsecret").status_code == 404


def test_cors(client):
    ok = client.options("/variables", headers={"Origin": "http://localhost:5173", "Access-Control-Request-Method": "GET"})
    assert ok.headers.get("access-control-allow-origin") == "http://localhost:5173"
    bad = client.get("/variables", headers={"Origin": "https://evil.example"})
    assert "access-control-allow-origin" not in bad.headers


def _wait(client, job_id):
    for _ in range(200):
        job = client.get(f"/jobs/{job_id}").json()
        if job["status"] in ("done", "error"):
            return job
        time.sleep(0.05)
    raise AssertionError("job did not finish")


def test_cache_second_request_skips_nasa(client):
    body = {"variable": "t2m", "region": FAR, "start": "2001-01", "end": "2024-12"}
    first = client.post("/analyze", json=body).json()
    assert first["data_source"]["cached"] is False
    assert client.post("/plan", json=body).json()["source"] == "cache"
    second = client.post("/analyze", json=body).json()
    assert second["data_source"]["cached"] is True and len(client.cloud_calls) == 1
    assert second["stats"] == first["stats"]
    health = client.get("/health").json()["cache"]
    assert health["entries"] == 1 and health["hits"] >= 1
    assert client.post("/cache/clear").json()["entries"] == 0
    assert client.post("/plan", json=body).json()["source"] == "cloud"


def test_compare_job(client):
    body = {"variable": "t2m", "start": "2001-01", "end": "2024-12", "regions": [
        {"name": "Desert", "region": POLY},       # local tile
        {"name": "Europe", "region": FAR},        # cloud
    ]}
    plan = client.post("/compare/plan", json=body).json()
    assert [p["source"] for p in plan["regions"]] == ["local", "cloud"] and plan["source"] == "cloud"
    r = client.post("/compare/jobs", json=body)
    assert r.status_code == 202
    job = _wait(client, r.json()["job"]["id"])
    assert job["status"] == "done", job
    res = job["result"]
    assert [x["name"] for x in res["regions"]] == ["Desert", "Europe"]
    assert [x["data_source"]["type"] for x in res["regions"]] == ["local", "cloud"]
    assert len(res["regions"][0]["series"]) == 288
    assert set(res["summary"]["significant"]) == {"Desert", "Europe"}
    # everything is now cached or local -> the sync endpoint answers instantly
    again = client.post("/compare/plan", json=body).json()
    assert again["source"] == "local" and [p["source"] for p in again["regions"]] == ["cache", "cache"]
    sync = client.post("/compare", json={**body, "include_series": False}).json()
    assert "series" not in sync["regions"][0]


def test_compare_validation(client):
    one = {"variable": "t2m", "regions": [{"name": "A", "region": POLY}]}
    assert client.post("/compare", json=one).status_code == 422
    six = {"variable": "t2m", "regions": [{"name": str(i), "region": POLY} for i in range(6)]}
    assert client.post("/compare", json=six).status_code == 422
    dup = {"variable": "t2m", "regions": [{"name": "A", "region": POLY}, {"name": "A", "region": FAR}]}
    assert client.post("/compare", json=dup).status_code == 422
    bad = {"variable": "t2m", "regions": [{"name": "A", "region": POLY}, {"name": "B", "region": {"type": "Point", "coordinates": [0, 0]}}]}
    assert client.post("/compare", json=bad).status_code == 422


def test_drivers_sync_without_ai(client, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    body = {"variable": "t2m", "region": FAR, "start": "2001-01", "end": "2024-12", "region_name": "Europe"}
    r = client.post("/drivers", json=body)
    assert r.status_code == 200, r.text
    res = r.json()
    assert [d["key"] for d in res["drivers"]] and {d["key"] for d in res["drivers"]} <= {"precip", "soil_moisture", "evapotranspiration", "ndvi"}
    assert res["explanation"]["available"] is False and "ANTHROPIC_API_KEY" in res["explanation"]["reason"]
    assert client.get("/health").json()["ai_enabled"] is False


def test_drivers_job(client, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    r = client.post("/drivers/jobs", json={"variable": "t2m", "region": POLY, "start": "2001-01",
                                           "end": "2024-12", "explain": False})
    assert r.status_code == 202
    job = _wait(client, r.json()["job"]["id"])
    assert job["status"] == "done", job
    assert job["result"]["explanation"]["reason"] == "Not requested."
    assert job["result"]["models"]["regression"]["r_squared"] is not None
