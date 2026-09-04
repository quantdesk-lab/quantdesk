"""Weight-execution backtest engine tests (run_weight_backtest, Phase B).

Proves the properties that make it institutional: decide-close/execute-next-
open (no lookahead), the no-trade band as first-class turnover control,
long/flat clipping + gross scaling, cash feasibility (never negative), fees
strictly reducing equity, None = hold, and the faithful vol-scaled TSMOM
running end-to-end. Plus Spearman rank-IC sanity."""
from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

from quantdesk.backtest.engine import run_weight_backtest
from quantdesk.backtest.metrics import spearman_rank_ic
from quantdesk.backtest.signals import tsmom_weight
from quantdesk.backtest.types import Bar


def _series(prices: list[float], start: datetime | None = None) -> list[Bar]:
    t0 = start or datetime(2024, 1, 1, tzinfo=timezone.utc)
    return [
        Bar(timestamp=t0 + timedelta(days=i),
            open=p, high=p * 1.002, low=p * 0.998, close=p, volume=1.0)
        for i, p in enumerate(prices)
    ]


def _flat(n=30, px=100.0):
    return _series([px] * n)


# ------------------------------------------------------------ timeline ------
def test_decides_on_close_executes_next_open_no_lookahead():
    seen: list[datetime] = []

    def wf(ts, sym, history):
        assert history[-1].timestamp == ts  # never sees past the decision bar
        seen.append(ts)
        return 1.0

    bars = _series([100.0, 110.0, 120.0, 130.0])
    res = run_weight_backtest({"X": bars}, wf, initial_capital=1000.0,
                              rebalance_every_n_bars=1, cost_bps=0, slippage_bps=0,
                              no_trade_band=0.0)
    # first decision at t0 close -> first trade at t1 open (110), never at t0
    assert res.trades[0].timestamp == bars[1].timestamp
    assert res.trades[0].price == 110.0


def test_no_trade_band_suppresses_small_rebalances():
    def wf(ts, sym, history):
        return 0.55 if len(history) % 2 else 0.50  # oscillates within the band

    res = run_weight_backtest({"X": _flat(20)}, wf, initial_capital=1000.0,
                              rebalance_every_n_bars=1, cost_bps=10, slippage_bps=5,
                              no_trade_band=0.10)
    # first trade establishes ~0.5; after that every |delta| = 0.05 < band -> nothing
    assert len(res.trades) == 1


def test_gross_over_one_scaled_to_one_remainder_cash():
    def wf(ts, sym, history):
        return 0.8  # two symbols -> gross 1.6 -> scaled to 0.5 each

    prices = {"A": _flat(5), "B": _flat(5)}
    res = run_weight_backtest(prices, wf, initial_capital=1000.0,
                              rebalance_every_n_bars=1, cost_bps=0, slippage_bps=0,
                              no_trade_band=0.0)
    _, w = res.weight_history[-1]
    assert abs(w["A"] - 0.5) < 1e-6 and abs(w["B"] - 0.5) < 1e-6


def test_cash_never_negative_and_fees_reduce_equity():
    def wf(ts, sym, history):
        return 1.0

    fee = run_weight_backtest({"X": _flat(10)}, wf, initial_capital=1000.0,
                              rebalance_every_n_bars=1, cost_bps=120, slippage_bps=5,
                              no_trade_band=0.0)
    free = run_weight_backtest({"X": _flat(10)}, wf, initial_capital=1000.0,
                               rebalance_every_n_bars=1, cost_bps=0, slippage_bps=0,
                               no_trade_band=0.0)
    assert fee.final_equity < free.final_equity  # fees are real
    # cash-cap: buying 100% with fees must not overdraw (equity stays finite/positive)
    assert fee.final_equity > 0


def test_long_flat_never_sells_below_zero():
    calls = {"n": 0}

    def wf(ts, sym, history):
        calls["n"] += 1
        return 0.0 if calls["n"] > 1 else 1.0  # buy full, then sell to flat, repeat

    res = run_weight_backtest({"X": _flat(8)}, wf, initial_capital=1000.0,
                              rebalance_every_n_bars=1, cost_bps=0, slippage_bps=0,
                              no_trade_band=0.0)
    # final position flat, and no trade ever pushed qty negative
    _, w = res.weight_history[-1]
    assert abs(w["X"]) < 1e-9
    running = 0.0
    for t in res.trades:
        running += t.delta_qty
        assert running >= -1e-9


def test_none_means_hold_current_position():
    state = {"i": 0}

    def wf(ts, sym, history):
        state["i"] += 1
        return 1.0 if state["i"] == 1 else None  # buy once, then "no view"

    res = run_weight_backtest({"X": _flat(12)}, wf, initial_capital=1000.0,
                              rebalance_every_n_bars=1, cost_bps=0, slippage_bps=0,
                              no_trade_band=0.0)
    assert len(res.trades) == 1  # None never generates a trade
    _, w = res.weight_history[-1]
    assert w["X"] > 0.99


def test_broken_weight_fn_holds_instead_of_trading():
    def wf(ts, sym, history):
        raise RuntimeError("boom")

    res = run_weight_backtest({"X": _flat(6)}, wf, initial_capital=1000.0,
                              rebalance_every_n_bars=1, no_trade_band=0.0)
    assert res.trades == [] and res.final_equity == 1000.0


# ------------------------------------------------ faithful TSMOM end-to-end --
def test_tsmom_weight_invests_in_uptrend_and_stays_out_early():
    # 400 daily bars, mild steady uptrend
    closes = [100.0 * math.exp(0.002 * i) for i in range(400)]
    res = run_weight_backtest({"BTC": _series(closes)}, tsmom_weight(),
                              initial_capital=1000.0, rebalance_every_n_bars=7,
                              cost_bps=60, slippage_bps=5, no_trade_band=0.10)
    # warmup: no trades before bar 263 (None -> hold cash)
    first_trade_day = (res.trades[0].timestamp - res.equity_curve[0][0]).days
    assert first_trade_day >= 263
    # ends invested (positive weight) and profitable net of fees
    _, w = res.weight_history[-1]
    assert w["BTC"] > 0.0
    assert res.final_equity > 1000.0
    # weekly cadence + band: turnover stays tiny
    assert len(res.trades) < 20


# ------------------------------------------------------------- rank IC ------
def test_spearman_rank_ic_bounds_and_ties():
    assert spearman_rank_ic([1, 2, 3, 4], [10, 20, 30, 40]) == 1.0
    assert spearman_rank_ic([1, 2, 3, 4], [40, 30, 20, 10]) == -1.0
    mid = spearman_rank_ic([1.0, 1.0, 2.0, 3.0], [5.0, 6.0, 7.0, 8.0])
    assert mid is not None and 0.0 < mid < 1.0  # midrank ties handled
    assert spearman_rank_ic([1, 2], [1, 2]) is None          # too few
    assert spearman_rank_ic([1, 1, 1], [1, 2, 3]) is None     # degenerate
