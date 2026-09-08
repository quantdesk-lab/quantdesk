"""Designer tests (quantdesk.search.designer): seeded determinism, cap
enforcement, every mutation operator reachable and named, the window-step
neighbour rule, lineage reporting, and the volume_price grammar invariant.
No model, no data."""
from __future__ import annotations

import pytest

from quantdesk.search.designer import MODES, MUTATIONS, Designer
from quantdesk.search.expr import (
    LAGS,
    OPS,
    WINDOWS,
    param,
    parse,
    seed_nodes,
    subtrees,
    terminals_of,
    to_text,
    validate,
)


def _params(node):
    return sorted((p, s[0], param(s)) for p, s in subtrees(node) if param(s) is not None)


def _stream(seed, parents, n=50):
    d = Designer(seed)
    return [d.propose(m, f, parents) for _ in range(n) for m in MODES for f in ("reversal", "range")]


def test_same_seed_same_proposals():
    parents = [n for n, _ in seed_nodes()]
    assert _stream(3, parents) == _stream(3, parents)
    assert _stream(3, parents) != _stream(4, parents)


def test_widen_stays_inside_caps_and_family_grammar():
    d = Designer(1)
    for fam in ("reversal", "volume_price", "volatility", "range"):
        for _ in range(60):
            node, op, reason, used = d.propose("widen", fam, [])
            assert op == "sample" and used == []
            assert reason is None, to_text(node)
            assert validate(node, **d.caps) is None
            if fam == "volume_price":
                assert "volume" in terminals_of(node)


def test_deepen_uses_every_named_operator_and_reports_parents():
    d = Designer(7)
    parents = [parse("-1 * delta(close, 1)"), parse("-1 * (close - sma(close, 10))")]
    seen = set()
    for _ in range(400):
        node, op, _, used = d.propose("deepen", "reversal", parents)
        assert op in MUTATIONS
        seen.add(op)
        assert used and all(u in parents for u in used)
        assert len(used) == (2 if op == "crossover" else 1)
    assert seen == set(MUTATIONS)


def test_rejections_are_reported_not_repaired():
    d = Designer(2, max_size=3)
    parents = [parse("-1 * (close - sma(close, 10))")]  # already size 4
    reasons = {d.propose("deepen", "reversal", parents)[2] for _ in range(40)}
    assert "too_big" in reasons


def test_window_step_moves_one_grid_place():
    d = Designer(5)
    parent = parse("ts_rank(delta(close, 3), 20)")
    moved = 0
    for _ in range(200):
        child, op, _, _ = d.propose("deepen", "reversal", [parent])
        if op != "window_step":
            continue
        moved += 1
        before, after = _params(parent), _params(child)
        diff = [(x, y) for x, y in zip(before, after) if x != y]
        assert len(diff) == 1, (before, after)
        (path, op_name, old), (_, _, new) = diff[0]
        grid = LAGS if OPS[op_name][1] == "lag" else WINDOWS
        assert abs(grid.index(new) - grid.index(old)) == 1
    assert moved > 20


def test_deepen_without_parents_falls_back_to_widen_and_bad_args_raise():
    d = Designer(0)
    node, op, _, used = d.propose("deepen", "range", [])
    assert op == "sample" and used == []
    with pytest.raises(ValueError):
        d.propose("explode", "range", [])
    with pytest.raises(ValueError):
        d.propose("widen", "nope", [])
    with pytest.raises(ValueError):
        d.deepen([], "range")
