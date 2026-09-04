from __future__ import annotations

import math

from quantdesk.factors.quant import (
    funding_zscore_summary,
    momentum_zscores,
    volatility_regime,
)


# ---------- momentum_zscores ----------


def test_momentum_zscores_flags_insufficient_data_per_horizon():
    closes = [100.0] * 5
    out = momentum_zscores(closes, horizons=[1, 30], lookback=20)
    assert out["horizons"]["1b"]["zscore"] is None  # samples is 0 (history empty)
    assert out["horizons"]["30b"]["error"] == "insufficient_data"


def test_momentum_zscores_extreme_move_yields_high_zscore():
    # 90 days of tiny +/-0.1% moves, then a +10% spike on the last day.
    closes = [100.0]
    for i in range(1, 91):
        closes.append(closes[-1] * (1.001 if i % 2 == 0 else 0.999))
    closes.append(closes[-1] * 1.10)  # spike
    out = momentum_zscores(closes, horizons=[1], lookback=80)
    h = out["horizons"]["1b"]
    assert h["zscore"] is not None
    assert h["zscore"] > 5.0
    assert h["label"] == "extremely_high"
    assert h["percentile"] >= 0.99


def test_momentum_zscores_neutral_move_in_normal_range():
    # Random-looking but bounded series; today's move is in the middle of the dist.
    rng_seed = [
        100.0, 100.5, 99.7, 100.2, 100.8, 100.3, 100.1, 100.6,
        99.9, 100.4, 100.0, 100.7, 100.2, 99.8, 100.5,
    ] * 8
    out = momentum_zscores(rng_seed, horizons=[1], lookback=60)
    h = out["horizons"]["1b"]
    assert h["label"] in {"neutral", "low", "high"}
    # Z within +/-2 for a non-tail event.
    assert h["zscore"] is None or abs(h["zscore"]) < 3.0


def test_momentum_zscores_horizon_keys_format():
    closes = [100.0 + i for i in range(50)]
    out = momentum_zscores(closes, horizons=[1, 7], lookback=30)
    assert set(out["horizons"].keys()) == {"1b", "7b"}


# ---------- volatility_regime ----------


def test_volatility_regime_flags_insufficient_data():
    out = volatility_regime([100.0, 101.0], vol_window=14, lookback=60, periods_per_year=365)
    assert "error" in out


def test_volatility_regime_extreme_when_recent_window_explodes():
    # 200 days of low vol, then 20 days of large oscillations.
    calm = [100.0]
    for _ in range(200):
        calm.append(calm[-1] * 1.0005)
    spiky = list(calm)
    for i in range(20):
        spiky.append(spiky[-1] * (1.05 if i % 2 == 0 else 0.96))
    out = volatility_regime(spiky, vol_window=14, lookback=120, periods_per_year=365)
    assert out["regime"] in {"elevated", "extreme"}
    assert out["percentile"] > 0.7


def test_volatility_regime_normal_when_consistent_vol():
    # Constant +/-1% noise -> vol stable -> today should sit near median.
    closes = [100.0]
    for i in range(1, 200):
        closes.append(closes[-1] * (1.01 if i % 2 == 0 else 0.99))
    out = volatility_regime(closes, vol_window=14, lookback=120, periods_per_year=365)
    assert out["regime"] == "normal"
    assert 0.3 <= out["percentile"] <= 0.7


def test_volatility_regime_annualization_uses_sqrt_factor():
    # Daily vol of 0.01 (1%) should annualize to ~ 0.01 * sqrt(365) ~= 19.1%.
    closes = [100.0]
    for i in range(1, 200):
        closes.append(closes[-1] * (1.01 if i % 2 == 0 else (1.0 / 1.01)))
    out = volatility_regime(closes, vol_window=14, lookback=120, periods_per_year=365)
    expected = 0.01 * math.sqrt(365) * 100
    assert abs(out["current_vol_annual_pct"] - expected) < 5.0


# ---------- funding_zscore_summary ----------


def test_funding_zscore_handles_empty_input():
    assert funding_zscore_summary([]) == {"error": "insufficient_data"}


def test_funding_zscore_extreme_positive():
    # 99 quiet samples noisy around 0.0001 (0.01%), current at 0.001 (0.10%) -> tail event.
    history = [0.0001 + 0.00001 * ((i % 5) - 2) for i in range(99)]
    rates = history + [0.001]
    out = funding_zscore_summary(rates)
    assert out["zscore"] is not None and out["zscore"] > 3.0
    assert out["regime"] == "extremely_positive"
    assert out["percentile"] == 1.0


def test_funding_zscore_extreme_negative():
    history = [0.0001 + 0.00001 * ((i % 5) - 2) for i in range(99)]
    rates = history + [-0.001]
    out = funding_zscore_summary(rates)
    assert out["zscore"] is not None and out["zscore"] < -3.0
    assert out["regime"] == "extremely_negative"


def test_funding_zscore_neutral_when_current_matches_history():
    rates = [0.0001] * 100
    out = funding_zscore_summary(rates)
    # Std of constant series is 0 -> zscore is None, but percentile and median are still defined.
    assert out["zscore"] is None
    assert out["median_funding_rate"] == 0.0001


def test_funding_zscore_annualized_pct():
    # Single funding rate of 0.0001 (0.01%) settled 3x/day = 1095 settlements/year.
    # Annual = 0.0001 * 1095 * 100 = 10.95%
    rates = [0.0001]
    out = funding_zscore_summary(rates, funding_intervals_per_year=365 * 3)
    assert abs(out["current_funding_annual_pct"] - 10.95) < 0.01
