"""Read a region's data straight from NASA's cloud, without storing it.

For each month, NASA's cloud OPeNDAP service (opendap.earthdata.nasa.gov) cuts out
only the grid cells around the polygon and sends them back - a few KB per month.
The months are requested in parallel and assembled into a small in-memory
(time, lat, lon) cube, which the normal polygon-average and statistics code uses.

Nothing is written to disk except each dataset's grid coordinates (a few KB,
fetched once), so any number of users can't fill the server's storage.
Measured: 24 years (288 months) of MERRA-2 temperature for the Barents Sea in ~25 s.
"""
from __future__ import annotations

import threading
import warnings
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.parse import quote

import netCDF4
import numpy as np
import pandas as pd
import xarray as xr
from shapely.geometry.base import BaseGeometry

from . import data
from .catalog import Variable

THREADS = 16  # parallel requests to NASA per analysis


def _granules(var: Variable, start: str, end: str) -> list:
    import earthaccess

    data._login(interactive=False)
    end_ts = pd.Period(end, "M").end_time.strftime("%Y-%m-%d")
    return earthaccess.search_data(short_name=var.collection, version=var.version,
                                   temporal=(f"{start}-01", end_ts))


def _opendap_base(granule) -> str:
    for u in granule["umm"].get("RelatedUrls", []):
        if u.get("Subtype") == "OPENDAP DATA":
            return u["URL"]
    raise data.DataError(f"No cloud OPeNDAP link for {granule.data_links()[0]}")


def _find(ds: netCDF4.Dataset, name: str):
    """Find a variable by name anywhere in a (possibly nested) netCDF4 file.
    `name` may include a group path ("ascending/Data_Fields/X"); only the last part is matched,
    except when the same name exists in several groups, where the path decides."""
    if "/" in name:
        *groups, leaf = name.split("/")
        node = ds
        for g in groups:
            if g in node.groups:
                node = node.groups[g]
            else:
                node = None
                break
        if node is not None and leaf in node.variables:
            return node.variables[leaf]
        name = leaf
    if name in ds.variables:
        return ds.variables[name]
    for sub in ds.groups.values():
        found = _find(sub, name)
        if found is not None:
            return found
    return None


def _prefix(group: str | None) -> str:
    return f"/{group}" if group else ""


def _read_field(nc: netCDF4.Dataset, var: Variable) -> np.ndarray:
    """The variable (components summed, or averaged) as a float32 (lat, lon) array, NaN where
    missing, converted to the catalog's units."""
    parts = []
    for name in var.source_vars:
        v = _find(nc, name)
        if v is None:
            raise data.DataError(f"NASA's response has no '{name}'")
        if var.manual_scaling:
            # e.g. MODIS: its scale_factor means "divide by", the opposite of the usual
            # convention, so read raw integers and apply the catalog's scale ourselves.
            v.set_auto_maskandscale(False)
            a = np.asarray(v[:], dtype="float32")
            if var.fill_value is not None:
                a[a == var.fill_value] = np.nan
        else:
            a = np.ma.filled(np.ma.asarray(v[:], dtype="float32"), np.nan)
        a = a.reshape(a.shape[-2:])  # drop a length-1 time axis if present
        if var.dim_order == ("lon", "lat"):  # IMERG stores (lon, lat)
            a = a.T
        parts.append(a)
    if var.combine == "mean":  # e.g. AIRS day + night passes: use whichever exist
        with np.errstate(invalid="ignore"), warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)  # all-NaN cells stay NaN
            total = np.nanmean(np.stack(parts), axis=0)
    else:
        total = np.sum(np.stack(parts), axis=0)
    return (total * np.float32(var.scale) + np.float32(var.offset)).astype("float32")


def grid(var: Variable, sample_granule=None) -> tuple[np.ndarray, np.ndarray]:
    """The collection's full lat/lon coordinates, cached on disk after the first call."""
    path = data.DATA_DIR / "grids" / f"{var.collection}.npz"
    if path.exists():
        g = np.load(path)
        return g["lat"], g["lon"]
    if sample_granule is None:
        sample_granule = _granules(var, var.first_month, var.first_month)[0]
    import earthaccess

    p = _prefix(var.coord_group or var.group)
    ce = f"{p}/{var.lat_name};{p}/{var.lon_name}"
    url = _opendap_base(sample_granule) + ".dap.nc4?dap4.ce=" + quote(ce, safe="/")
    r = earthaccess.get_requests_https_session().get(url, timeout=120)
    r.raise_for_status()
    nc = netCDF4.Dataset("inmemory.nc", memory=r.content)
    lat = np.asarray(_find(nc, var.lat_name)[:], dtype="float64")
    lon = np.asarray(_find(nc, var.lon_name)[:], dtype="float64")
    if var.coords_2d:  # AIRS stores a full 2-D lat/lon grid; take the 1-D axes from it
        lat, lon = lat[:, 0], lon[0, :]
    path.parent.mkdir(parents=True, exist_ok=True)
    np.savez(path, lat=lat, lon=lon)
    return lat, lon


def _open_single_file(var: Variable, geom: BaseGeometry, start: str, end: str,
                      progress: data.Progress | None = None) -> xr.DataArray:
    """Datasets whose whole record is one small file (e.g. OMI/MLS monthly ozone, ~10 MB):
    download it once to data/datasets/<collection>/, then cut regions from the local copy."""
    import earthaccess

    folder = data.DATA_DIR / "datasets" / var.collection
    files = sorted(folder.glob("*.nc*")) if folder.exists() else []
    if not files:
        data._login(interactive=False)
        granules = earthaccess.search_data(short_name=var.collection, version=var.version)
        if not granules:
            raise data.DataError(f"NASA has no {var.collection} v{var.version} file.")
        folder.mkdir(parents=True, exist_ok=True)
        files = [Path(f) for f in earthaccess.download(granules[:1], local_path=str(folder)) if f]
        if not files:
            raise data.DataError(f"Couldn't download the {var.name} file from NASA.")
    if progress:
        progress(0, 1)
    with xr.open_dataset(files[0], decode_times=False) as ds:
        da = ds[var.source_var].load()
        lat_dim = ds[var.lat_name].dims[0]
        lon_dim = ds[var.lon_name].dims[0]
        times = pd.to_datetime([str(t) for t in ds["Time"].values], format="%b%Y")  # "Oct2004"
    time_dim = [d for d in da.dims if d not in (lat_dim, lon_dim)][0]
    da = da.rename({time_dim: "time", lat_dim: "lat", lon_dim: "lon"}).assign_coords(time=times)
    da = da.transpose("time", "lat", "lon").sortby("lat")
    lat, lon = da["lat"].values, da["lon"].values
    minx, miny, maxx, maxy = geom.bounds
    la0, la1 = _span(lat, miny, maxy)
    lo0, lo1 = _span(lon, minx, maxx)
    da = da.isel(lat=slice(la0, la1 + 1), lon=slice(lo0, lo1 + 1)).sel(time=slice(start, end))
    da = da.where(da > 0)  # no retrieval (e.g. polar night) -> NaN
    da = (da * np.float32(var.scale) + np.float32(var.offset)).astype("float32")
    if da.sizes["time"] == 0:
        raise data.DataError(f"NASA has no {var.name.lower()} data between {start} and {end}.")
    if progress:
        progress(1, 1)
    da.name = var.key
    da.attrs = {"units": var.units, "long_name": var.name, "source": "nasa-file"}
    return da


def _span(coord: np.ndarray, lo: float, hi: float) -> tuple[int, int]:
    """Inclusive index range of coord values within [lo, hi], padded by one cell;
    the nearest cell if the range falls between cells."""
    step = float(np.abs(np.diff(coord)).mean())
    idx = np.where((coord >= lo - step) & (coord <= hi + step))[0]
    if idx.size == 0:
        i = int(np.abs(coord - (lo + hi) / 2).argmin())
        return i, i
    return int(idx.min()), int(idx.max())


def open_region(var: Variable, geom: BaseGeometry, start: str, end: str,
                progress: data.Progress | None = None) -> xr.DataArray:
    """(time, lat, lon) data for the polygon's bounding box, start..end, in memory."""
    import earthaccess

    if var.single_file:
        return _open_single_file(var, geom, start, end, progress)

    granules = _granules(var, start, end)
    if not granules:
        raise data.DataError(f"NASA has no {var.name.lower()} data between {start} and {end}.")
    lat, lon = grid(var, granules[0])
    minx, miny, maxx, maxy = geom.bounds
    la0, la1 = _span(lat, miny, maxy)
    lo0, lo1 = _span(lon, minx, maxx)

    p = _prefix(var.group)
    order = {"lat": f"[{la0}:{la1}]", "lon": f"[{lo0}:{lo1}]"}
    dims = "".join(order[d] for d in var.dim_order)  # IMERG stores (lon, lat)
    t0 = "[0]" if var.has_time_dim else ""
    # One entry per component; a component may carry its own group path (AIRS day/night groups).
    # Coordinates aren't requested: they come from the cached grid.
    wanted = [(f"/{name}" if "/" in name else f"{p}/{name}") + t0 + dims for name in var.source_vars]
    query = ".dap.nc4?dap4.ce=" + quote(";".join(wanted), safe="/[]:")
    sub_lat, sub_lon = lat[la0:la1 + 1], lon[lo0:lo1 + 1]

    local = threading.local()

    def fetch(g) -> xr.DataArray:
        if not hasattr(local, "session"):
            local.session = earthaccess.get_requests_https_session()
        url = _opendap_base(g) + query
        last = None
        for _ in range(3):
            try:
                r = local.session.get(url, timeout=120)
                r.raise_for_status()
                nc = netCDF4.Dataset("inmemory.nc", memory=r.content)
                values = _read_field(nc, var)
                month = data.month_from_filename_str(g.data_links()[0])
                return xr.DataArray(values[None], dims=("time", "lat", "lon"),
                                    coords={"time": [month], "lat": sub_lat, "lon": sub_lon})
            except Exception as e:  # network hiccup: retry
                last = e
        raise data.DataError(f"NASA request failed for {g.data_links()[0].rsplit('/', 1)[-1]}: {last}")

    months: dict[pd.Timestamp, xr.DataArray] = {}
    if progress:
        progress(0, len(granules))
    with ThreadPoolExecutor(THREADS) as pool:
        futures = [pool.submit(fetch, g) for g in granules]
        for i, fut in enumerate(as_completed(futures), 1):
            da = fut.result()
            months[pd.Timestamp(da.time.values[0])] = da  # duplicates: keep one per month
            if progress:
                progress(i, len(granules))

    # NASA's search can return a file whose time range only touches the edge of the request
    # (e.g. AIRS's December file when asking from January); keep only the requested months.
    lo, hi = pd.Timestamp(f"{start}-01"), pd.Timestamp(f"{end}-01")
    keep = [m for m in sorted(months) if lo <= m <= hi]
    if not keep:
        raise data.DataError(f"NASA has no {var.name.lower()} data between {start} and {end}.")
    cube = xr.concat([months[m] for m in keep], dim="time")
    cube.name = var.key
    cube.attrs = {"units": var.units, "long_name": var.name, "source": "nasa-cloud"}
    return cube
