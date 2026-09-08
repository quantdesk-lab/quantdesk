"""Loop tests (quantdesk.search.loop): byte-identical payloads for a seed,
monotone best-so-far and threshold, ledger consistency, the single holdout
touch (and its refusal on resume), resume continuing the numbering, the
expected outcomes on the random walk and on the planted fixture, no
timestamps anywhere, and the runtime budget the site build depends on."""
from __future__ import annotations

import json
import re
import time

import pytest

from quantdesk.demo.fixtures import gbm_bars, planted_bars, split_ohlcv
from quantdesk.search.archive import Archive
from quantdesk.search.expr import SEEDS
from quantdesk.search.gates import calibrate_gates
from quantdesk.search.loop import run_search
from quantdesk.search.walkforward import HoldoutSpent, split

SITE_SEED = 7          # the site's GBM fixture seed (scripts/build_site.py --seed)
PLANTED_SEED = 9       # the site's planted fixture seed (scripts/build_site.py PLANTED_SEED)
_TS = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}")


@pytest.fixture(scope="module")
def gates():
    return calibrate_gates()


@pytest.fixture(scope="module")
def planted_run(gates):
    t0 = time.perf_counter()
    out = run_search(planted_bars(2400, seed=PLANTED_SEED), symbol="PLANTED-1", seed=PLANTED_SEED,
                     gates=gates, generations=8, per_generation=6, kind="synthetic-ar1")
    out["_elapsed"] = time.perf_counter() - t0
    return out


@pytest.fixture(scope="module")
def walk_run(gates):
    return run_search(gbm_bars(2400, seed=SITE_SEED, sigma=0.01), symbol="SYN-1", seed=SITE_SEED,
                      gates=gates, generations=8, per_generation=6, kind="synthetic-gbm")


def _scored(out):
    return [r for r in out["records"] if r["verdict"] in ("noise", "redundant", "unstable", "candidate")]


def test_payload_is_deterministic_and_seed_sensitive(gates):
    rows = planted_bars(1200, seed=3)
    a = run_search(rows, symbol="P", seed=1, gates=gates, generations=2, per_generation=3)
    b = run_search(rows, symbol="P", seed=1, gates=gates, generations=2, per_generation=3)
    c = run_search(rows, symbol="P", seed=2, gates=gates, generations=2, per_generation=3)
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)
    assert json.dumps(a, sort_keys=True) != json.dumps(c, sort_keys=True)
    assert not _TS.search(json.dumps(a))


def test_shape_ledger_and_monotone_curves(planted_run):
    out = planted_run
    assert out["symbol"] == "PLANTED-1" and out["trial_count"] == out["ledger"]["n_trials"]
    assert out["ledger"]["n_trials"] == len(_scored(out))
    assert len(out["generations"]) == 9 and out["generations"][0]["candidates"]
    assert len(out["generations"][0]["candidates"]) == len(SEEDS)
    assert sum(len(g["candidates"]) for g in out["generations"][1:]) == 8 * 6
    curve = [b["abs_ic"] for b in out["best_so_far"]]
    assert curve == sorted(curve)
    thr = [b["threshold_ref"] for b in out["best_so_far"]]
    assert thr == sorted(thr) and thr[0] < thr[-1]
    assert [b["n_trials"] for b in out["best_so_far"]] == sorted(b["n_trials"] for b in out["best_so_far"])
    assert all(g["bandit"]["families"] for g in out["generations"])
    for r in _scored(out):
        assert r["trial_no"] is not None and r["threshold_final"] >= r["insample"]["threshold"]
        assert r["gates_version"] == out["gates"]["version"]
    for e in out["lineage"]:
        assert {"child", "parent", "op"} <= set(e)


def test_planted_run_recovers_the_reversal_and_touches_the_holdout_once(planted_run):
    out = planted_run
    h = out["holdout"]
    assert h["touched"] and 1 <= h["k"] <= 3 and h["run_id"] == f"PLANTED-1-seed{PLANTED_SEED}-gen0"
    top = h["results"][0]
    assert "delta(close" in top["text"] or "returns" in top["text"], top["text"]
    assert top["passed"] and top["p_adj"] < 0.05 and top["ic"] > 0
    assert top["fee_after"]["dies_at_bps"] is not None and top["fee_after"]["label"] == "feature-only"
    assert out["best_so_far"][-1]["abs_ic"] > out["best_so_far"][-1]["threshold"]
    assert out["_elapsed"] < 60.0


def test_planted_holdout_pass_rate_over_seeds(gates):
    """The planted effect is real but a single 480-bar holdout is one draw:
    docs/SEARCH.md reports this rate, so it is pinned rather than implied."""
    passes = 0
    for seed in range(7, 12):
        out = run_search(planted_bars(2400, seed=seed), symbol="P", seed=seed, gates=gates,
                         generations=3, per_generation=4)
        passes += any(r["passed"] for r in out["holdout"]["results"])
    assert passes >= 3, passes


def test_random_walk_converges_to_refusal(walk_run):
    out = walk_run
    passed = [r for r in out["holdout"]["results"] if r["passed"]]
    assert passed == [], passed
    assert out["ledger"]["n_trials"] > 30


def test_random_walk_false_positive_rate_over_seeds(gates):
    hits = 0
    for seed in range(11, 16):
        out = run_search(gbm_bars(1500, seed=seed, sigma=0.01), symbol="W", seed=seed, gates=gates,
                         generations=3, per_generation=4)
        hits += any(r["passed"] for r in out["holdout"]["results"])
    assert hits <= 1


def test_resume_continues_numbering_and_refuses_a_second_holdout_touch(gates):
    rows = planted_bars(2400, seed=5)
    archive = Archive()
    first = run_search(rows, symbol="P", seed=5, gates=gates, generations=2, per_generation=4, archive=archive)
    n1 = first["ledger"]["n_trials"]
    assert archive.meta["generations_done"] == 3
    if first["holdout"]["touched"]:
        with pytest.raises(HoldoutSpent):
            run_search(rows, symbol="P", seed=5, gates=gates, generations=1, per_generation=4,
                       archive=archive, resume=True)
    else:
        second = run_search(rows, symbol="P", seed=5, gates=gates, generations=1, per_generation=4,
                            archive=archive, resume=True)
        assert second["ledger"]["n_trials"] >= n1 and second["generations"][0]["gen"] == 3
    with pytest.raises(ValueError):
        run_search(rows, symbol="P", seed=5, gates=gates, generations=1, archive=archive)
    with pytest.raises(ValueError):
        run_search(rows, symbol="OTHER", seed=5, gates=gates, generations=1, archive=archive, resume=True)


def test_archive_round_trip_preserves_the_run(gates, tmp_path):
    rows = planted_bars(1200, seed=9)
    archive = Archive()
    run_search(rows, symbol="P", seed=9, gates=gates, generations=1, per_generation=3, archive=archive)
    path = archive.to_jsonl(tmp_path / "p.jsonl")
    again = Archive.from_jsonl(path)
    assert again.meta == archive.meta and len(again) == len(archive)
    assert again.replay(split_ohlcv(rows), split(1200), gates) == []


def test_bad_arguments():
    with pytest.raises(ValueError):
        run_search(planted_bars(500), symbol="P", generations=-1)
    with pytest.raises(ValueError):
        run_search(planted_bars(500), symbol="P", per_generation=0)
