from __future__ import annotations

import math

from .config import PERIODS_PER_YEAR, RF_ANNUAL
from .types import BacktestResult


def _returns(equity: list[float]) -> list[float]:
    return [
        (equity[i] / equity[i - 1]) - 1.0
        for i in range(1, len(equity))
        if equity[i - 1] > 0
    ]


def _mean(xs: list[float]) -> float:
    return sum(xs) / len(xs) if xs else 0.0


def _stdev(xs: list[float]) -> float:
    if len(xs) < 2:
        return 0.0
    m = _mean(xs)
    return math.sqrt(sum((x - m) ** 2 for x in xs) / (len(xs) - 1))


def max_drawdown(equity: list[float]) -> float:
    """Return the worst peak-to-trough drawdown as a negative fraction."""
    peak = -math.inf
    mdd = 0.0
    for v in equity:
        if v > peak:
            peak = v
        if peak > 0:
            dd = (v - peak) / peak
            if dd < mdd:
                mdd = dd
    return mdd


def compute_metrics(result: BacktestResult) -> dict[str, float]:
    eq = [v for _, v in result.equity_curve]
    if len(eq) < 2 or eq[0] <= 0:
        return {}
    rets = _returns(eq)
    pyear = PERIODS_PER_YEAR.get(result.granularity, 365)

    total_return = eq[-1] / eq[0] - 1.0
    n_periods = len(eq) - 1
    cagr = (eq[-1] / eq[0]) ** (pyear / n_periods) - 1.0 if n_periods > 0 and eq[-1] > 0 else 0.0

    mu = _mean(rets) * pyear
    sigma = _stdev(rets) * math.sqrt(pyear)
    excess = mu - RF_ANNUAL
    sharpe = excess / sigma if sigma > 0 else 0.0

    downside = [r for r in rets if r < 0]
    dn_sigma = _stdev(downside) * math.sqrt(pyear) if len(downside) >= 2 else 0.0
    sortino = excess / dn_sigma if dn_sigma > 0 else 0.0

    mdd = max_drawdown(eq)
    calmar = cagr / abs(mdd) if mdd < 0 else 0.0

    avg_eq = _mean(eq)
    turnover = (
        sum(abs(t.delta_qty) * t.price for t in result.trades) / avg_eq
        if avg_eq > 0
        else 0.0
    )

    return {
        "total_return": total_return,
        "cagr": cagr,
        "ann_vol": sigma,
        "sharpe": sharpe,
        "sortino": sortino,
        "max_drawdown": mdd,
        "calmar": calmar,
        "n_trades": float(len(result.trades)),
        "turnover": turnover,
        "n_bars": float(len(eq)),
    }


def spearman_rank_ic(scores: list[float], fwd_returns: list[float]) -> float | None:
    """Spearman rank correlation between factor scores and forward returns —
    the Rank-IC of docs/RESEARCH_DISCIPLINE.md (0.02-0.05 = institutionally
    good; anything much higher is presumed leakage until proven otherwise).
    Midrank ties; None below 3 pairs or on degenerate (constant) inputs."""
    n = min(len(scores), len(fwd_returns))
    if n < 3:
        return None

    def _midranks(values: list[float]) -> list[float]:
        order = sorted(range(n), key=lambda i: values[i])
        ranks = [0.0] * n
        i = 0
        while i < n:
            j = i
            while j + 1 < n and values[order[j + 1]] == values[order[i]]:
                j += 1
            mid = (i + j) / 2.0 + 1.0
            for k in range(i, j + 1):
                ranks[order[k]] = mid
            i = j + 1
        return ranks

    rx = _midranks(list(scores[:n]))
    ry = _midranks(list(fwd_returns[:n]))
    mx = sum(rx) / n
    my = sum(ry) / n
    cov = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    vx = sum((a - mx) ** 2 for a in rx)
    vy = sum((b - my) ** 2 for b in ry)
    if vx <= 0 or vy <= 0:
        return None  # constant ranks: correlation undefined
    return cov / (vx * vy) ** 0.5
