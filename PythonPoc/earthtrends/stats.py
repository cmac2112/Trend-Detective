"""Trend statistics for a monthly time series.

Steps:
1. Remove the seasonal cycle (subtract each calendar month's long-term mean) to get anomalies.
2. Fit a straight line to the anomalies: slope, standard error, t-test, 95% CI.
3. Correct the t-test for autocorrelation (neighbouring months are similar, so we have
   fewer independent data points than months). Uses the effective-sample-size method
   of Santer et al. (2000).
4. Mann-Kendall trend tests with Sen's slope (robust, no normality assumption).
5. Plain-English verdict.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pymannkendall as mk
from scipy import stats as st

ALPHA = 0.05


def deseasonalize(series: pd.Series) -> tuple[pd.Series, pd.Series]:
    """Return (anomalies, monthly climatology)."""
    clim = series.groupby(series.index.month).mean()
    anomalies = series - clim.reindex(series.index.month).to_numpy()
    return anomalies, clim


def decimal_years(index: pd.DatetimeIndex) -> np.ndarray:
    return (index.year + (index.month - 0.5) / 12).to_numpy(dtype=float)


def trend_stats(series: pd.Series, units: str = "") -> dict:
    series = series.dropna().sort_index()
    n = len(series)
    if n < 24:
        raise ValueError(f"Need at least 24 months of data, got {n}")

    anom, clim = deseasonalize(series)
    t = decimal_years(series.index)
    y = anom.to_numpy(dtype=float)

    # --- ordinary least squares + t-test
    fit = st.linregress(t, y)
    resid = y - (fit.intercept + fit.slope * t)
    r1 = float(np.corrcoef(resid[:-1], resid[1:])[0, 1]) if n > 2 else 0.0

    # --- autocorrelation-adjusted t-test
    r1c = max(r1, 0.0)
    n_eff = n * (1 - r1c) / (1 + r1c)
    n_eff = max(n_eff, 3.0)
    se_adj = fit.stderr * np.sqrt((n - 2) / (n_eff - 2)) if n_eff > 2 else np.inf
    df_adj = n_eff - 2
    t_adj = fit.slope / se_adj if se_adj > 0 else 0.0
    p_adj = float(2 * st.t.sf(abs(t_adj), df_adj))
    tcrit = st.t.ppf(1 - ALPHA / 2, df_adj)
    ci = (fit.slope - tcrit * se_adj, fit.slope + tcrit * se_adj)

    # --- Mann-Kendall family
    mk_hr = mk.hamed_rao_modification_test(y)  # MK corrected for autocorrelation
    mk_seasonal = mk.seasonal_test(series.to_numpy(dtype=float), period=12)

    years = t[-1] - t[0]
    mean = float(series.mean())
    slope_dec = fit.slope * 10
    result = {
        "n_months": n,
        "start": series.index[0].strftime("%Y-%m"),
        "end": series.index[-1].strftime("%Y-%m"),
        "years": round(years, 2),
        "units": units,
        "mean": mean,
        "linear": {
            "slope_per_decade": slope_dec,
            "ci95_per_decade": [ci[0] * 10, ci[1] * 10],
            "total_change": fit.slope * years,
            "percent_of_mean_per_decade": (slope_dec / abs(mean) * 100) if mean else None,
            "r_squared": fit.rvalue ** 2,
            "p_value_naive": float(fit.pvalue),
            "p_value": p_adj,
            "lag1_autocorrelation": r1,
            "effective_n": n_eff,
            "intercept": float(fit.intercept),
            "slope_per_year": float(fit.slope),
        },
        "mann_kendall": {
            "trend": mk_hr.trend,
            "p_value": float(mk_hr.p),
            "tau": float(mk_hr.Tau),
            "sen_slope_per_decade": float(mk_hr.slope) * 120,  # per month -> per decade
        },
        "seasonal_mann_kendall": {
            "trend": mk_seasonal.trend,
            "p_value": float(mk_seasonal.p),
            "sen_slope_per_decade": float(mk_seasonal.slope) * 10,  # per year -> per decade
        },
        "climatology": {int(m): float(v) for m, v in clim.items()},
    }
    result["significant"] = bool(p_adj < ALPHA and mk_hr.p < ALPHA)
    result["verdict"] = verdict(result)
    return result


def verdict(r: dict) -> str:
    lin, mkr = r["linear"], r["mann_kendall"]
    slope, u = lin["slope_per_decade"], r["units"]
    direction = "increasing" if slope > 0 else "decreasing"
    size = f"{abs(slope):.3g} {u} per decade".strip()
    pct = lin["percent_of_mean_per_decade"]
    pct_txt = f" ({abs(pct):.1f}% of the average)" if pct is not None and abs(r["mean"]) > 1e-6 else ""
    period = f"{r['start']} to {r['end']}"

    t_sig = lin["p_value"] < ALPHA
    mk_sig = mkr["p_value"] < ALPHA
    if t_sig and mk_sig:
        return (f"Significant trend: {direction} by about {size}{pct_txt} over {period}. "
                f"Both the t-test (p = {lin['p_value']:.3f}) and Mann-Kendall test "
                f"(p = {mkr['p_value']:.3f}) say this is unlikely to be random variation.")
    if t_sig or mk_sig:
        return (f"Possible trend: {direction} by about {size}{pct_txt} over {period}, but the "
                f"tests disagree (t-test p = {lin['p_value']:.3f}, Mann-Kendall p = "
                f"{mkr['p_value']:.3f}). Treat it as borderline; a longer record may settle it.")
    return (f"No significant trend: the data drift {direction} by about {size}{pct_txt} over "
            f"{period}, but that could easily be natural year-to-year variation "
            f"(t-test p = {lin['p_value']:.3f}, Mann-Kendall p = {mkr['p_value']:.3f}). "
            f"A longer record might reveal a trend.")
