"""Synthetic market-data fixtures - the ONLY data source the demo site uses.

Everything in this module is generated from a seeded geometric Brownian
motion (GBM). Nothing here is, or resembles, recorded venue data: no venue
data is stored, displayed, or redistributed by this package. The fixtures
exist so the research board, the ticket builder and the null calibration can
be exercised end to end, deterministically, with zero network access.

Shapes produced (all oldest -> newest):

- ``gbm_bars``          numeric candle rows ``[ts, o, h, l, c, v]``
- ``planted_bars``      the same rows with a planted AR(1) return component
                        (a known one-bar mean reversion for the search loop)
- ``SyntheticClient``   the injected-client surface the research board expects
                        (``get_candles(symbol, granularity, limit)`` returning
                        STRING candle rows with a still-forming last bar)
- ``synthetic_book``    ``{"bids": [[px, sz], ...], "asks": [[px, sz], ...]}``
- ``synthetic_trades``  ``[{"price", "size", "side"}, ...]``
- ``write_synthetic_lake`` lake_v1 ``candles_1m`` parquet (lazy pyarrow)

Pure stdlib apart from the optional parquet writer.
"""
from __future__ import annotations

import hashlib
import math
import random
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

# A fixed, obviously-synthetic epoch for timestamped fixtures that take no
# ``start_ts`` (2026-01-01T00:00:00Z). Real bars never start on this second.
DEFAULT_START_TS = 1_767_225_600.0

_GRANULARITY_SECONDS: dict[str, int] = {
    "1h": 3600, "ONE_HOUR": 3600, "one_hour": 3600, "3600": 3600,
    "1d": 86400, "ONE_DAY": 86400, "one_day": 86400, "86400": 86400,
    "1m": 60, "ONE_MINUTE": 60, "one_minute": 60, "60": 60,
}


def _stable_seed(*parts: Any) -> int:
    """Process-independent integer seed from arbitrary parts (Python's ``hash``
    of a str is salted per process, so it is not usable here)."""
    key = "|".join(str(p) for p in parts).encode("utf-8")
    return int.from_bytes(hashlib.sha256(key).digest()[:8], "big")


def bar_seconds_for(granularity: str | int | float) -> int:
    """Map a granularity label (``"1h"``/``"ONE_HOUR"``/``3600`` ...) to seconds.

    Synthetic/illustrative helper: accepts both the short labels the research
    board passes and the upper-case labels some venue APIs use.
    """
    if isinstance(granularity, (int, float)):
        secs = int(granularity)
    else:
        try:
            secs = _GRANULARITY_SECONDS[str(granularity)]
        except KeyError:
            raise ValueError(f"unknown granularity {granularity!r}") from None
    if secs <= 0:
        raise ValueError(f"granularity must be positive, got {granularity!r}")
    return secs


def gbm_bars(
    n: int,
    *,
    seed: int = 7,
    start_ts: float = DEFAULT_START_TS,
    bar_seconds: int = 3600,
    s0: float = 100.0,
    mu: float = 0.0,
    sigma: float = 0.02,
) -> list[list[float]]:
    """``n`` synthetic OHLCV rows ``[ts, o, h, l, c, v]`` from a seeded GBM.

    Illustrative data only. Per bar the close follows
    ``c_t = c_{t-1} * exp(mu + sigma * z_t)``; the open is the previous close
    (a 24/7 market has no overnight gap), the high/low straddle the body with
    a small lognormal wick, and volume is lognormal around 100 units. Prices
    are strictly positive by construction, ``high >= max(o, c)`` and
    ``low <= min(o, c)``, timestamps are ``start_ts + i * bar_seconds``.
    Fully determined by ``(n, seed, start_ts, bar_seconds, s0, mu, sigma)``.
    """
    if n < 0:
        raise ValueError("n must be >= 0")
    if s0 <= 0:
        raise ValueError("s0 must be > 0")
    if sigma < 0:
        raise ValueError("sigma must be >= 0")
    rng = random.Random(seed)
    rows: list[list[float]] = []
    prev_close = float(s0)
    for i in range(n):
        close = prev_close * math.exp(mu + sigma * rng.gauss(0.0, 1.0))
        rows.append([float(start_ts + i * bar_seconds), *_dress_bar(rng, prev_close, close, sigma)])
        prev_close = close
    return rows


def _dress_bar(
    rng: random.Random, prev_close: float, close: float, sigma: float
) -> tuple[float, float, float, float, float]:
    """``(open, high, low, close, volume)`` around a close: the open is the
    previous close, the high/low straddle the body with a small lognormal
    wick, volume is lognormal around 100 units. Shared by ``gbm_bars`` and
    ``planted_bars`` so the two fixtures differ only in their close path
    (three RNG draws per bar, in this order)."""
    open_ = prev_close
    body_hi, body_lo = max(open_, close), min(open_, close)
    wick = 0.25 * sigma if sigma > 0 else 0.001
    high = body_hi * (1.0 + wick * abs(rng.gauss(0.0, 1.0)))
    low = body_lo * (1.0 - wick * abs(rng.gauss(0.0, 1.0)))
    low = max(low, 1e-9)
    volume = 100.0 * math.exp(0.5 * rng.gauss(0.0, 1.0))
    return open_, high, low, close, volume


def planted_bars(
    n: int,
    *,
    seed: int = 7,
    start_ts: float = DEFAULT_START_TS,
    bar_seconds: int = 3600,
    s0: float = 100.0,
    mu: float = 0.0,
    sigma: float = 0.01,
    phi: float = -0.12,
) -> list[list[float]]:
    """``n`` synthetic OHLCV rows whose log returns carry a PLANTED AR(1)
    component: ``r_t = phi * r_{t-1} + sigma * sqrt(1 - phi^2) * z_t``,
    ``c_t = c_{t-1} * exp(mu + r_t)``. The innovation is scaled so the
    unconditional return variance equals the ``gbm_bars`` twin's; with
    ``phi = 0.0`` the output is bit-identical to ``gbm_bars`` for the same
    arguments (same RNG draw order, same candle dressing).

    Purpose: a synthetic series on which a one-bar mean-reversion expression
    has real, known predictive rank correlation (about ``0.93 * |phi|`` at
    horizon 1, decaying within a few bars) so the search loop can be shown
    recovering planted structure while its random-walk twin yields refusal.
    Illustrative data only; no relationship to any real asset. ``|phi| < 1``.
    """
    if n < 0:
        raise ValueError("n must be >= 0")
    if s0 <= 0:
        raise ValueError("s0 must be > 0")
    if sigma < 0:
        raise ValueError("sigma must be >= 0")
    if not abs(phi) < 1.0:
        raise ValueError("phi must satisfy |phi| < 1")
    rng = random.Random(seed)
    rows: list[list[float]] = []
    prev_close = float(s0)
    innov = sigma * math.sqrt(1.0 - phi * phi)
    r_prev = 0.0
    for i in range(n):
        r = phi * r_prev + innov * rng.gauss(0.0, 1.0)
        close = prev_close * math.exp(mu + r)
        rows.append([float(start_ts + i * bar_seconds), *_dress_bar(rng, prev_close, close, sigma)])
        prev_close = close
        r_prev = r
    return rows


def split_ohlcv(rows: list[list[float]]) -> dict[str, list[float]]:
    """``{"ts", "o", "h", "l", "c", "v"}`` column lists from ``gbm_bars`` rows
    (numeric or string fields; illustrative convenience)."""
    out: dict[str, list[float]] = {k: [] for k in ("ts", "o", "h", "l", "c", "v")}
    for row in rows:
        for key, val in zip(("ts", "o", "h", "l", "c", "v"), row):
            out[key].append(float(val))
    return out


class SyntheticClient:
    """Injected-client stand-in for the research board - synthetic GBM only.

    Matches the surface ``build_symbol_factors`` / ``compute_factors`` call:
    ``get_candles(symbol, granularity, limit)`` returning candle rows
    ``[ts, o, h, l, c, v]`` as STRINGS, oldest -> newest, aligned to bar
    boundaries, with the LAST row still forming (its open time plus the bar
    length exceeds ``now``) so the board's closed-bar drop is exercised.

    The price path is derived per ``(symbol, granularity, seed)`` through a
    stable hash, so ``"SYN-1"`` and ``"SYN-2"`` get distinct, reproducible
    series and the hourly and daily series of one symbol differ. ``limit``
    slices the tail of a fixed-length path (``max_bars``), so a shorter
    request sees the same recent bars as a longer one.

    ``raise_for``: symbols (or the literal ``"candles"`` for every symbol)
    whose fetch raises ``ConnectionError`` - for failure-isolation tests.
    """

    def __init__(
        self,
        *,
        seed: int = 0,
        now: float | None = None,
        max_bars: int = 400,
        s0: float = 100.0,
        sigma_1h: float = 0.01,
        sigma_1d: float = 0.03,
        mu: float = 0.0,
        raise_for: set[str] | None = None,
    ) -> None:
        self.seed = int(seed)
        self.now = float(now) if now is not None else time.time()
        self.max_bars = int(max_bars)
        self.s0 = float(s0)
        self.sigma = {3600: float(sigma_1h), 86400: float(sigma_1d)}
        self.mu = float(mu)
        self.raise_for = set(raise_for or ())
        self._cache: dict[tuple[str, int], list[list[float]]] = {}
        self.calls: list[tuple[str, str, int]] = []

    def _path(self, symbol: str, secs: int) -> list[list[float]]:
        key = (symbol, secs)
        if key not in self._cache:
            sigma = self.sigma.get(secs, 0.02)
            seed = _stable_seed("quantdesk.demo", symbol, secs, self.seed)
            # The forming bar opens on the boundary at-or-before ``now``; the
            # path is laid out backwards from it on exact bar boundaries.
            t_form = math.floor(self.now / secs) * secs
            start = t_form - (self.max_bars - 1) * secs
            self._cache[key] = gbm_bars(
                self.max_bars, seed=seed, start_ts=start, bar_seconds=secs,
                s0=self.s0, mu=self.mu, sigma=sigma,
            )
        return self._cache[key]

    def get_candles(
        self, symbol: str, granularity: str = "1h", limit: int = 350
    ) -> list[list[str]]:
        """String candle rows for ``symbol``; the last row is still forming."""
        self.calls.append((symbol, str(granularity), int(limit)))
        if symbol in self.raise_for or "candles" in self.raise_for:
            raise ConnectionError(f"synthetic fetch failure for {symbol}")
        secs = bar_seconds_for(granularity)
        rows = self._path(symbol, secs)
        take = max(0, min(int(limit), len(rows)))
        return [[str(v) for v in row] for row in rows[len(rows) - take:]]

    def closed_bars(
        self, symbol: str, granularity: str = "1d", limit: int = 350
    ) -> list[list[float]]:
        """Numeric ``[ts, o, h, l, c, v]`` rows WITHOUT the forming last bar -
        exactly the bars the research board keeps after its closed-bar drop,
        ready for the ticket builder / backtest. Same per-symbol path as
        ``get_candles``."""
        rows = self.get_candles(symbol, granularity, limit)
        secs = bar_seconds_for(granularity)
        return [[float(v) for v in row] for row in rows if float(row[0]) + secs <= self.now]

    def close(self) -> None:  # mirrors the real client surface; nothing to release
        return None


def synthetic_book(
    n_levels: int = 10,
    mid: float = 100.0,
    seed: int = 0,
    *,
    tick: float = 0.01,
    spread_ticks: int = 2,
) -> dict[str, list[list[float]]]:
    """Synthetic top-``n_levels`` order book around ``mid`` in the
    ``{"bids": [[px, sz], ...], "asks": [[px, sz], ...]}`` shape the
    microstructure factors consume (bids descending, asks ascending, sizes
    lognormal). Illustrative only - not a recorded snapshot."""
    if n_levels <= 0:
        raise ValueError("n_levels must be > 0")
    if mid <= 0 or tick <= 0:
        raise ValueError("mid and tick must be > 0")
    rng = random.Random(_stable_seed("book", seed))
    half = max(1, spread_ticks) * tick / 2.0
    best_bid = round(mid - half, 8)
    best_ask = round(mid + half, 8)
    bids = [[round(best_bid - i * tick, 8), round(2.0 * math.exp(0.6 * rng.gauss(0, 1)), 6)]
            for i in range(n_levels)]
    asks = [[round(best_ask + i * tick, 8), round(2.0 * math.exp(0.6 * rng.gauss(0, 1)), 6)]
            for i in range(n_levels)]
    return {"bids": bids, "asks": asks}


def synthetic_trades(
    n: int = 50,
    mid: float = 100.0,
    seed: int = 0,
    *,
    tick: float = 0.01,
    buy_prob: float = 0.5,
) -> list[dict[str, Any]]:
    """``n`` synthetic prints ``[{"price", "size", "side"}, ...]`` (oldest ->
    newest) around a random walk from ``mid``; ``side`` is ``"buy"``/``"sell"``
    with a Bernoulli(``buy_prob``) taker side. Illustrative only."""
    if n < 0:
        raise ValueError("n must be >= 0")
    rng = random.Random(_stable_seed("trades", seed))
    px = float(mid)
    out: list[dict[str, Any]] = []
    for _ in range(n):
        px = max(tick, px + tick * rng.choice((-1, 0, 0, 1)))
        side = "buy" if rng.random() < buy_prob else "sell"
        size = round(math.exp(0.8 * rng.gauss(0, 1)), 6)
        out.append({"price": round(px, 8), "size": size, "side": side})
    return out


def write_synthetic_lake(
    root: Path | str,
    symbol: str,
    days: int,
    seed: int = 0,
    *,
    venue: str = "synthetic",
    start: datetime | None = None,
    s0: float = 100.0,
    sigma_1m: float = 0.0008,
    writer: str = "synthetic",
) -> list[Path] | None:
    """Write ``days`` UTC days of synthetic 1-minute candles into a lake_v1
    tree ``<root>/<venue>/candles_1m/date=YYYY-MM-DD/00-<writer>.parquet``
    using the package's own candle schema (one file per day).

    Returns the written paths, or ``None`` when pyarrow is not installed (the
    lake is an optional extra; the caller decides whether that is fatal).
    Synthetic/illustrative data only - never a venue recording.
    """
    try:
        import pyarrow as pa
        import pyarrow.parquet as pq
    except ImportError:
        return None
    from quantdesk.lake.schemas import candles_schema

    if days < 0:
        raise ValueError("days must be >= 0")
    day0 = start if start is not None else datetime(2026, 1, 1, tzinfo=timezone.utc)
    if day0.tzinfo is None:
        day0 = day0.replace(tzinfo=timezone.utc)
    root = Path(root)
    schema = candles_schema()
    rows = gbm_bars(
        1440 * days, seed=_stable_seed("lake", symbol, seed),
        start_ts=day0.timestamp(), bar_seconds=60, s0=s0, sigma=sigma_1m,
    )
    written: list[Path] = []
    for d in range(days):
        chunk = rows[d * 1440:(d + 1) * 1440]
        day = day0 + timedelta(days=d)
        path = (root / venue / "candles_1m" / f"date={day.date().isoformat()}"
                / f"00-{writer}.parquet")
        path.parent.mkdir(parents=True, exist_ok=True)
        table = pa.table(
            {
                "venue": [venue] * len(chunk),
                "product_id": [symbol] * len(chunk),
                "ts": pa.array(
                    [datetime.fromtimestamp(r[0], tz=timezone.utc) for r in chunk],
                    type=pa.timestamp("us", tz="UTC"),
                ),
                "open": [r[1] for r in chunk],
                "high": [r[2] for r in chunk],
                "low": [r[3] for r in chunk],
                "close": [r[4] for r in chunk],
                "volume": [r[5] for r in chunk],
            },
            schema=schema,
        )
        pq.write_table(table, path)
        written.append(path)
    return written
