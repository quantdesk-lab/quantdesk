"""Null-band tests (quantdesk.research.null_calibration).

The empirical null is what makes the board's Rank-IC column readable, so its
shape, determinism, ordering invariants, the honesty-gate pass-through and
the band width itself (pooled p95 well below 0.25 at 350 bars) are pinned,
along with the runtime budget the site build depends on.
"""
from __future__ import annotations

import time

import pytest

from quantdesk.factors.alpha101 import ALPHAS
from quantdesk.research.null_calibration import (
    alpha_ics_on_walk,
    null_ic_distribution,
    percentile,
)


@pytest.fixture(scope="module")
def null20():
    t0 = time.perf_counter()
    out = null_ic_distribution(20, 350)
    out["_elapsed"] = time.perf_counter() - t0
    return out


def test_percentile_helper_known_values():
    xs = [4.0, 1.0, 3.0, 2.0]
    assert percentile(xs, 0) == 1.0
    assert percentile(xs, 100) == 4.0
    assert percentile(xs, 50) == pytest.approx(2.5)
    assert percentile(xs, 25) == pytest.approx(1.75)
    assert percentile([7.0], 95) == 7.0
    assert percentile([], 50) is None
    with pytest.raises(ValueError):
        percentile(xs, 101)


def test_structure_and_registry_order(null20):
    assert null20["n_reseeds"] == 20 and null20["bars"] == 350
    assert null20["horizon"] == 1 and null20["timeframe"] == "1h"
    assert [a["id"] for a in null20["alphas"]] == [e["id"] for e in ALPHAS]
    assert [a["num"] for a in null20["alphas"]] == [e["num"] for e in ALPHAS]
    for a in null20["alphas"]:
        assert set(a) == {"id", "num", "abs_ic_p50", "abs_ic_p95", "abs_ic_max", "n",
                          "n_pairs_median"}
        assert 0 <= a["n"] <= 20
        if a["n"]:
            assert 0.0 <= a["abs_ic_p50"] <= a["abs_ic_p95"] <= a["abs_ic_max"] <= 1.0
            assert a["n_pairs_median"] >= 30  # the board's honesty gate
    pooled = null20["pooled"]
    assert set(pooled) == {"p50", "p95", "p99", "n"}
    assert pooled["n"] == sum(a["n"] for a in null20["alphas"])
    assert 0.0 <= pooled["p50"] <= pooled["p95"] <= pooled["p99"] <= 1.0
    assert "indistinguishable from noise" in null20["note"]


def test_band_is_narrow_at_350_bars(null20):
    """Random walks carry no information: the pooled |IC| band must sit well
    inside the institutional register (p95 < 0.25), and a factor's IC must be
    read against it, not against zero."""
    assert null20["pooled"]["p95"] < 0.25
    assert null20["pooled"]["p50"] < 0.10
    assert null20["pooled"]["n"] >= 19 * 20 * 0.9  # nearly every alpha prints every time
    # short-warmup alphas (many pairs) have tighter nulls than long-warmup ones
    by_id = {a["id"]: a for a in null20["alphas"]}
    assert by_id["a101"]["abs_ic_p95"] < by_id["a032"]["abs_ic_p95"]
    assert by_id["a101"]["n_pairs_median"] > by_id["a032"]["n_pairs_median"]


def test_runtime_budget(null20):
    assert null20["_elapsed"] < 60.0


def test_deterministic_and_seed_sensitive():
    a = null_ic_distribution(3, 120, seed0=5)
    b = null_ic_distribution(3, 120, seed0=5)
    assert a == b
    c = null_ic_distribution(3, 120, seed0=6)
    assert c["pooled"] != a["pooled"]


def test_gates_pass_through_as_missing_samples():
    # 100 bars: alphas with lookback >= 100 (a024: 200, a032: 295) never print an IC
    out = null_ic_distribution(2, 100, seed0=1)
    by_id = {a["id"]: a for a in out["alphas"]}
    assert by_id["a024"]["n"] == 0 and by_id["a024"]["abs_ic_p95"] is None
    assert by_id["a032"]["n"] == 0 and by_id["a032"]["abs_ic_max"] is None
    assert by_id["a101"]["n"] == 2
    assert out["pooled"]["n"] < 19 * 2


def test_overlapping_horizon_is_gated_by_n_eff():
    out = null_ic_distribution(2, 120, horizon=24, seed0=1)
    assert out["horizon"] == 24
    # 120 bars at h=24 leaves < 8 effective samples for every alpha -> nothing prints
    assert out["pooled"]["n"] == 0
    assert out["pooled"]["p95"] is None


def test_alpha_ics_on_walk_rows_match_board_ic_shape():
    rows = alpha_ics_on_walk(200, seed=3)
    assert set(rows) == {e["id"] for e in ALPHAS}
    for r in rows.values():
        assert {"h", "ic", "n", "overlap"} <= set(r)
        assert r["h"] == 1 and r["overlap"] is False
    with pytest.raises(ValueError):
        alpha_ics_on_walk(50, seed=1, timeframe="5m")


def test_invalid_arguments():
    with pytest.raises(ValueError):
        null_ic_distribution(0, 100)
    with pytest.raises(ValueError):
        null_ic_distribution(2, 1)
    with pytest.raises(ValueError):
        null_ic_distribution(2, 100, horizon=0)
