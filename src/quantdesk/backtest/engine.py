from __future__ import annotations

from datetime import datetime

from ..policy import translate_regime_to_action
from .config import (
    DEFAULT_INITIAL_CAPITAL,
    HALVE_KEEP,
    REACCUMULATE_RATE,
    REDUCE_10_KEEP,
    REDUCE_25_KEEP,
    SLIPPAGE_BPS,
    TARGET_FRACTIONS,
    TARGET_WEIGHT_CAP,
    TRADING_COST_BPS,
)
from .types import Bar, BacktestResult, Decision, SignalFn, Trade, WeightFn


def _aligned_timestamps(prices: dict[str, list[Bar]]) -> list[datetime]:
    common: set[datetime] | None = None
    for bars in prices.values():
        ts = {b.timestamp for b in bars}
        common = ts if common is None else (common & ts)
    return sorted(common or set())


def _build_index(prices: dict[str, list[Bar]]) -> dict[str, dict[datetime, int]]:
    return {sym: {b.timestamp: i for i, b in enumerate(bars)} for sym, bars in prices.items()}


def _initial_quantities(
    prices: dict[str, list[Bar]],
    idx: dict[str, dict[datetime, int]],
    t0: datetime,
    initial_capital: float,
    initial_weights: dict[str, float] | None,
) -> tuple[dict[str, float], float]:
    if initial_weights is None:
        n = len(prices)
        initial_weights = {sym: 1.0 / n for sym in prices}
    total_w = sum(initial_weights.values())
    if total_w <= 0:
        raise ValueError("initial_weights must sum to a positive number")
    if total_w > 1.0 + 1e-9:
        raise ValueError(f"initial_weights sum to {total_w} > 1.0; leave the remainder as cash")
    qtys: dict[str, float] = {}
    spent = 0.0
    # Weights are absolute fractions of capital. Anything left over stays in cash —
    # we do NOT normalize {X: 0.5} to {X: 1.0}.
    for sym, w in initial_weights.items():
        if sym not in prices:
            raise ValueError(f"initial weight given for {sym} but no price data")
        bar0 = prices[sym][idx[sym][t0]]
        alloc = initial_capital * w
        qtys[sym] = alloc / bar0.open
        spent += alloc
    return qtys, max(0.0, initial_capital - spent)


def run_backtest(
    prices: dict[str, list[Bar]],
    signal_fn: SignalFn,
    initial_capital: float = DEFAULT_INITIAL_CAPITAL,
    initial_weights: dict[str, float] | None = None,
    rebalance_every_n_bars: int = 1,
    cost_bps: float = TRADING_COST_BPS,
    slippage_bps: float = SLIPPAGE_BPS,
    granularity: str = "1day",
) -> BacktestResult:
    """Time-aligned multi-asset backtest.

    Decisions formed on bar t close are executed at bar t+1 open (no lookahead).
    Equity is marked-to-market at each bar's close.
    """
    if not prices:
        raise ValueError("prices is empty")
    timestamps = _aligned_timestamps(prices)
    if len(timestamps) < 2:
        raise ValueError("need at least 2 aligned bars across symbols")

    idx = _build_index(prices)
    qtys, cash = _initial_quantities(prices, idx, timestamps[0], initial_capital, initial_weights)

    cost_factor = (cost_bps + slippage_bps) / 10_000.0

    trades: list[Trade] = []
    decisions: list[Decision] = []
    equity_curve: list[tuple[datetime, float]] = []
    weight_history: list[tuple[datetime, dict[str, float]]] = []

    pending: dict[str, Decision] = {}

    for i, ts in enumerate(timestamps):
        # 1. Execute pending decisions at this bar's open.
        if pending:
            equity_open = cash + sum(qtys[s] * prices[s][idx[s][ts]].open for s in qtys)
            reaccum_syms = [s for s, d in pending.items() if d.action == "reaccumulate_small"]
            total_demand = REACCUMULATE_RATE * equity_open * len(reaccum_syms)
            scale = min(1.0, cash / total_demand) if total_demand > 0 else 1.0

            for sym, dec in pending.items():
                bar = prices[sym][idx[sym][ts]]
                px = bar.open
                action = dec.action
                if action == "reduce_10_percent":
                    delta = qtys[sym] * (REDUCE_10_KEEP - 1.0)
                elif action == "reduce_25_percent":
                    delta = qtys[sym] * (REDUCE_25_KEEP - 1.0)
                elif action == "reaccumulate_small":
                    spend = REACCUMULATE_RATE * equity_open * scale
                    delta = spend / px
                elif action in TARGET_FRACTIONS:
                    # absolute target: fraction of the per-symbol cap (the same
                    # table an execution-side weights engine would use)
                    target_qty = TARGET_FRACTIONS[action] * TARGET_WEIGHT_CAP * equity_open / px
                    delta = target_qty - qtys[sym]
                elif action == "halve_position":
                    delta = (HALVE_KEEP - 1.0) * qtys[sym]
                else:
                    delta = 0.0
                if delta > 0.0:
                    # cash guard for absolute-target buys (reaccum has its own scale)
                    affordable = cash / (px * (1.0 + cost_factor)) if px > 0 else 0.0
                    delta = min(delta, max(0.0, affordable))
                if delta == 0.0:
                    continue
                trade_value = abs(delta) * px
                cost = trade_value * cost_factor
                qtys[sym] += delta
                cash -= delta * px + cost
                trades.append(Trade(ts, sym, action, delta, px, cost))
            pending = {}

        # 2. Mark equity at this bar's close.
        equity_close = cash + sum(qtys[s] * prices[s][idx[s][ts]].close for s in qtys)
        equity_curve.append((ts, equity_close))
        if equity_close > 0:
            weights = {
                s: (qtys[s] * prices[s][idx[s][ts]].close) / equity_close for s in qtys
            }
        else:
            weights = {s: 0.0 for s in qtys}
        weight_history.append((ts, weights))

        # 3. Generate decisions on this close, to execute at next bar's open.
        if i % rebalance_every_n_bars != 0:
            continue
        if i == len(timestamps) - 1:
            continue
        for sym, bars in prices.items():
            history = bars[: idx[sym][ts] + 1]
            regime, conf = signal_fn(ts, sym, history)
            action = translate_regime_to_action(regime, conf)
            dec = Decision(ts, sym, str(regime), float(conf), action)
            decisions.append(dec)
            if action not in ("hold", "stop_adding", "maintain"):
                pending[sym] = dec

    return BacktestResult(
        equity_curve=equity_curve,
        trades=trades,
        decisions=decisions,
        weight_history=weight_history,
        granularity=granularity,
    )


def run_weight_backtest(
    prices: dict[str, list[Bar]],
    weight_fn: WeightFn,
    initial_capital: float = DEFAULT_INITIAL_CAPITAL,
    rebalance_every_n_bars: int = 7,
    cost_bps: float = TRADING_COST_BPS,
    slippage_bps: float = SLIPPAGE_BPS,
    no_trade_band: float = 0.10,
    granularity: str = "1day",
) -> BacktestResult:
    """Target-weight execution mode (docs/RESEARCH_DISCIPLINE.md, target-weight mode).

    The continuous counterpart of run_backtest: instead of 5 discrete actions,
    the strategy emits a TARGET weight per symbol and the engine trades the
    difference. Same no-lookahead timeline (decide on close(t), execute at
    open(t+1)), plus the fee-survival machinery the discrete path lacks:

    - no_trade_band: |target - current| below the band trades NOTHING — the
      first-class turnover control at 60-120bps/side (Robot Wealth / Harvey et al. (2022));
      band width is a sweepable parameter, default 10 weight-points.
    - Long/flat spot: targets are clipped to [0,1]; gross > 1 is scaled down
      proportionally (remainder stays cash); sells execute before buys and
      buys are cash-capped — cash can never go negative.
    - weight_fn returning None means "no view": hold the current position.
    - Starts ALL-CASH (weights are the strategy's own output, unlike
      run_backtest's initial_weights allocation).

    Trades carry action="rebalance" (the discrete Action vocabulary does not
    apply on this path). Default cadence is weekly on daily bars.
    """
    if not prices:
        raise ValueError("prices is empty")
    timestamps = _aligned_timestamps(prices)
    if len(timestamps) < 2:
        raise ValueError("need at least 2 aligned bars across symbols")
    if no_trade_band < 0:
        raise ValueError("no_trade_band must be >= 0")

    idx = _build_index(prices)
    qtys: dict[str, float] = {sym: 0.0 for sym in prices}
    cash = initial_capital
    cost_factor = (cost_bps + slippage_bps) / 10_000.0

    trades: list[Trade] = []
    equity_curve: list[tuple[datetime, float]] = []
    weight_history: list[tuple[datetime, dict[str, float]]] = []
    target_history: list[tuple[datetime, dict[str, float]]] = []

    pending_targets: dict[str, float] | None = None

    for i, ts in enumerate(timestamps):
        # 1. Execute pending targets at this bar's open.
        if pending_targets is not None:
            equity_open = cash + sum(
                qtys[s] * prices[s][idx[s][ts]].open for s in qtys
            )
            orders: list[tuple[str, float, float]] = []  # (sym, delta_w, px)
            if equity_open > 0:
                for sym, target_w in pending_targets.items():
                    px = prices[sym][idx[sym][ts]].open
                    if px <= 0:
                        continue
                    current_w = qtys[sym] * px / equity_open
                    delta_w = target_w - current_w
                    if abs(delta_w) < no_trade_band:
                        continue  # inside the band: the fee is not worth it
                    orders.append((sym, delta_w, px))
            # Sells first so their proceeds fund the buys within the same open.
            for sym, delta_w, px in sorted(orders, key=lambda o: o[1]):
                delta_qty = delta_w * equity_open / px
                if delta_qty > 0:
                    # cash-cap the buy: shares * px * (1 + fee) <= cash
                    affordable = cash / (px * (1.0 + cost_factor))
                    delta_qty = min(delta_qty, affordable)
                    if delta_qty <= 1e-12:
                        continue
                elif qtys[sym] + delta_qty < 0:
                    delta_qty = -qtys[sym]  # long/flat: never sell below zero
                    if delta_qty >= -1e-12:
                        continue
                notional = abs(delta_qty) * px
                cost = notional * cost_factor
                qtys[sym] += delta_qty
                cash -= delta_qty * px + cost
                trades.append(Trade(ts, sym, "rebalance", delta_qty, px, cost))  # type: ignore[arg-type]
            pending_targets = None

        # 2. Mark equity at this bar's close.
        equity_close = cash + sum(
            qtys[s] * prices[s][idx[s][ts]].close for s in qtys
        )
        equity_curve.append((ts, equity_close))
        if equity_close > 0:
            weights = {
                s: (qtys[s] * prices[s][idx[s][ts]].close) / equity_close for s in qtys
            }
        else:
            weights = {s: 0.0 for s in qtys}
        weight_history.append((ts, weights))

        # 3. Form targets on this close, to execute at next bar's open.
        if i % rebalance_every_n_bars != 0:
            continue
        if i == len(timestamps) - 1:
            continue
        targets: dict[str, float] = {}
        for sym, bars in prices.items():
            history = bars[: idx[sym][ts] + 1]
            try:
                w = weight_fn(ts, sym, history)
            except Exception:  # hygiene: a broken signal holds, never trades
                w = None
            if w is None:
                continue  # no view: keep current position for this symbol
            targets[sym] = min(1.0, max(0.0, float(w)))
        gross = sum(targets.values())
        if gross > 1.0:  # long-only spot: scale down, remainder is cash
            targets = {s: w / gross for s, w in targets.items()}
        if targets:
            target_history.append((ts, dict(targets)))
            pending_targets = targets

    result = BacktestResult(
        equity_curve=equity_curve,
        trades=trades,
        decisions=[],
        weight_history=weight_history,
        granularity=granularity,
    )
    result.metrics["target_rebalances"] = float(len(target_history))
    return result
