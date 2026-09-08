"""Judge tests (quantdesk.search.judge): the verdict vocabulary and record
shape, refusal on short samples, the false-positive rate on random walks,
recovery of the planted reversal, redundancy against itself, and the
fee-after cost grid on holdout bars (fees kill a one-hour signal: pinned)."""
from __future__ import annotations

import random

import pytest

from quantdesk.demo.fixtures import gbm_bars, planted_bars, split_ohlcv
from quantdesk.search.expr import parse, sample, to_text
from quantdesk.search.gates import calibrate_gates
from quantdesk.search.judge import (
    DEFAULT_COST_GRID,
    VERDICTS,
    evaluate_cols,
    fee_after,
    holdout_ic,
    judge,
)
from quantdesk.search.walkforward import split

_KEYS = {"expr_id", "text", "warmup", "insample", "n_trials_at_verdict", "gates_version", "h24",
         "blocks", "sign_agreement", "turnover_proxy", "decay", "max_rho_vs_survivors",
         "cleared_null", "verdict"}


@pytest.fixture(scope="module")
def gates():
    return calibrate_gates()


@pytest.fixture(scope="module")
def planted():
    rows = planted_bars(2400, seed=7)
    return rows, split_ohlcv(rows), split(2400)


@pytest.fixture(scope="module")
def walk():
    rows = gbm_bars(2400, seed=7, sigma=0.01)
    return rows, split_ohlcv(rows), split(2400)


def test_record_shape_and_planted_seed_is_a_candidate(planted, gates):
    _, cols, sp = planted
    rec = judge(parse("-1 * delta(close, 1)"), cols, sp, gates, 1)
    assert set(rec) == _KEYS
    assert rec["verdict"] == "candidate" and rec["cleared_null"]
    assert rec["insample"]["ic"] > 0.06 and rec["insample"]["abs_ic"] > rec["insample"]["threshold"]
    assert rec["insample"]["n"] == sp.insample_end - 1 - rec["warmup"]
    assert rec["sign_agreement"]["printable"] == 3 and rec["sign_agreement"]["agree"] >= 2
    assert len(rec["blocks"]) == 3 and rec["decay"]["lags"][0] == 1
    assert rec["h24"]["n_eff"] is not None and rec["gates_version"] == gates.version
    assert rec["n_trials_at_verdict"] == 1 and rec["warmup"] == 1
    # the same candidate judged after 50 trials faces a higher bar
    later = judge(parse("-1 * delta(close, 1)"), cols, sp, gates, 50)
    assert later["insample"]["threshold"] > rec["insample"]["threshold"]


def test_refusal_on_a_short_sample(gates):
    rows = planted_bars(90, seed=1)
    cols = split_ohlcv(rows)
    sp = split(90, purge=2, embargo=2, n_blocks=2)  # 68 in-sample rows, 8 pairs after warmup
    rec = judge(parse("sma(close, 60)"), cols, sp, gates, 1)
    assert rec["verdict"] == "refused" and not rec["cleared_null"]
    assert rec["insample"]["ic"] is None and rec["insample"]["n"] < gates.min_ic_pairs
    assert rec["blocks"] == [] and rec["decay"] is None


def test_random_walk_yields_mostly_noise(walk, gates):
    _, cols, sp = walk
    rng = random.Random(3)
    verdicts = []
    for k in range(30):
        node = sample(rng, max_depth=3)
        verdicts.append(judge(node, cols, sp, gates, k + 1)["verdict"])
    assert all(v in VERDICTS for v in verdicts)
    assert verdicts.count("candidate") + verdicts.count("unstable") + verdicts.count("redundant") <= 2, verdicts


def test_redundant_against_itself_and_a_rescaled_twin(planted, gates):
    _, cols, sp = planted
    node = parse("-1 * delta(close, 1)")
    series = evaluate_cols(node, cols)
    rec = judge(node, cols, sp, gates, 1, [("self", series)])
    assert rec["verdict"] == "redundant" and rec["max_rho_vs_survivors"] == 1.0
    twin = parse("-1 * delta(close, 1) / close")
    rec2 = judge(twin, cols, sp, gates, 2, [("orig", series)])
    assert rec2["verdict"] == "redundant" and rec2["max_rho_vs_survivors"] > 0.9


def test_fee_after_grid_on_holdout_bars(planted):
    rows, cols, sp = planted
    node = parse("-1 * delta(close, 1)")
    series = evaluate_cols(node, cols)
    hic = holdout_ic(series, cols["c"], sp)
    assert hic["n"] == sp.n - sp.holdout_start - 1
    out = fee_after(series, rows, sp, 1.0, cost_grid=DEFAULT_COST_GRID)
    assert [g["cost_bps"] for g in out["grid"]] == [float(c) for c in DEFAULT_COST_GRID]
    rets = [g["total_return"] for g in out["grid"]]
    assert rets == sorted(rets, reverse=True)      # more cost, less return
    assert out["grid"][0]["n_trades"] > 50           # a 1h sign signal trades a lot
    assert out["dies_at_bps"] is not None and out["dies_at_bps"] <= 20.0, out
    assert out["label"] == "feature-only" and out["n_bars"] == sp.n - sp.holdout_start
    assert "simulated fills" in out["note"]
    with pytest.raises(ValueError):
        fee_after(series, rows[:10], split(10, purge=0, embargo=0, n_blocks=1, holdout_frac=0.1), 1.0)


def test_text_round_trip_of_judged_records(planted, gates):
    _, cols, sp = planted
    rng = random.Random(1)
    for _ in range(10):
        node = sample(rng, max_depth=3)
        rec = judge(node, cols, sp, gates, 1)
        assert parse(rec["text"]) == node and rec["text"] == to_text(node)
