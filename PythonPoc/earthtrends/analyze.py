"""Polygon + variable -> time series, trend statistics, CSV/JSON/PNG outputs."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from . import catalog, data, region, stats


def analyze(var_key: str, polygon, da=None) -> dict:
    """Core function the web API will call. `polygon` is GeoJSON (path, str, or dict)."""
    var = catalog.get(var_key)
    geom = region.load_polygon(polygon)
    if da is None:
        da = data.open_cube(var)
    series, info = region.polygon_mean(da, geom)
    anomalies, _ = stats.deseasonalize(series)
    result = stats.trend_stats(series, units=var.units)
    return {
        "variable": {"key": var.key, "name": var.name, "units": var.units,
                     "definition": var.definition, "source": f"{var.collection} v{var.version}"},
        "region": info,
        "stats": result,
        "series": [
            {"date": d.strftime("%Y-%m"), "value": float(v), "anomaly": float(a)}
            for d, v, a in zip(series.index, series.to_numpy(), anomalies.to_numpy())
        ],
    }


def save_outputs(res: dict, out_dir: Path, stem: str, show: bool = False) -> list[Path]:
    """Write CSV, JSON and PNG. With show=True the figure stays open; call
    show_figures() afterwards to display every open chart."""
    out_dir.mkdir(parents=True, exist_ok=True)
    df = pd.DataFrame(res["series"])
    csv_path = out_dir / f"{stem}.csv"
    df.to_csv(csv_path, index=False)
    json_path = out_dir / f"{stem}.json"
    json_path.write_text(json.dumps(res, indent=2))
    png_path = out_dir / f"{stem}.png"
    fig = make_figure(res)
    fig.savefig(png_path, dpi=130)
    if not show:
        import matplotlib.pyplot as plt
        plt.close(fig)
    return [csv_path, json_path, png_path]


def show_figures() -> None:
    """Open an interactive window for every figure (zoom/pan with the toolbar)."""
    import matplotlib.pyplot as plt
    plt.show()


def trend_level(s: dict) -> str:
    """'significant', 'possible' (tests disagree) or 'none'."""
    t_sig = s["linear"]["p_value"] < stats.ALPHA
    mk_sig = s["mann_kendall"]["p_value"] < stats.ALPHA
    return "significant" if t_sig and mk_sig else "possible" if t_sig or mk_sig else "none"


def make_figure(res: dict):
    import matplotlib.pyplot as plt

    df = pd.DataFrame(res["series"])
    df["date"] = pd.to_datetime(df["date"])
    v, s = res["variable"], res["stats"]
    lin = s["linear"]
    t = stats.decimal_years(pd.DatetimeIndex(df["date"]))
    trend_anom = lin["intercept"] + lin["slope_per_year"] * t
    trend_raw = s["mean"] + trend_anom - trend_anom.mean()  # same slope, drawn through the raw data
    level = trend_level(s)

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(10, 6.5), sharex=True)
    fig.canvas.manager.set_window_title(f"{v['name']} trend") if fig.canvas.manager else None

    ax1.plot(df["date"], df["value"], lw=0.8, color="#7a8ca3", label="Monthly value")
    ax1.plot(df["date"], df["value"].rolling(12, center=True).mean(), lw=2,
             color="#1f4e79", label="12-month average")
    ax1.set_ylabel(v["units"])
    ax1.set_title(f"{v['name']}: raw monthly data")

    ax2.axhline(0, color="#cccccc", lw=1)
    ax2.plot(df["date"], df["anomaly"], lw=0.8, color="#7a8ca3", label="Anomaly (seasonal cycle removed)")
    ax2.set_ylabel(f"Anomaly ({v['units']})")
    ax2.set_title("After removing the seasonal cycle")

    # Trend line only when a trend shows up: solid red if significant, dashed orange if borderline.
    if level != "none":
        style = {"significant": dict(color="#c0392b", ls="-"), "possible": dict(color="#e67e22", ls="--")}[level]
        label = (f"Trend line {lin['slope_per_decade']:+.3g} {v['units']}/decade "
                 f"(p = {lin['p_value']:.3f}, {'significant' if level == 'significant' else 'borderline'})")
        ax1.plot(df["date"], trend_raw, lw=2.5, **style, label="Trend line")
        ax2.plot(df["date"], trend_anom, lw=2.5, **style, label=label)
    else:
        ax2.text(0.99, 0.95, f"No significant trend (p = {lin['p_value']:.2f})", transform=ax2.transAxes,
                 ha="right", va="top", fontsize=9, color="#555555")

    ax1.legend(loc="upper left", frameon=False)
    ax2.legend(loc="upper left", frameon=False)
    fig.text(0.01, 0.005, s["verdict"], fontsize=8, wrap=True, va="bottom")
    fig.tight_layout(rect=(0, 0.06, 1, 1))
    return fig


def print_summary(res: dict) -> None:
    s, v, r = res["stats"], res["variable"], res["region"]
    lin, mkr = s["linear"], s["mann_kendall"]
    u = v["units"]
    print(f"\n{v['name']} ({v['source']})")
    print(f"  Region: {r['grid_cells']} grid cells, bounds {r['bounds']}")
    print(f"  Period: {s['start']} to {s['end']} ({s['n_months']} months), mean {s['mean']:.3g} {u}")
    print(f"  Linear trend:   {lin['slope_per_decade']:+.4g} {u}/decade  "
          f"95% CI [{lin['ci95_per_decade'][0]:+.4g}, {lin['ci95_per_decade'][1]:+.4g}]")
    print(f"  t-test p-value: {lin['p_value']:.4f} (autocorrelation-adjusted; naive {lin['p_value_naive']:.4f})")
    print(f"  Mann-Kendall:   {mkr['trend']}, p = {mkr['p_value']:.4f}, "
          f"Sen's slope {mkr['sen_slope_per_decade']:+.4g} {u}/decade")
    print(f"\n  {s['verdict']}\n")
