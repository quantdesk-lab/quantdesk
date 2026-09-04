"""Decision-ticket tests (quantdesk.research.tickets).

Pinned here: the TICKET / decision shapes the site renders, the no-lookahead
property (the decision at bar t is exactly what a run on bars[:t+1] alone
produces, outcomes included), policy-table consistency, parity with the real
engine (the recording wrapper adds no fills of its own), realized-P&L
accounting on closed round trips, and the summary/cost-grid payload.
Everything runs on synthetic GBM bars; no network, no model.
"""
from __future__ import annotations

import re

import pytest

from quantdesk.backtest.config import TARGET_FRACTIONS
from quantdesk.backtest.engine import run_weight_backtest
from quantdesk.backtest.signals import tsmom_weight
from quantdesk.demo.fixtures import gbm_bars
from quantdesk.factors.tsmom import target_weight, tsmom_regime
from quantdesk.policy import translate_regime_to_action
from quantdesk.research.tickets import (
    DEFAULT_COST_GRID,
    backtest_payload,
    backtest_summary,
    build_tickets,
    decide,
    reasoning_text,
    rows_to_bars,
    run_ticket_backtest,
    tickets_from_decisions,
)

_DAY = 86400
_TICKET_KEYS = {
    "ticket_id", "symbol", "side", "open_ts", "close_ts", "entry", "exit", "size", "pnl",
    "fees", "n_decisions", "thesis", "why_open", "why_close", "decisions",
}
_DECISION_KEYS = {"tick_no", "ts", "action", "confidence", "regime", "observation",
                  "reasoning", "outcome"}
_OBS_KEYS = {"close", "tsmom_score", "sigma_ann", "vol_ratio", "target_weight",
             "position_weight"}
_OUTCOME_KEYS = {"fill_px", "fee", "weight_after"}


@pytest.fixture(scope="module")
def walk():
    """400 daily random-walk bars (a seed that produces closed round trips)."""
    return gbm_bars(400, seed=1, bar_seconds=_DAY, sigma=0.03)


@pytest.fixture(scope="module")
def trend_then_crash():
    """300 up-drift bars followed by 150 down-drift bars: guarantees a long
    ticket that opens on trend_up and closes on a high-confidence trend_down."""
    up = gbm_bars(300, seed=5, bar_seconds=_DAY, sigma=0.02, mu=0.004)
    down = gbm_bars(150, seed=6, bar_seconds=_DAY, sigma=0.02, mu=-0.012,
                    s0=up[-1][4], start_ts=up[-1][0] + _DAY)
    return up + down


def _all_decisions(tickets):
    return [d for t in tickets for d in t["decisions"]]


# ---------------------------------------------------------------- shapes --
def test_ticket_and_decision_shapes(walk):
    tickets = build_tickets("SYN-1", walk)
    assert tickets
    ids = [t["ticket_id"] for t in tickets]
    assert ids == [f"SYN-1-T{i:03d}" for i in range(1, len(tickets) + 1)]
    for t in tickets:
        assert _TICKET_KEYS <= set(t)
        assert t["side"] in ("long", "flat")
        assert t["symbol"] == "SYN-1"
        assert t["n_decisions"] == len(t["decisions"]) >= 1
        assert isinstance(t["thesis"], str) and t["thesis"]
        assert t["why_open"] == t["decisions"][0]["reasoning"]
        assert isinstance(t["entry"], float) and t["entry"] > 0
        assert t["fees"] >= 0.0
        if t["side"] == "flat":
            assert t["size"] == 0.0 and t["pnl"] is None and t["exit"] is None
            assert t["fees"] == 0.0
        if t["close_ts"] is None:
            assert t["pnl"] is None and t["exit"] is None and t["why_close"] is None
        for d in t["decisions"]:
            assert _DECISION_KEYS <= set(d)
            assert _OBS_KEYS <= set(d["observation"])
            assert _OUTCOME_KEYS <= set(d["outcome"])
            assert 0.0 <= d["confidence"] <= 1.0
            assert re.match(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\+00:00$", d["ts"])
            assert d["regime"] in ("trend_up", "trend_down", "range_bound",
                                   "high_volatility_event", "uncertain")
    # the decision stream is contiguous and strictly increasing in tick_no
    ticks = [d["tick_no"] for d in _all_decisions(tickets)]
    assert ticks == sorted(ticks) and len(set(ticks)) == len(ticks)
    assert ticks == list(range(ticks[0], ticks[-1] + 1))
    assert ticks[0] == 262  # first bar with a TSMOM view (263 closes)
    assert ticks[-1] == len(walk) - 2  # the last bar never decides


def test_long_tickets_open_and_close_on_fills(walk):
    tickets = build_tickets("SYN-1", walk)
    longs = [t for t in tickets if t["side"] == "long"]
    assert longs
    for t in longs:
        first = t["decisions"][0]
        assert first["outcome"]["fill_px"] == t["entry"]
        assert first["observation"]["position_weight"] == 0.0
        assert first["outcome"]["delta_qty"] > 0
        assert t["open_ts"] == first["outcome"]["fill_ts"]
        assert t["size"] == first["outcome"]["weight_after"] > 0
        assert t["peak_weight"] >= t["size"]
        if t["close_ts"] is not None:
            last = t["decisions"][-1]
            assert last["outcome"]["weight_after"] == 0.0
            assert last["outcome"]["delta_qty"] < 0
            assert t["exit"] == last["outcome"]["fill_px"]
            assert t["why_close"] == last["reasoning"]
            assert isinstance(t["pnl"], float)
    closed = [t for t in longs if t["close_ts"] is not None]
    assert closed, "seed 1 is expected to produce at least one closed round trip"
    # at most the final ticket may still be open
    assert all(t["close_ts"] is not None for t in tickets[:-1])


def test_closed_ticket_pnl_is_the_net_cash_flow_of_its_fills(trend_then_crash):
    tickets = build_tickets("SYN-X", trend_then_crash)
    closed = [t for t in tickets if t["side"] == "long" and t["close_ts"] is not None]
    assert closed
    for t in closed:
        fills = [d["outcome"] for d in t["decisions"] if d["outcome"]["fill_px"] is not None]
        cash = sum(-(f["delta_qty"] * f["fill_px"]) - f["fee"] for f in fills)
        fees = sum(f["fee"] for f in fills)
        assert t["pnl"] == pytest.approx(cash, abs=1e-4)
        assert t["fees"] == pytest.approx(fees, abs=1e-6)
        assert sum(f["delta_qty"] for f in fills) == pytest.approx(0.0, abs=1e-9)
        buys = sum(f["delta_qty"] * f["fill_px"] for f in fills if f["delta_qty"] > 0)
        assert t["return_on_cost"] == pytest.approx(cash / buys, abs=1e-6)
    # the crash leg closes the first long on a high-confidence trend_down
    first_long = next(t for t in tickets if t["side"] == "long")
    assert first_long["decisions"][-1]["action"] == "flat_position"
    assert "trend_down" in first_long["why_close"]
    assert first_long["pnl"] < 0  # bought the top, sold the crash


# ----------------------------------------------------------- no lookahead --
@pytest.mark.parametrize("cut", [300, 350, 399])
def test_decisions_equal_prefix_run(walk, cut):
    """Every decision (outcome included) formed before bar `cut` must be
    identical when the builder only ever sees bars[:cut+1]."""
    _, full, _ = run_ticket_backtest("SYN-1", walk)
    _, prefix, _ = run_ticket_backtest("SYN-1", walk[:cut + 1])
    expected = [d for d in full if d["tick_no"] <= cut - 1]
    assert prefix == expected
    assert prefix[-1]["tick_no"] == cut - 1


def test_prefix_run_tickets_are_a_prefix_of_full_tickets(walk):
    full = build_tickets("SYN-1", walk)
    cut = 360
    part = build_tickets("SYN-1", walk[:cut + 1])
    # every ticket that CLOSED before the cut is reproduced exactly
    closed_full = [t for t in full if t["close_ts"] is not None
                   and t["decisions"][-1]["tick_no"] <= cut - 1]
    assert part[:len(closed_full)] == closed_full


def test_observation_is_the_regime_on_the_prefix_vol_scaled(walk):
    """Stateless mode: each observation equals tsmom_regime on bars[:t+1]."""
    _, decisions, bars = run_ticket_backtest("SYN-1", walk, weight_mode="vol_scaled")
    closes = [b.close for b in bars]
    for d in decisions[::17]:
        t = d["tick_no"]
        rr = tsmom_regime(closes[:t + 1])
        assert d["regime"] == rr["regime"]
        assert d["confidence"] == pytest.approx(rr["confidence"])
        assert d["observation"]["tsmom_score"] == pytest.approx(rr["diag"]["score"], abs=1e-6)
        assert d["observation"]["target_weight"] == pytest.approx(
            target_weight(rr["diag"]["score"], rr["diag"]["sigma_ann"]), abs=1e-6)
        assert d["observation"]["close"] == pytest.approx(closes[t], abs=1e-6)


# ------------------------------------------------------- policy + engine --
def test_actions_come_from_the_policy_table(walk):
    _, decisions, _ = run_ticket_backtest("SYN-1", walk)
    seen = set()
    for d in decisions:
        assert d["action"] == translate_regime_to_action(d["regime"], d["confidence"])
        tgt = d["observation"]["target_weight"]
        if d["action"] in TARGET_FRACTIONS:
            assert tgt == pytest.approx(TARGET_FRACTIONS[d["action"]])
        elif d["action"] == "maintain":
            assert tgt is None
        seen.add(d["action"])
    assert len(seen) >= 3  # the walk exercises more than one policy row


def test_hold_decisions_never_fill(walk):
    _, decisions, _ = run_ticket_backtest("SYN-1", walk)
    for d in decisions:
        if d["observation"]["target_weight"] is None:
            assert d["outcome"]["fill_px"] is None and d["outcome"]["fee"] is None
            assert d["reasoning"].endswith("-> hold (band 0.10).")


def test_engine_parity_vol_scaled(walk):
    """The recording wrapper is the engine: same fills as run_weight_backtest
    driven by the package's own tsmom_weight signal."""
    result, _, bars = run_ticket_backtest("SYN-1", walk, weight_mode="vol_scaled")
    ref = run_weight_backtest({"SYN-1": bars}, tsmom_weight(), rebalance_every_n_bars=1,
                              no_trade_band=0.10, granularity="1d")
    assert result.equity_curve == ref.equity_curve
    assert result.trades == ref.trades


def test_weight_cap_scales_policy_targets(walk):
    _, capped, _ = run_ticket_backtest("SYN-1", walk, weight_cap=0.5)
    for d in capped:
        if d["action"] in TARGET_FRACTIONS:
            assert d["observation"]["target_weight"] == pytest.approx(
                0.5 * TARGET_FRACTIONS[d["action"]])


def test_include_warmup_reports_every_bar(walk):
    _, decisions, _ = run_ticket_backtest("SYN-1", walk, include_warmup=True)
    assert len(decisions) == len(walk) - 1
    warm = [d for d in decisions if d["tick_no"] < 262]
    assert len(warm) == 262
    for d in warm:
        assert d["action"] == "maintain" and d["regime"] == "uncertain"
        assert d["reasoning"].startswith("Insufficient history (")
        assert d["observation"]["tsmom_score"] is None


# --------------------------------------------------------------- reasoning --
def test_reasoning_text_is_deterministic_english():
    view = {"ok": True, "regime": "trend_up", "confidence": 0.71, "action": "target_weight_60",
            "score": 0.42, "s22": 0.5, "s261": 0.3, "vol_ratio": 0.92, "sigma_ann": 0.4,
            "target": 0.6}
    s = reasoning_text(view, 0.0)
    assert s == ("TSMOM blend +0.42 (s22 +0.50, s261 +0.30), vol ratio 0.92 below the 1.25 "
                 "overheat line -> trend_up at confidence 0.71 -> target weight 0.60; "
                 "position 0.00 -> buy to 0.60 (band 0.10).")
    assert reasoning_text(view, 0.55).endswith(
        "position 0.55 -> inside band, no trade (band 0.10).")
    assert reasoning_text(view, 0.9).endswith("position 0.90 -> sell to 0.60 (band 0.10).")
    view_hv = dict(view, regime="high_volatility_event", action="halve_position",
                   vol_ratio=1.4, target=0.3)
    s2 = reasoning_text(view_hv, 0.6)
    assert "above the 1.25 overheat line" in s2 and "halve position to 0.30" in s2
    view_flat = dict(view, regime="trend_down", action="flat_position", score=-0.5,
                     s22=-0.6, s261=-0.4, target=0.0)
    assert ("target weight 0.00 (flat); position 0.60 -> sell to 0.00"
            in reasoning_text(view_flat, 0.6))
    warm = {"ok": False, "n": 100, "need": 263, "regime": "uncertain", "confidence": 0.3,
            "action": "maintain", "target": None}
    assert reasoning_text(warm, 0.0) == ("Insufficient history (100/263 daily bars) -> uncertain "
                                         "at confidence 0.30 -> maintain (no order); position "
                                         "0.00 -> hold.")
    vs = reasoning_text(view, 0.0, weight_mode="vol_scaled")
    assert "vol-scaled: +0.42 x 0.10 / 0.40; policy label target_weight_60" in vs
    assert not re.search(r"[^\x00-\x7f]", s + s2 + vs)  # ASCII only


def test_decide_on_short_history_and_modes():
    short = [100.0 + i for i in range(50)]
    v = decide(short)
    assert v["ok"] is False and v["action"] == "maintain" and v["target"] is None
    assert v["n"] == 50 and v["need"] == 263
    with pytest.raises(ValueError):
        decide(short, weight_mode="magic")
    closes = [r[4] for r in gbm_bars(300, seed=9, bar_seconds=_DAY, sigma=0.03)]
    pol = decide(closes)
    vol = decide(closes, weight_mode="vol_scaled")
    assert pol["regime"] == vol["regime"] and pol["action"] == vol["action"]
    assert vol["target"] is not None and 0.0 <= vol["target"] <= 1.0
    # halve_position uses half of the last emitted target
    hv = decide(closes, last_target=0.6)
    if hv["action"] == "halve_position":
        assert hv["target"] == pytest.approx(0.3)


# ---------------------------------------------------------------- summary --
def test_backtest_summary_payload(walk):
    s = backtest_summary("SYN-1", walk)
    assert s["symbol"] == "SYN-1" and s["trial_count"] == 1
    assert s["signal"] == "tsmom_policy" and s["weight_mode"] == "policy"
    assert s["band"] == 0.10 and s["cost_bps"] == 10.0 and s["slippage_bps"] == 5.0
    assert s["n_bars"] == 400 and s["warmup_bars"] == 262
    assert s["n_decisions"] == 400 - 1 - 262
    assert len(s["equity"]) == len(s["buy_hold"]) == 400
    assert s["equity"][0]["ts"] == s["buy_hold"][0]["ts"]
    assert s["equity"][0]["equity"] == pytest.approx(10_000.0)  # all-cash start
    assert all(set(p) == {"ts", "equity"} for p in s["equity"] + s["buy_hold"])
    for key in ("sharpe", "sortino", "calmar", "max_drawdown", "total_return", "n_trades",
                "fees_paid_bps", "cagr", "ann_vol", "turnover"):
        assert key in s["metrics"], key
    assert s["metrics"]["n_trades"] >= 1
    assert s["metrics"]["fees_paid_bps"] > 0
    assert s["metrics"]["max_drawdown"] <= 0
    assert [g["cost_bps"] for g in s["cost_grid"]] == [float(c) for c in DEFAULT_COST_GRID]
    rets = [g["total_return"] for g in s["cost_grid"]]
    assert all(a >= b - 1e-12 for a, b in zip(rets, rets[1:]))  # fees only hurt
    assert s["tickets"] == build_tickets("SYN-1", walk)
    assert sum(t["n_decisions"] for t in s["tickets"]) == s["n_decisions"]


def test_backtest_summary_vol_scaled_signal_name(walk):
    s = backtest_summary("SYN-1", walk, weight_mode="vol_scaled", cost_grid=(0, 120))
    assert s["signal"] == "tsmom_weight"
    assert [g["cost_bps"] for g in s["cost_grid"]] == [0.0, 120.0]


def test_backtest_payload_document(walk):
    doc = backtest_payload({"SYN-1": walk, "SYN-2": gbm_bars(300, seed=2, bar_seconds=_DAY)},
                           cost_grid=(0, 10))
    assert set(doc["symbols"]) == {"SYN-1", "SYN-2"}
    assert doc["signal"] == "tsmom_policy" and doc["band"] == 0.10
    assert "synthetic" in doc["note"].lower() and "language model" in doc["note"]
    assert doc["symbols"]["SYN-2"]["n_decisions"] == 300 - 1 - 262


def test_inputs_are_validated(walk):
    with pytest.raises(ValueError):
        build_tickets("SYN-1", walk[:1])
    with pytest.raises(ValueError):
        build_tickets("SYN-1", walk, weight_mode="nope")
    bars = rows_to_bars(walk[:3])
    assert bars[0].timestamp.tzinfo is not None
    assert rows_to_bars(bars) == bars  # Bar input passes through
    assert rows_to_bars([[str(x) for x in r] for r in walk[:3]]) == bars


def test_tickets_from_decisions_empty():
    assert tickets_from_decisions("SYN-1", []) == []


# ------------------------------------------------------- honesty markers --
def test_every_fill_is_marked_simulated(walk):
    """HONESTY rule 4: the ticket stream marks every fill as simulated, and
    only fills carry the marker (a no-fill decision carries None)."""
    tickets = build_tickets("SYN-1", walk)
    decs = _all_decisions(tickets)
    fills = [d for d in decs if d["outcome"]["fill_px"] is not None]
    assert fills, "the fixture must produce at least one fill"
    for d in decs:
        kind = d["outcome"]["fill_kind"]
        if d["outcome"]["fill_px"] is None:
            assert kind is None
        else:
            assert kind == "simulated"


def _decision(regime, action, confidence, *, delta_qty, target, close=100.0, score=0.3):
    """A hand-built decision entry (the shape run_ticket_backtest emits)."""
    return {
        "tick_no": 0, "ts": "2026-01-01T00:00:00+00:00", "action": action,
        "confidence": confidence, "regime": regime,
        "observation": {"close": close, "tsmom_score": score, "sigma_ann": 0.5,
                        "vol_ratio": 1.0, "target_weight": target, "position_weight": 0.0},
        "reasoning": "hand-built decision",
        "outcome": {"fill_kind": "simulated", "fill_ts": "2026-01-02T00:00:00+00:00",
                    "fill_px": close, "fee": 0.1, "delta_qty": delta_qty,
                    "side": "buy" if delta_qty > 0 else "sell", "weight_after": target},
    }


def test_thesis_never_says_enter_long_on_a_downtrend_read():
    """A medium-confidence trend_down maps to target_weight_20 - an absolute
    target that BUYS a flat book to 0.20. The thesis must call that a policy
    floor, never an entry call; a trend_up entry keeps the plain wording."""
    down = _decision("trend_down", "target_weight_20", 0.62, delta_qty=2.0, target=0.2, score=-0.27)
    (ticket,) = tickets_from_decisions("SYN-1", [down])
    assert ticket["side"] == "long"
    assert ticket["thesis"].startswith("Policy floor, not a bullish call: trend_down")
    assert "Enter long" not in ticket["thesis"]
    assert "target_weight_20" in ticket["thesis"] and "buying to 0.20" in ticket["thesis"]

    up = _decision("trend_up", "target_weight_60", 0.71, delta_qty=6.0, target=0.6, score=0.42)
    (ticket_up,) = tickets_from_decisions("SYN-1", [up])
    assert ticket_up["thesis"].startswith("Enter long: trend_up at confidence 0.71")

    # the wording holds on the real fixture too: no long ticket opened on a
    # trend_down read may say "Enter long"
    for t in build_tickets("SYN-2", gbm_bars(400, seed=3, bar_seconds=_DAY, sigma=0.03)):
        if t["side"] == "long" and t["decisions"][0]["regime"] == "trend_down":
            assert "Enter long" not in t["thesis"]
            assert t["thesis"].startswith("Policy floor")
