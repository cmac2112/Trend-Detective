"""Cause analysis: which related variables move with the target, and how much of its
trend could they account for?

For one region and period this:
  1. analyzes the target variable and each of its `related` variables (cache, local
     data or NASA cloud, same as any analysis)
  2. correlates the target's anomalies (seasonal cycle removed) with each driver's,
     at lags of 0-3 months (driver leading), with p-values adjusted for autocorrelation
  3. fits a multiple linear regression of the target on all drivers, and turns each
     coefficient into "how much of the target's trend this driver's own trend implies"
  4. trains a small random forest on the drivers (with lags) and measures each
     driver's permutation importance, plus time-ordered cross-validation so we can say
     honestly whether the model predicts anything at all
  5. ranks the drivers and labels the strength of evidence

This finds *associations*, not proof of cause. The output carries explicit caveats
and is the evidence an LLM explanation (narrative.py) is grounded in.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from scipy import stats as st

from . import catalog, data, region
from .analyze import analyze, default_range, plan, run_together

MAX_LAG = 3  # months a driver may lead the target

# Known physical links between the catalog variables, so a correlation can be read the
# right way round. direction: "driver->target", "target->driver" or "both".
MECHANISMS: dict[tuple[str, str], tuple[str, str]] = {
    ("t2m", "soil_moisture"): ("both", "Drier soil evaporates less water, so less of the sun's energy goes into "
                               "evaporation (which cools) and more into heating the air. Hotter air also dries soil."),
    ("t2m", "precip"): ("driver->target", "Less rain usually means fewer clouds and drier ground, both of which "
                        "let surface temperatures rise."),
    ("t2m", "evapotranspiration"): ("both", "Evaporation cools the surface, like sweat. Less of it means warmer "
                                    "air; warmer air can also raise evaporation if water is available."),
    ("precip", "t2m"): ("target->driver", "Rainfall changes more often drive regional temperature than the "
                        "reverse, though warming can shift rainfall patterns."),
    ("precip", "soil_moisture"): ("target->driver", "Rain is the main source of soil moisture, so soil moisture "
                                  "mostly follows rain. Drier soil can feed back to reduce local rain "
                                  "(land-atmosphere feedback), especially in forests like the Amazon."),
    ("precip", "evapotranspiration"): ("both", "In forests, evapotranspiration returns water to the air that "
                                       "falls again as rain (moisture recycling); less forest means less "
                                       "recycled rain."),
    ("soil_moisture", "precip"): ("driver->target", "Rain adds water to the soil."),
    ("soil_moisture", "t2m"): ("both", "Warmer air increases evaporation and dries soil; dry soil in turn heats "
                               "the air."),
    ("soil_moisture", "evapotranspiration"): ("both", "Evapotranspiration removes water from the soil, but wetter "
                                              "soil also has more water to evaporate, so they often rise together."),
    ("evapotranspiration", "precip"): ("driver->target", "Water must be available to evaporate; in dry places "
                                       "evapotranspiration follows rainfall."),
    ("evapotranspiration", "t2m"): ("driver->target", "Warmer temperatures increase the air's demand for water."),
    ("evapotranspiration", "soil_moisture"): ("driver->target", "Wetter soil supplies more water for evaporation "
                                              "and plants."),
    # runoff
    ("runoff", "precip"): ("driver->target", "Rain that the ground can't soak up runs off into streams; more "
                           "rain usually means more runoff."),
    ("runoff", "snow_water"): ("driver->target", "Melting snowpack feeds streams in spring and summer; less snow "
                               "means less meltwater runoff."),
    ("runoff", "soil_moisture"): ("both", "Wet soil can't absorb more water, so more rain runs off; runoff also "
                                  "follows the same rain that wets the soil."),
    ("runoff", "t2m"): ("driver->target", "Warmer air increases evaporation and melts snow earlier, which "
                        "usually reduces and shifts runoff."),
    # snow
    ("snow_water", "t2m"): ("driver->target", "Warmer temperatures mean more rain instead of snow and earlier "
                            "melting, shrinking the snowpack."),
    ("snow_water", "precip"): ("driver->target", "Snowpack is built from winter precipitation that falls as snow."),
    # root zone
    ("root_zone_moisture", "precip"): ("driver->target", "Rain slowly soaks down into the root zone; long dry "
                                       "spells drain it."),
    ("root_zone_moisture", "evapotranspiration"): ("both", "Plants pull water out of the root zone; but when the "
                                                   "root zone is wet there is more water for plants to use."),
    ("root_zone_moisture", "t2m"): ("driver->target", "Warmer air makes plants and soil lose water faster."),
    # land surface temperature
    ("land_surface_temp", "soil_moisture"): ("driver->target", "Dry ground can't cool itself by evaporation, so "
                                             "its surface heats up much more in the sun."),
    ("land_surface_temp", "evapotranspiration"): ("driver->target", "Evaporation and plant transpiration cool the "
                                                  "surface; less of it means a hotter surface."),
    ("land_surface_temp", "precip"): ("driver->target", "Rain and clouds cool the surface; drier, sunnier "
                                      "conditions heat it."),
    # humidity
    ("humidity", "t2m"): ("both", "Warmer air can hold more water vapor (about 7% more per °C), so humidity "
                          "often rises with temperature when water is available."),
    ("humidity", "evapotranspiration"): ("driver->target", "Evaporation from land and plants is a main source "
                                         "of water vapor in the air over land."),
    ("humidity", "precip"): ("both", "Moist air is needed for rain; wet ground after rain also adds moisture "
                             "back to the air."),
    # vegetation (MODIS NDVI)
    ("ndvi", "precip"): ("driver->target", "Plants need water: less rain usually means less green vegetation, "
                         "often a few months later."),
    ("ndvi", "t2m"): ("both", "Heat stress can brown vegetation, and in cold places warming can lengthen the "
                      "growing season; losing vegetation also warms the surface."),
    ("ndvi", "soil_moisture"): ("driver->target", "Plants draw water from the soil; dry soil means stressed, "
                                "less green plants."),
    ("t2m", "ndvi"): ("both", "Less vegetation (for example after deforestation) means less evaporative "
                      "cooling, so the surface and air warm; heat and drought can also brown vegetation."),
    ("evapotranspiration", "ndvi"): ("driver->target", "Plants move water from the soil into the air "
                                     "(transpiration); fewer or less green plants means less evapotranspiration."),
    ("land_surface_temp", "ndvi"): ("driver->target", "Bare or sparse ground heats up much more in the sun "
                                    "than leafy vegetation, which cools itself by transpiring."),
    # AIRS satellite temperature: same physics as the model air temperature
    ("airs_surface_temp", "soil_moisture"): ("both", "Drier soil evaporates less water, so less of the sun's "
                                             "energy goes into evaporation (which cools) and more into heating "
                                             "the air. Hotter air also dries soil."),
    ("airs_surface_temp", "precip"): ("driver->target", "Less rain usually means fewer clouds and drier "
                                      "ground, both of which let surface temperatures rise."),
    ("airs_surface_temp", "ndvi"): ("both", "Less vegetation means less evaporative cooling, so the surface "
                                    "warms; heat and drought can also brown vegetation."),
    # AIRS water vapor
    ("water_vapor", "t2m"): ("both", "Warmer air can hold about 7% more water vapor per °C, so water vapor "
                             "usually rises with temperature; water vapor also traps heat (a feedback)."),
    ("water_vapor", "evapotranspiration"): ("driver->target", "Evaporation from land, lakes and plants adds "
                                            "water vapor to the air above."),
    ("water_vapor", "precip"): ("both", "Rain removes water vapor from the air, but moist air is also needed "
                                "to make rain."),
    # OMI lower-atmosphere ozone
    ("tropospheric_ozone", "t2m"): ("driver->target", "Ground-level ozone forms faster in hot, sunny weather, "
                                    "when sunlight reacts with pollution from traffic, industry and fires."),
    ("tropospheric_ozone", "humidity"): ("driver->target", "In clean air, water vapor helps break ozone down, "
                                         "so more humid air tends to hold less ozone."),
    # carbon dioxide: local drivers only explain the seasonal wiggle, not the long-term rise
    ("co2", "ndvi"): ("driver->target", "Growing plants pull CO2 out of the air, so greener seasons lower "
                      "CO2 a little. The long-term rise, though, comes from fossil fuels burned worldwide, "
                      "which this regional data cannot measure."),
    ("co2", "t2m"): ("both", "Warmer seasons speed up plant growth and decay, shifting CO2 up and down. "
                     "Globally, rising CO2 traps heat and warms the planet, but local temperature doesn't "
                     "control the global CO2 rise."),
    # pressure
    ("sea_level_pressure", "t2m"): ("both", "Changes in pressure patterns shift winds and air masses, which "
                                    "changes temperature; heating also changes pressure."),
    ("sea_level_pressure", "precip"): ("target->driver", "High pressure usually means sinking, dry air and "
                                       "less rain; it is more a cause of rain changes than a result."),
}


def _effective_p(r: float, n: int, x: np.ndarray, y: np.ndarray) -> float:
    """Two-sided p-value for a correlation, with the sample size shrunk for
    autocorrelation in both series (Bretherton et al. 1999)."""
    def lag1(a):
        return float(np.corrcoef(a[:-1], a[1:])[0, 1]) if len(a) > 2 else 0.0
    rx, ry = max(lag1(x), 0.0), max(lag1(y), 0.0)
    n_eff = max(n * (1 - rx * ry) / (1 + rx * ry), 4.0)
    t = r * np.sqrt((n_eff - 2) / max(1 - r * r, 1e-12))
    return float(2 * st.t.sf(abs(t), n_eff - 2))


def _best_lag(y: pd.Series, x: pd.Series) -> dict:
    """The lag (0-MAX_LAG months, driver leading) with the strongest correlation.

    Picking the best of several lags and reporting its p-value as-is would overstate the
    evidence (four tries at p < 0.05 succeed by luck ~19% of the time), so `p_value` is
    Bonferroni-corrected for the number of lags tried; `p_value_single_lag` is the raw one."""
    best, tried = None, 0
    for lag in range(MAX_LAG + 1):
        pair = pd.concat([y, x.shift(lag)], axis=1).dropna()
        if len(pair) < 24:
            continue
        tried += 1
        a, b = pair.iloc[:, 0].to_numpy(), pair.iloc[:, 1].to_numpy()
        r = float(np.corrcoef(a, b)[0, 1])
        if best is None or abs(r) > abs(best["r"]) + 0.02:  # prefer shorter lags unless clearly better
            best = {"r": r, "lag_months": lag, "p_value_single_lag": _effective_p(r, len(pair), a, b),
                    "n": len(pair)}
    if best is None:
        return {"r": 0.0, "lag_months": 0, "p_value": 1.0, "p_value_single_lag": 1.0, "lags_tried": 0, "n": 0}
    best["lags_tried"] = tried
    best["p_value"] = min(1.0, best["p_value_single_lag"] * tried)
    return best


def _regression(y: pd.Series, X: pd.DataFrame) -> dict:
    """OLS of target anomalies on driver anomalies (same month)."""
    frame = pd.concat([y.rename("y"), X], axis=1).dropna()
    A = np.column_stack([np.ones(len(frame)), frame[X.columns].to_numpy()])
    coef, *_ = np.linalg.lstsq(A, frame["y"].to_numpy(), rcond=None)
    fitted = A @ coef
    ss_res = float(((frame["y"] - fitted) ** 2).sum())
    ss_tot = float(((frame["y"] - frame["y"].mean()) ** 2).sum())
    sd_x = frame[X.columns].std().to_numpy()
    sd_y = float(frame["y"].std())
    return {
        "coef": dict(zip(X.columns, coef[1:])),
        "std_coef": dict(zip(X.columns, coef[1:] * sd_x / sd_y if sd_y else coef[1:] * 0)),
        "r_squared": 1 - ss_res / ss_tot if ss_tot else 0.0,
        "n": len(frame),
    }


def _random_forest(y: pd.Series, X: pd.DataFrame) -> dict:
    """Random forest on lagged drivers: time-ordered CV skill + permutation importance."""
    from sklearn.ensemble import RandomForestRegressor
    from sklearn.inspection import permutation_importance
    from sklearn.model_selection import TimeSeriesSplit, cross_val_score

    feats = {f"{c}|{lag}": X[c].shift(lag) for c in X.columns for lag in range(MAX_LAG + 1)}
    frame = pd.concat([y.rename("y"), pd.DataFrame(feats)], axis=1).dropna()
    if len(frame) < 48:
        return {"available": False, "reason": "Need at least 4 years of overlapping data for the ML model."}
    Xf, yf = frame.drop(columns="y"), frame["y"]
    model = RandomForestRegressor(n_estimators=300, max_depth=4, min_samples_leaf=5, random_state=0, n_jobs=-1)
    cv = cross_val_score(model, Xf, yf, cv=TimeSeriesSplit(n_splits=5), scoring="r2")
    model.fit(Xf, yf)
    perm = permutation_importance(model, Xf, yf, n_repeats=10, random_state=0, n_jobs=-1)
    per_driver: dict[str, float] = {}
    for name, imp in zip(Xf.columns, perm.importances_mean):
        key = name.split("|")[0]
        per_driver[key] = per_driver.get(key, 0.0) + max(float(imp), 0.0)
    total = sum(per_driver.values())
    cv_r2 = float(np.mean(cv))
    return {
        "available": True,
        "cv_r2": cv_r2,
        "has_skill": cv_r2 > 0.05,
        "importance_share": {k: (v / total if total else 0.0) for k, v in per_driver.items()},
    }


def _evidence(corr: dict, share: float | None, target_sig: bool) -> str:
    sig = corr["p_value"] < 0.05
    if sig and abs(corr["r"]) >= 0.4 and (not target_sig or (share is not None and share > 0.15)):
        return "strong"
    if sig and abs(corr["r"]) >= 0.2:
        return "moderate"
    return "weak"


def _region_context(geom, results: dict[str, dict]) -> dict:
    c = geom.centroid
    lat = c.y
    minx, miny, maxx, maxy = geom.bounds
    # approximate area: degrees^2 scaled by cos(latitude), 111 km per degree
    area_km2 = float(geom.area * np.cos(np.deg2rad(lat)) * 111.32 ** 2)
    means = {k: r["stats"]["mean"] for k, r in results.items()}
    zone = ("tropical" if abs(lat) < 23.5 else "subtropical" if abs(lat) < 35
            else "mid-latitude" if abs(lat) < 60 else "polar / subpolar")
    ctx = {
        "centroid": {"lat": round(lat, 3), "lon": round(c.x, 3)},
        "bounds": [round(b, 3) for b in (minx, miny, maxx, maxy)],
        "area_km2": round(area_km2),
        "latitude_zone": zone,
        "mean_values": {k: round(v, 3) for k, v in means.items()},
    }
    if "precip" in means:
        ctx["annual_precip_mm"] = round(means["precip"] * 365.25)
    if "t2m" in means:
        ctx["mean_temp_c"] = round(means["t2m"], 1)
    return ctx


def analyze_drivers(var_key: str, polygon, start: str | None = None, end: str | None = None,
                    source: str = "auto", progress: data.Progress | None = None) -> dict:
    var = catalog.get(var_key)
    geom = region.load_polygon(polygon)
    d0, d1 = default_range(var)
    start, end = start or d0, end or d1
    keys = [var.key, *var.related]

    # progress across every variable that has to stream from NASA
    plans = {}
    for k in keys:
        try:
            plans[k] = plan(k, polygon, start, end, source=source)
        except data.DataError:
            plans[k] = {"source": "unavailable", "months": 0}
    # the target and its candidate drivers stream at the same time
    sizes = [plans[k]["months"] if plans[k]["source"] == "cloud" else 0 for k in keys]
    tasks = [lambda prog, k=k: analyze(k, polygon, start=start, end=end, source=source, progress=prog)
             for k in keys]
    results: dict[str, dict] = {}
    skipped: dict[str, str] = {}
    for k, res in zip(keys, run_together(tasks, sizes, progress)):
        if isinstance(res, Exception):
            if k == var.key:
                raise res
            skipped[k] = str(res)
        else:
            results[k] = res

    def anomalies(res: dict) -> pd.Series:
        s = pd.Series({pd.Timestamp(p["date"] + "-01"): p["anomaly"] for p in res["series"]})
        return s.sort_index()

    target = results[var.key]
    y = anomalies(target)
    driver_keys = [k for k in var.related if k in results]
    X = pd.DataFrame({k: anomalies(results[k]) for k in driver_keys})
    t_lin = target["stats"]["linear"]
    target_slope = t_lin["slope_per_decade"]
    target_sig = target["stats"]["significant"]

    drivers = []
    reg = _regression(y, X) if driver_keys else None
    rf = _random_forest(y, X) if driver_keys else {"available": False, "reason": "No drivers available."}
    for k in driver_keys:
        dv = catalog.get(k)
        d_stats = results[k]["stats"]
        corr = _best_lag(y, X[k])
        contribution = reg["coef"][k] * d_stats["linear"]["slope_per_decade"] if reg else None
        share = (contribution / target_slope) if (contribution is not None and target_slope) else None
        direction, mechanism = MECHANISMS.get((var.key, k), ("unknown", ""))
        drivers.append({
            "key": k,
            "name": dv.name,
            "units": dv.units,
            "definition": dv.definition,
            "trend": {
                "slope_per_decade": d_stats["linear"]["slope_per_decade"],
                "p_value": d_stats["linear"]["p_value"],
                "significant": d_stats["significant"],
                "verdict": d_stats["verdict"],
            },
            "correlation": corr,
            "regression": {
                "coef_per_unit": reg["coef"][k] if reg else None,
                "standardized_coef": reg["std_coef"][k] if reg else None,
                "trend_contribution_per_decade": contribution,
                "share_of_target_trend": share,
            },
            "ml_importance_share": rf.get("importance_share", {}).get(k) if rf.get("available") else None,
            "evidence": _evidence(corr, share, target_sig),
            "physical_link": {"likely_direction": direction, "mechanism": mechanism},
        })

    order = {"strong": 0, "moderate": 1, "weak": 2}
    drivers.sort(key=lambda d: (order[d["evidence"]], -abs(d["correlation"]["r"])))
    for i, d in enumerate(drivers, 1):
        d["rank"] = i

    caveats = [
        "These are statistical associations, not proof of cause. Two variables can move together "
        "because a third factor drives both, and a correlation doesn't say which way the effect runs "
        "(see each driver's physical link).",
        "Only the variables in this tool are tested. Causes such as land-use change, deforestation, "
        "sea-ice loss, aerosols, irrigation or large-scale climate patterns (e.g. El Niño) are not measured here.",
        "MERRA-2 and GLDAS are model reanalyses that share some input data, so their variables are "
        "not fully independent of each other.",
    ]
    if reg and len(driver_keys) > 1:
        caveats.append("The drivers are correlated with each other (e.g. rain and soil moisture), so "
                       "the regression may split credit between them unevenly.")
    if rf.get("available") and not rf["has_skill"]:
        caveats.append("The machine-learning model could not predict month-to-month changes better than "
                       "a simple average (cross-validated R² ≤ 0.05), so its importance scores are unreliable.")
    if not target_sig:
        caveats.append("The target's own trend is not statistically significant, so 'share of the trend' "
                       "numbers are especially uncertain.")
    for k, why in skipped.items():
        caveats.append(f"{catalog.get(k).name} was left out: {why}")

    return {
        "variable": target["variable"],
        "start": start,
        "end": end,
        "target": {
            "stats": target["stats"],
            "region": target["region"],
            "data_source": target["data_source"],
        },
        "drivers": drivers,
        "models": {
            "regression": {"r_squared": reg["r_squared"], "n_months": reg["n"]} if reg else None,
            "random_forest": {k: v for k, v in rf.items() if k != "importance_share"},
        },
        "region_context": _region_context(geom, results),
        "skipped": skipped,
        "caveats": caveats,
    }
