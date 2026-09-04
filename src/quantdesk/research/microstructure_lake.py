"""Lake-fed microstructure panel -- the consumer wiring for quantdesk/factors/microstructure.py.

Kept separate from board.py so the candle/alpha plane and the order-book plane
stay separately readable; board.py attaches the section this module builds to
every symbol row.

Data source is the hive-partitioned Parquet lake (docs/DATA.md):

- ``{lake_root}/{venue}/book_top10/date=*/HH-writer.parquet`` -- throttled
  top-10 book snapshots. We tail the most recent ``_BOOK_TAIL_N`` snapshots
  for the product (newest-first file walk with early stop, then re-sorted
  oldest -> newest) and convert each row to the ``{"bids": [[px, sz], ...],
  "asks": [[px, sz], ...]}`` shape the factor functions expect. NaN levels
  (depth < 10 per the schema) pass through -- microstructure._levels drops
  non-finite levels itself, and the integration tests prove that end to end.
- ``{lake_root}/{venue}/market_trades/date=*/...`` -- taker prints inside the
  book-snapshot window feed the two trade-flow factors. Sides are venue
  convention ``BUY``/``SELL``; microstructure._signed normalizes case.

Payload honesty (mirrors the board.py register):

- Book-shape factors are per-snapshot SERIES -> latest value + mean/std/n over
  the window. Trade-flow factors are single WINDOW AGGREGATES (trade_flow /
  kyle_lambda_proxy consume the whole tape at once) and are flagged
  ``window_aggregate`` instead of pretending to have a series.
- NO IC / decay / turnover is attached -- there is no evaluation history for
  these yet; every section carries ``"observables only; no IC evaluation yet"``
  and the use-class line from the microstructure module docstring (execution
  timing / regime features, never standalone alpha at 60-120bps/side).
- Missing lake, missing table, or no rows for the product -> the first-class
  empty state ``{"available": False, "note": "no book_top10 data in the lake
  yet (see docs/DATA.md)"}`` -- never an exception into the caller.
- ``*.tmp`` files are in-progress writes and are never read (docs/DATA.md).

Pure stdlib + pyarrow (imported lazily inside the readers, so importing this
module never requires pyarrow). The default lake root is
``$QUANTDESK_LAKE_ROOT`` or ``./data/lake``.
"""
from __future__ import annotations

import math
import os
import statistics
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

from ..factors.microstructure import (
    book_pressure,
    kyle_lambda_proxy,
    micro_price,
    queue_imbalance,
    snapshot_ofi,
    spread_bps,
    trade_flow,
)

_DEFAULT_LAKE_ROOT = Path(
    os.environ.get("QUANTDESK_LAKE_ROOT") or (Path.cwd() / "data" / "lake")
)
_BOOK_SCAN_MAX_AGE_S = 48 * 3600.0  # book snapshots older than this (vs the newest file) never feed a live panel
_BOOK_TAIL_N = 600     # snapshots tailed per product (~1 min at the 100ms throttle floor)
_MAX_TRADES = 5000     # newest prints kept inside the book window
_N_LEVELS = 10         # book_top10 contract depth

_NO_DATA_NOTE = "no book_top10 data in the lake yet (see docs/DATA.md)"
_NOTE = "observables only; no IC evaluation yet"
_USE_CLASS = (
    "execution-layer timing / hour-aggregated regime features — never standalone "
    "alpha at 60-120bps/side fees (quantdesk/factors/microstructure.py)"
)
_TRADES_NOTE = (
    "no market_trades rows inside the book window — trade-flow factors "
    "(tfi/cvd/flow_accel/intensity/large_share/impact_bps_per_unit) unavailable"
)

# Paper lineage per displayed key (docstring citations, compacted for the payload).
_CITATIONS = {
    "micro_dev_bps": "Stoikov (2017) micro-price, arXiv:1708.03135 — deviation from mid in bps",
    "queue_imbalance": "Gould & Bonart (2016) best-level queue imbalance",
    "book_pressure": "depth-weighted multi-level imbalance (Cont-Kukanov-Stoikov / MLOFI lineage)",
    "depth_ratio": "plain top-10 depth ratio (book_pressure companion output)",
    "spread_bps": "relative bid-ask spread — instantaneous cost-of-immediacy",
    "snapshot_ofi": (
        "Cont-Kukanov-Stoikov (2014) OFI, arXiv:1011.6402 — snapshot-diff "
        "approximation, NOT event-level e_n (book feed is throttled snapshots)"
    ),
    "tfi": "Silantyev (2019) trade-flow imbalance",
    "cvd": "cumulative volume delta over the window (trade_flow)",
    "flow_accel": "TFI(second half) - TFI(first half) (trade_flow)",
    "intensity": "trade count in window — activity-clock proxy (trade_flow)",
    "large_share": "gross-volume share of prints > 3x mean size (trade_flow)",
    "impact_bps_per_unit": "Kyle-lambda-flavor impact proxy (Amihud intuition at trade frequency)",
}

_BOOK_COLS = ["product_id", "ts"] + [
    f"{side}_{kind}_{i}"
    for side in ("bid", "ask")
    for kind in ("px", "sz")
    for i in range(1, _N_LEVELS + 1)
]
_TRADE_COLS = ["product_id", "ts", "price", "size", "side"]


def _safe(fn: Callable[[], Any], default: Any = None) -> Any:
    try:
        return fn()
    except Exception:  # noqa: BLE001 — one dead factor must not kill the section
        return default


# --------------------------------------------------------------------------- #
# lake readers
# --------------------------------------------------------------------------- #
def _parquet_files(table_dir: Path) -> list[Path]:
    """Finalized partition files, oldest -> newest. ``date=YYYY-MM-DD`` dirs and
    ``HH-writer`` names are zero-padded, so lexicographic sort is chronological.
    ``*.tmp`` in-progress writes are excluded by pattern AND by explicit guard
    (docs/DATA.md: never read them)."""
    if not table_dir.is_dir():
        return []
    return sorted(
        p for p in table_dir.glob("date=*/*.parquet") if not p.name.endswith(".tmp")
    )


def _as_utc(ts: Any) -> datetime | None:
    if not isinstance(ts, datetime):
        return None
    return ts.replace(tzinfo=timezone.utc) if ts.tzinfo is None else ts


def _row_book(cols: dict[str, list], i: int) -> dict[str, list[list[float]]]:
    """Lake row -> the {"bids": [[px, sz], ...], "asks": ...} shape the factor
    functions expect. Levels arrive best-first per the schema; None cells are
    dropped here, NaN cells (depth < 10) are passed through for
    microstructure._levels to reject — one defense, exercised end to end."""
    book: dict[str, list[list[float]]] = {"bids": [], "asks": []}
    for side, key in (("bid", "bids"), ("ask", "asks")):
        for lvl in range(1, _N_LEVELS + 1):
            px = cols[f"{side}_px_{lvl}"][i]
            sz = cols[f"{side}_sz_{lvl}"][i]
            if px is None or sz is None:
                continue
            book[key].append([px, sz])
    return book


def _tail_books(files: list[Path], product_id: str, n: int) -> list[tuple[datetime, dict]]:
    """Newest ``n`` book snapshots for one product, returned oldest -> newest.

    Walks files newest-first and stops as soon as enough rows are collected,
    so a long-running lake never makes the panel read history it will not use.
    Snapshots are deduped by ts; the newest-written row wins (files are walked
    newest-first and rows within a file are walked last-first, so the first
    occurrence seen IS the last written). Unreadable files are skipped.

    Two scan bounds keep a product that is NOT in the lake from triggering a
    full-history scan (measured on a real lake: 537 files / 1.2 GB = 55
    minutes): the walk stops at files older than _BOOK_SCAN_MAX_AGE_S before
    the NEWEST file present (newest-anchored, so replayed fixtures still
    read), and each file is probed by its product_id column alone before any
    full column conversion."""
    import pyarrow.parquet as pq

    floor = None
    if files:
        newest_end = _file_hour_end(files[-1])
        if newest_end is not None:
            floor = newest_end - timedelta(seconds=_BOOK_SCAN_MAX_AGE_S)
    by_ts: dict[datetime, dict] = {}
    for path in reversed(files):
        if floor is not None:
            hour_end = _file_hour_end(path)
            if hour_end is not None and hour_end < floor:
                break  # older than any live panel cares about
        try:
            tbl = pq.read_table(path, columns=_BOOK_COLS)
        except Exception:  # noqa: BLE001 — a bad file is skipped, not fatal
            continue
        pids = tbl.column("product_id").to_pylist()
        if product_id not in pids:
            continue  # one-column probe: skip converting 40+ book columns
        cols = {name: tbl.column(name).to_pylist() for name in tbl.column_names}
        stamps = cols["ts"]
        for i in range(tbl.num_rows - 1, -1, -1):
            if pids[i] != product_id:
                continue
            ts = _as_utc(stamps[i])
            if ts is None:
                continue
            by_ts.setdefault(ts, _row_book(cols, i))
        if len(by_ts) >= n:
            break
    return sorted(by_ts.items())[-n:]


def _file_hour_end(path: Path) -> datetime | None:
    """UTC end of the hour a partition file covers, parsed from the contract
    path ``date=YYYY-MM-DD/HH-writer.parquet``; None when unparseable."""
    try:
        date_s = path.parent.name.split("=", 1)[1]
        hour = int(path.name.split("-", 1)[0])
        day = datetime.strptime(date_s, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        return day.replace(hour=hour) + timedelta(hours=1)
    except Exception:  # noqa: BLE001
        return None


def _window_trades(
    trades_dir: Path, product_id: str, t0: datetime, t1: datetime, cap: int
) -> list[dict[str, Any]]:
    """Prints for one product inside [t0, t1], oldest -> newest, capped to the
    newest ``cap``. Files older than the window (by their contract path hour)
    stop the newest-first walk early."""
    import pyarrow.parquet as pq

    files = _parquet_files(trades_dir)
    out: list[tuple[datetime, dict[str, Any]]] = []
    for path in reversed(files):
        try:
            tbl = pq.read_table(path, columns=_TRADE_COLS)
        except Exception:  # noqa: BLE001
            continue
        cols = {name: tbl.column(name).to_pylist() for name in tbl.column_names}
        for i in range(tbl.num_rows):
            if cols["product_id"][i] != product_id:
                continue
            ts = _as_utc(cols["ts"][i])
            if ts is None or ts < t0 or ts > t1:
                continue
            out.append((ts, {
                "price": cols["price"][i],
                "size": cols["size"][i],
                "side": cols["side"][i],
            }))
        hour_end = _file_hour_end(path)
        if hour_end is not None and hour_end <= t0:
            break  # every remaining (older) file predates the window
    out.sort(key=lambda pair: pair[0])
    return [row for _, row in out[-cap:]]


def _pick_venue(root: Path, product_id: str, tail_n: int) -> tuple[str | None, list]:
    """The venue whose newest snapshot for this product is freshest (books from
    different venues must never be interleaved into one series). Usually a
    single venue; the loop is for contract completeness."""
    best_venue: str | None = None
    best_books: list = []
    if not root.is_dir():
        return None, []
    for venue_dir in sorted(p for p in root.iterdir() if p.is_dir()):
        books = _tail_books(_parquet_files(venue_dir / "book_top10"), product_id, tail_n)
        if books and (not best_books or books[-1][0] > best_books[-1][0]):
            best_venue, best_books = venue_dir.name, books
    return best_venue, best_books


# --------------------------------------------------------------------------- #
# payload entries
# --------------------------------------------------------------------------- #
def _finite(v: Any) -> float | None:
    return float(v) if isinstance(v, (int, float)) and math.isfinite(v) else None


def _series_entry(vals: list[float | None]) -> dict[str, Any]:
    """latest value (None if the newest snapshot is degenerate — the
    _factor_row 'value is null this bar' convention) + mean / sample std / n
    over the valid window values."""
    xs = [f for f in (_finite(v) for v in vals) if f is not None]
    latest = _finite(vals[-1]) if vals else None
    return {
        "value": round(latest, 4) if latest is not None else None,
        "mean": round(statistics.fmean(xs), 4) if xs else None,
        "std": round(statistics.stdev(xs), 4) if len(xs) >= 2 else None,
        "n": len(xs),
    }


def _aggregate_entry(value: Any, n_trades: int) -> dict[str, Any]:
    v = _finite(value)
    return {
        "value": round(v, 4) if v is not None else None,
        "n": n_trades,
        "window_aggregate": True,  # one value over the whole tape — no series stats
    }


# --------------------------------------------------------------------------- #
# section builder — what factors.py attaches per symbol
# --------------------------------------------------------------------------- #
def build_micro_section(
    product_id: str,
    lake_root: str | Path | None = None,
    *,
    tail_n: int = _BOOK_TAIL_N,
    max_trades: int = _MAX_TRADES,
    now: float | None = None,
) -> dict[str, Any]:
    """The per-symbol ``microstructure`` payload section. Never raises."""
    root = Path(lake_root) if lake_root is not None else _DEFAULT_LAKE_ROOT
    try:
        venue, books = _pick_venue(root, product_id, tail_n)
    except Exception as exc:  # noqa: BLE001 — e.g. pyarrow missing: honest, not fatal
        return {"available": False,
                "note": f"book_top10 reader failed: {type(exc).__name__}: {exc}"}
    if not venue or not books:
        return {"available": False, "note": _NO_DATA_NOTE}

    # Book-shape factors: one value per snapshot, oldest -> newest.
    dev: list = []
    qi: list = []
    press: list = []
    depth: list = []
    spread: list = []
    for _, book in books:
        mp = _safe(lambda b=book: micro_price(b))
        dev.append(mp["deviation_bps"] if mp else None)
        qi.append(_safe(lambda b=book: queue_imbalance(b)))
        bp = _safe(lambda b=book: book_pressure(b))
        press.append(bp["pressure"] if bp else None)
        depth.append(bp["depth_ratio"] if bp else None)
        spread.append(_safe(lambda b=book: spread_bps(b)))
    ofi: list = [None]  # aligned to snapshots; element t diffs t-1 -> t
    for (_, prev), (_, curr) in zip(books, books[1:]):
        ofi.append(_safe(lambda p=prev, c=curr: snapshot_ofi(p, c)))

    factors: dict[str, Any] = {
        "micro_dev_bps": _series_entry(dev),
        "queue_imbalance": _series_entry(qi),
        "book_pressure": _series_entry(press),
        "depth_ratio": _series_entry(depth),
        "spread_bps": _series_entry(spread),
        "snapshot_ofi": _series_entry(ofi),
    }

    # Trade-flow factors: whole-window aggregates from market_trades.
    t0, t1 = books[0][0], books[-1][0]
    trades = _safe(
        lambda: _window_trades(root / venue / "market_trades", product_id, t0, t1, max_trades),
        [],
    ) or []
    trades_note: str | None = None
    if trades:
        tf = _safe(lambda: trade_flow(trades))
        if tf:
            for key, src in (("tfi", "tfi"), ("cvd", "cvd"), ("flow_accel", "accel"),
                             ("intensity", "intensity"), ("large_share", "large_share")):
                factors[key] = _aggregate_entry(tf.get(src), len(trades))
        kl = _safe(lambda: kyle_lambda_proxy(trades))
        if kl is not None:
            factors["impact_bps_per_unit"] = _aggregate_entry(kl, len(trades))
        if not tf and kl is None:
            trades_note = _TRADES_NOTE
    else:
        trades_note = _TRADES_NOTE

    now_s = now if now is not None else time.time()
    section: dict[str, Any] = {
        "available": True,
        "venue": venue,
        "product_id": product_id,
        "note": _NOTE,
        "use_class": _USE_CLASS,
        "window": {
            "snapshots": len(books),
            "trades": len(trades),
            "from_ts": round(t0.timestamp(), 3),
            "to_ts": round(t1.timestamp(), 3),
            "span_s": round((t1 - t0).total_seconds(), 3),
            "age_s": round(max(0.0, now_s - t1.timestamp()), 1),
        },
        "factors": factors,
        "citations": dict(_CITATIONS),
    }
    if trades_note:
        section["trades_note"] = trades_note
    return section
