"""Command line interface.

  python -m earthtrends list
  python -m earthtrends fetch precip --start 2001-01 --end 2024-12
  python -m earthtrends fetch all
  python -m earthtrends build precip          # rebuild cube from already-downloaded files
  python -m earthtrends analyze precip examples/lake_mead.geojson     # local data if it covers it, else NASA cloud
  python -m earthtrends analyze t2m my_region.geojson --source cloud
  python -m earthtrends prepare-examples      # save the demo regions locally for offline presentations
"""
import argparse
import sys
from pathlib import Path

from . import catalog, data


def _keys(arg: str) -> list[str]:
    return list(catalog.VARIABLES) if arg == "all" else [catalog.get(arg).key]


def main() -> None:
    p = argparse.ArgumentParser(prog="earthtrends", description="Earth science trend detective")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("list", help="show available variables")

    f = sub.add_parser("fetch", help="download data and build the local cube")
    f.add_argument("var", help="variable key or 'all'")
    f.add_argument("--start", default="2001-01")
    f.add_argument("--end", default="2024-12")
    f.add_argument("--threads", type=int, default=4)

    b = sub.add_parser("build", help="(re)build cube from downloaded files")
    b.add_argument("var", help="variable key or 'all'")

    a = sub.add_parser("analyze", help="trend analysis for a polygon")
    a.add_argument("var", help="variable key or 'all'")
    a.add_argument("region", help="GeoJSON file with a Polygon/MultiPolygon (lon/lat)")
    a.add_argument("--out", default="output", help="folder for CSV/JSON/PNG")
    a.add_argument("--no-show", action="store_true", help="save files only, don't open a chart window")
    a.add_argument("--start", help="first month YYYY-MM (default 2001-01)")
    a.add_argument("--end", help="last month YYYY-MM (default December of last year)")
    a.add_argument("--source", choices=["auto", "local", "cloud"], default="auto",
                   help="where to read data: local copy, NASA cloud, or auto (local if it covers the request)")

    e = sub.add_parser("prepare-examples",
                       help="save small local copies of the example regions (for offline presentations)")
    e.add_argument("--start", default="2001-01")
    e.add_argument("--end", default="2024-12")
    e.add_argument("--var", default="all", help="variable key or 'all'")

    args = p.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    if args.cmd == "list":
        from . import local

        for v in catalog.VARIABLES.values():
            tiles = sorted(p.stem for p in local.tile_dir(v).glob("*.zarr")) if local.tile_dir(v).exists() else []
            have = ("global data local" if data.cube_path(v).exists() else "NASA cloud") +                 (f"; local examples: {', '.join(tiles)}" if tiles else "")
            print(f"{v.key:20s} {v.name} [{v.units}] - {v.collection} v{v.version} ({have})")
            print(f"{'':20s} {v.definition}\n")

    elif args.cmd == "fetch":
        done_collections = set()
        for key in _keys(args.var):
            var = catalog.get(key)
            if var.collection not in done_collections:
                data.download(var, args.start, args.end, args.threads)
                done_collections.add(var.collection)
            data.build_cube(var)

    elif args.cmd == "build":
        for key in _keys(args.var):
            data.build_cube(catalog.get(key))

    elif args.cmd == "analyze":
        from .analyze import analyze, print_summary, save_outputs, show_figures

        show = not args.no_show
        for key in _keys(args.var):
            res = analyze(key, args.region, start=args.start, end=args.end, source=args.source,
                          progress=_progress_printer(f"{key} from NASA cloud"))
            print_summary(res)
            stem = f"{Path(args.region).stem}_{key}"
            for path in save_outputs(res, Path(args.out), stem, show=show):
                print(f"  saved {path}")
        if show:
            print("\nChart window open - close it to finish.")
            show_figures()

    elif args.cmd == "prepare-examples":
        prepare_examples(_keys(args.var), args.start, args.end)


EXAMPLES_DIR = Path(__file__).resolve().parent.parent / "examples"


def prepare_examples(keys: list[str], start: str, end: str) -> None:
    """Stream each example region x variable from NASA's cloud once and keep a small
    local copy, so those analyses work offline and instantly."""
    from . import cloud, local, region

    for path in sorted(EXAMPLES_DIR.glob("*.geojson")):
        geom = region.load_polygon(path)
        for key in keys:
            var = catalog.get(key)
            s = max(start, var.first_month)
            e = min(end, var.last_month) if var.last_month else end
            if local.tile_covers(var, path.stem, geom, s, e):
                print(f"{path.stem} / {key}: already saved locally")
                continue
            da = cloud.open_region(var, geom, s, e, progress=_progress_printer(f"{path.stem} / {key}"))
            out = local.save_tile(da, var, path.stem)
            print(f"  saved {out} ({da.sizes['time']} months, {da.sizes['lat']}x{da.sizes['lon']} cells)")


def _progress_printer(label: str):
    def show(done: int, total: int) -> None:
        if done == total or done % 48 == 0:
            print(f"{label}: {done}/{total} months", flush=True)
    return show


if __name__ == "__main__":
    try:
        main()
    except data.DataError as e:
        raise SystemExit(f"Error: {e}")
