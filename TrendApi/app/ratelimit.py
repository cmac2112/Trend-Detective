"""Per-client rate limiting, so a public deployment can't be abused.

Each request is put in a tier by its method and path, and each tier allows a number of
requests per client IP in one or more sliding windows (e.g. 15 a minute AND 300 a day).
Over the limit, the API answers 429 with a Retry-After header and a readable message,
which the React client shows like any other error.

The counters live in memory, which is right for this API: it runs as ONE process (jobs and
the result cache are in memory too). Running several instances would need a shared store
such as Redis instead.

The client IP comes from the connection. Behind Azure's ingress, uvicorn must run with
--proxy-headers so that is the caller's address (from X-Forwarded-For), not the proxy's;
the Dockerfile does this.

Settings (environment variables):
  RATE_LIMIT_ENABLED   1 (default) or 0 to turn limiting off
  RATE_LIMIT_<TIER>    override a tier, e.g. RATE_LIMIT_ANALYSIS="15/minute,300/day"
                       tiers: ANALYSIS, DRIVERS, POLL, DEFAULT
"""
from __future__ import annotations

import json
import math
import os
import re
import threading
import time
from collections import deque

WINDOWS = {"second": 1, "minute": 60, "hour": 3600, "day": 86400}

# (tier, description shown to the user, default limits)
TIERS = {
    # Each starts NASA streaming (or reads the cache): the expensive part of the app.
    "analysis": ("analyses", "15/minute,300/day"),
    # Cause analysis streams several variables AND calls Claude (costs money per call).
    "drivers": ("cause analyses", "5/minute,50/day"),
    # The client polls a running job once a second; allow a few tabs at once.
    "poll": ("progress checks", "240/minute"),
    # Everything else: variables, examples, plans. Cheap.
    "default": ("requests", "120/minute"),
}

_ROUTES = [
    ("POST", re.compile(r"^/(analyze|compare)(/jobs)?/?$"), "analysis"),
    ("POST", re.compile(r"^/drivers(/jobs)?/?$"), "drivers"),
    ("GET", re.compile(r"^/jobs/[^/]+/?$"), "poll"),
]
# Never limited: health probes from Azure, and CORS preflights.
_EXEMPT_PATHS = {"/health"}

MAX_TRACKED_CLIENTS = 20_000  # memory bound; the oldest idle clients are forgotten first


def parse_limits(spec: str) -> list[tuple[int, int]]:
    """'15/minute,300/day' -> [(15, 60), (300, 86400)]."""
    limits = []
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        count, _, unit = part.partition("/")
        unit = unit.strip().lower().rstrip("s")
        if unit not in WINDOWS or not count.strip().isdigit() or int(count) < 1:
            raise ValueError(f"Bad rate limit '{part}': use e.g. '15/minute' ({', '.join(WINDOWS)})")
        limits.append((int(count), WINDOWS[unit]))
    if not limits:
        raise ValueError(f"Empty rate limit '{spec}'")
    return limits


def tier_for(method: str, path: str) -> str | None:
    if method == "OPTIONS" or path in _EXEMPT_PATHS:
        return None
    for m, pattern, tier in _ROUTES:
        if method == m and pattern.match(path):
            return tier
    return "default"


def _describe(count: int, window: int) -> str:
    unit = next(name for name, secs in WINDOWS.items() if secs == window)
    return f"{count} per {unit}"


class RateLimiter:
    def __init__(self, limits: dict[str, list[tuple[int, int]]], clock=time.monotonic):
        self.limits = limits
        self.clock = clock
        self._hits: dict[tuple[str, str], deque] = {}
        self._lock = threading.Lock()

    @classmethod
    def from_env(cls) -> "RateLimiter":
        limits = {t: parse_limits(os.environ.get(f"RATE_LIMIT_{t.upper()}", spec))
                  for t, (_, spec) in TIERS.items()}
        return cls(limits)

    def check(self, tier: str, client: str) -> tuple[bool, float, str]:
        """Record one request. Returns (allowed, seconds until allowed again, limit text)."""
        now = self.clock()
        rules = self.limits[tier]
        longest = max(w for _, w in rules)
        key = (tier, client)
        with self._lock:
            hits = self._hits.get(key)
            if hits is None:
                if len(self._hits) >= MAX_TRACKED_CLIENTS:
                    self._forget_idle(now)
                hits = self._hits[key] = deque()
            while hits and now - hits[0] >= longest:
                hits.popleft()
            for count, window in rules:
                # requests inside this window (hits are in time order, newest last)
                inside = [t for t in hits if now - t < window] if window < longest else list(hits)
                if len(inside) >= count:
                    retry = inside[-count] + window - now
                    return False, max(retry, 0.0), _describe(count, window)
            hits.append(now)
            return True, 0.0, ""

    def _forget_idle(self, now: float) -> None:
        def last(item):
            return item[1][-1] if item[1] else -math.inf
        for key, _ in sorted(self._hits.items(), key=last)[: max(1, len(self._hits) // 10)]:
            self._hits.pop(key, None)

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


def enabled() -> bool:
    return os.environ.get("RATE_LIMIT_ENABLED", "1").strip().lower() not in ("0", "false", "no")


# The one limiter for this process (tests can swap or reset it).
LIMITER = RateLimiter.from_env()


class RateLimitMiddleware:
    """Plain ASGI middleware. Add it BEFORE CORSMiddleware, so CORS is the outer layer and
    429 responses still carry CORS headers (otherwise the browser hides the message)."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or not enabled():
            return await self.app(scope, receive, send)
        tier = tier_for(scope["method"], scope["path"])
        if tier is None:
            return await self.app(scope, receive, send)
        client = (scope.get("client") or ("unknown", 0))[0]
        allowed, retry, limit = LIMITER.check(tier, client)
        if allowed:
            return await self.app(scope, receive, send)

        wait = max(1, math.ceil(retry))
        what = TIERS[tier][0]
        body = json.dumps({"detail": f"Too many {what} from your address (limit: {limit}). "
                                     f"Try again in {_human(wait)}."}).encode()
        await send({"type": "http.response.start", "status": 429, "headers": [
            (b"content-type", b"application/json"),
            (b"retry-after", str(wait).encode()),
            (b"content-length", str(len(body)).encode()),
        ]})
        await send({"type": "http.response.body", "body": body})


def _human(seconds: int) -> str:
    if seconds < 90:
        return f"{seconds} s"
    if seconds < 5400:
        return f"{round(seconds / 60)} min"
    return f"{round(seconds / 3600)} h"
