"""Archive tests (quantdesk.search.archive): append/has/get, family ranking,
lineage to a seed, JSON Lines round trip with meta, and replay."""
from __future__ import annotations

import json

from quantdesk.demo.fixtures import planted_bars, split_ohlcv
from quantdesk.search.archive import Archive
from quantdesk.search.expr import parse
from quantdesk.search.gates import calibrate_gates
from quantdesk.search.judge import judge
from quantdesk.search.walkforward import split


def _rec(eid, text, family, abs_ic, verdict="noise", parents=(), op="sample"):
    return {"expr_id": eid, "text": text, "family": family, "verdict": verdict,
            "parents": list(parents), "op": op, "mode": "widen",
            "insample": {"ic": abs_ic, "n": 100, "abs_ic": abs_ic, "threshold": 0.05}}


def test_append_has_get_and_family_ranking():
    a = Archive()
    a.append(_rec("s1", "-1 * delta(close, 1)", "reversal", 0.10, "candidate"))
    a.append(_rec("s2", "-1 * (close - sma(close, 10))", "reversal", 0.02))
    a.append(_rec("r1", "(high - low) / close", "range", 0.01))
    a.append({"expr_id": "x1", "text": "abs(close)", "verdict": "rejected", "reason": "too_big"})
    a.append({"expr_id": "s1", "text": "-1 * delta(close, 1)", "verdict": "duplicate"})
    assert len(a) == 5 and a.has("s1") and not a.has("zz")
    assert a.get("s2")["family"] == "reversal" and a.get("zz") is None
    assert [r["expr_id"] for r in a.by_family("reversal")] == ["s1", "s2"]
    assert [r["expr_id"] for r in a.survivors()] == ["s1"]
    assert len(a.scored()) == 3
    assert [str(n) for n in a.nodes_of(a.by_family("range"))] == [str(parse("(high - low) / close"))]


def test_lineage_walks_to_a_seed():
    a = Archive()
    a.append(_rec("s1", "-1 * delta(close, 1)", "reversal", 0.10, "candidate", op="seed"))
    a.append(_rec("c1", "-1 * delta(close, 2)", "reversal", 0.05, parents=["s1"], op="window_step"))
    a.append(_rec("c2", "abs(-1 * delta(close, 2))", "reversal", 0.01, parents=["c1", "s1"], op="crossover"))
    chain = a.lineage("c2")
    assert [r["expr_id"] for r in chain] == ["c2", "c1", "s1"]
    assert [r["op"] for r in chain] == ["crossover", "window_step", "seed"]
    assert a.lineage("nope") == []


def test_jsonl_round_trip_with_meta(tmp_path):
    a = Archive(meta={"symbol": "SYN-1", "seed": 7, "holdout": None})
    a.append(_rec("s1", "-1 * delta(close, 1)", "reversal", 0.10, "candidate"))
    a.append({"expr_id": "x1", "text": "abs(close)", "verdict": "rejected", "reason": "too_big"})
    path = a.to_jsonl(tmp_path / "runs" / "a.jsonl")
    lines = path.read_text(encoding="utf-8").splitlines()
    assert json.loads(lines[0])["_meta"] is True and len(lines) == 3
    assert path.read_text(encoding="utf-8").isascii()
    b = Archive.from_jsonl(path)
    assert b.meta == a.meta and b.records == a.records and b.has("x1")


def test_replay_is_empty_on_a_faithful_archive_and_flags_a_tampered_record():
    rows = planted_bars(2400, seed=7)
    cols = split_ohlcv(rows)
    sp = split(2400)
    gates = calibrate_gates()
    a = Archive()
    for k, text in enumerate(("-1 * delta(close, 1)", "(high - low) / close"), start=1):
        rec = judge(parse(text), cols, sp, gates, k)
        rec.update({"family": "reversal", "mode": "seed", "op": "seed", "parents": []})
        a.append(rec)
    assert a.replay(cols, sp, gates) == []
    a.records[0]["insample"]["ic"] = 0.5
    assert a.replay(cols, sp, gates) == [a.records[0]["expr_id"]]
