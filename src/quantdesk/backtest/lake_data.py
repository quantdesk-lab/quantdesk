"""Lake-backed candle source for the backtest.

Reads 1-minute OHLCV bars from a hive-partitioned Parquet lake keyed by
product id and resamples them deterministically; no network, no cache, no
exceptions on missing data. Bring your own candles -- docs/DATA.md documents
the layout and a small writer example. Layout
``{lake_root}/{venue}/candles_1m/date=YYYY-MM-DD/{HH}-{writer}.parquet``;
columns venue / product_id / ts (timestamp[us, UTC], candle OPEN time) /
open / high / low / close / volume (float64, base units). Files ending
``.tmp`` are in-progress writes and are never read.

Reader rules (each an explicit adaptation, pinned by tests/test_backtest_lake.py):

- Merge across every venue directory and every file; rows de-duplicate by
  ``ts`` with last write winning in (sorted file path, then row) order.
- Missing lake root, unknown product, or an unreadable file -> honest empty
  list / skipped file, never an exception (reader convention).
- ``start``/``end`` are applied to the 1-minute rows BEFORE resampling, so an
  ``end`` that cuts a bucket mid-way leaves that trailing bucket unfinished
  and it is dropped (see below) -- a window can never manufacture a bar.
- Resampling 1m -> coarser is deterministic: bucket key =
  floor(epoch_seconds / span); open = first row, high = max, low = min,
  close = last row, volume = sum; the emitted timestamp is the bucket start
  (UTC, epoch-aligned, so "1d" buckets open at UTC midnight).
- Interior buckets with recording gaps aggregate whatever minutes exist --
  their time span has fully elapsed, so they are finished bars.
- The TRAILING bucket is emitted only when its final minute is present (last
  1m open time + 60s reaches the bucket boundary). A partially covered final
  bucket would present an unfinished bar as finished -- no lookahead.
- A ``start`` that cuts a bucket mid-way yields a leading bucket built from
  the covered remainder, still stamped at the bucket floor: that is truncated
  history, not lookahead, so it is allowed (and pinned by a test).
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path

from .types import Bar

#: Resample targets: label → bucket span in seconds. "1day" is accepted as an
#: alias of "1d" so the legacy venue-style --granularity value
#: also works here. Keep in sync with config.PERIODS_PER_YEAR.
GRANULARITY_SECONDS: dict[str, int] = {
    "1m": 60,
    "5m": 5 * 60,
    "15m": 15 * 60,
    "30m": 30 * 60,
    "1h": 60 * 60,
    "4h": 4 * 60 * 60,
    "6h": 6 * 60 * 60,
    "12h": 12 * 60 * 60,
    "1d": 24 * 60 * 60,
    "1day": 24 * 60 * 60,
}

_CANDLE_COLUMNS = ["product_id", "ts", "open", "high", "low", "close", "volume"]


def default_lake_root() -> Path:
    """``$QUANTDESK_LAKE_ROOT`` when set, else ``./data/lake`` under the current
    working directory. Never a path baked in at import time."""
    env = os.environ.get("QUANTDESK_LAKE_ROOT")
    return Path(env) if env else Path.cwd() / "data" / "lake"


def read_1m_bars(
    lake_root: Path | str,
    product_id: str,
    start: datetime | None = None,
    end: datetime | None = None,
) -> list[Bar]:
    """Merged, de-duplicated (last write wins), time-sorted 1-minute Bars for
    one product across every venue directory under ``lake_root``.

    Defensive by contract: missing root or unreadable files yield an empty
    list / a skipped file, never an exception; ``*.tmp`` in-progress files are
    never read (docs/DATA.md). ``start``/``end`` filter on the 1m open time.
    """
    root = Path(lake_root)
    if not root.exists():
        return []
    import pyarrow.parquet as pq  # deferred: keep module import cheap

    by_ts: dict[datetime, Bar] = {}
    for path in sorted(root.glob("*/candles_1m/date=*/*.parquet")):
        if path.name.endswith(".tmp"):  # belt and braces; the glob already excludes them
            continue
        try:
            table = pq.read_table(path, columns=_CANDLE_COLUMNS)
        except Exception:  # noqa: BLE001 — a bad file is skipped, not fatal
            continue
        cols = [table.column(name).to_pylist() for name in _CANDLE_COLUMNS]
        for prod, ts, o, hi, lo, c, v in zip(*cols):
            if prod != product_id or ts is None:
                continue
            if o is None or hi is None or lo is None or c is None:
                continue
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            if start is not None and ts < start:
                continue
            if end is not None and ts > end:
                continue
            by_ts[ts] = Bar(
                timestamp=ts,
                open=float(o),
                high=float(hi),
                low=float(lo),
                close=float(c),
                volume=float(v) if v is not None else 0.0,
            )
    return [by_ts[k] for k in sorted(by_ts)]


def resample_1m(bars: list[Bar], granularity: str) -> list[Bar]:
    """Deterministic 1m → ``granularity`` OHLCV resample (rules in the module
    docstring). Input must be sorted by timestamp — read_1m_bars guarantees
    it. An unknown granularity raises ValueError: silently mis-bucketing an
    operator typo would answer a different question than the one asked.
    """
    try:
        span = GRANULARITY_SECONDS[granularity]
    except KeyError:
        raise ValueError(
            f"unsupported granularity {granularity!r}; supported: "
            + ", ".join(sorted(GRANULARITY_SECONDS))
        ) from None
    if span == 60 or not bars:
        return list(bars)

    out: list[Bar] = []
    key: int | None = None
    group: list[Bar] = []

    def flush() -> None:
        if key is None or not group:
            return
        out.append(
            Bar(
                timestamp=datetime.fromtimestamp(key * span, tz=timezone.utc),
                open=group[0].open,
                high=max(b.high for b in group),
                low=min(b.low for b in group),
                close=group[-1].close,
                volume=sum(b.volume for b in group),
            )
        )

    for b in bars:
        k = int(b.timestamp.timestamp()) // span
        if k != key:
            flush()  # bars are sorted, so the previous bucket is final
            key = k
            group = []
        group.append(b)

    # Trailing bucket: emit only if its final minute is present, i.e. the last
    # 1m bar's open time + 60s reaches the bucket boundary. A partially
    # covered final bucket must not appear (no lookahead).
    assert key is not None and group  # bars is non-empty here
    if int(group[-1].timestamp.timestamp()) + 60 >= (key + 1) * span:
        flush()
    return out


def load_lake_candles(
    product_id: str,
    granularity: str = "1h",
    *,
    lake_root: Path | str | None = None,
    start: datetime | None = None,
    end: datetime | None = None,
) -> list[Bar]:
    """The Bar rows the engine consumes (tz-aware UTC timestamp + float OHLCV),
    sourced from a parquet lake keyed by venue-native product ids (e.g.
    ``"BTC-USD"``). No network, no cache, no exceptions on missing data.
    """
    root = Path(lake_root) if lake_root is not None else default_lake_root()
    return resample_1m(read_1m_bars(root, product_id, start=start, end=end), granularity)
