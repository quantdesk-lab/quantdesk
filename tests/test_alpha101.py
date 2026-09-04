"""Alpha101 factor engine tests (quantdesk/factors/alpha101.py).

Synthetic known-answer proofs of the properties that make the adaptation
honest rather than decorative: operator conventions (argmax position,
midrank ties, ddof=1, A-guard Nones), hand-computed alphas, prefix
determinism over every registry entry (the no-lookahead proof), graceful
degradation on short/degenerate history, and registry metadata whose
declared lookbacks are verified against observed warmup."""
from __future__ import annotations

import math
import random
import statistics as st

import pytest

from quantdesk.factors.alpha101 import (
    ALPHAS,
    alpha006,
    alpha009,
    alpha012,
    alpha046,
    alpha053,
    alpha054,
    alpha101,
    correlation,
    delay,
    delta,
    returns,
    signedpower,
    sma,
    stddev,
    ts_argmax,
    ts_max,
    ts_min,
    ts_rank,
    ts_scale,
    ts_sum,
)


def _gbm_bars(n, *, start=100.0, drift=0.0, vol=0.02, seed=7):
    """OHLCV adaptation of tests/test_factors.py _gbm: 24/7 bars (open ==
    prev close), high/low straddle the body, lognormal varying volume."""
    rng = random.Random(seed)
    closes = [start]
    for _ in range(n - 1):
        closes.append(closes[-1] * math.exp(drift + vol * rng.gauss(0, 1)))
    opens = [closes[0]] + closes[:-1]
    highs, lows, volumes = [], [], []
    for o, c in zip(opens, closes):
        highs.append(max(o, c) * (1.0 + 0.003 * rng.random()))
        lows.append(min(o, c) * (1.0 - 0.003 * rng.random()))
        volumes.append(100.0 * math.exp(0.5 * rng.gauss(0, 1)))
    return opens, highs, lows, closes, volumes


_BARS350 = _gbm_bars(350)


# --------------------------------------------------------------- operators --
def test_delay_delta_known_values():
    x = [1.0, 2.0, 4.0, 7.0]
    assert delay(x, 2) == [None, None, 1.0, 2.0]
    assert delta(x, 2) == [None, None, 3.0, 5.0]
    assert delta(x, 1) == [None, 1.0, 2.0, 3.0]


def test_ts_min_max_argmax_convention():
    x = [1.0, 3.0, 2.0, 5.0, 4.0]
    assert ts_min(x, 3) == [None, None, 1.0, 2.0, 2.0]
    assert ts_max(x, 3) == [None, None, 3.0, 5.0, 5.0]
    am = ts_argmax(x, 3)
    assert am[:2] == [None, None]
    assert am[2] == 2.0  # window [1,3,2]: max one bar back
    assert am[3] == 3.0  # window [3,2,5]: max is the CURRENT bar -> w
    assert am[4] == 2.0  # window [2,5,4]: max one bar back -> 2


def test_ts_rank_midranks_and_bounds():
    # ties midrank: window [2,1,2], current 2 -> (1 less + (2 equal + 1)/2)/3
    r = ts_rank([2.0, 1.0, 2.0], 3)
    assert r[:2] == [None, None]
    assert r[2] == pytest.approx(2.5 / 3.0)
    # strict window max hits the upper bound 1.0; strict min stays > 0
    assert ts_rank([1.0, 2.0, 3.0], 3)[2] == 1.0
    assert ts_rank([3.0, 2.0, 1.0], 3)[2] == pytest.approx(1.0 / 3.0)
    # any None inside the window -> None
    assert ts_rank([1.0, None, 3.0, 4.0], 2) == [None, None, None, 1.0]


def test_stddev_matches_statistics_stdev():
    x = [3.0, 1.0, 4.0, 1.5, 9.2, 2.6]
    got = stddev(x, 4)
    assert got[:3] == [None, None, None]
    assert got[3] == pytest.approx(st.stdev(x[0:4]))  # ddof=1, repo convention
    assert got[5] == pytest.approx(st.stdev(x[2:6]))


def test_correlation_perfect_and_degenerate():
    x = [1.0, 2.0, 4.0, 8.0, 16.0, 5.0]
    y = [2.0 * v + 1.0 for v in x]
    c = correlation(x, y, 4)
    assert c[:3] == [None, None, None]
    assert c[3] == pytest.approx(1.0)
    assert c[5] == pytest.approx(1.0)
    # constant leg -> zero variance -> None, never a ZeroDivisionError
    assert correlation(x, [7.0] * 6, 4)[-1] is None


def test_signedpower_preserves_sign():
    assert signedpower([-4.0, 3.0, 0.0], 2.0) == [-16.0, 9.0, 0.0]


def test_ts_scale_unit_trailing_mean_abs():
    s = ts_scale([1.0, -2.0, 3.0], 3)
    assert s[:2] == [None, None]
    assert s[2] == pytest.approx(3.0 / 2.0)  # 3 / mean(|1|,|2|,|3|)
    # constant series normalizes to +/-1 (sign preserved)
    assert ts_scale([-5.0] * 4, 3)[-1] == pytest.approx(-1.0)
    # all-zero window -> None (A-guard)
    assert ts_scale([0.0] * 5, 3)[-1] is None


def test_operator_warmup_none_counts():
    x = [float(i * i % 7 + 1) for i in range(20)]  # varying, positive
    y = [float(i + 1) for i in range(20)]
    cases = [
        (delay(x, 3), 3),
        (delta(x, 3), 3),
        (ts_sum(x, 5), 4),
        (sma(x, 5), 4),
        (ts_min(x, 5), 4),
        (ts_max(x, 5), 4),
        (ts_argmax(x, 5), 4),
        (ts_rank(x, 5), 4),
        (ts_scale(x, 5), 4),
        (stddev(x, 5), 4),
        (correlation(x, y, 5), 4),
        (returns(y), 1),
    ]
    for series, warm in cases:
        assert all(v is None for v in series[:warm])
        assert all(v is not None for v in series[warm:])


# ------------------------------------------------------- no-lookahead proof --
@pytest.mark.parametrize("entry", ALPHAS, ids=[e["id"] for e in ALPHAS])
def test_prefix_determinism_all_alphas(entry):
    """fn(prefix) == fn(full)[:len(prefix)]: element t is a pure function of
    bars <= t, so appending future bars must not change the past."""
    o, h, l, c, v = _BARS350
    cut = 300
    full = entry["fn"](o, h, l, c, v)
    pre = entry["fn"](o[:cut], h[:cut], l[:cut], c[:cut], v[:cut])
    assert pre == full[:cut]


# ------------------------------------------------------ hand-computed alphas --
def test_alpha101_hand_computed():
    out = alpha101([100.0], [112.0], [99.0], [110.0], [1000.0])
    assert out == [pytest.approx(10.0 / 13.001)]


def test_alpha012_hand_computed():
    closes = [100.0, 102.0, 101.0]
    volumes = [10.0, 12.0, 11.0]
    out = alpha012(closes, closes, closes, closes, volumes)
    assert out[0] is None
    assert out[1] == pytest.approx(-2.0)  # sign(+2) * -(+2)
    assert out[2] == pytest.approx(-1.0)  # sign(-1) * -(-1)


def test_alpha006_correlated_open_volume_is_minus_one():
    opens = [100.0 + (i * 1.7) % 9 + 0.3 * i for i in range(15)]
    volumes = [3.0 * o + 7.0 for o in opens]  # perfectly linear in open
    out = alpha006(opens, opens, opens, opens, volumes)
    assert out[8] is None  # 10-bar window not yet full
    for v in out[9:]:
        assert v == pytest.approx(-1.0)


def test_alpha009_momentum_and_reversal_branches():
    up = [100.0 + i for i in range(8)]  # deltas all +1
    out_up = alpha009(up, up, up, up, [1.0] * 8)
    assert out_up[5] == pytest.approx(1.0)  # ts_min(delta,5) > 0 -> momentum
    down = [100.0 - i for i in range(8)]  # deltas all -1
    out_dn = alpha009(down, down, down, down, [1.0] * 8)
    assert out_dn[5] == pytest.approx(-1.0)  # ts_max < 0 -> ride the move
    mixed = [100.0, 101.0, 102.0, 103.0, 104.0, 105.0, 104.0, 105.0]
    out_mx = alpha009(mixed, mixed, mixed, mixed, [1.0] * 8)
    assert out_mx[6] == pytest.approx(1.0)   # mixed window -> -delta = +1
    assert out_mx[7] == pytest.approx(-1.0)  # mixed window -> -delta = -1


# ------------------------------------------------------ degenerate inputs --
def test_flat_bars_no_zerodivision():
    """h == l == o == c: division-guarded alphas must return None or a finite
    value at every index — never raise."""
    flat = [100.0] * 30
    vols = [5.0] * 30
    for fn in (alpha046, alpha053, alpha054, alpha101):
        out = fn(flat, flat, flat, flat, vols)
        assert len(out) == 30
        for v in out:
            assert v is None or math.isfinite(v)
    # spot checks: zero-range guards fire, epsilon keeps a101 finite at 0
    assert all(v is None for v in alpha053(flat, flat, flat, flat, vols))
    assert all(v is None for v in alpha054(flat, flat, flat, flat, vols))
    assert alpha101(flat, flat, flat, flat, vols)[-1] == 0.0


def test_all_alphas_on_gbm_shape_and_last_value():
    o, h, l, c, v = _BARS350
    for entry in ALPHAS:
        out = entry["fn"](o, h, l, c, v)
        assert len(out) == 350, entry["id"]
        assert out[-1] is not None, entry["id"]
        for val in out:
            if val is not None:
                assert math.isfinite(val), entry["id"]


def test_all_alphas_short_history_graceful():
    o, h, l, c, v = _gbm_bars(30, seed=9)
    for entry in ALPHAS:
        out = entry["fn"](o, h, l, c, v)  # must not raise
        assert len(out) == 30, entry["id"]
        if entry["lookback"] > 30:
            assert out[-1] is None, entry["id"]


# ---------------------------------------------------------------- registry --
def test_registry_metadata_complete_and_lookback_honest():
    assert len(ALPHAS) == 19
    ids = [e["id"] for e in ALPHAS]
    assert len(set(ids)) == 19
    o, h, l, c, v = _BARS350
    for entry in ALPHAS:
        for key in ("id", "num", "fn", "style", "formula", "adaptation", "paper_ref", "lookback"):
            assert key in entry, f"{entry.get('id')}: missing {key}"
        out = entry["fn"](o, h, l, c, v)
        first_valid = next(i for i, val in enumerate(out) if val is not None)
        assert first_valid <= entry["lookback"], (
            f"{entry['id']}: first valid at {first_valid} "
            f"> declared lookback {entry['lookback']}"
        )
