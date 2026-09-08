"""Ledger and deflation tests (quantdesk.search.ledger): counts, the
max-of-N threshold against a brute-force null simulation, its monotonicity,
and the holdout p-value on known values."""
from __future__ import annotations

import math
import random
from statistics import NormalDist

import pytest

from quantdesk.search.ledger import TrialLedger, deflated_threshold, holdout_p_value


def test_ledger_counts_by_kind():
    lg = TrialLedger()
    assert lg.record_scored("reversal") == 1
    assert lg.record_scored("reversal") == 2
    assert lg.record_scored("range") == 1
    lg.record_duplicate()
    lg.record_refused()
    lg.record_rejected("too_deep")
    lg.record_rejected("too_deep")
    lg.record_rejected("warmup")
    assert lg.counts() == {
        "n_trials": 3, "n_duplicates": 1, "n_refused": 1, "n_rejected": 3,
        "per_family": {"range": 1, "reversal": 2},
        "rejections": {"too_deep": 2, "warmup": 1},
    }


def test_threshold_n_equals_one_is_the_two_sided_normal_bar():
    for n in (31, 300, 1900):
        expect = NormalDist().inv_cdf(0.975) / math.sqrt(n - 1)
        assert deflated_threshold(n, 1) == pytest.approx(expect, abs=1e-9)
        assert deflated_threshold(n, 1, kappa=1.1) == pytest.approx(1.1 * expect, abs=1e-9)


def test_threshold_rises_with_trials_and_falls_with_pairs():
    ts = [deflated_threshold(760, k) for k in (1, 2, 5, 10, 50, 200)]
    assert ts == sorted(ts) and ts[0] < ts[-1]
    ns = [deflated_threshold(n, 50) for n in (60, 300, 760, 1900)]
    assert ns == sorted(ns, reverse=True)
    # the review's reference points: about 0.071 (N=1) and 0.119 (N=50) at 759 pairs
    assert deflated_threshold(759, 1) == pytest.approx(0.0712, abs=0.002)
    assert deflated_threshold(759, 50) == pytest.approx(0.119, abs=0.003)


def test_threshold_matches_a_brute_force_max_of_n_simulation():
    rng = random.Random(42)
    n_pairs, trials_sim = 400, 20000
    sd = 1.0 / math.sqrt(n_pairs - 1)
    for big_n in (1, 10, 50):
        t = deflated_threshold(n_pairs, big_n)
        below = 0
        for _ in range(trials_sim):
            m = max(abs(rng.gauss(0.0, sd)) for _ in range(big_n))
            below += m < t
        assert below / trials_sim == pytest.approx(0.95, abs=0.01), big_n


def test_threshold_rejects_bad_args():
    for kw in ({"n_pairs": 1, "n_trials": 1}, {"n_pairs": 30, "n_trials": 0},
               {"n_pairs": 30, "n_trials": 1, "q": 1.0}, {"n_pairs": 30, "n_trials": 1, "kappa": 0.0}):
        with pytest.raises(ValueError):
            deflated_threshold(**kw)


def test_holdout_p_value_known_values():
    p, p_adj = holdout_p_value(0.0, 100, 1.0, 1)
    assert p == pytest.approx(0.5) and p_adj == pytest.approx(0.5)
    p, p_adj = holdout_p_value(0.2, 101, 1.0, 1)  # z = 2.0
    assert p == pytest.approx(1 - NormalDist().cdf(2.0), abs=1e-9) and p_adj == p
    p3, p3_adj = holdout_p_value(0.2, 101, 1.0, 3)
    assert p3 == p and p3_adj == pytest.approx(1 - (1 - p) ** 3)
    # a holdout IC against the in-sample sign is evidence against, p > 0.5
    assert holdout_p_value(0.2, 101, -1.0, 1)[0] > 0.9
    with pytest.raises(ValueError):
        holdout_p_value(0.1, 1, 1.0, 1)
    with pytest.raises(ValueError):
        holdout_p_value(0.1, 10, 1.0, 0)
