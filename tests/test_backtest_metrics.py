from __future__ import annotations

from datetime import datetime, timedelta, timezone

from quantdesk.backtest.metrics import compute_metrics, max_drawdown
from quantdesk.backtest.types import BacktestResult


def _curve(values: list[float]):
    t0 = datetime(2024, 1, 1, tzinfo=timezone.utc)
    return [(t0 + timedelta(days=i), v) for i, v in enumerate(values)]


def _result(values: list[float], granularity: str = "1day") -> BacktestResult:
    return BacktestResult(
        equity_curve=_curve(values),
        trades=[],
        decisions=[],
        weight_history=[],
        granularity=granularity,
    )


def test_max_drawdown_on_known_curve():
    eq = [100, 120, 90, 110, 80, 130]
    # peaks: 100, 120, 120, 120, 120, 130; worst trough vs peak = (80 - 120) / 120
    assert abs(max_drawdown(eq) - (-1.0 / 3.0)) < 1e-9


def test_max_drawdown_zero_on_monotonic_up():
    assert max_drawdown([1, 2, 3, 4, 5]) == 0.0


def test_total_return_doubling_year():
    eq = [100.0 * (2 ** (i / 364)) for i in range(365)]
    m = compute_metrics(_result(eq))
    assert abs(m["total_return"] - 1.0) < 1e-6
    # CAGR over ~1 year should be approximately 100% (allow small numerical slack).
    assert abs(m["cagr"] - 1.0) < 0.05


def test_flat_curve_zeros_out_risk_metrics():
    m = compute_metrics(_result([1000.0] * 100))
    assert m["total_return"] == 0.0
    assert m["sharpe"] == 0.0
    assert m["sortino"] == 0.0
    assert m["max_drawdown"] == 0.0
    assert m["cagr"] == 0.0


def test_higher_vol_lowers_sharpe_for_same_drift():
    # Both curves drift up at ~0.5%/period but with very different oscillation
    # amplitudes. Higher vol -> lower risk-adjusted return.
    low_vol = [100.0]
    high_vol = [100.0]
    for i in range(1, 200):
        low_vol.append(low_vol[-1] * (1.005 + (0.001 if i % 2 == 0 else -0.001)))
        high_vol.append(high_vol[-1] * (1.005 + (0.04 if i % 2 == 0 else -0.04)))
    m_low = compute_metrics(_result(low_vol))
    m_high = compute_metrics(_result(high_vol))
    assert m_low["ann_vol"] < m_high["ann_vol"]
    assert m_low["sharpe"] > m_high["sharpe"]


def test_too_short_curve_returns_empty():
    assert compute_metrics(_result([100.0])) == {}
