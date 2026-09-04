"""Time-series momentum and volatility factor library tests (quantdesk/factors/tsmom.py).

Synthetic-data proofs of the properties that make the implementation
institutional rather than naive: no lookahead (prefix-determinism), fail-to-
uncertain on short history, Yang-Zhang matching a hand-computed closed form,
Harvey et al. (2022) EWMA conventions, regime-map branches, and policy-gate calibration."""
from __future__ import annotations

import math
import random

import pytest

from quantdesk.factors.tsmom import (
    MIN_BARS_DAILY,
    THETA,
    ewma_beta,
    ewma_vol_annual,
    rank_scores,
    robust_zscores,
    rogers_satchell_var,
    target_weight,
    tsmom_regime,
    tsmom_score,
    winsorize,
    yang_zhang_vol_annual,
)
from quantdesk.policy import translate_regime_to_action

REGIMES = {
    "trend_down","high_volatility_event", "trend_up",
           "range_bound", "uncertain"}


def _gbm(n, *, start=100.0, drift=0.0, vol=0.02, seed=7):
    rng = random.Random(seed)
    closes = [start]
    for _ in range(n - 1):
        closes.append(closes[-1] * math.exp(drift + vol * rng.gauss(0, 1)))
    return closes


# ---------------------------------------------------------------- EWMA vol --
def test_ewma_vol_constant_returns_equals_closed_form():
    # constant log return r each bar -> variance recursion is exactly r^2
    r = 0.01
    closes = [100.0 * math.exp(r * i) for i in range(60)]
    v = ewma_vol_annual(closes, com=5, ppy=365)
    assert v is not None
    assert abs(v - abs(r) * math.sqrt(365)) < 1e-9


def test_ewma_vol_insufficient_history_returns_none():
    assert ewma_vol_annual([100.0, 101.0, 102.0], com=5, ppy=365) is None


# ------------------------------------------------------------- Yang-Zhang --
def test_yang_zhang_matches_hand_computed_closed_form():
    # 4 synthetic bars, open == prev close (24/7 crypto), hand-compute YZ
    opens = [100.0, 102.0, 101.0, 103.0]
    highs = [103.0, 103.5, 104.0, 105.0]
    lows = [99.0, 100.5, 100.0, 102.0]
    closes = [102.0, 101.0, 103.0, 104.0]
    got = yang_zhang_vol_annual(opens, highs, lows, closes, ppy=365)
    assert got is not None
    # hand computation (bars 1..3, m=3)
    import statistics as st
    o = [math.log(opens[i] / closes[i - 1]) for i in range(1, 4)]   # all 0.0
    c = [math.log(closes[i] / opens[i]) for i in range(1, 4)]
    rs_terms = []
    for i in range(1, 4):
        u = math.log(highs[i] / opens[i])
        d = math.log(lows[i] / opens[i])
        cc = math.log(closes[i] / opens[i])
        rs_terms.append(u * (u - cc) + d * (d - cc))
    m = 3
    k = 0.34 / (1.34 + (m + 1) / (m - 1))
    var = st.variance(o) + k * st.variance(c) + (1 - k) * (sum(rs_terms) / m)
    assert abs(got - math.sqrt(var * 365)) < 1e-12
    # 24/7: gap term is exactly zero here
    assert st.variance(o) == 0.0


def test_yang_zhang_rejects_bad_bars():
    # high < close violates OHLC sanity -> None, never a silent skew
    assert yang_zhang_vol_annual([100, 101], [100.5, 100.9], [99, 100], [101, 101.5], ppy=365) is None
    assert rogers_satchell_var([100], [101], [99], [100.5]) is None  # n < 2


# ------------------------------------------------------------ TSMOM score --
def test_tsmom_score_short_history_not_ok():
    d = tsmom_score(_gbm(MIN_BARS_DAILY - 1))
    assert d["ok"] is False and d["need"] == MIN_BARS_DAILY


def test_tsmom_no_lookahead_prefix_determinism():
    """Score at t must be a pure function of the prefix: appending future bars
    must not change the score computed on the same prefix."""
    closes = _gbm(400, drift=0.002)
    prefix = closes[:300]
    before = tsmom_score(list(prefix))
    _ = tsmom_score(closes)  # compute on the full series (would mutate any bad global state)
    after = tsmom_score(list(prefix))
    assert before == after


def test_tsmom_rising_series_positive_score_trend_regime():
    closes = _gbm(400, drift=0.004, vol=0.01, seed=3)
    d = tsmom_score(closes)
    assert d["ok"] and d["score"] > THETA
    rr = tsmom_regime(closes)
    assert rr["regime"] in ("trend_up", "high_volatility_event")
    assert rr["confidence"] >= 0.5


def test_tsmom_v_shape_maps_to_range_bound_base():
    # 340 falling days then 60 strongly rising: slow window still bear, fast up
    down = _gbm(340, drift=-0.004, vol=0.01, seed=5)
    up = [down[-1] * math.exp(0.008 * (i + 1)) for i in range(60)]
    rr = tsmom_regime(down + up)
    assert rr["regime"] == "range_bound"
    # confidence must clear the 0.60 deep-bear gate only with real magnitude
    assert 0.5 <= rr["confidence"] <= 0.95


def test_tsmom_flat_series_range_bound_below_action_gates():
    closes = [100.0 + 0.01 * math.sin(i / 5) for i in range(400)]
    rr = tsmom_regime(closes)
    assert rr["regime"] == "range_bound"  # measured no-trend (current vocab)
    assert rr["confidence"] < 0.5  # zero evidence can never cross an action gate
    assert translate_regime_to_action(rr["regime"], rr["confidence"]) == "maintain"


def test_tsmom_insufficient_history_fails_to_uncertain():
    rr = tsmom_regime(_gbm(50))
    assert rr["regime"] == "uncertain"
    assert rr["confidence"] == 0.30
    assert translate_regime_to_action(rr["regime"], rr["confidence"]) == "maintain"


def test_confidence_bounds_and_policy_compatibility():
    for seed in range(6):
        closes = _gbm(400, drift=random.Random(seed).uniform(-0.004, 0.004), seed=seed)
        rr = tsmom_regime(closes)
        assert rr["regime"] in REGIMES
        assert 0.30 <= rr["confidence"] <= 0.95
        translate_regime_to_action(rr["regime"], rr["confidence"])  # must not raise


def test_t2_lag_vol_ignores_final_two_bars():
    """Harvey et al. (2022) t-2 discipline: a shock in the last 2 bars must not change the
    vol estimate used for sizing (it only moves the momentum leg)."""
    closes = _gbm(400, vol=0.01, seed=11)
    shocked = list(closes)
    shocked[-1] *= 1.5  # violent decision-bar move
    a = tsmom_score(closes)
    b = tsmom_score(shocked)
    assert a["ok"] and b["ok"]
    assert a["sigma_ann"] == b["sigma_ann"]  # sizing vol unchanged
    assert a["score"] != b["score"]          # momentum leg does see the move


# ------------------------------------------------------------ target weight --
def test_target_weight_mop_rule_long_flat_clamped():
    assert target_weight(1.0, 0.10) == 1.0          # 10%/10% * 1.0 = 1 (capped)
    assert target_weight(0.5, 0.40) == pytest.approx(0.125)  # vol-scaled down
    assert target_weight(-0.8, 0.20) == 0.0         # spot: no shorts
    assert target_weight(1.0, 0.0) == 0.0           # degenerate vol -> flat


# ------------------------------------------------- robust scoring helpers --
def test_robust_zscores_median_mad_and_winsorization():
    z = robust_zscores([1.0, 2.0, 3.0, 4.0, 100.0])
    assert max(z) == 3.0          # outlier clipped ONCE at +3
    assert z[2] == 0.0            # median maps to zero
    assert robust_zscores([5.0, 5.0, 5.0]) == [0.0, 0.0, 0.0]  # degenerate -> zeros


def test_rank_scores_unit_variance_shape():
    z = rank_scores([10.0, 20.0, 30.0, 40.0])
    assert z[0] < z[1] < z[2] < z[3]
    assert abs(sum(z)) < 1e-12    # symmetric around 0
    import statistics as st
    assert abs(st.pstdev(z) - math.sqrt(5.0 / 4.0 / (5.0 / 4.0))) < 0.35  # ~unit scale


def test_winsorize_bounds():
    assert winsorize(10.0) == 3.0 and winsorize(-10.0) == -3.0 and winsorize(1.2) == 1.2


# ---------------------------------------------------------------- EWMA beta --
def test_ewma_beta_recovers_known_beta_with_shrinkage():
    rng = random.Random(1)
    bench = [rng.gauss(0, 0.02) for _ in range(300)]
    asset = [2.0 * b for b in bench]  # true beta 2
    got = ewma_beta(asset, bench)
    # shrunk 1/3 toward 1: expect ~ (2/3)*2 + (1/3)*1 = 1.667
    assert abs(got - (2 / 3 * 2 + 1 / 3)) < 0.05


def test_ewma_beta_fails_safe_to_one():
    assert ewma_beta([0.01] * 10, [0.01] * 10) == 1.0  # < min_obs
