"""Microstructure factor tests.

Unit half: each quantdesk/factors/microstructure.py factor function is proven
against hand-computed values on tiny synthetic books/tapes, including the
defensive None paths its docstrings promise.

Wiring half: synthetic book_top10 / market_trades Parquet written with the
frozen lake schemas (quantdesk/lake/schemas.py -- the contract tie-in) into a
tmp lake, then read back through
quantdesk.research.microstructure_lake.build_micro_section and the full
compute_factors payload. Honest empty states (missing lake, wrong product,
``*.tmp``-only) are first-class asserts, as is the absence of any IC/decay
claim in the section.

No network: the candle client is a fake; the lake is tmp_path.
"""
from __future__ import annotations

import json
import statistics
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

pytest.importorskip("pyarrow")

from quantdesk.research.board import build_symbol_factors, compute_factors
from quantdesk.research.microstructure_lake import build_micro_section
from quantdesk.lake.schemas import BOOK_TOP10_SCHEMA, TRADES_SCHEMA
from quantdesk.factors.microstructure import (
    book_pressure,
    kyle_lambda_proxy,
    micro_price,
    microstructure_bundle,
    queue_imbalance,
    snapshot_ofi,
    spread_bps,
    trade_flow,
)

_T0 = datetime(2026, 8, 1, 0, 0, tzinfo=timezone.utc)

_BOOK = {"bids": [[100.0, 3.0]], "asks": [[101.0, 1.0]]}


# ======================================================================= unit
# ------------------------------------------------------------- micro_price --
def test_micro_price_hand_computed():
    # Stoikov: (P_ask*Q_bid + P_bid*Q_ask)/(Q_bid+Q_ask)
    out = micro_price(_BOOK)
    assert out is not None
    assert out["mid"] == pytest.approx(100.5)
    assert out["micro"] == pytest.approx((101.0 * 3.0 + 100.0 * 1.0) / 4.0)  # 100.75
    assert out["deviation_bps"] == pytest.approx(0.25 / 100.5 * 1e4)  # +24.876 bps

    # bid queue heavier -> micro sits ABOVE mid (upward pressure), and mirror
    heavy_ask = micro_price({"bids": [[100.0, 1.0]], "asks": [[101.0, 3.0]]})
    assert heavy_ask["deviation_bps"] == pytest.approx(-out["deviation_bps"])


def test_micro_price_defensive_none():
    assert micro_price({}) is None
    assert micro_price({"bids": [[100.0, 1.0]], "asks": []}) is None
    assert micro_price({"bids": [[101.0, 1.0]], "asks": [[100.0, 1.0]]}) is None  # crossed
    assert micro_price({"bids": [[100.0, 0.0]], "asks": [[101.0, 0.0]]}) is None  # empty queues


# --------------------------------------------------------- queue_imbalance --
def test_queue_imbalance_hand_computed():
    assert queue_imbalance(_BOOK) == pytest.approx((3.0 - 1.0) / 4.0)  # +0.5
    assert queue_imbalance({"bids": [[100.0, 1.0]], "asks": [[101.0, 3.0]]}) == pytest.approx(-0.5)
    assert queue_imbalance({"bids": [[100.0, 7.0]], "asks": [[101.0, 7.0]]}) == 0.0
    assert queue_imbalance({"bids": [], "asks": [[101.0, 1.0]]}) is None
    assert queue_imbalance({"bids": [[100.0, 0.0]], "asks": [[101.0, 0.0]]}) is None


# ----------------------------------------------------------- book_pressure --
def test_book_pressure_hand_computed_two_levels():
    book = {"bids": [[100.0, 5.0], [99.0, 3.0]], "asks": [[101.0, 2.0], [102.0, 4.0]]}
    out = book_pressure(book, n=10, decay=0.5)
    # w0=1: (5-2)=3 / (5+2)=7 ; w1=0.5: 0.5*(3-4)=-0.5 / 0.5*7=3.5
    assert out["pressure"] == pytest.approx(2.5 / 10.5)
    assert out["depth_ratio"] == pytest.approx(8.0 / 14.0)


def test_book_pressure_n1_reduces_to_queue_imbalance():
    book = {"bids": [[100.0, 5.0], [99.0, 3.0]], "asks": [[101.0, 2.0], [102.0, 4.0]]}
    assert book_pressure(book, n=1)["pressure"] == pytest.approx(queue_imbalance(book))
    assert book_pressure({}, n=10) is None


# --------------------------------------------------------------- spread_bps --
def test_spread_bps_hand_computed():
    assert spread_bps({"bids": [[100.0, 1.0]], "asks": [[100.5, 1.0]]}) == pytest.approx(50.0)
    assert spread_bps({"bids": [[100.0, 1.0]], "asks": []}) is None


# ------------------------------------------------------------- snapshot_ofi --
def test_snapshot_ofi_all_branches_hand_computed():
    prev = {"bids": [[100.0, 5.0]], "asks": [[101.0, 7.0]]}
    # both sides bullish: bid px up (+curr bid sz), ask px up = retreat (+prev ask sz)
    up = {"bids": [[100.5, 4.0]], "asks": [[101.5, 6.0]]}
    assert snapshot_ofi(prev, up) == pytest.approx(4.0 + 7.0)
    # equal prices: size deltas, mirrored on the ask
    same = {"bids": [[100.0, 8.0]], "asks": [[101.0, 4.0]]}
    assert snapshot_ofi(prev, same) == pytest.approx((8.0 - 5.0) - (4.0 - 7.0))  # +6
    # both sides bearish: bid level lost (-prev bid sz), ask improved (-curr ask sz)
    down = {"bids": [[99.0, 2.0]], "asks": [[100.5, 3.0]]}
    assert snapshot_ofi(prev, down) == pytest.approx(-5.0 - 3.0)
    assert snapshot_ofi({}, up) is None
    assert snapshot_ofi(prev, {}) is None


# --------------------------------------------------------------- trade_flow --
def test_trade_flow_hand_computed_venue_case_normalized():
    # Lake stores taker side as BUY/SELL (docs/DATA.md) — case must normalize.
    trades = [
        {"price": 100.0, "size": 2.0, "side": "BUY"},
        {"price": 100.1, "size": 1.0, "side": "SELL"},
        {"price": 100.2, "size": 1.0, "side": "buy"},
    ]
    out = trade_flow(trades)
    assert out["tfi"] == pytest.approx(2.0 / 4.0)     # signed [2,-1,1]: net 2, gross 4
    assert out["cvd"] == pytest.approx(2.0)
    # half=1: tfi([-1, 1]) - tfi([2]) = 0 - 1
    assert out["accel"] == pytest.approx(-1.0)
    assert out["intensity"] == 3.0
    assert out["large_share"] == 0.0                  # 3x mean = 4.0; no print exceeds it


def test_trade_flow_large_share_institutional_print():
    trades = [{"price": 100.0, "size": s, "side": "BUY"} for s in (1.0, 1.0, 1.0, 10.0)]
    out = trade_flow(trades)
    assert out["tfi"] == pytest.approx(1.0)
    assert out["large_share"] == pytest.approx(10.0 / 13.0)  # mean 3.25, threshold 9.75


def test_trade_flow_defensive_none():
    assert trade_flow([]) is None
    assert trade_flow([{"price": 100.0, "size": 1.0, "side": "hold"}]) is None
    assert trade_flow([{"price": 100.0, "size": 0.0, "side": "buy"}]) is None


# -------------------------------------------------------- kyle_lambda_proxy --
def test_kyle_lambda_proxy_hand_computed():
    trades = [{"price": 100.0, "size": 1.0, "side": "buy"},
              {"price": 101.0, "size": 1.0, "side": "sell"}]
    # |101-100|/100 * 1e4 = 100 bps over gross 2 units -> 50 bps/unit
    assert kyle_lambda_proxy(trades) == pytest.approx(50.0)
    flat = [{"price": 100.0, "size": 2.0}, {"price": 100.0, "size": 2.0}]
    assert kyle_lambda_proxy(flat) == 0.0             # flat tape: zero impact, not None
    assert kyle_lambda_proxy([{"price": 100.0, "size": 1.0}]) is None  # single print


# ------------------------------------------------------------------- bundle --
def test_bundle_failure_isolated_and_keys():
    assert microstructure_bundle({}, []) == {}
    out = microstructure_bundle(
        {"bids": [[100.0, 3.0], [99.9, 1.0]], "asks": [[100.1, 1.0], [100.2, 2.0]]},
        [{"price": 100.0, "size": 1.0, "side": "buy"},
         {"price": 100.1, "size": 2.0, "side": "sell"}],
    )
    assert {"micro_dev_bps", "queue_imbalance", "book_pressure", "depth_ratio",
            "spread_bps", "tfi", "flow_accel", "large_share", "intensity",
            "impact_bps_per_unit"} <= set(out)


# ================================================================== wiring ==
def _snap(ts, *, product="BTC-USD", venue="coinbase", bid=100.0, ask=100.1,
          bid_sz=5.0, ask_sz=3.0, depth=2, tick=0.01, seq=1):
    """One book_top10 row: `depth` real levels, NaN tail (depth < 10 per the
    schema) — proving the NaN path end to end through the reader."""
    row = {"venue": venue, "product_id": product, "ts": ts, "seq": seq}
    nan = float("nan")
    for i in range(1, 11):
        have = i <= depth
        row[f"bid_px_{i}"] = bid - (i - 1) * tick if have else nan
        row[f"bid_sz_{i}"] = bid_sz if have else nan
        row[f"ask_px_{i}"] = ask + (i - 1) * tick if have else nan
        row[f"ask_sz_{i}"] = ask_sz if have else nan
    return row


def _trade(ts, price, size, side, *, product="BTC-USD", venue="coinbase", tid="t"):
    return {"venue": venue, "product_id": product, "ts": ts,
            "trade_id": tid, "price": price, "size": size, "side": side}


def _write(path: Path, rows: list[dict], schema) -> None:
    import pyarrow as pa
    import pyarrow.parquet as pq

    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.Table.from_pylist(rows, schema=schema), path)


def _book_lake(tmp_path: Path) -> Path:
    """Three snapshots + two in-window trades (+ decoys that must be excluded):
    every downstream number in the tests is hand-derived from these rows."""
    lake = tmp_path / "lake"
    day = "date=2026-08-01"
    _write(lake / "coinbase" / "book_top10" / day / "00-py.parquet", [
        _snap(_T0, bid=100.0, ask=100.1, bid_sz=5.0, ask_sz=3.0),
        _snap(_T0 + timedelta(seconds=1), bid=100.0, ask=100.1, bid_sz=6.0, ask_sz=2.0),
        _snap(_T0 + timedelta(seconds=2), bid=100.02, ask=100.12, bid_sz=4.0, ask_sz=2.0),
    ], BOOK_TOP10_SCHEMA)
    _write(lake / "coinbase" / "market_trades" / day / "00-py.parquet", [
        _trade(_T0 + timedelta(seconds=0.5), 100.05, 2.0, "BUY"),
        _trade(_T0 + timedelta(seconds=1.5), 100.04, 1.0, "SELL"),
        _trade(_T0 + timedelta(seconds=30), 100.50, 50.0, "BUY"),     # after window
        _trade(_T0 - timedelta(seconds=5), 99.50, 50.0, "SELL"),      # before window
        _trade(_T0 + timedelta(seconds=1), 10.0, 50.0, "BUY", product="ETH-USD"),
    ], TRADES_SCHEMA)
    return lake


def test_build_micro_section_hand_checked_series(tmp_path):
    lake = _book_lake(tmp_path)
    sec = build_micro_section("BTC-USD", lake)
    assert sec["available"] is True
    assert sec["venue"] == "coinbase"
    assert sec["note"] == "observables only; no IC evaluation yet"
    assert sec["window"]["snapshots"] == 3
    assert sec["window"]["trades"] == 2               # decoy trades excluded
    assert sec["window"]["span_s"] == pytest.approx(2.0)
    assert sec["window"]["age_s"] >= 0.0
    f = sec["factors"]
    # queue series [0.25, 0.5, 1/3] — latest / mean / sample std / n
    assert f["queue_imbalance"]["value"] == pytest.approx(1.0 / 3.0, abs=1e-4)
    assert f["queue_imbalance"]["mean"] == pytest.approx((0.25 + 0.5 + 1 / 3) / 3, abs=1e-4)
    assert f["queue_imbalance"]["std"] == pytest.approx(
        statistics.stdev([0.25, 0.5, 1 / 3]), abs=1e-4)
    assert f["queue_imbalance"]["n"] == 3
    # constant per-side sizes across 2 levels: pressure == queue imbalance
    assert f["book_pressure"]["value"] == pytest.approx(1.0 / 3.0, abs=1e-4)
    assert f["depth_ratio"]["value"] == pytest.approx(8.0 / 12.0, abs=1e-4)
    assert f["spread_bps"]["value"] == pytest.approx(0.10 / 100.02 * 1e4, abs=1e-3)
    micro3 = (100.12 * 4.0 + 100.02 * 2.0) / 6.0      # Stoikov on the last snapshot
    assert f["micro_dev_bps"]["value"] == pytest.approx(
        (micro3 - 100.07) / 100.07 * 1e4, abs=1e-3)
    # OFI series [None, +2, +6]: n=2 (first snapshot has no predecessor)
    assert f["snapshot_ofi"]["value"] == pytest.approx(6.0)
    assert f["snapshot_ofi"]["mean"] == pytest.approx(4.0)
    assert f["snapshot_ofi"]["n"] == 2
    # trade-flow window aggregates: signed [2, -1]
    assert f["tfi"] == {"value": pytest.approx(1.0 / 3.0, abs=1e-4), "n": 2,
                        "window_aggregate": True}
    assert f["cvd"]["value"] == pytest.approx(1.0)
    assert f["flow_accel"]["value"] == pytest.approx(-2.0)  # tfi([-1]) - tfi([2])
    assert f["intensity"]["value"] == pytest.approx(2.0)
    assert f["impact_bps_per_unit"]["value"] == pytest.approx(
        (0.01 / 100.05 * 1e4) / 3.0, abs=1e-3)
    # observables only — no IC/decay/turnover claims anywhere in the section
    assert "ic" not in sec and "decay" not in sec
    for entry in f.values():
        assert "ic" not in entry and "decay" not in entry and "turnover_proxy" not in entry
    # strict-JSON clean: the NaN-padded lake levels must never leak into the payload
    json.dumps(sec, allow_nan=False)


def test_missing_lake_is_first_class_empty(tmp_path):
    sec = build_micro_section("BTC-USD", tmp_path / "no-such-lake")
    assert sec == {"available": False,
                   "note": "no book_top10 data in the lake yet (see docs/DATA.md)"}


def test_tmp_files_never_read_and_bad_files_skipped(tmp_path):
    lake = tmp_path / "lake"
    day = lake / "coinbase" / "book_top10" / "date=2026-08-01"
    # a VALID parquet under a .tmp name: reading it would flip available -> True
    _write(day / "00-py.parquet.tmp", [_snap(_T0)], BOOK_TOP10_SCHEMA)
    day.joinpath("01-py.parquet").write_bytes(b"not a parquet file")  # unreadable: skipped
    sec = build_micro_section("BTC-USD", lake)
    assert sec["available"] is False
    assert sec["note"] == "no book_top10 data in the lake yet (see docs/DATA.md)"


def test_wrong_product_is_empty_not_borrowed(tmp_path):
    lake = tmp_path / "lake"
    _write(lake / "coinbase" / "book_top10" / "date=2026-08-01" / "00-py.parquet",
           [_snap(_T0, product="ETH-USD")], BOOK_TOP10_SCHEMA)
    assert build_micro_section("BTC-USD", lake)["available"] is False
    assert build_micro_section("ETH-USD", lake)["available"] is True


def test_tail_window_caps_across_files_oldest_to_newest(tmp_path):
    lake = tmp_path / "lake"
    root = lake / "coinbase" / "book_top10" / "date=2026-08-01"
    _write(root / "00-py.parquet",
           [_snap(_T0 + timedelta(seconds=i)) for i in range(5)], BOOK_TOP10_SCHEMA)
    _write(root / "01-py.parquet",
           [_snap(_T0 + timedelta(hours=1, seconds=i)) for i in range(5)], BOOK_TOP10_SCHEMA)
    sec = build_micro_section("BTC-USD", lake, tail_n=4)
    assert sec["window"]["snapshots"] == 4
    # last 4 snapshots live in the 01 file: window starts at +1h+1s
    assert sec["window"]["from_ts"] == pytest.approx(
        (_T0 + timedelta(hours=1, seconds=1)).timestamp())
    assert sec["factors"]["snapshot_ofi"]["n"] == 3   # 4 snapshots -> 3 diffs


def test_books_without_trades_get_honest_trades_note(tmp_path):
    lake = tmp_path / "lake"
    _write(lake / "coinbase" / "book_top10" / "date=2026-08-01" / "00-py.parquet",
           [_snap(_T0), _snap(_T0 + timedelta(seconds=1))], BOOK_TOP10_SCHEMA)
    sec = build_micro_section("BTC-USD", lake)
    assert sec["available"] is True
    assert sec["window"]["trades"] == 0
    assert "tfi" not in sec["factors"]
    assert "trade-flow factors" in sec["trades_note"]


def test_freshest_venue_wins_no_series_interleaving(tmp_path):
    lake = tmp_path / "lake"
    _write(lake / "aaa" / "book_top10" / "date=2026-08-01" / "00-py.parquet",
           [_snap(_T0, venue="aaa")], BOOK_TOP10_SCHEMA)
    _write(lake / "bbb" / "book_top10" / "date=2026-08-01" / "00-py.parquet",
           [_snap(_T0 + timedelta(seconds=100), venue="bbb")], BOOK_TOP10_SCHEMA)
    sec = build_micro_section("BTC-USD", lake)
    assert sec["venue"] == "bbb"
    assert sec["window"]["snapshots"] == 1            # never merged across venues


# ------------------------------------------------- compute_factors payload --
class FakeCoinbase:
    """Minimal candle-client surface (string fields like a real venue
    adapter, still-forming last bar dropped by _closed_bars)."""

    def __init__(self, raise_for=None):
        self._raise_for = raise_for or set()

    def get_candles(self, symbol, granularity="1h", limit=350):
        if symbol in self._raise_for:
            raise ConnectionError("boom")
        n, secs = (40, 3600) if granularity == "1h" else (10, 86400)
        now = time.time()
        rows = []
        for i in range(n):
            ts = now - (n - i) * secs + secs / 2.0    # last bar forming
            c = 100.0 + i + (i % 3)
            o = 100.0 + max(i - 1, 0)
            hi, lo = max(o, c) + 0.5 + 0.01 * i, min(o, c) - 0.5
            rows.append([str(ts), str(o), str(hi), str(lo), str(c), str(10.0 + i % 7)])
        return rows

    def close(self):
        pass


def test_compute_factors_includes_microstructure_section(tmp_path, monkeypatch):
    lake = _book_lake(tmp_path)                       # BTC books; nothing for ETH
    out = compute_factors(["BTC-USD", "ETH-USD"], FakeCoinbase(), lake_root=lake)
    rows = {r["symbol"]: r for r in out["symbols"]}

    btc = rows["BTC-USD"]["microstructure"]
    assert btc["available"] is True
    assert {"micro_dev_bps", "queue_imbalance", "book_pressure", "depth_ratio",
            "spread_bps", "snapshot_ofi"} <= set(btc["factors"])
    eth = rows["ETH-USD"]["microstructure"]
    assert eth == {"available": False,
                   "note": "no book_top10 data in the lake yet (see docs/DATA.md)"}

    # payload stays backward compatible: envelope + per-symbol shape only ADDED to
    assert out["ttl_s"] == 60 and out["granularity"] == "1h"
    assert "disclaimer" in out and "ic_convention" in out
    for sym in out["symbols"]:
        assert sym["ok"] is True
        assert len(sym["alpha101"]) == 19 and "existing" in sym and "correlation" in sym
        assert "recommendation" not in sym and "action" not in sym


def test_fetch_failed_symbol_still_carries_lake_section(tmp_path):
    lake = _book_lake(tmp_path)
    row = build_symbol_factors("BTC-USD", FakeCoinbase(raise_for={"BTC-USD"}),
                               lake_root=lake)
    assert row["ok"] is False and row["error"].startswith("fetch_failed")
    assert row["microstructure"]["available"] is True  # lake needs no venue
