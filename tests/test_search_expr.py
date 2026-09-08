"""Expression-tree tests (quantdesk.search.expr).

Pinned: the parse/print round trip in registry notation, digest stability,
structural helpers (size/depth/nesting/warmup as an upper bound on the first
valid index), dispatch equality with the registered alpha functions for the
formulas the grammar covers, and - most importantly - the no-lookahead
property inherited from the operator library, asserted by prefix
determinism over random trees. No network, no model.
"""
from __future__ import annotations

import random

import pytest

from quantdesk.demo.fixtures import gbm_bars, split_ohlcv
from quantdesk.factors.alpha101 import ALPHAS, alpha006, alpha012, alpha043
from quantdesk.search.expr import (
    FAMILIES,
    GRAMMAR,
    OPS,
    SEEDS,
    TERMINALS,
    depth,
    evaluate,
    expr_id,
    make,
    nesting,
    parse,
    replace_at,
    sample,
    seed_nodes,
    size,
    subtrees,
    terminals_of,
    to_text,
    validate,
    warmup,
)


@pytest.fixture(scope="module")
def cols():
    return split_ohlcv(gbm_bars(400, seed=3, sigma=0.01))


def _ev(node, c):
    return evaluate(node, c["o"], c["h"], c["l"], c["c"], c["v"])


def _random_trees(n, seed=0, **kw):
    rng = random.Random(seed)
    return [sample(rng, **kw) for _ in range(n)]


# ------------------------------------------------------------- text form --
def test_seeds_parse_and_print_canonically():
    for text, fam in SEEDS:
        node = parse(text)
        assert to_text(node) == text
        assert fam in FAMILIES
    assert len(seed_nodes()) == len(SEEDS)


def test_round_trip_over_random_trees():
    for node in _random_trees(300, seed=11):
        text = to_text(node)
        assert text.isascii()
        assert parse(text) == node, text


def test_precedence_and_negation_are_unambiguous():
    a, b, c = ("close",), ("open",), ("high",)
    assert to_text(make("mul", [make("neg", [a]), b])) == "-1 * close * open"
    assert to_text(make("neg", [make("mul", [a, b])])) == "-1 * (close * open)"
    assert to_text(make("sub", [a, make("sub", [b, c])])) == "close - (open - high)"
    assert to_text(make("sub", [make("sub", [a, b]), c])) == "close - open - high"
    assert to_text(make("div", [make("add", [a, b]), c])) == "(close + open) / high"
    assert parse("close - open - high") == make("sub", [make("sub", [a, b]), c])
    assert to_text(make("neg", [make("neg", [a])])) == "-1 * (-1 * close)"
    assert parse("-1 * (-1 * close)") == make("neg", [make("neg", [a])])


def test_parse_rejects_what_the_grammar_does_not_cover():
    for bad in ("where(close > 0, 1, 0)", "sqrt(close)", "close ^ 2", "close + 0.001",
                "delta(close)", "correlation(close, 10)", "foo(close, 3)", "-2 * close",
                "close +", "vwap = close", "delta(close, 1) extra"):
        with pytest.raises(ValueError):
            parse(bad)


def test_registry_formulas_evaluate_like_the_registered_alphas(cols):
    by_id = {e["id"]: e for e in ALPHAS}
    for aid, fn in (("a006", alpha006), ("a012", alpha012), ("a043", alpha043)):
        node = parse(by_id[aid]["formula"])
        assert _ev(node, cols) == fn(cols["o"], cols["h"], cols["l"], cols["c"], cols["v"])


def test_expr_id_is_stable_and_text_derived():
    node = parse("-1 * delta(close, 1)")
    assert expr_id(node) == "12c9a2980df7"  # pinned: an archive id must never drift
    assert expr_id(node) == expr_id(parse(to_text(node)))
    assert len(expr_id(node)) == 12 and expr_id(node) != expr_id(parse("delta(close, 1)"))


# --------------------------------------------------------------- structure --
def test_structural_helpers():
    node = parse("ts_rank(volume / sma(volume, 20), 20)")
    assert size(node) == 5 and depth(node) == 4 and nesting(node) == 2
    assert warmup(node) == 19 + 19
    assert terminals_of(node) == {"volume"}
    assert warmup(parse("returns")) == 1 and warmup(parse("delta(close, 5)")) == 5
    assert warmup(parse("correlation(open, delay(volume, 2), 10)")) == 2 + 9
    paths = [p for p, _ in subtrees(node)]
    assert paths[0] == () and len(paths) == size(node)
    swapped = replace_at(node, (0, 1), ("close",))
    assert to_text(swapped) == "ts_rank(volume / close, 20)"
    assert node == parse("ts_rank(volume / sma(volume, 20), 20)")  # immutable


def test_make_validates_arity_and_parameters():
    with pytest.raises(ValueError):
        make("delta", [("close",)])
    with pytest.raises(ValueError):
        make("abs", [("close",)], 3)
    with pytest.raises(ValueError):
        make("sma", [("close",)], 0)
    with pytest.raises(ValueError):
        make("close", [("open",)])
    with pytest.raises(ValueError):
        make("nope", [])


def test_validate_reasons():
    assert validate(("close",)) == "bare_terminal"
    assert validate(parse("-1 * delta(close, 1)")) is None
    deep = parse("abs(abs(abs(abs(abs(close)))))")
    assert validate(deep, max_depth=5) == "too_deep"
    assert validate(parse("ts_rank(sma(stddev(returns, 5), 5), 5)"), max_nesting=2) == "too_nested"
    assert validate(parse("sma(close, 60)"), max_warmup=40) == "warmup"
    wide = parse("close + open + high + low + volume + returns + vwap")
    assert validate(wide, max_size=12, max_depth=20) == "too_big"


def test_warmup_bounds_the_first_valid_index(cols):
    for node in _random_trees(120, seed=5, max_depth=4):
        series = _ev(node, cols)
        first = next((i for i, v in enumerate(series) if v is not None), None)
        if first is not None:
            assert first <= warmup(node), to_text(node)


# ------------------------------------------------------------- no lookahead --
def test_prefix_determinism_over_random_trees(cols):
    n = len(cols["c"])
    cut = 250
    prefix = {k: v[:cut] for k, v in cols.items()}
    for node in _random_trees(100, seed=9, max_depth=4):
        full = _ev(node, cols)
        part = _ev(node, prefix)
        assert len(full) == n and len(part) == cut
        assert part == full[:cut], to_text(node)


def test_shared_subtrees_do_not_change_results(cols):
    inner = parse("sma(close, 10)")
    node = make("sub", [inner, make("delay", [inner], 1)])
    direct = parse("sma(close, 10) - delay(sma(close, 10), 1)")
    assert _ev(node, cols) == _ev(direct, cols)


# ------------------------------------------------------------------ grammar --
def test_sampler_respects_its_grammar_and_is_seeded():
    for fam in FAMILIES:
        g = GRAMMAR[fam]
        assert set(g["terminals"]) <= set(TERMINALS) and set(g["ops"]) <= set(OPS)
        rng = random.Random(1)
        for _ in range(50):
            node = sample(rng, terminals=g["terminals"], ops=g["ops"], max_depth=4)
            assert node[0] in g["ops"]
            assert terminals_of(node) <= set(g["terminals"])
            assert depth(node) <= 4
    a = [to_text(t) for t in _random_trees(30, seed=4)]
    assert a == [to_text(t) for t in _random_trees(30, seed=4)]
    assert a != [to_text(t) for t in _random_trees(30, seed=5)]
    with pytest.raises(ValueError):
        sample(random.Random(0), max_depth=1)
