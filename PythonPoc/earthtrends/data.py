"""Download NASA data and pack each variable into a local Zarr "cube".

Downloads use NASA's cloud OPeNDAP service, which sends only the variables we
need instead of whole files (e.g. MERRA-2: 0.5 MB instead of 61 MB per month).

Subset files: data/raw/<collection>/<original file name>
Cubes:        data/cubes/<variable>.zarr   (time, lat, lon), converted units

Cubes are chunked spatially so a polygon query only reads the small piece of the
globe it needs. That keeps queries to a few seconds even for 25 years of data.
"""
from __future__ import annotations

import os
import re
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.parse import quote

import numpy as np
import pandas as pd
import xarray as xr

from .catalog import VARIABLES, Variable

# Override with the EARTHTRENDS_DATA_DIR environment variable (the API uses this).
DATA_DIR = Path(os.environ.get("EARTHTRENDS_DATA_DIR") or Path(__file__).resolve().parent.parent / "data")
RAW_DIR = DATA_DIR / "raw"
CUBE_DIR = DATA_DIR / "cubes"

SPATIAL_CHUNK = 200  # grid cells per chunk along lat and lon
_MONTH_RE = re.compile(r"(?<!\d)((?:19|20)\d{2})(0[1-9]|1[0-2])")


def cube_path(var: Variable) -> Path:
    return CUBE_DIR / f"{var.key}.zarr"


def month_from_filename(path: Path) -> pd.Timestamp:
    """All three products put YYYYMM in the file name; it's more reliable than
    decoding each product's own time convention."""
    m = _MONTH_RE.search(path.name)
    if not m:
        raise ValueError(f"Can't find a YYYYMM date in file name: {path.name}")
    return pd.Timestamp(year=int(m.group(1)), month=int(m.group(2)), day=1)


# ---------------------------------------------------------------- download

def _opendap_url(granule, var: Variable) -> str:
    """OPeNDAP (DAP4) URL asking for just the variables we use from this collection,
    plus lat/lon. Every catalog variable sharing the collection is included, so
    soil moisture and evapotranspiration come down in one request."""
    base = next(
        (u["URL"] for u in granule["umm"].get("RelatedUrls", [])
         if u.get("Subtype") == "OPENDAP DATA"),
        None,
    )
    if base is None:
        raise RuntimeError(f"No OPeNDAP link for {granule.data_links()[0]}")
    prefix = f"/{var.group}" if var.group else ""
    names = sorted({v.source_var for v in VARIABLES.values() if v.collection == var.collection})
    ce = ";".join([f"{prefix}/{n}" for n in names] + [f"{prefix}/lat", f"{prefix}/lon"])
    return f"{base}.dap.nc4?dap4.ce={quote(ce, safe='/')}"


def download(var: Variable, start: str, end: str, threads: int = 4) -> list[Path]:
    """Download monthly subsets for var's collection between start and end (YYYY-MM).
    Files already on disk are skipped, so an interrupted download can be resumed."""
    import earthaccess

    auth = earthaccess.login(persist=True)  # env vars -> .netrc -> interactive prompt
    if not auth or not getattr(auth, "authenticated", False):
        raise SystemExit("Earthdata login failed. See README for setup.")

    end_ts = pd.Period(end, "M").end_time.strftime("%Y-%m-%d")
    results = earthaccess.search_data(
        short_name=var.collection,
        version=var.version,
        temporal=(f"{start}-01", end_ts),
    )
    out = RAW_DIR / var.collection
    out.mkdir(parents=True, exist_ok=True)

    jobs = []
    for g in results:
        target = out / g.data_links()[0].rsplit("/", 1)[-1]
        if not target.exists():
            jobs.append((_opendap_url(g, var), target))
    print(f"{var.collection} v{var.version}: {len(results)} months found, "
          f"{len(results) - len(jobs)} already downloaded, {len(jobs)} to download")

    local = threading.local()

    def fetch(url: str, target: Path) -> Path:
        if not hasattr(local, "session"):
            local.session = earthaccess.get_requests_https_session()
        last_err = None
        for attempt in range(3):
            try:
                r = local.session.get(url, timeout=300)
                r.raise_for_status()
                tmp = target.with_suffix(target.suffix + ".part")
                tmp.write_bytes(r.content)
                tmp.replace(target)  # only complete files get the real name
                return target
            except Exception as e:  # network hiccups: retry
                last_err = e
        raise RuntimeError(f"Failed {target.name}: {last_err}")

    done, failed = [], []
    with ThreadPoolExecutor(max_workers=threads) as pool:
        futures = {pool.submit(fetch, u, t): t for u, t in jobs}
        for i, fut in enumerate(as_completed(futures), 1):
            try:
                done.append(fut.result())
            except Exception as e:
                failed.append(futures[fut])
                print(f"  {e}")
            if i % 12 == 0 or i == len(jobs):
                print(f"  {i}/{len(jobs)} downloaded")
    if failed:
        # Stop before building the cube so it never has gaps in the middle.
        raise SystemExit(f"{len(failed)} downloads failed. Run the same command again to retry them.")
    return done


def raw_files(var: Variable) -> list[Path]:
    folder = RAW_DIR / var.collection
    exts = {".nc4", ".nc", ".hdf5", ".h5"}
    return sorted(p for p in folder.glob("*") if p.suffix.lower() in exts)


# ---------------------------------------------------------------- cube building

def _read_month(path: Path, var: Variable) -> xr.DataArray:
    with xr.open_dataset(path, group=var.group, decode_times=False, engine="netcdf4") as ds:
        da = ds[var.source_var]
        da = da.squeeze([d for d in da.dims if d == "time"], drop=True)
        da = da.transpose("lat", "lon").astype("float32").load()
    da = da * np.float32(var.scale) + np.float32(var.offset)
    da = da.expand_dims(time=[month_from_filename(path)])
    da.name = var.key
    da.attrs = {"units": var.units, "long_name": var.name}
    return da


def build_cube(var: Variable) -> Path:
    """Append every raw month not already in the cube. Safe to re-run."""
    files = raw_files(var)
    if not files:
        raise SystemExit(f"No raw files for {var.collection}. Run the download first.")

    path = cube_path(var)
    path.parent.mkdir(parents=True, exist_ok=True)
    have: set[pd.Timestamp] = set()
    if path.exists():
        with xr.open_zarr(path, consolidated=False) as existing:
            have = set(pd.to_datetime(existing.time.values))

    # Pick one file per month (MERRA-2 sometimes has reprocessed duplicates; keep the last).
    by_month: dict[pd.Timestamp, Path] = {}
    for f in files:
        by_month[month_from_filename(f)] = f
    todo = sorted(m for m in by_month if m not in have)
    if have and todo and todo[0] < max(have):
        raise SystemExit(
            f"New months older than the existing cube for {var.key}. "
            f"Delete {path} and rebuild."
        )
    print(f"{var.key}: {len(have)} months in cube, {len(todo)} to add")

    batch = 12  # write a year at a time to keep memory modest
    for i in range(0, len(todo), batch):
        months = todo[i : i + batch]
        da = xr.concat([_read_month(by_month[m], var) for m in months], dim="time")
        ds = da.to_dataset().chunk({"time": batch, "lat": SPATIAL_CHUNK, "lon": SPATIAL_CHUNK})
        if path.exists():
            ds.to_zarr(path, mode="a", append_dim="time", consolidated=False)
        else:
            ds.to_zarr(path, mode="w", consolidated=False)
        print(f"  wrote {months[0]:%Y-%m} .. {months[-1]:%Y-%m}")
    return path


def open_cube(var: Variable) -> xr.DataArray:
    path = cube_path(var)
    if not path.exists():
        raise SystemExit(f"No cube for '{var.key}'. Run: python -m earthtrends fetch {var.key}")
    return xr.open_zarr(path, consolidated=False)[var.key]
