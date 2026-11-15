"""Polygon + variable -> time series, trend statistics, CSV/JSON/PNG outputs."""
from __future__ import annotations

import json
import threading
from pathlib import Path

import numpy as np
import pandas as pd

from . import cache, catalog, cloud, data, local, region, stats, trendmap


def default_range(var: catalog.Variable) -> tuple[str, str]:
    """2001 (or the dataset's first month) through December of last year."""
    start = max(var.first_month, "2001-01")
    end = f"{pd.Timestamp.now().year - 1}-12"
    if var.last_month and var.last_month < end:
        end = var.last_month  # discontinued record
    return start, end


MAX_COMPARE_REGIONS = 5


def plan(var_key: str, polygon, start: str | None = None, end: str | None = None,
         source: str = "auto") -> dict:
    """Where an analysis would read its data from (cache, local or cloud), without reading it."""
    var = catalog.get(var_key)
    geom = region.load_polygon(polygon)
    d0, d1 = default_range(var)
    start, end = start or d0, end or d1
    months = len(var.available_months(start, end))
    if months == 0:
        span = f"{var.first_month} to {var.last_month or 'today'}"
        raise ValueError(f"{var.name} only has data from {span}; choose dates in that range.")
    base = {"start": start, "end": end, "months": months}
    if source != "cloud" and cache.RESULTS.contains(cache.key(var.key, geom, start, end)):
        return {"source": "cache", "description": "already analyzed recently", **base, "estimated_seconds": 0}
    found = local.find(var, geom, start, end) if source != "cloud" else None
    if found:
        return {"source": "local", "description": found[1], **base, "estimated_seconds": 1}
    if source == "local":
        raise data.DataError(f"No local {var.name.lower()} data covers this region and period.")
    return {"source": "cloud", "description": "streamed from NASA Earthdata Cloud", **base,
            "estimated_seconds": round(3 + months * var.cloud_seconds_per_month)}


def analyze(var_key: str, polygon, da=None, start: str | None = None, end: str | None = None,
            source: str = "auto", progress: data.Progress | None = None) -> dict:
    """Core function the web API calls. `polygon` is GeoJSON (path, str, or dict).

    Order of preference (source="auto"):
      1. a cached result for the same variable, shape and period (instant)
      2. local storage that covers the region and every requested month
      3. streaming from NASA's cloud (not stored; the result is cached)
    source="local" never uses the network (cached or stored data only);
    source="cloud" always streams fresh data.
    Pass `da` to analyze an in-memory cube directly (tests; not cached)."""
    var = catalog.get(var_key)
    geom = region.load_polygon(polygon)
    cache_key = None
    if da is not None:
        if start or end:
            da = da.sel(time=slice(start, end))
        origin = {"type": "provided", "description": "data passed in directly"}
    else:
        d0, d1 = default_range(var)
        start, end = start or d0, end or d1
        cache_key = cache.key(var.key, geom, start, end)
        if source != "cloud":
            hit = cache.RESULTS.get(cache_key)
            if hit is not None:
                return hit
        found = local.find(var, geom, start, end) if source in ("auto", "local") else None
        if found:
            da = found[0].sel(time=slice(start, end))
            origin = {"type": "local", "description": found[1]}
        elif source == "local":
            raise data.DataError(f"No local {var.name.lower()} data covers this region and period.")
        else:
            da = cloud.open_region(var, geom, start, end, progress=progress)
            origin = {"type": "cloud", "description": "streamed from NASA Earthdata Cloud"}
    series, info = region.polygon_mean(da, geom)
    if series.empty:
        raise ValueError(f"No {var.name.lower()} data inside this region "
                         "(land-only variables like soil moisture have no data over the ocean).")
    anomalies, _ = stats.deseasonalize(series)
    result = stats.trend_stats(series, units=var.units, percent=var.percent_meaningful)
    try:
        tmap = trendmap.trend_map(da, geom, units=var.units)
    except Exception as e:  # the map is extra; never let it sink the main analysis
        tmap = {"error": f"Couldn't build the trend map: {e}"}
    out = {
        "variable": {"key": var.key, "name": var.name, "units": var.units,
                     "definition": var.definition, "source": f"{var.collection} v{var.version}",
                     "global_note": var.global_note},
        "region": info,
        "data_source": {**origin, "cached": False},
        "stats": result,
        "series": [
            {"date": d.strftime("%Y-%m"), "value": float(v), "anomaly": float(a)}
            for d, v, a in zip(series.index, series.to_numpy(), anomalies.to_numpy())
        ],
        "trend_map": tmap,
    }
    if cache_key:
        cache.RESULTS.put(cache_key, out)
    return out


def run_together(tasks: list, sizes: list[int], progress: data.Progress | None = None) -> list:
    """Run tasks (each `fn(progress) -> value`) at the same time and return their outcomes in
    the original order: the value, or the DataError/ValueError it raised.

    `sizes` is how many NASA months each task streams (0 = local or cached); progress is
    reported as the combined total. NASA requests from all tasks share cloud's process-wide
    limit, so running them together doesn't multiply the load on NASA."""
    from concurrent.futures import ThreadPoolExecutor

    total = sum(sizes)
    done = [0] * len(tasks)
    lock = threading.Lock()

    def report(i: int, d: int) -> None:
        if progress and total:
            with lock:
                done[i] = min(d, sizes[i]) if sizes[i] else 0
                progress(sum(done), total)

    def run(i: int):
        try:
            value = tasks[i](lambda d, n, i=i: report(i, d))
        except (data.DataError, ValueError) as e:
            value = e
        report(i, sizes[i])
        return value

    if progress and total:
        progress(0, total)
    with ThreadPoolExecutor(max(1, len(tasks)), thread_name_prefix="together") as pool:
        return list(pool.map(run, range(len(tasks))))


def compare(var_key: str, regions: list[dict], start: str | None = None, end: str | None = None,
            source: str = "auto", progress: data.Progress | None = None) -> dict:
    """Analyze one variable over 2-5 regions for the same period.

    `regions` is a list of {"name": str, "region": GeoJSON}. Regions are analyzed at the
    same time (sharing one limit on requests to NASA), and progress is reported across all
    of them. A region that fails (e.g. ocean for a land-only variable) gets an `error`
    entry instead of stopping the comparison."""
    var = catalog.get(var_key)
    if not 2 <= len(regions) <= MAX_COMPARE_REGIONS:
        raise ValueError(f"Compare needs 2 to {MAX_COMPARE_REGIONS} regions, got {len(regions)}.")
    d0, d1 = default_range(var)
    start, end = start or d0, end or d1

    plans = [plan(var.key, r["region"], start, end, source=source) for r in regions]
    sizes = [p["months"] if p["source"] == "cloud" else 0 for p in plans]
    tasks = [lambda prog, r=r: analyze(var.key, r["region"], start=start, end=end,
                                       source=source, progress=prog)
             for r in regions]
    items = []
    for r, res in zip(regions, run_together(tasks, sizes, progress)):
        if isinstance(res, Exception):
            items.append({"name": r["name"], "error": str(res)})
        else:
            res.pop("variable", None)
            items.append({"name": r["name"], **res})

    ok = [i for i in items if "error" not in i]
    if not ok:
        raise ValueError("None of the regions could be analyzed: " + "; ".join(i["error"] for i in items))
    fastest = max(ok, key=lambda i: abs(i["stats"]["linear"]["slope_per_decade"]))
    # Testing several regions at p < 0.05 makes a lucky "significant" more likely
    # (5 regions: ~23%), so also report which survive a false-discovery-rate correction.
    from .trendmap import benjamini_hochberg
    survives = benjamini_hochberg(np.array([max(i["stats"]["linear"]["p_value"],
                                                i["stats"]["mann_kendall"]["p_value"]) for i in ok]))
    for i, keep in zip(ok, survives):
        i["stats"]["significant_after_correction"] = bool(keep) and i["stats"]["significant"]
    return {
        "variable": {"key": var.key, "name": var.name, "units": var.units,
                     "definition": var.definition, "source": f"{var.collection} v{var.version}",
                     "global_note": var.global_note},
        "start": start,
        "end": end,
        "regions": items,
        "summary": {
            "analyzed": len(ok),
            "significant": [i["name"] for i in ok if i["stats"]["significant"]],
            "significant_after_correction": [i["name"] for i in ok
                                             if i["stats"]["significant_after_correction"]],
            "fastest_change": {"name": fastest["name"],
                               "slope_per_decade": fastest["stats"]["linear"]["slope_per_decade"]},
        },
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
