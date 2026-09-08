"""The local judge: deterministic, refusal-first verdicts on one candidate.

For a candidate expression on one series of closed bars:

1. Evaluate the tree once on the full series (``expr.evaluate``; element t
   depends only on bars <= t) and slice it - no per-fold re-evaluation.
2. In-sample selection statistic: ONE ``board.ic_for`` at horizon 1 on the
   in-sample rows. Fewer than the board's 30 pairs -> ``refused`` (the count
   is still reported; the candidate is not a trial).
3. Null gate: ``|IC| > deflated_threshold(n, N)`` for the current ledger
   count ``N`` -> ``cleared_null``. The threshold and ``N`` are stamped.
4. Stability observable: per-block ICs; majority sign agreement with the
   in-sample sign, else ``unstable``.
5. Redundancy: Spearman against every archived survivor's in-sample series;
   ``|rho| > 0.7`` -> ``redundant``.
6. Reported, never gated: horizon-24 IC (with the board's ``n_eff`` gate),
   the decay sweep and the lag-1 turnover proxy.

Verdict vocabulary (in-sample): ``refused | noise | redundant | unstable |
candidate``. After the single holdout touch, ``fee_after`` labels a survivor
``feature-only`` or ``standalone`` from the cost grid on holdout bars: a
long/flat position from the sign of the factor, filled by the package's own
weight engine at the crossing price (simulated fills, stated in the
payload). Illustrative; nothing here is a recommendation.
"""
from __future__ import annotations

import math
from typing import Any, Sequence

from quantdesk.backtest.config import DEFAULT_INITIAL_CAPITAL, TRADING_COST_BPS
from quantdesk.backtest.engine import run_weight_backtest
from quantdesk.backtest.metrics import compute_metrics, spearman_rank_ic
from quantdesk.research.board import _pairs, decay_for, self_corr_lag1
from quantdesk.research.tickets import rows_to_bars

from .expr import Node, evaluate, expr_id, to_text, warmup
from .gates import Gates
from .ledger import deflated_threshold
from .walkforward import Split, ic_on_range

VERDICTS: tuple[str, ...] = ("refused", "noise", "redundant", "unstable", "candidate")
FEE_LABELS: tuple[str, ...] = ("feature-only", "standalone")
REDUNDANCY_RHO = 0.7
HORIZON_MAIN = 1
HORIZON_REPORT = 24
DECAY_LAGS: tuple[int, ...] = (1, 2, 3, 4, 6, 12, 24)
DEFAULT_COST_GRID: tuple[int, ...] = (0, 10, 20, 40, 60, 120)

_FEE_NOTE = (
    "Long/flat position from the sign of the factor on holdout bars only, filled at the "
    "next open by the package's own weight engine (simulated fills at the crossing price, "
    "no queue position). Costs are per side; the grid value folds slippage in."
)


def _r(v: Any, nd: int = 4) -> float | None:
    return round(float(v), nd) if isinstance(v, (int, float)) and math.isfinite(v) else None


def evaluate_cols(node: Node, cols: dict[str, Sequence[float]]) -> list:
    """``expr.evaluate`` on a ``split_ohlcv``-shaped column dict."""
    return evaluate(node, cols["o"], cols["h"], cols["l"], cols["c"], cols["v"])


def judge(
    node: Node,
    cols: dict[str, Sequence[float]],
    sp: Split,
    gates: Gates,
    n_trials: int,
    survivors: Sequence[tuple[str, Sequence[float | None]]] = (),
    *,
    series: Sequence[float | None] | None = None,
) -> dict[str, Any]:
    """One verdict record (see the module docstring). ``n_trials`` is the
    ledger count INCLUDING this candidate; ``survivors`` are
    ``(expr_id, series)`` pairs of archived candidates on the same symbol.
    ``series`` may be passed when already evaluated."""
    closes = list(cols["c"])
    if series is None:
        series = evaluate_cols(node, cols)
    ie = sp.insample_end
    ins = ic_on_range(series, closes, 0, ie, HORIZON_MAIN)
    rec: dict[str, Any] = {
        "expr_id": expr_id(node),
        "text": to_text(node),
        "warmup": warmup(node),
        "insample": {"ic": ins["ic"], "n": ins["n"], "abs_ic": None, "threshold": None},
        "n_trials_at_verdict": int(n_trials),
        "gates_version": gates.version,
        "h24": None,
        "blocks": [],
        "sign_agreement": None,
        "turnover_proxy": None,
        "decay": None,
        "max_rho_vs_survivors": None,
        "cleared_null": False,
        "verdict": "refused",
    }
    if ins["ic"] is None:
        return rec
    ic = float(ins["ic"])
    threshold = deflated_threshold(int(ins["n"]), int(n_trials), kappa=gates.kappa, q=gates.q)
    rec["insample"].update({"abs_ic": _r(abs(ic)), "threshold": _r(threshold)})
    rec["cleared_null"] = abs(ic) > threshold

    h24 = ic_on_range(series, closes, 0, ie, HORIZON_REPORT)
    rec["h24"] = {"ic": h24["ic"], "n": h24["n"], "n_eff": h24.get("n_eff")}
    blocks = []
    agree = printable = 0
    for a, b in sp.blocks:
        r = ic_on_range(series, closes, a, b, HORIZON_MAIN)
        blocks.append({"start": a, "end": b, "ic": r["ic"], "n": r["n"]})
        if r["ic"] is not None:
            printable += 1
            agree += (r["ic"] > 0) == (ic > 0)
    rec["blocks"] = blocks
    rec["sign_agreement"] = {"agree": agree, "printable": printable}
    unstable = printable >= 2 and agree < math.ceil(printable / 2)
    rec["turnover_proxy"] = self_corr_lag1(list(series[:ie]))
    rec["decay"] = decay_for(list(series[:ie]), closes[:ie], DECAY_LAGS)

    max_rho = None
    if rec["cleared_null"] and survivors:
        for _sid, other in survivors:
            xs, ys = _pairs(series[:ie], list(other[:ie]))
            if len(xs) < gates.min_ic_pairs:
                continue
            rho = spearman_rank_ic(xs, ys)
            if rho is not None and (max_rho is None or abs(rho) > max_rho):
                max_rho = abs(rho)
        rec["max_rho_vs_survivors"] = _r(max_rho)

    if not rec["cleared_null"]:
        rec["verdict"] = "noise"
    elif max_rho is not None and max_rho > REDUNDANCY_RHO:
        rec["verdict"] = "redundant"
    elif unstable:
        rec["verdict"] = "unstable"
    else:
        rec["verdict"] = "candidate"
    return rec


def holdout_ic(series: Sequence[float | None], closes: Sequence[float], sp: Split) -> dict[str, Any]:
    """The single holdout statistic: ``ic_for`` at horizon 1 on holdout rows
    (factor values from the full series, forward returns inside the holdout)."""
    return ic_on_range(series, closes, sp.holdout_start, sp.n, HORIZON_MAIN)


def fee_after(
    series: Sequence[float | None],
    rows: Sequence[Sequence[float]],
    sp: Split,
    sign: float,
    *,
    cost_grid: Sequence[float] = DEFAULT_COST_GRID,
    initial_capital: float = DEFAULT_INITIAL_CAPITAL,
    symbol: str = "X",
) -> dict[str, Any]:
    """Cost grid of a long/flat sign strategy on the holdout bars. ``sign`` is
    the in-sample IC sign (the direction predicted before the holdout was
    touched). ``dies_at_bps`` is the first grid cost at which the net return
    is not positive (``None`` if it never dies on the grid); the label is
    ``standalone`` only when the edge survives twice the default cost."""
    bars = rows_to_bars(rows)[sp.holdout_start:sp.n]
    if len(bars) < 2:
        raise ValueError("holdout needs at least 2 bars")
    offset = sp.holdout_start
    index = {b.timestamp: i for i, b in enumerate(bars)}
    s = 1.0 if sign >= 0 else -1.0

    def weight_fn(ts, sym, history):
        v = series[offset + index[ts]]
        if v is None:
            return None
        return 1.0 if s * float(v) > 0 else 0.0

    grid: list[dict[str, Any]] = []
    dies_at = None
    for c in cost_grid:
        res = run_weight_backtest(
            {symbol: bars}, weight_fn, initial_capital=initial_capital,
            rebalance_every_n_bars=1, cost_bps=float(c), slippage_bps=0.0,
            no_trade_band=0.0, granularity="1h",
        )
        m = compute_metrics(res)
        tr = m.get("total_return")
        grid.append({"cost_bps": float(c), "total_return": _r(tr), "sharpe": _r(m.get("sharpe")),
                     "n_trades": float(len(res.trades))})
        if dies_at is None and (tr is None or tr <= 0.0):
            dies_at = float(c)
    label = "standalone" if (dies_at is None or dies_at > 2.0 * TRADING_COST_BPS) else "feature-only"
    return {"grid": grid, "dies_at_bps": dies_at, "label": label, "n_bars": len(bars),
            "sign": s, "note": _FEE_NOTE}
