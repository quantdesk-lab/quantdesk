"""Lake-backed backtest data + decision replay, end to end.

The backtest runs on a recorded parquet lake (docs/DATA.md) with venue-native
product ids, and a pipeline-style decisions document replays through the
engine. Everything is synthetic parquet in tmp_path via pyarrow -- mocked, no
network.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

pytest.importorskip("pyarrow")

from quantdesk.backtest import cli
from quantdesk.backtest.engine import run_backtest
from quantdesk.backtest.lake_data import (
    load_lake_candles,
    read_1m_bars,
    resample_1m,
)
from quantdesk.backtest.signals import replay_decisions
from quantdesk.backtest.types import Bar

_T0 = datetime(2026, 8, 1, 0, 0, tzinfo=timezone.utc)


# ---------- synthetic-lake helpers ----------


def _write_lake_file(path: Path, rows: list[tuple], venue: str = "coinbase") -> None:
    """rows: (product_id, ts, open, high, low, close, volume) — the full
    docs/DATA.md candles_1m schema."""
    import pyarrow as pa
    import pyarrow.parquet as pq

    path.parent.mkdir(parents=True, exist_ok=True)
    table = pa.table(
        {
            "venue": [venue] * len(rows),
            "product_id": [r[0] for r in rows],
            "ts": pa.array([r[1] for r in rows], type=pa.timestamp("us", tz="UTC")),
            "open": [float(r[2]) for r in rows],
            "high": [float(r[3]) for r in rows],
            "low": [float(r[4]) for r in rows],
            "close": [float(r[5]) for r in rows],
            "volume": [float(r[6]) for r in rows],
        }
    )
    pq.write_table(table, path)


def _minute_rows(
    product: str, start: datetime, minutes: range, price: float | None = None
) -> list[tuple]:
    """One lake row per minute m: open=base+m, high=+0.5, low=-0.5, close=+0.25."""
    base = 100.0 if price is None else price
    out = []
    for m in minutes:
        px = base + m
        out.append((product, start + timedelta(minutes=m), px, px + 0.5, px - 0.5, px + 0.25, 1.0))
    return out


def _bars(minutes: range) -> list[Bar]:
    """Bar equivalent of _minute_rows for direct resample tests."""
    out = []
    for m in minutes:
        px = 100.0 + m
        out.append(Bar(_T0 + timedelta(minutes=m), px, px + 0.5, px - 0.5, px + 0.25, 1.0))
    return out


def _build_flat_lake(root: Path, product: str, days: int, price: float = 100.0) -> None:
    """days full UTC days of constant-price 1m candles, hive-partitioned by date."""
    for d in range(days):
        day0 = _T0 + timedelta(days=d)
        rows = [
            (product, day0 + timedelta(minutes=m), price, price, price, price, 1.0)
            for m in range(1440)
        ]
        _write_lake_file(
            root / "coinbase" / "candles_1m" / f"date={day0.date().isoformat()}" / "00-py.parquet",
            rows,
        )


def _pipeline_doc(
    generated_at: datetime,
    symbol: str = "BTC-USD",
    regime: str = "high_volatility_event",
    confidence: float = 0.9,
    action: str = "reduce_25_percent",
) -> dict:
    """the exact shape a decision pipeline writes — format unchanged."""
    return {
        "generated_at": generated_at.isoformat(),
        "decisions": [
            {
                "symbol": symbol,
                "regime_decision": regime,
                "confidence": confidence,
                "candidates_considered": [],
                "missing_information": [],
                "evidence_for": ["synthetic"],
                "evidence_against": [],
                "action": action,
            }
        ],
        "audit": {
            "focus_symbols": [symbol],
            "evidence_branch_taken": False,
            "tool_calls_made": [],
        },
    }


# ---------- resample rules ----------


def test_resample_1h_aggregates_ohlcv_and_drops_partial_trailing() -> None:
    out = resample_1m(_bars(range(0, 150)), "1h")  # 2 full hours + 30 partial minutes
    assert len(out) == 2  # the partially-covered trailing bucket must not appear
    b0, b1 = out
    assert b0.timestamp == _T0 and b1.timestamp == _T0 + timedelta(hours=1)
    assert b0.open == 100.0          # first minute's open
    assert b0.high == 159.5          # minute 59's high
    assert b0.low == 99.5            # minute 0's low
    assert b0.close == 159.25        # last minute's close
    assert b0.volume == 60.0         # sum of 60 one-minute volumes
    assert (b1.open, b1.close) == (160.0, 219.25)


def test_resample_trailing_bucket_kept_when_its_final_minute_is_present() -> None:
    out = resample_1m(_bars(range(0, 120)), "1h")  # exactly 2 full hours
    assert len(out) == 2
    assert out[1].close == 219.25


def test_resample_interior_gap_is_kept_only_trailing_incompleteness_drops() -> None:
    # Hour 1 has a recording gap (only minutes 60-69) but its span has fully
    # elapsed, so it is a finished bar built from what was recorded.
    out = resample_1m(_bars(range(0, 70)) + _bars(range(120, 180)), "1h")
    assert len(out) == 3
    assert out[1].volume == 10.0 and out[1].close == 100.0 + 69 + 0.25
    # Same gap at the END (final minute of the last bucket missing) → dropped.
    out2 = resample_1m(_bars(range(0, 119)), "1h")  # hour 1 missing minute 119
    assert len(out2) == 1


def test_resample_1d_daily_buckets() -> None:
    out = resample_1m(_bars(range(0, 2 * 1440 + 720)), "1d")  # 2 full days + half
    assert len(out) == 2
    assert out[0].timestamp == _T0
    assert out[0].open == 100.0
    assert out[0].close == 100.0 + 1439 + 0.25
    assert out[0].volume == 1440.0


def test_resample_1m_identity_1day_alias_and_empty() -> None:
    bars = _bars(range(0, 5))
    assert resample_1m(bars, "1m") == bars
    assert len(resample_1m(_bars(range(0, 1440)), "1day")) == 1  # legacy-string alias
    assert resample_1m([], "1h") == []


def test_resample_unknown_granularity_is_refused() -> None:
    with pytest.raises(ValueError, match="unsupported granularity"):
        resample_1m([], "2h")


# ---------- lake reader ----------


def test_reader_filters_product_skips_tmp_and_dedupes_last_wins(tmp_path: Path) -> None:
    day = tmp_path / "lake" / "coinbase" / "candles_1m" / "date=2026-08-01"
    _write_lake_file(
        day / "00-py.parquet",
        _minute_rows("BTC-USD", _T0, range(0, 2)) + _minute_rows("ETH-USD", _T0, range(0, 2), price=10.0),
    )
    # A later file re-writes minute 1: last write wins (sorted-path order).
    _write_lake_file(day / "01-py.parquet", [("BTC-USD", _T0 + timedelta(minutes=1), 200.0, 200.0, 200.0, 200.0, 5.0)])
    (day / "02-py.parquet.tmp").write_text("in progress", encoding="utf-8")

    bars = read_1m_bars(tmp_path / "lake", "BTC-USD")
    assert [b.close for b in bars] == [100.25, 200.0]
    assert bars[1].volume == 5.0
    eth = read_1m_bars(tmp_path / "lake", "ETH-USD")
    assert [b.close for b in eth] == [10.25, 11.25]


def test_reader_merges_across_venue_directories(tmp_path: Path) -> None:
    root = tmp_path / "lake"
    _write_lake_file(
        root / "coinbase" / "candles_1m" / "date=2026-08-01" / "00-py.parquet",
        _minute_rows("BTC-USD", _T0, range(0, 1)),
    )
    _write_lake_file(
        root / "legacyvenue" / "candles_1m" / "date=2026-08-01" / "00-py.parquet",
        _minute_rows("BTC-USD", _T0, range(1, 2)),
        venue="legacyvenue",
    )
    bars = read_1m_bars(root, "BTC-USD")
    assert [b.timestamp for b in bars] == [_T0, _T0 + timedelta(minutes=1)]


def test_reader_skips_unreadable_files(tmp_path: Path) -> None:
    day = tmp_path / "lake" / "coinbase" / "candles_1m" / "date=2026-08-01"
    day.mkdir(parents=True)
    (day / "00-py.parquet").write_bytes(b"not parquet at all")
    _write_lake_file(day / "01-py.parquet", _minute_rows("BTC-USD", _T0, range(0, 3)))
    bars = read_1m_bars(tmp_path / "lake", "BTC-USD")
    assert len(bars) == 3


def test_missing_lake_and_unknown_product_are_honest_empty(tmp_path: Path) -> None:
    assert read_1m_bars(tmp_path / "nope", "BTC-USD") == []
    assert load_lake_candles("BTC-USD", "1h", lake_root=tmp_path / "nope") == []
    root = tmp_path / "lake"
    _write_lake_file(
        root / "coinbase" / "candles_1m" / "date=2026-08-01" / "00-py.parquet",
        _minute_rows("BTC-USD", _T0, range(0, 2)),
    )
    assert load_lake_candles("SOL-USD", "1h", lake_root=root) == []


def test_loader_window_is_applied_before_resampling(tmp_path: Path) -> None:
    root = tmp_path / "lake"
    _write_lake_file(
        root / "coinbase" / "candles_1m" / "date=2026-08-01" / "00-py.parquet",
        _minute_rows("BTC-USD", _T0, range(0, 120)),  # 2 full hours
    )
    assert len(load_lake_candles("BTC-USD", "1h", lake_root=root)) == 2
    # An `end` cutting hour 0 mid-way leaves it unfinished → no bar at all.
    assert load_lake_candles("BTC-USD", "1h", lake_root=root, end=_T0 + timedelta(minutes=45)) == []
    # A `start` cutting hour 0 mid-way keeps a leading bucket built from the
    # covered remainder (truncated history, not lookahead), stamped at floor.
    got = load_lake_candles("BTC-USD", "1h", lake_root=root, start=_T0 + timedelta(minutes=30))
    assert len(got) == 2
    assert got[0].timestamp == _T0 and got[0].open == 130.0 and got[0].volume == 30.0
    # Window entirely past the data → honest empty.
    assert load_lake_candles("BTC-USD", "1h", lake_root=root, start=_T0 + timedelta(hours=3)) == []


def test_lake_bars_match_the_engine_row_shape(tmp_path: Path) -> None:
    """The exact candle row shape the legacy REST loader produced:
    Bar with tz-aware UTC datetime + plain-float OHLCV."""
    root = tmp_path / "lake"
    _write_lake_file(
        root / "coinbase" / "candles_1m" / "date=2026-08-01" / "00-py.parquet",
        _minute_rows("BTC-USD", _T0, range(0, 120)),
    )
    bars = load_lake_candles("BTC-USD", "1h", lake_root=root)
    assert bars and all(isinstance(b, Bar) for b in bars)
    for b in bars:
        assert b.timestamp.tzinfo is not None
        assert b.timestamp.utcoffset() == timedelta(0)
        for x in (b.open, b.high, b.low, b.close, b.volume):
            assert isinstance(x, float)


# ---------- replay: legacy rows + pipeline run documents ----------


def test_replay_legacy_rows_and_cross_venue_symbol_shim(tmp_path: Path) -> None:
    ts = datetime(2024, 1, 1, tzinfo=timezone.utc)
    path = tmp_path / "d.json"
    path.write_text(json.dumps([
        {"timestamp": ts.isoformat(), "symbol": "BTC-USD",
         "regime": "high_volatility_event", "confidence": 0.8},
    ]))
    sig = replay_decisions(path)
    # Exact-match semantics preserved…
    assert sig(ts, "BTC-USD", []) == ("high_volatility_event", 0.8)
    assert sig(ts + timedelta(days=1), "BTC-USD", []) == ("uncertain", 0.0)
    # ...and the product-id shim maps dash-separated BTC-USD onto USDT-quoted
    # BTCUSDT bars.
    assert sig(ts, "BTCUSDT", []) == ("high_volatility_event", 0.8)
    assert sig(ts, "ETHUSDT", []) == ("uncertain", 0.0)


def test_replay_pipeline_doc_fires_once_at_first_bar_at_or_after_generated_at(tmp_path: Path) -> None:
    path = tmp_path / "run.json"
    path.write_text(json.dumps(_pipeline_doc(_T0 + timedelta(minutes=90))))
    sig = replay_decisions(path)
    assert sig(_T0 + timedelta(hours=1), "BTC-USD", []) == ("uncertain", 0.0)  # before
    assert sig(_T0 + timedelta(hours=2), "ETH-USD", []) == ("uncertain", 0.0)  # other symbol
    assert sig(_T0 + timedelta(hours=2), "BTC-USD", []) == ("high_volatility_event", 0.9)          # fires once
    assert sig(_T0 + timedelta(hours=3), "BTC-USD", []) == ("uncertain", 0.0)  # not standing


def test_replay_pipeline_symbol_shim_reaches_legacy_bars(tmp_path: Path) -> None:
    path = tmp_path / "run.json"
    path.write_text(json.dumps(_pipeline_doc(_T0, symbol="BTC-USD")))
    sig = replay_decisions(path)
    assert sig(_T0 + timedelta(hours=1), "BTCUSDT", []) == ("high_volatility_event", 0.9)


def test_replay_pipeline_newest_run_wins_when_bars_are_sparse(tmp_path: Path) -> None:
    docs = [
        _pipeline_doc(_T0 + timedelta(minutes=10), regime="high_volatility_event", confidence=0.55),
        _pipeline_doc(_T0 + timedelta(minutes=50), regime="range_bound", confidence=0.9),
    ]
    path = tmp_path / "runs.json"
    path.write_text(json.dumps(docs))
    sig = replay_decisions(path)
    # Both runs precede the first bar: the newest advisory supersedes the older.
    assert sig(_T0 + timedelta(hours=1), "BTC-USD", []) == ("range_bound", 0.9)
    assert sig(_T0 + timedelta(hours=2), "BTC-USD", []) == ("uncertain", 0.0)


def test_replay_pipeline_each_run_fires_on_its_own_bar(tmp_path: Path) -> None:
    docs = [
        _pipeline_doc(_T0 + timedelta(minutes=30), regime="high_volatility_event", confidence=0.9),
        _pipeline_doc(_T0 + timedelta(minutes=195), regime="range_bound", confidence=0.8),
    ]
    path = tmp_path / "runs.json"
    path.write_text(json.dumps(docs))
    sig = replay_decisions(path)
    assert sig(_T0 + timedelta(hours=1), "BTC-USD", []) == ("high_volatility_event", 0.9)
    assert sig(_T0 + timedelta(hours=2), "BTC-USD", []) == ("uncertain", 0.0)
    assert sig(_T0 + timedelta(hours=3), "BTC-USD", []) == ("uncertain", 0.0)
    assert sig(_T0 + timedelta(hours=4), "BTC-USD", []) == ("range_bound", 0.8)
    assert sig(_T0 + timedelta(hours=5), "BTC-USD", []) == ("uncertain", 0.0)


def test_replay_mixed_and_malformed_inputs_are_refused(tmp_path: Path) -> None:
    """Silently dropping the run you asked to replay would look valid and
    answer a different question — malformed input stops loudly."""
    mixed = tmp_path / "mixed.json"
    mixed.write_text(json.dumps([
        _pipeline_doc(_T0),
        {"timestamp": _T0.isoformat(), "symbol": "BTC-USD", "regime": "x", "confidence": 0.5},
    ]))
    with pytest.raises(ValueError, match="mixed formats"):
        replay_decisions(mixed)

    bad_row = tmp_path / "bad_row.json"
    doc = _pipeline_doc(_T0)
    del doc["decisions"][0]["regime_decision"]
    bad_row.write_text(json.dumps(doc))
    with pytest.raises(ValueError, match="regime_decision"):
        replay_decisions(bad_row)

    bad_gen = tmp_path / "bad_gen.json"
    bad_gen.write_text(json.dumps({"generated_at": "not-a-date", "decisions": []}))
    with pytest.raises(ValueError, match="generated_at"):
        replay_decisions(bad_gen)

    scalar = tmp_path / "scalar.json"
    scalar.write_text("42")
    with pytest.raises(ValueError, match="expected a JSON list"):
        replay_decisions(scalar)


# ---------- end to end: lake → replay → engine → fills ----------


def test_functions_chain_lake_bars_plus_pipeline_replay_through_engine(tmp_path: Path) -> None:
    """load_lake_candles → replay_decisions(pipeline-shape doc) → run_backtest:
    the replayed regime goes through the SAME policy table every consumer uses and
    comes out as exactly one reduce_25_percent fill at the next bar's open."""
    lake = tmp_path / "lake"
    _build_flat_lake(lake, "BTC-USD", days=2, price=100.0)
    bars = load_lake_candles("BTC-USD", "1h", lake_root=lake)
    assert len(bars) == 48

    dec_path = tmp_path / "decisions.json"
    dec_path.write_text(json.dumps(_pipeline_doc(_T0 + timedelta(days=1, minutes=30))))

    result = run_backtest(
        prices={"BTC-USD": bars},
        signal_fn=replay_decisions(dec_path),
        granularity="1h",
    )
    fired = [d for d in result.decisions if d.action not in ("hold", "maintain")]
    assert len(fired) == 1
    assert fired[0].timestamp == _T0 + timedelta(days=1, hours=1)  # first bar ≥ generated_at
    assert (fired[0].regime, fired[0].confidence, fired[0].action) == (
        "high_volatility_event", 0.9, "halve_position",
    )
    assert len(result.trades) == 1
    trade = result.trades[0]
    assert trade.timestamp == _T0 + timedelta(days=1, hours=2)  # executed next bar's open
    assert trade.action == "halve_position"
    assert trade.price == 100.0
    # Initial allocation is 10_000/100 = 100 units; halve_position sells half
    # (HALVE_KEEP=0.5 in backtest/config.py -- shared with any consumer that sizes
    # from the same table).
    assert trade.delta_qty == pytest.approx(-50.0)


def test_cli_lake_replay_end_to_end(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    lake = tmp_path / "lake"
    _build_flat_lake(lake, "BTC-USD", days=3, price=100.0)
    dec_path = tmp_path / "decisions.json"
    dec_path.write_text(json.dumps(_pipeline_doc(_T0 + timedelta(days=1, minutes=30))))
    out_path = tmp_path / "run.json"

    rc = cli.main([
        "--symbols", "BTC-USD",
        "--lake-root", str(lake),
        "--signal", "replay",
        "--replay-path", str(dec_path),
        "--out", str(out_path),
    ])
    assert rc == 0
    out = capsys.readouterr().out
    assert "replay" in out and "BTC-USD" in out
    assert "72 bars @ 1h" in out  # lake default granularity resolved to 1h

    dump = json.loads(out_path.read_text(encoding="utf-8"))
    assert len(dump["equity_curve"]) == 72
    non_hold = [d for d in dump["decisions"] if d["action"] not in ("hold", "maintain")]
    assert len(non_hold) == 1
    assert non_hold[0]["timestamp"] == (_T0 + timedelta(days=1, hours=1)).isoformat()
    assert non_hold[0]["regime"] == "high_volatility_event"
    assert non_hold[0]["confidence"] == 0.9
    assert non_hold[0]["action"] == "halve_position"  # high_volatility_event @0.9
    assert len(dump["trades"]) == 1
    trade = dump["trades"][0]
    assert trade["symbol"] == "BTC-USD"
    assert trade["action"] == "halve_position"
    assert trade["timestamp"] == (_T0 + timedelta(days=1, hours=2)).isoformat()
    assert trade["price"] == 100.0
    assert trade["delta_qty"] == pytest.approx(-50.0)  # halve_position


def test_cli_lake_granularity_1d_reachable(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    lake = tmp_path / "lake"
    _build_flat_lake(lake, "BTC-USD", days=3, price=100.0)
    rc = cli.main([
        "--symbols", "BTC-USD",
        "--lake-root", str(lake),
        "--granularity", "1d",
    ])
    assert rc == 0
    assert "3 bars @ 1d" in capsys.readouterr().out


def test_cli_lake_missing_lake_is_honest_exit_2(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    rc = cli.main([
        "--symbols", "BTC-USD",
        "--lake-root", str(tmp_path / "nope"),
    ])
    assert rc == 2
    assert "no usable price data" in capsys.readouterr().err
