"""Synthetic fixture tests (quantdesk.demo.fixtures).

The fixtures are the only data the demo site ever sees, so their contract is
pinned here: deterministic shapes, well-formed candles, the injected-client
surface the research board expects (string rows, forming last bar, distinct
per-symbol / per-granularity paths), microstructure input shapes, and the
optional lake writer round-tripping through the package's own reader.
"""
from __future__ import annotations

import math

import pytest

from quantdesk.demo.fixtures import (
    DEFAULT_START_TS,
    SyntheticClient,
    bar_seconds_for,
    gbm_bars,
    planted_bars,
    split_ohlcv,
    synthetic_book,
    synthetic_trades,
    write_synthetic_lake,
)
from quantdesk.factors.microstructure import microstructure_bundle, spread_bps, trade_flow
from quantdesk.research.board import _closed_bars, compute_factors

_NOW = 1_800_000_000.0  # fixed "now" so forming-bar arithmetic is reproducible


# ------------------------------------------------------------------ gbm_bars --
def test_gbm_bars_shape_and_timestamps():
    rows = gbm_bars(50, seed=1, start_ts=1000.0, bar_seconds=60)
    assert len(rows) == 50
    assert all(len(r) == 6 for r in rows)
    assert [r[0] for r in rows] == [1000.0 + 60 * i for i in range(50)]
    assert gbm_bars(0) == []


def test_gbm_bars_are_well_formed_candles():
    rows = gbm_bars(500, seed=3, sigma=0.05)
    prev_close = None
    for ts, o, h, l, c, v in rows:
        assert o > 0 and h > 0 and l > 0 and c > 0 and v > 0
        assert h >= max(o, c) and l <= min(o, c)
        if prev_close is not None:
            assert o == prev_close  # 24/7 market: no gap
        prev_close = c
        assert all(isinstance(x, float) for x in (ts, o, h, l, c, v))


def test_gbm_bars_deterministic_and_seed_sensitive():
    a = gbm_bars(100, seed=11)
    b = gbm_bars(100, seed=11)
    c = gbm_bars(100, seed=12)
    assert a == b
    assert a != c
    # the price path is a prefix-stable function of the seed
    assert gbm_bars(40, seed=11) == a[:40]


def test_gbm_bars_drift_and_zero_vol():
    flat = gbm_bars(10, seed=1, sigma=0.0, mu=0.0)
    assert all(r[4] == pytest.approx(100.0) for r in flat)
    up = gbm_bars(10, seed=1, sigma=0.0, mu=0.01)
    assert up[-1][4] == pytest.approx(100.0 * math.exp(0.10))  # 10 bars x 0.01 drift


def test_gbm_bars_rejects_bad_args():
    with pytest.raises(ValueError):
        gbm_bars(-1)
    with pytest.raises(ValueError):
        gbm_bars(5, s0=0.0)
    with pytest.raises(ValueError):
        gbm_bars(5, sigma=-0.1)


def test_split_ohlcv_columns():
    rows = gbm_bars(5, seed=2)
    cols = split_ohlcv(rows)
    assert set(cols) == {"ts", "o", "h", "l", "c", "v"}
    assert cols["c"] == [r[4] for r in rows]
    assert split_ohlcv([[str(x) for x in r] for r in rows])["c"] == cols["c"]


def test_bar_seconds_for_aliases():
    assert bar_seconds_for("1h") == bar_seconds_for("ONE_HOUR") == 3600
    assert bar_seconds_for("1d") == bar_seconds_for("ONE_DAY") == 86400
    assert bar_seconds_for(60) == 60
    with pytest.raises(ValueError):
        bar_seconds_for("2w")


# ----------------------------------------------------------- SyntheticClient --
def test_client_rows_are_strings_with_forming_last_bar():
    cl = SyntheticClient(seed=0, now=_NOW)
    rows = cl.get_candles("SYN-1", "1h", limit=350)
    assert len(rows) == 350
    assert all(isinstance(x, str) for r in rows for x in r)
    ts = [float(r[0]) for r in rows]
    assert all(t % 3600 == 0 for t in ts)  # aligned to bar boundaries
    assert ts[-1] + 3600 > _NOW  # forming
    assert ts[-2] + 3600 <= _NOW  # closed
    closed = _closed_bars(rows, 3600.0, _NOW)
    assert len(closed["c"]) == 349
    assert cl.calls == [("SYN-1", "1h", 350)]


def test_client_granularity_aliases_and_distinct_paths():
    cl = SyntheticClient(seed=0, now=_NOW)
    assert cl.get_candles("SYN-1", "1h", 100) == cl.get_candles("SYN-1", "ONE_HOUR", 100)
    assert cl.get_candles("SYN-1", "1d", 100) == cl.get_candles("SYN-1", "ONE_DAY", 100)
    h = [r[4] for r in cl.get_candles("SYN-1", "1h", 100)]
    d = [r[4] for r in cl.get_candles("SYN-1", "1d", 100)]
    other = [r[4] for r in cl.get_candles("SYN-2", "1h", 100)]
    assert h != d and h != other
    daily_ts = [float(r[0]) for r in cl.get_candles("SYN-1", "1d", 5)]
    assert all(t % 86400 == 0 for t in daily_ts)


def test_client_deterministic_across_instances_and_limit_is_a_tail():
    a = SyntheticClient(seed=5, now=_NOW).get_candles("SYN-3", "1h", 350)
    b = SyntheticClient(seed=5, now=_NOW).get_candles("SYN-3", "1h", 350)
    assert a == b
    short = SyntheticClient(seed=5, now=_NOW).get_candles("SYN-3", "1h", 50)
    assert short == a[-50:]
    assert SyntheticClient(seed=6, now=_NOW).get_candles("SYN-3", "1h", 350) != a
    assert len(SyntheticClient(seed=5, now=_NOW, max_bars=20).get_candles("X", "1h", 350)) == 20


def test_client_raise_for_and_close():
    cl = SyntheticClient(now=_NOW, raise_for={"BAD"})
    with pytest.raises(ConnectionError):
        cl.get_candles("BAD", "1h", 10)
    assert cl.get_candles("GOOD", "1h", 10)
    assert SyntheticClient(now=_NOW, raise_for={"candles"}).close() is None
    with pytest.raises(ConnectionError):
        SyntheticClient(now=_NOW, raise_for={"candles"}).get_candles("GOOD", "1h", 10)


def test_client_closed_bars_matches_board_drop():
    cl = SyntheticClient(seed=3, now=_NOW)
    numeric = cl.closed_bars("SYN-1", "1d", 400)
    ref = _closed_bars(cl.get_candles("SYN-1", "1d", 400), 86400.0, _NOW)
    assert len(numeric) == 399 == len(ref["c"])
    assert [r[4] for r in numeric] == ref["c"]
    assert all(isinstance(x, float) for r in numeric for x in r)


def test_client_drives_the_research_board_end_to_end():
    cl = SyntheticClient(seed=1, now=_NOW)
    out = compute_factors(["SYN-1", "SYN-2", "SYN-3"], cl, now=_NOW)
    assert out["bars_1h"] == 349 and out["bars_1d"] == 349
    assert [r["symbol"] for r in out["symbols"]] == ["SYN-1", "SYN-2", "SYN-3"]
    for row in out["symbols"]:
        assert row["ok"] is True
        assert len(row["alpha101"]) == 19
        assert "action" not in row and "recommendation" not in row
        tsmom = row["existing"][0]
        assert tsmom["id"] == "tsmom_score" and tsmom["ok"] is True
        assert all(v is not None for v in tsmom["diag"].values())
    # distinct symbols carry distinct numbers
    v1 = out["symbols"][0]["existing"][0]["value"]
    v2 = out["symbols"][1]["existing"][0]["value"]
    assert v1 != v2


# ------------------------------------------------------ book / trades shapes --
def test_synthetic_book_shape_and_ordering():
    book = synthetic_book(10, mid=100.0, seed=0)
    assert set(book) == {"bids", "asks"}
    assert len(book["bids"]) == len(book["asks"]) == 10
    bid_px = [px for px, _ in book["bids"]]
    ask_px = [px for px, _ in book["asks"]]
    assert bid_px == sorted(bid_px, reverse=True)
    assert ask_px == sorted(ask_px)
    assert bid_px[0] < 100.0 < ask_px[0]
    assert all(sz > 0 for _, sz in book["bids"] + book["asks"])
    assert synthetic_book(10, seed=0) == book
    assert synthetic_book(10, seed=1) != book
    assert spread_bps(book) == pytest.approx(0.02 / bid_px[0] * 1e4)
    with pytest.raises(ValueError):
        synthetic_book(0)


def test_synthetic_trades_shape_and_flow():
    trades = synthetic_trades(60, mid=100.0, seed=4)
    assert len(trades) == 60
    assert all(set(t) == {"price", "size", "side"} for t in trades)
    assert all(t["price"] > 0 and t["size"] > 0 for t in trades)
    assert {t["side"] for t in trades} <= {"buy", "sell"}
    assert synthetic_trades(60, seed=4) == trades
    tf = trade_flow(trades)
    assert tf is not None and -1.0 <= tf["tfi"] <= 1.0 and tf["intensity"] == 60.0
    assert all(t["side"] == "buy" for t in synthetic_trades(20, seed=1, buy_prob=1.0))
    assert synthetic_trades(0) == []


def test_synthetic_inputs_feed_the_microstructure_bundle():
    out = microstructure_bundle(synthetic_book(seed=2), synthetic_trades(seed=2))
    for key in ("micro_dev_bps", "queue_imbalance", "book_pressure", "depth_ratio",
                "spread_bps", "tfi", "flow_accel", "large_share", "intensity"):
        assert key in out, key
    assert out["spread_bps"] > 0


# ------------------------------------------------------------- lake writer --
def test_write_synthetic_lake_round_trips_through_reader(tmp_path):
    pytest.importorskip("pyarrow")
    from quantdesk.backtest.lake_data import read_1m_bars

    paths = write_synthetic_lake(tmp_path / "lake", "SYN-1", 2, seed=0)
    assert paths is not None and len(paths) == 2
    assert all(p.exists() and p.suffix == ".parquet" for p in paths)
    assert paths[0].parent.name == "date=2026-01-01"
    assert paths[0].parts[-4] == "synthetic" and paths[0].parts[-3] == "candles_1m"
    bars = read_1m_bars(tmp_path / "lake", "SYN-1")
    assert len(bars) == 2 * 1440
    assert bars == sorted(bars, key=lambda b: b.timestamp)
    assert (bars[1].timestamp - bars[0].timestamp).total_seconds() == 60
    assert all(b.high >= max(b.open, b.close) >= min(b.open, b.close) >= b.low for b in bars)
    assert read_1m_bars(tmp_path / "lake", "OTHER") == []
    # deterministic: a second write with the same seed is byte-for-byte the same prices
    again = write_synthetic_lake(tmp_path / "lake2", "SYN-1", 1, seed=0)
    assert [b.close for b in read_1m_bars(tmp_path / "lake2", "SYN-1")] == \
        [b.close for b in bars[:1440]]
    assert again is not None and len(again) == 1
    assert write_synthetic_lake(tmp_path / "lake3", "SYN-1", 0) == []


def test_default_start_is_the_synthetic_epoch():
    assert gbm_bars(1)[0][0] == DEFAULT_START_TS


# -------------------------------------------------------------- planted_bars --
def _h1_rank_ic_of_neg_delta(rows):
    """Time-series Rank-IC of ``-1 * delta(close, 1)`` at horizon 1 through the
    board's own gate-protected path (the search loop's judge uses the same)."""
    from quantdesk.factors.alpha101 import delta
    from quantdesk.research.board import ic_for

    closes = split_ohlcv(rows)["c"]
    series = [None if v is None else -v for v in delta(closes, 1)]
    return ic_for(series, closes, 1)


def test_planted_bars_phi_zero_is_gbm_bit_for_bit():
    assert planted_bars(300, seed=4, phi=0.0, sigma=0.02) == gbm_bars(300, seed=4, sigma=0.02)
    assert planted_bars(0) == []


def test_planted_bars_are_well_formed_and_deterministic():
    rows = planted_bars(400, seed=9)
    prev_close = None
    for ts, o, h, l, c, v in rows:
        assert o > 0 and h > 0 and l > 0 and c > 0 and v > 0
        assert h >= max(o, c) and l <= min(o, c)
        if prev_close is not None:
            assert o == prev_close
        prev_close = c
    assert rows == planted_bars(400, seed=9)
    assert rows != planted_bars(400, seed=10)
    assert planted_bars(50, seed=9) == rows[:50]
    assert rows != gbm_bars(400, seed=9, sigma=0.01)  # phi != 0 changes the path


def test_planted_bars_plant_a_one_bar_mean_reversion():
    # phi = -0.12 -> Rank-IC of -delta(close, 1) about 0.93 * |phi| ~ 0.11 at
    # horizon 1 (sd ~ 1/sqrt(n-1) ~ 0.02 at 2400 bars); the GBM twin sits at 0.
    r = _h1_rank_ic_of_neg_delta(planted_bars(2400, seed=7))
    assert r["ic"] is not None and 0.06 <= r["ic"] <= 0.16, r
    g = _h1_rank_ic_of_neg_delta(gbm_bars(2400, seed=7, sigma=0.01))
    assert g["ic"] is not None and abs(g["ic"]) < 0.06, g
    # the planted effect is one bar long: at horizon 24 it is inside the noise
    from quantdesk.factors.alpha101 import delta
    from quantdesk.research.board import ic_for

    closes = split_ohlcv(planted_bars(2400, seed=7))["c"]
    series = [None if v is None else -v for v in delta(closes, 1)]
    assert abs(ic_for(series, closes, 24)["ic"] or 0.0) < 0.06


def test_planted_bars_rejects_bad_args():
    for bad in ({"n": -1}, {"s0": 0.0}, {"sigma": -0.1}, {"phi": 1.0}, {"phi": -1.5}):
        kw = {"n": 5, **bad}
        n = kw.pop("n")
        with pytest.raises(ValueError):
            planted_bars(n, **kw)
