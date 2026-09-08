"""Bandit tests (quantdesk.search.bandit): Beta posterior arithmetic, seeded
determinism, learning under a scripted oracle, snapshot order, and
reconstruction from archived records."""
from __future__ import annotations

import pytest

from quantdesk.search.bandit import MODES, BetaArm, TwoLevelBandit
from quantdesk.search.expr import FAMILIES


def test_beta_arm_posterior_arithmetic():
    arm = BetaArm()
    assert arm.mean == 0.5 and arm.n == 0
    for s in (True, True, True, False):
        arm.update(s)
    assert arm.alpha == 4.0 and arm.beta == 2.0
    assert arm.mean == pytest.approx(4 / 6) and arm.n == 4
    assert arm.to_dict() == {"alpha": 4.0, "beta": 2.0, "mean": 0.6667, "n": 4}
    with pytest.raises(ValueError):
        BetaArm(0.0, 1.0)


def test_same_seed_same_pulls():
    a, b = TwoLevelBandit(FAMILIES, seed=5), TwoLevelBandit(FAMILIES, seed=5)
    pulls_a, pulls_b = [], []
    for i in range(200):
        fa, ma = a.choose()
        fb, mb = b.choose()
        pulls_a.append((fa, ma))
        pulls_b.append((fb, mb))
        a.update(fa, ma, i % 3 == 0)
        b.update(fb, mb, i % 3 == 0)
    assert pulls_a == pulls_b
    c = TwoLevelBandit(FAMILIES, seed=6)
    assert pulls_a != [c.choose() for _ in range(200)]


def test_scripted_oracle_shifts_the_posterior():
    b = TwoLevelBandit(FAMILIES, seed=1)
    picks = []
    for _ in range(300):
        f, m = b.choose()
        picks.append(f)
        b.update(f, m, f == "reversal")
    late = picks[-100:]
    assert late.count("reversal") > 60
    snap = b.snapshot()
    assert snap["families"]["reversal"]["mean"] > max(
        v["mean"] for k, v in snap["families"].items() if k != "reversal")


def test_snapshot_key_order_is_fixed():
    b = TwoLevelBandit(FAMILIES, seed=0)
    snap = b.snapshot()
    assert list(snap["families"]) == list(FAMILIES)
    assert list(snap["modes"]) == [f"{f}/{m}" for f in FAMILIES for m in MODES]
    assert set(snap["families"]["reversal"]) == {"alpha", "beta", "mean", "n"}


def test_from_records_rebuilds_posteriors():
    records = [
        {"family": "range", "mode": "widen", "cleared_null": True},
        {"family": "range", "mode": "widen", "cleared_null": False},
        {"family": "volatility", "mode": "deepen", "cleared_null": True},
        {"family": "unknown", "mode": "widen", "cleared_null": True},  # skipped
        {"family": "range", "mode": "widen"},                            # no verdict: skipped
    ]
    b = TwoLevelBandit.from_records(records, seed=0)
    snap = b.snapshot()
    assert snap["families"]["range"] == {"alpha": 2.0, "beta": 2.0, "mean": 0.5, "n": 2}
    assert snap["modes"]["volatility/deepen"]["n"] == 1
    assert snap["families"]["reversal"]["n"] == 0
    with pytest.raises(ValueError):
        TwoLevelBandit([], seed=0)
