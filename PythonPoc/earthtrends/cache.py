"""In-memory cache of finished analyses.

Streaming 24 years from NASA's cloud takes ~30 s; repeating the same region, variable
and period should be instant. Results are keyed by (variable, polygon shape, start,
end). The polygon is snapped to ~10 m precision so a re-sent copy of the same shape
still matches.

The cache lives in memory, holds at most MAX_ENTRIES results (~20 KB each) and drops
the least recently used first, so it can't grow without bound. It's cleared when the
process restarts.
"""
from __future__ import annotations

import copy
import hashlib
import threading
from collections import OrderedDict

import shapely
from shapely.geometry.base import BaseGeometry

MAX_ENTRIES = 512


def key(var_key: str, geom: BaseGeometry, start: str, end: str) -> str:
    snapped = shapely.set_precision(geom, 1e-4).normalize()
    shape_hash = hashlib.sha1(shapely.to_wkb(snapped)).hexdigest()[:16]
    return f"{var_key}|{shape_hash}|{start}|{end}"


class ResultCache:
    def __init__(self, max_entries: int = MAX_ENTRIES):
        self.max_entries = max_entries
        self._items: OrderedDict[str, dict] = OrderedDict()
        self._lock = threading.Lock()
        self.hits = 0
        self.misses = 0

    def get(self, k: str) -> dict | None:
        with self._lock:
            item = self._items.get(k)
            if item is None:
                self.misses += 1
                return None
            self._items.move_to_end(k)
            self.hits += 1
        result = copy.deepcopy(item)
        result["data_source"] = {**result["data_source"], "cached": True}
        return result

    def contains(self, k: str) -> bool:
        with self._lock:
            return k in self._items

    def put(self, k: str, result: dict) -> None:
        with self._lock:
            self._items[k] = copy.deepcopy(result)
            self._items.move_to_end(k)
            while len(self._items) > self.max_entries:
                self._items.popitem(last=False)

    def clear(self) -> None:
        with self._lock:
            self._items.clear()
            self.hits = self.misses = 0

    def stats(self) -> dict:
        with self._lock:
            return {"entries": len(self._items), "max_entries": self.max_entries,
                    "hits": self.hits, "misses": self.misses}


RESULTS = ResultCache()
