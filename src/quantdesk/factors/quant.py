"""Pure statistical context functions for the quant tools.

Each function is deterministic, takes plain numbers, and returns a flat dict.
Callers wire these to their own data source; the flat dicts are meant to be
consumed as structured evidence by whatever sits downstream.

Convention: time series are oldest → newest. The last element is "current".
"""
from __future__ import annotations

import math
import statistics
from typing import Any


# ---------- shared helpers ----------


def _percentile_rank(distribution: list[float], value: float) -> float:
    """Midpoint percentile rank of `value` in `distribution`, tolerant to FP noise.

    Definition: (# strictly below + 0.5 × # equal) / N, where "equal" uses a
    1e-9 relative tolerance. Without the tolerance, identical-by-construction
    rolling stats can differ by ULPs and a 50th-percentile event reads as 0.0
    or 1.0, flipping the regime label.
    """
    if not distribution:
        return 0.5
    scale = max(abs(value), max(abs(x) for x in distribution), 1e-12)
    tol = scale * 1e-9
    below = sum(1 for x in distribution if x < value - tol)
    equal = sum(1 for x in distribution if abs(x - value) <= tol)
    return (below + 0.5 * equal) / len(distribution)


def _zscore(distribution: list[float], value: float) -> float | None:
    if len(distribution) < 2:
        return None
    mu = statistics.fmean(distribution)
    sd = statistics.stdev(distribution)
    if sd == 0:
        return None
    return (value - mu) / sd


def _zscore_label(z: float | None) -> str:
    if z is None:
        return "insufficient_data"
    if z >= 2.0:
        return "extremely_high"
    if z >= 1.0:
        return "high"
    if z <= -2.0:
        return "extremely_low"
    if z <= -1.0:
        return "low"
    return "neutral"


# ---------- 1. Multi-horizon momentum z-score ----------


def _rolling_returns(closes: list[float], horizon: int) -> list[float]:
    """Returns over a sliding window of `horizon` bars. Length = len(closes) - horizon."""
    return [
        (closes[i + horizon] / closes[i]) - 1.0
        for i in range(len(closes) - horizon)
        if closes[i] > 0
    ]


def momentum_zscores(
    closes: list[float],
    horizons: list[int],
    lookback: int,
) -> dict[str, Any]:
    """For each horizon h, compute the current h-bar return and z-score it
    against rolling h-bar returns over the trailing `lookback` bars.

    Returns a flat dict with one entry per horizon plus diagnostic counts.
    Insufficient data per horizon is reported, not silently dropped.
    """
    out: dict[str, Any] = {"lookback_bars": lookback, "horizons": {}}
    if len(closes) < 2:
        out["error"] = "insufficient_closes"
        return out

    for h in horizons:
        key = f"{h}b"
        # Need at least h+1 bars to compute the current return,
        # and ideally lookback rolling samples to z-score it.
        if len(closes) < h + 1:
            out["horizons"][key] = {"error": "insufficient_data", "bars_needed": h + 1}
            continue
        current = (closes[-1] / closes[-1 - h]) - 1.0 if closes[-1 - h] > 0 else 0.0
        # Distribution of h-bar returns excluding the current one to avoid self-counting.
        sample_window = closes[-(lookback + h + 1) :]
        all_rolling = _rolling_returns(sample_window, h)
        # Drop the most recent (the current return) so the distribution is "history".
        history = all_rolling[:-1] if all_rolling else []
        z = _zscore(history, current)
        pct = _percentile_rank(history, current)
        out["horizons"][key] = {
            "return_pct": round(current * 100.0, 4),
            "zscore": round(z, 3) if z is not None else None,
            "percentile": round(pct, 3),
            "samples": len(history),
            "label": _zscore_label(z),
        }
    return out


# ---------- 2. Volatility regime ----------


def _annualization_factor(periods_per_year: int) -> float:
    return math.sqrt(periods_per_year)


def _rolling_realized_vol(closes: list[float], window: int) -> list[float]:
    """Per-bar log-return std over a rolling `window`. Length = len(closes) - window."""
    if len(closes) < window + 1:
        return []
    log_returns = [
        math.log(closes[i] / closes[i - 1])
        for i in range(1, len(closes))
        if closes[i - 1] > 0 and closes[i] > 0
    ]
    out: list[float] = []
    for end in range(window, len(log_returns) + 1):
        chunk = log_returns[end - window : end]
        if len(chunk) >= 2:
            out.append(statistics.stdev(chunk))
    return out


def _vol_regime_label(percentile: float) -> str:
    if percentile >= 0.90:
        return "extreme"
    if percentile >= 0.70:
        return "elevated"
    if percentile >= 0.30:
        return "normal"
    if percentile >= 0.10:
        return "compressed"
    return "extremely_compressed"


def volatility_regime(
    closes: list[float],
    vol_window: int,
    lookback: int,
    periods_per_year: int,
) -> dict[str, Any]:
    """Realized volatility now vs trailing distribution.

    `vol_window`: bars used for each realized-vol estimate.
    `lookback`: bars of vol history to compare against.
    `periods_per_year`: annualization (e.g. 365 for daily crypto).
    """
    rolling_vols = _rolling_realized_vol(closes, vol_window)
    if not rolling_vols:
        return {"error": "insufficient_data", "bars_needed": vol_window + 1}

    current = rolling_vols[-1]
    history = rolling_vols[-(lookback + 1) : -1] if len(rolling_vols) > 1 else []
    af = _annualization_factor(periods_per_year)

    pct = _percentile_rank(history, current) if history else 0.5
    z = _zscore(history, current)
    vol_of_vol = (
        statistics.stdev(history) / statistics.fmean(history)
        if len(history) >= 2 and statistics.fmean(history) > 0
        else 0.0
    )

    return {
        "vol_window_bars": vol_window,
        "lookback_bars": len(history),
        "current_vol_annual_pct": round(current * af * 100.0, 3),
        "median_vol_annual_pct": (
            round(statistics.median(history) * af * 100.0, 3) if history else None
        ),
        "percentile": round(pct, 3),
        "zscore": round(z, 3) if z is not None else None,
        "vol_of_vol": round(vol_of_vol, 3),
        "regime": _vol_regime_label(pct) if history else "insufficient_history",
    }


# ---------- 3. Funding rate z-score ----------


def _funding_regime_label(percentile: float) -> str:
    if percentile >= 0.95:
        return "extremely_positive"
    if percentile >= 0.80:
        return "positive"
    if percentile <= 0.05:
        return "extremely_negative"
    if percentile <= 0.20:
        return "negative"
    return "neutral"


def funding_zscore_summary(
    rates: list[float],
    funding_intervals_per_year: int = 365 * 3,  # USDT-perp settles every 8h → 3/day
) -> dict[str, Any]:
    """Funding rate context. `rates` oldest → newest; last entry is current.

    Returns current value, z-score / percentile vs history, and an annualized
    funding cost. Annualization assumes 3 settlements per day (USDT-perp standard).
    """
    if not rates:
        return {"error": "insufficient_data"}
    current = rates[-1]
    history = rates[:-1]
    z = _zscore(history, current)
    pct = _percentile_rank(history, current) if history else 0.5
    annualized_pct = current * funding_intervals_per_year * 100.0
    return {
        "samples": len(history),
        "current_funding_rate": round(current, 8),
        "current_funding_annual_pct": round(annualized_pct, 3),
        "median_funding_rate": (
            round(statistics.median(history), 8) if history else None
        ),
        "zscore": round(z, 3) if z is not None else None,
        "percentile": round(pct, 3),
        "regime": _funding_regime_label(pct) if history else "insufficient_history",
    }
