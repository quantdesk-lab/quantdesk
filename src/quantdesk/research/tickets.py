"""Decision tickets - a bar-by-bar, explain-every-step view of the
target-weight backtest, built on the real engine.

Illustrative research tooling: the ticket builder wraps
``quantdesk.backtest.engine.run_weight_backtest`` (the fills are the engine's,
not a reimplementation) with a RECORDING weight function. At every decision
bar the engine hands the weight function the price history up to and
including that bar (``bars[:t+1]``); the function evaluates the TSMOM regime
on exactly that prefix, maps ``(regime, confidence)`` through the policy
table, and remembers what it saw. Decisions are therefore lookahead-free by
construction and the ticket for bar ``t`` equals the ticket you would get by
running the builder on ``bars[:t+1]`` alone (the test suite asserts this).

Two weight modes:

- ``"policy"`` (default): the policy table's action IS the target weight -
  ``target_weight_60`` -> 0.60, ``flat_position`` -> 0.0, ``halve_position``
  -> half of the last emitted target, ``maintain`` -> no view (hold). The
  fractions are applied to ``weight_cap`` (default 1.0, i.e. a fraction of
  equity); the discrete backtest engine applies the same table under
  ``TARGET_WEIGHT_CAP = 0.10`` - each consumer states its cap.

  Reduce-class actions (``target_weight_20``, ``target_weight_30``,
  ``halve_position``, ``flat_position``) are absolute targets: on a flat
  book a medium-confidence ``trend_down`` read (-> ``target_weight_20``)
  therefore BUYS to 0.20. That is the policy table's floor, not a bullish
  call, and the ticket thesis says so in those words.
- ``"vol_scaled"``: the volatility-scaled TSMOM rule
  ``w = clip(score * sigma_target / sigma_ann, 0, 1)`` (the same rule the
  ``tsmom_weight`` backtest signal uses); the policy action is still recorded
  as a label.

Every ``reasoning`` string is generated deterministically from the numbers
and the policy table - there is no language model anywhere in this module.

Ticket semantics: the decision stream is partitioned into ``long`` and
``flat`` tickets; every decision belongs to exactly one ticket. A ``long``
ticket opens on the fill that takes the position from zero to positive
(the decision that produced that fill is its first decision) and closes on
the fill that returns it to zero; ``pnl`` is the realized cash flow of its
fills net of fees (``null`` while still open). A ``flat`` ticket collects
the decisions taken while no position is held (so two long tickets are
adjacent when the first decision after a close reopens immediately); its
``entry`` is the reference close at its first decision and it carries no
P&L. All figures come from the synthetic bars you pass in; nothing here is
a trading recommendation.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Sequence

from quantdesk.backtest.config import (
    DEFAULT_INITIAL_CAPITAL,
    SLIPPAGE_BPS,
    TARGET_FRACTIONS,
    TRADING_COST_BPS,
)
from quantdesk.backtest.engine import run_weight_backtest
from quantdesk.backtest.metrics import compute_metrics
from quantdesk.backtest.types import BacktestResult, Bar, Trade
from quantdesk.factors.tsmom import (
    MIN_BARS_DAILY,
    PPY_DAILY,
    VOL_OVERHEAT_RATIO,
    target_weight,
    tsmom_regime,
)
from quantdesk.policy import translate_regime_to_action

DEFAULT_BAND = 0.10
DEFAULT_COST_GRID: tuple[int, ...] = (0, 10, 20, 40, 60, 120)
WEIGHT_MODES = ("policy", "vol_scaled")
_DUST = 1e-9  # a position weight at or below this counts as flat

SIGNAL_NAMES = {"policy": "tsmom_policy", "vol_scaled": "tsmom_weight"}

_NOTE = (
    "Illustrative backtest on synthetic bars. Decisions are formed on the close of "
    "bar t and filled at the open of bar t+1 through the package's own engine "
    "(no-trade band, cash-capped buys, long/flat only). Every fill is a simulated "
    "fill at the crossing price with no queue position (outcome.fill_kind). Costs "
    "are per side. Target-weight actions are applied with weight_cap=1.0 here "
    "(target_weight_60 = 60% of equity); the discrete backtest engine applies the "
    "same policy table under TARGET_WEIGHT_CAP=0.10. Reduce-class actions are "
    "absolute targets, so a medium-confidence trend_down read buys a flat book to "
    "the 0.20 floor; the ticket thesis labels those as policy floors. `signal` is "
    "tsmom_policy in policy mode and tsmom_weight in vol_scaled mode. Reasoning "
    "strings are generated from the numbers and the policy table, not by a "
    "language model. Nothing here is a trading recommendation."
)


# --------------------------------------------------------------------------- #
# input coercion
# --------------------------------------------------------------------------- #
def rows_to_bars(rows: Sequence[Any]) -> list[Bar]:
    """``[ts, o, h, l, c, v]`` rows (numeric or string fields, epoch seconds)
    or ``Bar`` objects -> ``list[Bar]`` with UTC timestamps. Illustrative
    helper for the synthetic fixtures."""
    out: list[Bar] = []
    for row in rows:
        if isinstance(row, Bar):
            ts = row.timestamp
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            out.append(Bar(ts, row.open, row.high, row.low, row.close, row.volume))
            continue
        ts_raw, o, h, l, c, v = (float(row[i]) for i in range(6))
        out.append(Bar(datetime.fromtimestamp(ts_raw, tz=timezone.utc), o, h, l, c, v))
    return out


def _iso(ts: datetime) -> str:
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts.isoformat()


def _round(v: Any, nd: int = 6) -> Any:
    return round(float(v), nd) if isinstance(v, (int, float)) else None


# --------------------------------------------------------------------------- #
# one decision on one prefix (pure apart from the explicit ``last_target``)
# --------------------------------------------------------------------------- #
def decide(
    closes: Sequence[float],
    *,
    weight_mode: str = "policy",
    sigma_target: float = 0.10,
    ppy: int = PPY_DAILY,
    weight_cap: float = 1.0,
    last_target: float | None = None,
) -> dict[str, Any]:
    """Regime, confidence, policy action and target weight for ONE price
    prefix (``closes`` = every close up to and including the decision bar).

    Deterministic function of its inputs; ``last_target`` is the previously
    emitted target (policy mode needs it for ``halve_position``). Returns a
    flat dict; ``target`` is ``None`` for "no view / hold". Illustrative.
    """
    if weight_mode not in WEIGHT_MODES:
        raise ValueError(f"weight_mode must be one of {WEIGHT_MODES}, got {weight_mode!r}")
    rr = tsmom_regime(closes, ppy=ppy)
    diag = rr.get("diag") or {}
    regime = str(rr["regime"])
    confidence = float(rr["confidence"])
    action = str(translate_regime_to_action(regime, confidence))
    ok = bool(diag.get("ok"))
    view: dict[str, Any] = {
        "ok": ok,
        "n": int(diag.get("n", len(closes))),
        "need": int(diag.get("need", MIN_BARS_DAILY)),
        "regime": regime,
        "confidence": confidence,
        "action": action,
        "score": diag.get("score"),
        "s22": diag.get("s22"),
        "s65": diag.get("s65"),
        "s261": diag.get("s261"),
        "sigma_ann": diag.get("sigma_ann"),
        "vol_ratio": diag.get("vol_ratio"),
        "target": None,
    }
    if not ok:
        return view
    if weight_mode == "vol_scaled":
        view["target"] = target_weight(
            float(diag["score"]), float(diag["sigma_ann"]), sigma_target=sigma_target)
    elif action in TARGET_FRACTIONS:
        view["target"] = float(TARGET_FRACTIONS[action]) * float(weight_cap)
    elif action == "halve_position":
        view["target"] = 0.5 * (float(last_target) if last_target is not None else 0.0)
    else:  # maintain / unknown -> no view
        view["target"] = None
    return view


def reasoning_text(
    view: dict[str, Any],
    position_weight: float,
    *,
    band: float = DEFAULT_BAND,
    weight_mode: str = "policy",
    sigma_target: float = 0.10,
) -> str:
    """One deterministic English sentence explaining a decision from its
    numbers and the policy table. No language model; illustrative wording."""
    pos = float(position_weight)
    conf = float(view["confidence"])
    regime = view["regime"]
    action = view["action"]
    target = view.get("target")
    if not view.get("ok"):
        return (
            f"Insufficient history ({view.get('n', 0)}/{view.get('need', MIN_BARS_DAILY)} "
            f"daily bars) -> {regime} at confidence {conf:.2f} -> {action} (no order); "
            f"position {pos:.2f} -> hold."
        )
    score, s22, s261 = float(view["score"]), float(view["s22"]), float(view["s261"])
    vr = float(view["vol_ratio"])
    side = "above" if vr > VOL_OVERHEAT_RATIO else "below"
    head = (
        f"TSMOM blend {score:+.2f} (s22 {s22:+.2f}, s261 {s261:+.2f}), vol ratio {vr:.2f} "
        f"{side} the {VOL_OVERHEAT_RATIO:.2f} overheat line -> {regime} at confidence "
        f"{conf:.2f}"
    )
    if weight_mode == "vol_scaled":
        sigma = float(view["sigma_ann"])
        act = (f"target weight {float(target):.2f} (vol-scaled: {score:+.2f} x "
               f"{sigma_target:.2f} / {sigma:.2f}; policy label {action})")
    elif action in TARGET_FRACTIONS:
        act = f"target weight {float(target):.2f}"
        if action == "flat_position":
            act += " (flat)"
    elif action == "halve_position":
        act = f"halve position to {float(target):.2f}"
    else:
        act = f"{action} (no order)"
    if target is None:
        ex = "hold"
    elif abs(float(target) - pos) < band:
        ex = "inside band, no trade"
    elif float(target) > pos:
        ex = f"buy to {float(target):.2f}"
    else:
        ex = f"sell to {float(target):.2f}"
    return f"{head} -> {act}; position {pos:.2f} -> {ex} (band {band:.2f})."


# --------------------------------------------------------------------------- #
# engine wrap: run once, keep every decision
# --------------------------------------------------------------------------- #
def run_ticket_backtest(
    symbol: str,
    bars_1d: Sequence[Any],
    *,
    band: float = DEFAULT_BAND,
    cost_bps: float = TRADING_COST_BPS,
    slippage_bps: float = SLIPPAGE_BPS,
    weight_mode: str = "policy",
    sigma_target: float = 0.10,
    ppy: int = PPY_DAILY,
    weight_cap: float = 1.0,
    initial_capital: float = DEFAULT_INITIAL_CAPITAL,
    rebalance_every_n_bars: int = 1,
    include_warmup: bool = False,
) -> tuple[BacktestResult, list[dict[str, Any]], list[Bar]]:
    """Run the real target-weight engine on ``bars_1d`` with a recording
    weight function and return ``(result, decisions, bars)``.

    Each decision dict is the spec's TICKET decision entry:
    ``{tick_no, ts, action, confidence, regime, observation, reasoning,
    outcome}``. ``observation.position_weight`` is the weight marked at the
    decision bar's close; ``outcome`` describes the fill (if any) at the next
    bar's open and ``weight_after`` the weight marked at that bar's close.
    Warmup bars (no TSMOM view yet) are skipped unless ``include_warmup``.
    Synthetic/illustrative only.
    """
    if weight_mode not in WEIGHT_MODES:
        raise ValueError(f"weight_mode must be one of {WEIGHT_MODES}, got {weight_mode!r}")
    bars = rows_to_bars(bars_1d)
    if len(bars) < 2:
        raise ValueError("need at least 2 bars")
    record: dict[datetime, dict[str, Any]] = {}
    state = {"last_target": None}

    def weight_fn(ts: datetime, sym: str, history: list[Bar]) -> float | None:
        view = decide(
            [b.close for b in history], weight_mode=weight_mode, sigma_target=sigma_target,
            ppy=ppy, weight_cap=weight_cap, last_target=state["last_target"],
        )
        record[ts] = view
        if view["target"] is not None:
            state["last_target"] = float(view["target"])
        return view["target"]

    result = run_weight_backtest(
        {symbol: bars}, weight_fn, initial_capital=initial_capital,
        rebalance_every_n_bars=rebalance_every_n_bars, cost_bps=cost_bps,
        slippage_bps=slippage_bps, no_trade_band=band, granularity="1d",
    )
    result.metrics["warmup_bars"] = float(sum(1 for v in record.values() if not v["ok"]))
    weights = {ts: w.get(symbol, 0.0) for ts, w in result.weight_history}
    fills: dict[datetime, Trade] = {t.timestamp: t for t in result.trades}
    decisions: list[dict[str, Any]] = []
    for i, bar in enumerate(bars[:-1]):
        view = record.get(bar.timestamp)
        if view is None:
            continue
        if not view["ok"] and not include_warmup:
            continue
        pos = float(weights.get(bar.timestamp, 0.0))
        nxt = bars[i + 1]
        fill = fills.get(nxt.timestamp)
        decisions.append({
            "tick_no": i,
            "ts": _iso(bar.timestamp),
            "action": view["action"],
            "confidence": round(float(view["confidence"]), 4),
            "regime": view["regime"],
            "observation": {
                "close": _round(bar.close),
                "tsmom_score": _round(view["score"]),
                "sigma_ann": _round(view["sigma_ann"]),
                "vol_ratio": _round(view["vol_ratio"]),
                "target_weight": _round(view["target"]),
                "position_weight": round(pos, 6),
            },
            "reasoning": reasoning_text(
                view, pos, band=band, weight_mode=weight_mode, sigma_target=sigma_target),
            "outcome": {
                "fill_kind": "simulated" if fill is not None else None,
                "fill_ts": _iso(nxt.timestamp) if fill is not None else None,
                "fill_px": _round(fill.price) if fill is not None else None,
                "fee": _round(fill.cost) if fill is not None else None,
                "delta_qty": _round(fill.delta_qty, 10) if fill is not None else None,
                "side": (("buy" if fill.delta_qty > 0 else "sell") if fill is not None else None),
                "weight_after": round(float(weights.get(nxt.timestamp, 0.0)), 6),
            },
        })
    return result, decisions, bars


# --------------------------------------------------------------------------- #
# tickets
# --------------------------------------------------------------------------- #
def _new_ticket(symbol: str, n: int, side: str, first: dict[str, Any]) -> dict[str, Any]:
    return {
        "ticket_id": f"{symbol}-T{n:03d}",
        "symbol": symbol,
        "side": side,
        "open_ts": None,
        "close_ts": None,
        "entry": None,
        "exit": None,
        "size": 0.0,
        "pnl": None,
        "fees": 0.0,
        "n_decisions": 0,
        "thesis": "",
        "why_open": first["reasoning"],
        "why_close": None,
        "decisions": [],
        "_cash": 0.0,
        "_buy_notional": 0.0,
        "_peak": 0.0,
    }


#: Actions that are floors/reductions in the policy table. Applied to a flat
#: book they still buy (absolute targets), so a long ticket they open is a
#: policy floor, never a bullish call - the thesis must not say "Enter long".
_FLOOR_ACTIONS = ("target_weight_20", "halve_position")


def _thesis(side: str, d: dict[str, Any]) -> str:
    obs = d["observation"]
    score = obs.get("tsmom_score")
    score_txt = f"{score:+.2f}" if isinstance(score, (int, float)) else "n/a"
    if side == "long":
        tgt = obs.get("target_weight")
        tgt_txt = f"{tgt:.2f}" if isinstance(tgt, (int, float)) else "n/a"
        if d["regime"] == "trend_down" or d["action"] in _FLOOR_ACTIONS:
            return (f"Policy floor, not a bullish call: {d['regime']} at confidence "
                    f"{d['confidence']:.2f} (TSMOM blend {score_txt}) -> {d['action']} -> "
                    f"target weight {tgt_txt}; the book was flat, so reaching the floor "
                    f"means buying to {tgt_txt}.")
        return (f"Enter long: {d['regime']} at confidence {d['confidence']:.2f} "
                f"(TSMOM blend {score_txt}) -> {d['action']} -> target weight {tgt_txt}.")
    return (f"Stay flat: {d['regime']} at confidence {d['confidence']:.2f} "
            f"(TSMOM blend {score_txt}) -> {d['action']}; no position held.")


def _finalize(t: dict[str, Any]) -> dict[str, Any]:
    t["n_decisions"] = len(t["decisions"])
    t["fees"] = round(t["fees"], 6)
    if t["side"] == "long":
        t["peak_weight"] = round(t["_peak"], 6)
        if t["close_ts"] is not None:
            t["pnl"] = round(t["_cash"], 6)
            t["return_on_cost"] = (
                round(t["_cash"] / t["_buy_notional"], 6) if t["_buy_notional"] > 0 else None)
    for k in ("_cash", "_buy_notional", "_peak"):
        t.pop(k, None)
    return t


def tickets_from_decisions(
    symbol: str, decisions: Sequence[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Partition an ordered decision stream into long/flat tickets (see the
    module docstring for the semantics). Illustrative."""
    tickets: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for d in decisions:
        out = d["outcome"]
        pos_before = float(d["observation"]["position_weight"])
        w_after = float(out["weight_after"])
        filled = out["fill_px"] is not None
        opens_long = filled and pos_before <= _DUST and float(out["delta_qty"] or 0.0) > 0
        if current is None:
            side = "long" if opens_long else "flat"
            current = _new_ticket(symbol, len(tickets) + 1, side, d)
            current["thesis"] = _thesis(side, d)
            current["open_ts"] = out["fill_ts"] if side == "long" else d["ts"]
            current["entry"] = out["fill_px"] if side == "long" else d["observation"]["close"]
        elif current["side"] == "flat" and opens_long:
            current["close_ts"] = out["fill_ts"]
            tickets.append(_finalize(current))
            current = _new_ticket(symbol, len(tickets) + 1, "long", d)
            current["thesis"] = _thesis("long", d)
            current["open_ts"] = out["fill_ts"]
            current["entry"] = out["fill_px"]
        current["decisions"].append(d)
        if filled and current["side"] == "long":
            dq, px, fee = float(out["delta_qty"]), float(out["fill_px"]), float(out["fee"] or 0.0)
            current["_cash"] += -(dq * px) - fee
            current["fees"] += fee
            if dq > 0:
                current["_buy_notional"] += dq * px
            if current["size"] == 0.0 and dq > 0:
                current["size"] = round(w_after, 6)
        if current["side"] == "long":
            current["_peak"] = max(current["_peak"], w_after)
            if filled and float(out["delta_qty"] or 0.0) < 0 and w_after <= _DUST:
                current["close_ts"] = out["fill_ts"]
                current["exit"] = out["fill_px"]
                current["why_close"] = d["reasoning"]
                tickets.append(_finalize(current))
                current = None
    if current is not None:
        tickets.append(_finalize(current))
    return tickets


def build_tickets(
    symbol: str,
    bars_1d: Sequence[Any],
    *,
    band: float = DEFAULT_BAND,
    cost_bps: float = TRADING_COST_BPS,
    slippage_bps: float = SLIPPAGE_BPS,
    weight_mode: str = "policy",
    sigma_target: float = 0.10,
    ppy: int = PPY_DAILY,
    weight_cap: float = 1.0,
    initial_capital: float = DEFAULT_INITIAL_CAPITAL,
    rebalance_every_n_bars: int = 1,
    include_warmup: bool = False,
) -> list[dict[str, Any]]:
    """TICKET list for one symbol: the target-weight backtest run bar by bar
    through the real engine, every decision explained in deterministic
    English. Synthetic/illustrative - see the module docstring."""
    _, decisions, _ = run_ticket_backtest(
        symbol, bars_1d, band=band, cost_bps=cost_bps, slippage_bps=slippage_bps,
        weight_mode=weight_mode, sigma_target=sigma_target, ppy=ppy, weight_cap=weight_cap,
        initial_capital=initial_capital, rebalance_every_n_bars=rebalance_every_n_bars,
        include_warmup=include_warmup,
    )
    return tickets_from_decisions(symbol, decisions)


# --------------------------------------------------------------------------- #
# summary payloads
# --------------------------------------------------------------------------- #
def buy_and_hold_curve(
    bars: Sequence[Bar], *, initial_capital: float, cost_bps: float, slippage_bps: float
) -> list[dict[str, Any]]:
    """All-in at the first bar's open (one entry fee charged), marked at every
    close. Illustrative benchmark curve."""
    if not bars:
        return []
    cf = (cost_bps + slippage_bps) / 10_000.0
    px0 = bars[0].open
    qty = initial_capital / (px0 * (1.0 + cf)) if px0 > 0 else 0.0
    return [{"ts": _iso(b.timestamp), "equity": round(qty * b.close, 6)} for b in bars]


def backtest_summary(
    symbol: str,
    bars_1d: Sequence[Any],
    *,
    band: float = DEFAULT_BAND,
    cost_bps: float = TRADING_COST_BPS,
    slippage_bps: float = SLIPPAGE_BPS,
    cost_grid: Sequence[float] = DEFAULT_COST_GRID,
    weight_mode: str = "policy",
    sigma_target: float = 0.10,
    ppy: int = PPY_DAILY,
    weight_cap: float = 1.0,
    initial_capital: float = DEFAULT_INITIAL_CAPITAL,
    rebalance_every_n_bars: int = 1,
    include_warmup: bool = False,
) -> dict[str, Any]:
    """Per-symbol block of the site's ``backtest.json``: equity and buy-and-
    hold curves, metrics (``quantdesk.backtest.metrics.compute_metrics`` plus
    ``fees_paid_bps``), a per-side cost grid (``cost_bps`` swept with
    slippage folded in, i.e. the grid value is the TOTAL per-side cost), the
    ticket list, and ``trial_count = 1`` - one parameter set, no sweep, no
    selection. Synthetic/illustrative only."""
    kw = dict(
        band=band, weight_mode=weight_mode, sigma_target=sigma_target, ppy=ppy,
        weight_cap=weight_cap, initial_capital=initial_capital,
        rebalance_every_n_bars=rebalance_every_n_bars, include_warmup=include_warmup,
    )
    result, decisions, bars = run_ticket_backtest(
        symbol, bars_1d, cost_bps=cost_bps, slippage_bps=slippage_bps, **kw)
    tickets = tickets_from_decisions(symbol, decisions)
    metrics = {k: _round(v) for k, v in compute_metrics(result).items()}
    fees = sum(t.cost for t in result.trades)
    metrics["fees_paid_bps"] = (
        round(fees / initial_capital * 1e4, 4) if initial_capital > 0 else None)
    metrics["n_trades"] = float(len(result.trades))
    grid: list[dict[str, Any]] = []
    for c in cost_grid:
        r, _, _ = run_ticket_backtest(symbol, bars, cost_bps=float(c), slippage_bps=0.0, **kw)
        m = compute_metrics(r)
        grid.append({
            "cost_bps": float(c),
            "total_return": _round(m.get("total_return")),
            "sharpe": _round(m.get("sharpe")),
            "n_trades": float(len(r.trades)),
        })
    return {
        "symbol": symbol,
        "signal": SIGNAL_NAMES[weight_mode],
        "weight_mode": weight_mode,
        "band": float(band),
        "cost_bps": float(cost_bps),
        "slippage_bps": float(slippage_bps),
        "n_bars": len(bars),
        "warmup_bars": int(result.metrics.get("warmup_bars", 0.0)),
        "n_decisions": len(decisions),
        "equity": [{"ts": _iso(ts), "equity": round(eq, 6)} for ts, eq in result.equity_curve],
        "buy_hold": buy_and_hold_curve(
            bars, initial_capital=initial_capital, cost_bps=cost_bps, slippage_bps=slippage_bps),
        "metrics": metrics,
        "cost_grid": grid,
        "trial_count": 1,
        "tickets": tickets,
    }


def backtest_payload(
    bars_by_symbol: dict[str, Sequence[Any]],
    *,
    band: float = DEFAULT_BAND,
    cost_bps: float = TRADING_COST_BPS,
    slippage_bps: float = SLIPPAGE_BPS,
    cost_grid: Sequence[float] = DEFAULT_COST_GRID,
    weight_mode: str = "policy",
    **kwargs: Any,
) -> dict[str, Any]:
    """The whole ``backtest.json`` document: ``{symbols: {sym: summary},
    signal, weight_mode, band, cost_bps, slippage_bps, note}``. Synthetic/
    illustrative only."""
    symbols = {
        sym: backtest_summary(
            sym, bars, band=band, cost_bps=cost_bps, slippage_bps=slippage_bps,
            cost_grid=cost_grid, weight_mode=weight_mode, **kwargs)
        for sym, bars in bars_by_symbol.items()
    }
    return {
        "symbols": symbols,
        "signal": SIGNAL_NAMES[weight_mode],
        "weight_mode": weight_mode,
        "band": float(band),
        "cost_bps": float(cost_bps),
        "slippage_bps": float(slippage_bps),
        "note": _NOTE,
    }
