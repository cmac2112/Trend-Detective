"""Which variables are changing here? Run every catalog variable over one region and rank them.

The challenge's first hurdle is choosing a variable. A scan answers "what is changing in
this place?" before the user has to guess:

  * each variable is analyzed over the same region (cache, local data or NASA cloud, same
    as any analysis); the full results land in the result cache, so opening one afterwards
    is instant
  * the requested period is clipped to each dataset's record (OCO-2 starts in 2014, AIRS
    ends in 2016, ...), and the period actually used is reported per variable
  * variables are ranked by how significant the trend is, then by its size relative to
    the variable's own year-to-year variability (so a 0.3 K warming and a 2 mm drop in
    rainfall can be compared, which raw units can't)
  * testing 15 variables at p < 0.05 would turn up a "significant" one by luck fairly
    often, so each item also says whether it survives a false-discovery-rate correction
    across the scan (Benjamini-Hochberg)
"""
from __future__ import annotations

import numpy as np

from . import catalog, data, stats
from .analyze import analyze, default_range, plan, run_together
from .trendmap import benjamini_hochberg

LEVEL_ORDER = {"significant": 0, "possible": 1, "none": 2}


def _level(s: dict) -> str:
    t = s["linear"]["p_value"] < stats.ALPHA
    mk = s["mann_kendall"]["p_value"] < stats.ALPHA
    return "significant" if t and mk else "possible" if t or mk else "none"


def _period(var: catalog.Variable, start: str | None, end: str | None) -> tuple[str, str] | None:
    """The requested period clipped to the dataset's record, or None if under 24 months."""
    d0, d1 = default_range(var)
    s = max(start or d0, var.first_month)
    e = min(end or d1, var.last_month or end or d1)
    if s > e or len(var.available_months(s, e)) < 24:
        return None
    return s, e


def scan_plan(polygon, start: str | None = None, end: str | None = None, source: str = "auto") -> dict:
    """Where each variable's data would come from, and the total estimated time."""
    items, skipped = [], {}
    for var in catalog.VARIABLES.values():
        period = _period(var, start, end)
        if period is None:
            skipped[var.key] = f"{var.name} has under 2 years of data in this period."
            continue
        try:
            items.append({"key": var.key, **plan(var.key, polygon, *period, source=source)})
        except (data.DataError, ValueError) as e:
            skipped[var.key] = str(e)
    cloud = [i for i in items if i["source"] == "cloud"]
    return {
        "source": "cloud" if cloud else "local",
        # streams share one limit on requests to NASA, so the times add up rather than overlap
        "estimated_seconds": sum(i["estimated_seconds"] for i in items),
        "variables": items,
        "skipped": skipped,
    }


def scan(polygon, start: str | None = None, end: str | None = None, source: str = "auto",
         progress: data.Progress | None = None) -> dict:
    p = scan_plan(polygon, start, end, source=source)
    todo = p["variables"]
    sizes = [i["months"] if i["source"] == "cloud" else 0 for i in todo]
    tasks = [lambda prog, i=i: analyze(i["key"], polygon, start=i["start"], end=i["end"],
                                       source=source, progress=prog)
             for i in todo]
    results = run_together(tasks, sizes, progress)

    items, skipped = [], dict(p["skipped"])
    for plan_item, res in zip(todo, results):
        var = catalog.get(plan_item["key"])
        if isinstance(res, Exception):
            skipped[var.key] = str(res)
            continue
        s = res["stats"]
        anomalies = np.array([pt["anomaly"] for pt in res["series"]], dtype=float)
        sd = float(np.std(anomalies, ddof=1)) if anomalies.size > 1 else 0.0
        slope = s["linear"]["slope_per_decade"]
        if not (sd > 0 and np.isfinite(s["linear"]["p_value"])):
            skipped[var.key] = (f"{var.name} doesn't change at all here (e.g. no snow in the tropics), "
                                "so there's no trend to test.")
            continue
        tmap = res.get("trend_map", {}).get("summary", {})
        items.append({
            "key": var.key,
            "name": var.name,
            "category": var.category,
            "units": var.units,
            "definition": var.definition,
            "start": s["start"],
            "end": s["end"],
            "n_months": s["n_months"],
            "level": _level(s),
            "slope_per_decade": slope,
            "ci95_per_decade": s["linear"]["ci95_per_decade"],
            "percent_of_mean_per_decade": s["linear"]["percent_of_mean_per_decade"],
            # change per decade measured in "typical year-to-year wobbles"
            "change_in_sd_per_decade": slope / sd,
            "p_value": s["linear"]["p_value"],
            "mk_p_value": s["mann_kendall"]["p_value"],
            "mixed_inside_region": bool(tmap.get("mixed", False)),
            "global_note": var.global_note,
            "data_source": res["data_source"]["type"],
        })

    if items:
        passes = benjamini_hochberg(np.array([max(i["p_value"], i["mk_p_value"]) for i in items]))
        for i, ok in zip(items, passes):
            i["passes_fdr"] = bool(ok) and i["level"] == "significant"
    # Worldwide trends (CO2) go after the local ones of the same level: true everywhere, so
    # they say least about what makes this place different.
    items.sort(key=lambda i: (LEVEL_ORDER[i["level"]], bool(i["global_note"]),
                              -abs(i["change_in_sd_per_decade"] or 0)))
    for rank, i in enumerate(items, 1):
        i["rank"] = rank

    sig = [i for i in items if i["level"] == "significant"]
    return {
        "start": start,
        "end": end,
        "variables": items,
        "skipped": skipped,
        "summary": {
            "analyzed": len(items),
            "significant": len(sig),
            "passes_fdr": sum(i["passes_fdr"] for i in items),
            "strongest": sig[0]["key"] if sig else None,
            "description": _describe(items),
        },
    }


def _describe(items: list[dict]) -> str:
    if not items:
        return "None of the variables could be analyzed for this region and period."
    sig = [i for i in items if i["level"] == "significant"]
    local = [i for i in sig if not i["global_note"]]
    if not local and sig:
        return (f"Only worldwide trends show up here ({', '.join(i['name'] for i in sig)}): nothing "
                "local is changing significantly. Try a longer period or a larger region.")
    if not sig:
        return (f"None of the {len(items)} variables shows a significant trend here. "
                "Try a longer period, or a larger region to average out noise.")
    top = local[0]
    direction = "rising" if top["slope_per_decade"] > 0 else "falling"
    kept = sum(i["passes_fdr"] for i in items)
    return (f"{len(sig)} of {len(items)} variables show a significant trend; the strongest is "
            f"{top['name']}, {direction}. {kept} of them stay significant after allowing for "
            f"testing {len(items)} variables at once.")
