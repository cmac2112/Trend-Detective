"""Download NASA data and pack each variable into a local Zarr "cube".

Downloads use NASA's cloud OPeNDAP service, which sends only the variables we
need instead of whole files (e.g. MERRA-2: 0.5 MB instead of 61 MB per month).

Subset files: data/raw/<collection>/<original file name>
Cubes:        data/cubes/<variable>.zarr   (time, lat, lon), converted units

Cubes are chunked spatially so a polygon query only reads the small piece of the
globe it needs. That keeps queries to a few seconds even for 25 years of data.
"""
from __future__ import annotations

import math
import os
import re
import shutil
import threading
from typing import Callable
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
    return month_from_filename_str(path.name)


_DOY_RE = re.compile(r"\.A((?:19|20)\d{2})(\d{3})\.")  # MODIS: .AYYYYDDD. (year + day of year)
_DOTTED_RE = re.compile(r"(?<!\d)((?:19|20)\d{2})\.(0[1-9]|1[0-2])\.\d{2}\.")  # AIRS: AIRS.2003.12.01.


def month_from_filename_str(name: str) -> pd.Timestamp:
    name = name.rsplit("/", 1)[-1]
    doy = _DOY_RE.search(name)
    if doy:
        day = pd.Timestamp(year=int(doy.group(1)), month=1, day=1) + pd.Timedelta(days=int(doy.group(2)) - 1)
        return pd.Timestamp(year=day.year, month=day.month, day=1)
    dotted = _DOTTED_RE.search(name)
    if dotted:
        return pd.Timestamp(year=int(dotted.group(1)), month=int(dotted.group(2)), day=1)
    m = _MONTH_RE.search(name)
    if not m:
        raise ValueError(f"Can't find a YYYYMM date in file name: {name}")
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
    names = sorted({n for v in VARIABLES.values() if v.collection == var.collection for n in v.source_vars})
    ce = ";".join([f"{prefix}/{n}" for n in names] + [f"{prefix}/lat", f"{prefix}/lon"])
    return f"{base}.dap.nc4?dap4.ce={quote(ce, safe='/')}"


class DataError(Exception):
    """A problem the user can fix (missing data, failed login, failed downloads)."""


Progress = Callable[[int, int], None]  # (done, total)


TOKEN_URL = "https://urs.earthdata.nasa.gov/users/tokens"


def _password_allowed() -> bool:
    """Whether a username/password (env vars or _netrc) may be used when there's no token.
    The API turns this off (EARTHDATA_ALLOW_PASSWORD=0) so a hosted server only ever
    holds a token; the command-line PoC keeps it on for convenience."""
    return os.environ.get("EARTHDATA_ALLOW_PASSWORD", "1").strip().lower() not in ("0", "false", "no")


def token_status() -> dict:
    """What's known about EARTHDATA_TOKEN without contacting NASA (never includes the token).
    Earthdata tokens are JWTs that expire 60 days after they're created; the expiry date is
    read from the token itself (not verified - NASA checks the signature on every request)."""
    import base64
    import json
    import time

    token = (os.environ.get("EARTHDATA_TOKEN") or "").strip()
    if not token:
        return {"configured": False}
    status: dict = {"configured": True, "expires": None, "days_left": None, "expired": False}
    try:
        payload = token.split(".")[1]
        claims = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
        exp = int(claims["exp"])
        status["expires"] = pd.Timestamp(exp, unit="s").strftime("%Y-%m-%d")
        status["days_left"] = math.floor((exp - time.time()) / 86400)
        status["expired"] = exp <= time.time()
    except Exception:  # not a JWT we can read: let NASA decide
        pass
    return status


def have_credentials() -> bool:
    """True if Earthdata credentials are available without prompting anyone."""
    tok = token_status()
    if tok["configured"]:
        return not tok["expired"]
    if not _password_allowed():
        return False
    if os.environ.get("EARTHDATA_USERNAME") and os.environ.get("EARTHDATA_PASSWORD"):
        return True
    home = Path.home()
    return (home / ".netrc").exists() or (home / "_netrc").exists()


def _login(interactive: bool):
    import earthaccess

    tok = token_status()
    if tok["configured"]:  # a token always wins over a username/password
        if tok["expired"]:
            raise DataError(f"The Earthdata token expired on {tok['expires']}. "
                            f"Create a new one at {TOKEN_URL} and update EARTHDATA_TOKEN.")
        auth = earthaccess.login(strategy="environment")
    elif interactive and _password_allowed():
        auth = earthaccess.login(persist=True)  # env vars -> .netrc -> prompt
    else:  # servers must never wait on a password prompt
        if not have_credentials():
            hint = ("set EARTHDATA_TOKEN" if not _password_allowed()
                    else "set EARTHDATA_TOKEN or create a _netrc file")
            raise DataError(f"No Earthdata credentials on this machine ({hint}; tokens: {TOKEN_URL}).")
        strategy = "environment" if os.environ.get("EARTHDATA_USERNAME") else "netrc"
        auth = earthaccess.login(strategy=strategy)
    if not auth or not getattr(auth, "authenticated", False):
        raise DataError("Earthdata login failed. Check your credentials.")


def months_between(start: str, end: str) -> list[pd.Timestamp]:
    return list(pd.date_range(f"{start}-01", f"{end}-01", freq="MS"))


def cube_months(var: Variable) -> set[pd.Timestamp]:
    path = cube_path(var)
    if not path.exists():
        return set()
    with xr.open_zarr(path, consolidated=False) as ds:
        return set(pd.to_datetime(ds.time.values))


def raw_months(var: Variable) -> set[pd.Timestamp]:
    return {month_from_filename(f) for f in raw_files(var)}


def coverage(var: Variable, start: str, end: str) -> dict:
    """What's missing for start..end and roughly how big downloading it would be."""
    requested = var.available_months(start, end)
    in_cube = cube_months(var)
    on_disk = raw_months(var)
    missing = [m for m in requested if m not in in_cube]
    to_download = [m for m in missing if m not in on_disk]
    return {
        "requested_months": len(requested),
        "available_months": len(requested) - len(missing),
        "missing_months": len(missing),
        "missing_first": f"{missing[0]:%Y-%m}" if missing else None,
        "missing_last": f"{missing[-1]:%Y-%m}" if missing else None,
        "download_months": len(to_download),
        "estimated_mb": round(len(to_download) * var.mb_per_month, 1),
        "data_starts": var.first_month,
    }


def download(var: Variable, start: str, end: str, threads: int = 4,
             interactive: bool = True, progress: Progress | None = None) -> list[Path]:
    """Download monthly subsets for var's collection between start and end (YYYY-MM).
    Files already on disk are skipped, so an interrupted download can be resumed."""
    import earthaccess

    if not var.global_fetch:
        raise DataError(f"{var.name} files are too large to download whole; it is streamed from "
                        f"NASA's cloud per region instead (use analyze or prepare-examples).")
    _login(interactive)

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
    if progress:
        progress(0, len(jobs))
    with ThreadPoolExecutor(max_workers=threads) as pool:
        futures = {pool.submit(fetch, u, t): t for u, t in jobs}
        for i, fut in enumerate(as_completed(futures), 1):
            try:
                done.append(fut.result())
            except Exception as e:
                failed.append(futures[fut])
                print(f"  {e}")
            if progress:
                progress(i, len(jobs))
            if i % 12 == 0 or i == len(jobs):
                print(f"  {i}/{len(jobs)} downloaded")
    if failed:
        # Stop before building the cube so it never has gaps in the middle.
        raise DataError(f"{len(failed)} downloads failed. Try again to retry them.")
    return done


def raw_files(var: Variable) -> list[Path]:
    folder = RAW_DIR / var.collection
    exts = {".nc4", ".nc", ".hdf5", ".h5"}
    return sorted(p for p in folder.glob("*") if p.suffix.lower() in exts)


# ---------------------------------------------------------------- cube building

def _read_month(path: Path, var: Variable) -> xr.DataArray:
    with xr.open_dataset(path, group=var.group, decode_times=False, engine="netcdf4") as ds:
        missing = [n for n in var.source_vars if n not in ds]
        if missing:
            raise DataError(f"{path.name} has no {', '.join(missing)} (downloaded before {var.key} was "
                            f"added). Delete data/raw/{var.collection} and fetch again.")
        da = sum(ds[name] for name in var.source_vars)
        da = da.squeeze([d for d in da.dims if d == "time"], drop=True)
        da = da.transpose("lat", "lon").astype("float32").load()
    da = da * np.float32(var.scale) + np.float32(var.offset)
    da = da.expand_dims(time=[month_from_filename(path)])
    da.name = var.key
    da.attrs = {"units": var.units, "long_name": var.name}
    return da


def build_cube(var: Variable, progress: Progress | None = None) -> Path:
    """Add every downloaded month that isn't in the cube yet. Safe to re-run.

    New months after the cube's last month are appended. If any new month is
    *older* than that (e.g. extending a 2022-2024 cube back to 2001), the cube is
    rebuilt from all downloaded files in a temporary folder and swapped in, so
    months always stay in time order."""
    files = raw_files(var)
    if not files:
        raise DataError(f"No downloaded files for {var.collection}. Download first.")

    path = cube_path(var)
    path.parent.mkdir(parents=True, exist_ok=True)
    have = cube_months(var)

    # Pick one file per month (MERRA-2 sometimes has reprocessed duplicates; keep the last).
    by_month: dict[pd.Timestamp, Path] = {}
    for f in files:
        by_month[month_from_filename(f)] = f
    todo = sorted(m for m in by_month if m not in have)

    target = path
    if have and todo and todo[0] < max(have):
        todo = sorted(by_month)  # rebuild everything, in order
        target = path.with_name(path.name + ".rebuild")
        if target.exists():
            shutil.rmtree(target)
        print(f"{var.key}: adding older months, rebuilding cube with {len(todo)} months")
    else:
        print(f"{var.key}: {len(have)} months in cube, {len(todo)} to add")

    batch = 12  # write a year at a time to keep memory modest
    if progress:
        progress(0, len(todo))
    for i in range(0, len(todo), batch):
        months = todo[i : i + batch]
        da = xr.concat([_read_month(by_month[m], var) for m in months], dim="time")
        ds = da.to_dataset().chunk({"time": batch, "lat": SPATIAL_CHUNK, "lon": SPATIAL_CHUNK})
        if target.exists():
            ds.to_zarr(target, mode="a", append_dim="time", consolidated=False)
        else:
            ds.to_zarr(target, mode="w", consolidated=False)
        if progress:
            progress(min(i + batch, len(todo)), len(todo))
        print(f"  wrote {months[0]:%Y-%m} .. {months[-1]:%Y-%m}")

    if target != path:  # swap the rebuilt cube in
        old = path.with_name(path.name + ".old")
        if old.exists():
            shutil.rmtree(old)
        _rename_retry(path, old)
        try:
            _rename_retry(target, path)
        except OSError:
            _rename_retry(old, path)  # put the previous cube back so nothing goes missing
            raise
        shutil.rmtree(old, ignore_errors=True)
    return path


def _rename_retry(src: Path, dst: Path, attempts: int = 20) -> None:
    """Windows briefly locks freshly written folders (antivirus, indexing), which makes
    a rename fail with 'Access is denied'. Retry for a few seconds before giving up."""
    import time

    for i in range(attempts):
        try:
            src.rename(dst)
            return
        except PermissionError:
            if i == attempts - 1:
                raise
            time.sleep(0.5)


def open_cube(var: Variable) -> xr.DataArray:
    path = cube_path(var)
    if not path.exists():
        raise DataError(f"No data for '{var.key}' yet. Run: python -m earthtrends fetch {var.key}")
    return xr.open_zarr(path, consolidated=False)[var.key]
