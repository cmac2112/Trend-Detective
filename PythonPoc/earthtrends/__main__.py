"""Command line interface.

  python -m earthtrends list
  python -m earthtrends fetch precip --start 2001-01 --end 2024-12
  python -m earthtrends fetch all
  python -m earthtrends build precip          # rebuild cube from already-downloaded files
  python -m earthtrends analyze precip examples/lake_mead.geojson
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

    args = p.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    if args.cmd == "list":
        for v in catalog.VARIABLES.values():
            have = "ready" if data.cube_path(v).exists() else "not downloaded"
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
            if args.var == "all" and not data.cube_path(catalog.get(key)).exists():
                print(f"skipping {key}: not downloaded")
                continue
            res = analyze(key, args.region)
            print_summary(res)
            stem = f"{Path(args.region).stem}_{key}"
            for path in save_outputs(res, Path(args.out), stem, show=show):
                print(f"  saved {path}")
        if show:
            print("\nChart window open - close it to finish.")
            show_figures()


if __name__ == "__main__":
    main()
