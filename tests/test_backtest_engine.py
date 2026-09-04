from __future__ import annotations

from datetime import datetime, timedelta, timezone

from quantdesk.backtest.engine import run_backtest
from quantdesk.backtest.signals import buy_and_hold
from quantdesk.backtest.types import Bar


def _series(prices: list[float], start: datetime | None = None) -> list[Bar]:
    t0 = start or datetime(2024, 1, 1, tzinfo=timezone.utc)
    return [
        Bar(
            timestamp=t0 + timedelta(days=i),
            open=p, high=p * 1.001, low=p * 0.999, close=p, volume=1.0,
        )
        for i, p in enumerate(prices)
    ]


def test_buy_and_hold_matches_price_return_no_costs():
    bars = _series([100.0 + i for i in range(50)])  # 100 -> 149
    result = run_backtest(
        prices={"X": bars},
        signal_fn=buy_and_hold(),
        initial_capital=1000.0,
        cost_bps=0.0,
        slippage_bps=0.0,
    )
    assert result.trades == []
    expected_ratio = bars[-1].close / bars[0].open
    assert abs(result.final_equity / 1000.0 - expected_ratio) < 1e-9


def test_halve_position_decreases_holdings():
    bars = _series([100.0] * 10)  # flat -> no price change isolates the action effect

    def fn(ts, sym, history):
        if len(history) == 3:
            return ("high_volatility_event", 0.99)  # -> halve_position
        return ("uncertain", 0.0)  # -> maintain: no other trades

    result = run_backtest(
        prices={"X": bars},
        signal_fn=fn,
        initial_capital=1000.0,
        initial_weights={"X": 0.06},
        cost_bps=0.0,
        slippage_bps=0.0,
    )
    assert len(result.trades) == 1
    t = result.trades[0]
    assert t.action == "halve_position"
    assert t.delta_qty < 0
    # On a flat series with no costs, equity should be unchanged.
    assert abs(result.final_equity - 1000.0) < 1e-9


def test_costs_strictly_reduce_equity_versus_costless():
    bars = _series([100.0] * 10)

    def fn(ts, sym, history):
        if len(history) == 2:
            return ("high_volatility_event", 0.99)
        return ("trend_up", 0.5)

    no_cost = run_backtest(
        prices={"X": bars}, signal_fn=fn, initial_capital=1000.0,
        cost_bps=0.0, slippage_bps=0.0,
    ).final_equity
    with_cost = run_backtest(
        prices={"X": bars}, signal_fn=fn, initial_capital=1000.0,
        cost_bps=10.0, slippage_bps=5.0,
    ).final_equity
    assert with_cost < no_cost


def test_signal_function_never_sees_future_bars():
    bars = _series([100.0 + i for i in range(5)])
    seen_lengths = []

    def fn(ts, sym, history):
        seen_lengths.append(len(history))
        # Every bar in history must be <= ts (no peeking ahead).
        assert all(b.timestamp <= ts for b in history)
        return ("trend_up", 0.5)

    run_backtest(prices={"X": bars}, signal_fn=fn, initial_capital=1000.0,
                 cost_bps=0.0, slippage_bps=0.0)
    # The last bar generates no decision (no next bar to execute on), so we expect
    # one signal call per bar except the last: lengths 1, 2, 3, 4.
    assert seen_lengths == [1, 2, 3, 4]


def test_multi_asset_alignment_uses_intersection_of_timestamps():
    btc = _series([100.0] * 10, start=datetime(2024, 1, 1, tzinfo=timezone.utc))
    eth = _series([100.0] * 10, start=datetime(2024, 1, 5, tzinfo=timezone.utc))
    # Overlap is 6 days (Jan 5..10).
    result = run_backtest(
        prices={"BTC": btc, "ETH": eth},
        signal_fn=buy_and_hold(),
        initial_capital=1000.0,
        cost_bps=0.0,
        slippage_bps=0.0,
    )
    assert len(result.equity_curve) == 6


def test_reaccumulate_uses_cash_when_available():
    bars = _series([100.0] * 10)
    # Pre-allocate so cash > 0 by giving 50% weight only.
    initial_weights = {"X": 0.5}

    def fn(ts, sym, history):
        if len(history) == 2:
            return ("range_bound", 0.99)  # -> reaccumulate_small
        return ("trend_up", 0.5)

    result = run_backtest(
        prices={"X": bars},
        signal_fn=fn,
        initial_capital=1000.0,
        initial_weights=initial_weights,
        cost_bps=0.0,
        slippage_bps=0.0,
    )
    buys = [t for t in result.trades if t.delta_qty > 0]
    assert len(buys) == 1
    assert buys[0].action in ("target_weight_60", "target_weight_30", "target_weight_100")  # new-vocab buy


def test_uncertain_regime_produces_no_trades():
    bars = _series([100.0 + i * 0.1 for i in range(20)])

    def fn(ts, sym, history):
        return ("uncertain_need_more_info", 0.99)

    result = run_backtest(
        prices={"X": bars}, signal_fn=fn, initial_capital=1000.0,
        cost_bps=10.0, slippage_bps=5.0,
    )
    assert result.trades == []
