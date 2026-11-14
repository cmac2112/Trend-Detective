"""Cause analysis and AI explanation, without NASA or a real Anthropic API key."""
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import numpy as np
import pandas as pd
import pytest
import xarray as xr

from earthtrends import cloud, data, drivers, narrative

POLY = {"type": "Polygon", "coordinates": [[[-115, 35], [-113, 35], [-113, 37], [-115, 37], [-115, 35]]]}


def _cube(values: np.ndarray, name: str) -> xr.DataArray:
    time_ = pd.date_range("2001-01-01", periods=len(values), freq="MS")
    lat = np.arange(30.25, 40, 0.5)
    lon = np.arange(-119.75, -110, 0.5)
    grid = values[:, None, None] + np.zeros((len(values), lat.size, lon.size))
    return xr.DataArray(grid.astype("f4"), coords={"time": time_, "lat": lat, "lon": lon},
                        dims=("time", "lat", "lon"), name=name)


@pytest.fixture
def world(tmp_path, monkeypatch):
    """Synthetic region where soil moisture really drives temperature:
    soil dries over time, temperature = -0.5 * soil anomaly + noise; precip and
    evapotranspiration and NDVI are unrelated noise."""
    monkeypatch.setattr(data, "DATA_DIR", tmp_path)
    monkeypatch.setattr(data, "CUBE_DIR", tmp_path / "cubes")
    rng = np.random.default_rng(42)
    n = 288
    t = np.arange(n) / 12
    season = np.sin(2 * np.pi * np.arange(n) / 12)
    soil = 30 - 0.15 * t + 3 * season + rng.normal(0, 1.0, n)
    soil_anom = soil - (30 + 3 * season)
    series = {
        "soil_moisture": soil,
        "t2m": 20 + 8 * season - 0.5 * soil_anom + rng.normal(0, 0.4, n),
        "precip": 2 + season + rng.normal(0, 0.5, n),
        "evapotranspiration": 1.5 + 0.5 * season + rng.normal(0, 0.3, n),
        "ndvi": 0.6 + 0.1 * season + rng.normal(0, 0.03, n),
    }
    cubes = {k: _cube(v, k) for k, v in series.items()}
    monkeypatch.setattr(cloud, "open_region", lambda var, geom, s, e, progress=None: cubes[var.key].sel(time=slice(s, e)))


def test_driver_analysis_finds_the_real_driver(world):
    res = drivers.analyze_drivers("t2m", POLY, "2001-01", "2024-12")
    assert res["target"]["stats"]["significant"]
    top = res["drivers"][0]
    assert top["key"] == "soil_moisture" and top["evidence"] == "strong"
    assert top["correlation"]["r"] < -0.5 and top["correlation"]["lag_months"] == 0
    assert 0.6 < top["regression"]["share_of_target_trend"] < 1.4  # most of the warming
    assert top["physical_link"]["likely_direction"] == "both"
    others = {d["key"]: d for d in res["drivers"][1:]}
    assert all(d["evidence"] == "weak" for d in others.values())
    assert res["models"]["regression"]["r_squared"] > 0.4
    assert res["models"]["random_forest"]["available"]
    assert any("not proof" in c for c in res["caveats"])
    ctx = res["region_context"]
    assert ctx["latitude_zone"] == "mid-latitude" and ctx["area_km2"] > 0


def test_explain_without_key_is_graceful(monkeypatch, world):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    out = narrative.explain(drivers.analyze_drivers("t2m", POLY, "2001-01", "2024-12"))
    assert out["available"] is False and "ANTHROPIC_API_KEY" in out["reason"]


class _FakeAnthropic(BaseHTTPRequestHandler):
    requests: list = []
    reply: dict = {}

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["content-length"])))
        type(self).requests.append({"path": self.path, "headers": dict(self.headers), "body": body})
        payload = json.dumps({
            "id": "msg_test", "type": "message", "role": "assistant", "model": body["model"],
            "content": [{"type": "text", "text": json.dumps(type(self).reply)}],
            "stop_reason": "end_turn", "stop_sequence": None,
            "usage": {"input_tokens": 10, "output_tokens": 10},
        }).encode()
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *args):
        pass


def test_explain_request_and_parsing(monkeypatch, world):
    _FakeAnthropic.requests = []
    _FakeAnthropic.reply = {
        "headline": "The region is warming mostly because its soil is drying.",
        "summary": "Temperature rose about 0.6 °C per decade while soil dried.",
        "likely_causes": [{"cause": "Drying soil", "shown_by_data": True,
                           "explanation": "r = -0.9", "confidence": "strong"}],
        "other_possible_factors": ["Irrigation changes"],
        "caveats": ["Correlation is not proof."],
        "investigate_next": ["Compare with a nearby region."],
    }
    server = HTTPServer(("127.0.0.1", 0), _FakeAnthropic)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setenv("ANTHROPIC_BASE_URL", f"http://127.0.0.1:{server.server_port}")
    try:
        attribution = drivers.analyze_drivers("t2m", POLY, "2001-01", "2024-12")
        out = narrative.explain(attribution, region_name="Test Desert")
        again = narrative.explain(attribution, region_name="Test Desert")
    finally:
        server.shutdown()

    assert out["available"] and out["cached"] is False and again["cached"] is True
    assert out["likely_causes"][0]["cause"] == "Drying soil"
    assert len(_FakeAnthropic.requests) == 1  # second call came from the cache
    req = _FakeAnthropic.requests[0]
    body = req["body"]
    assert body["model"] == "claude-haiku-5-5"
    assert body["output_config"]["effort"] == "medium"
    assert body["output_config"]["format"]["type"] == "json_schema"
    assert "fallbacks" not in body  # Haiku has no server-side refusal fallback
    sent = body["messages"][0]["content"]
    assert "Test Desert" in sent and "soil" in sent.lower()
