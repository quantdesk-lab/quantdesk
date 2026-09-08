"""Empirical null band for the factor board's Rank-IC column.

Illustrative calibration: every registered alpha is evaluated on ``n_reseeds``
independent synthetic random walks (seeded GBM bars, no drift, no structure)
and its time-series Rank-IC is computed with the research board's own
``ic_for`` - the identical gate-protected code path the board uses on real
series. Because the walks carry no information, every |IC| that comes out is
pure sampling noise; the percentiles of that distribution are the band a
real factor must clear before its IC means anything.

The output is the site's ``null.json``::

    {n_reseeds, bars, horizon, timeframe,
     alphas: [{id, num, abs_ic_p50, abs_ic_p95, abs_ic_max, n, n_pairs_median}],
     pooled: {p50, p95, p99, n}, samples: [[abs_ic, n], ...], note}

``samples`` lists every printable |IC| with its pair count; the search
loop's gate calibration (``quantdesk.search.gates``) reads it to check the
analytic null scale ``1/sqrt(n-1)`` against these walks.

Reading it: with ``n`` independent pairs, the null Spearman correlation has a
standard deviation near ``1/sqrt(n-1)`` whatever the factor's own
autocorrelation (the forward returns are iid under the null), so at ~300
pairs the pooled 95th percentile sits near 0.11 and long-warmup alphas (fewer
pairs) sit higher. Anything a real factor reports inside this band is
indistinguishable from noise. Pure stdlib; synthetic data only.
"""
from __future__ import annotations

import math
from typing import Any, Sequence

from quantdesk.demo.fixtures import gbm_bars, split_ohlcv
from quantdesk.factors.alpha101 import ALPHAS
from quantdesk.research.board import ic_for

_NOTE = (
    "Empirical null: |Rank-IC| of every alpha on N reseeded random walks. Anything a "
    "real factor reports inside this band is indistinguishable from noise."
)

_TIMEFRAME_SECONDS = {"1h": 3600, "1d": 86400}


def percentile(values: Sequence[float], q: float) -> float | None:
    """Linear-interpolation percentile (``q`` in [0, 100]) of a non-empty
    sequence; ``None`` when empty. Illustrative stdlib helper."""
    xs = sorted(float(v) for v in values)
    if not xs:
        return None
    if not 0.0 <= q <= 100.0:
        raise ValueError("q must be in [0, 100]")
    if len(xs) == 1:
        return xs[0]
    pos = (len(xs) - 1) * q / 100.0
    lo = math.floor(pos)
    hi = min(lo + 1, len(xs) - 1)
    frac = pos - lo
    return xs[lo] + (xs[hi] - xs[lo]) * frac


def alpha_ics_on_walk(
    bars: int,
    *,
    seed: int,
    horizon: int = 1,
    timeframe: str = "1h",
    sigma: float = 0.01,
) -> dict[str, dict[str, Any]]:
    """Every alpha's ``ic_for`` row on ONE synthetic random walk of ``bars``
    bars: ``{alpha_id: {"ic": float | None, "n": int, ...}}``. Illustrative."""
    if timeframe not in _TIMEFRAME_SECONDS:
        raise ValueError(f"timeframe must be one of {tuple(_TIMEFRAME_SECONDS)}")
    rows = gbm_bars(bars, seed=seed, bar_seconds=_TIMEFRAME_SECONDS[timeframe], sigma=sigma)
    cols = split_ohlcv(rows)
    o, h, l, c, v = cols["o"], cols["h"], cols["l"], cols["c"], cols["v"]
    out: dict[str, dict[str, Any]] = {}
    for entry in ALPHAS:
        try:
            series = entry["fn"](o, h, l, c, v)
        except Exception:  # noqa: BLE001 - one dead alpha must not kill the calibration
            series = [None] * len(c)
        out[entry["id"]] = ic_for(series, c, horizon)
    return out


def null_ic_distribution(
    n_reseeds: int = 20,
    bars: int = 350,
    *,
    horizon: int = 1,
    seed0: int = 1000,
    timeframe: str = "1h",
    sigma: float = 0.01,
) -> dict[str, Any]:
    """The ``null.json`` document: |Rank-IC| percentiles of every alpha over
    ``n_reseeds`` independent synthetic random walks of ``bars`` bars each
    (seeds ``seed0 .. seed0 + n_reseeds - 1``), plus the pooled distribution.

    ICs the board's honesty gates refuse (too few pairs, degenerate ranks)
    are simply absent from the sample - ``n`` per alpha says how many walks
    produced a printable IC. Deterministic for fixed arguments; synthetic
    data only, no venue data involved.
    """
    if n_reseeds <= 0:
        raise ValueError("n_reseeds must be > 0")
    if bars < 2:
        raise ValueError("bars must be >= 2")
    if horizon < 1:
        raise ValueError("horizon must be >= 1")
    per_alpha: dict[str, list[float]] = {e["id"]: [] for e in ALPHAS}
    pairs: dict[str, list[int]] = {e["id"]: [] for e in ALPHAS}
    pooled: list[float] = []
    samples: list[list[float]] = []  # [abs_ic, n] per printable IC: feeds the search gates
    for k in range(n_reseeds):
        rows = alpha_ics_on_walk(
            bars, seed=seed0 + k, horizon=horizon, timeframe=timeframe, sigma=sigma)
        for aid, r in rows.items():
            pairs[aid].append(int(r["n"]))
            ic = r.get("ic")
            if ic is None:
                continue
            per_alpha[aid].append(abs(float(ic)))
            pooled.append(abs(float(ic)))
            samples.append([round(abs(float(ic)), 6), int(r["n"])])
    alphas: list[dict[str, Any]] = []
    for entry in ALPHAS:
        aid = entry["id"]
        xs = per_alpha[aid]
        alphas.append({
            "id": aid,
            "num": entry["num"],
            "abs_ic_p50": _r(percentile(xs, 50)),
            "abs_ic_p95": _r(percentile(xs, 95)),
            "abs_ic_max": _r(max(xs)) if xs else None,
            "n": len(xs),
            "n_pairs_median": _r(percentile(pairs[aid], 50), 1),
        })
    return {
        "n_reseeds": int(n_reseeds),
        "bars": int(bars),
        "horizon": int(horizon),
        "timeframe": timeframe,
        "alphas": alphas,
        "pooled": {
            "p50": _r(percentile(pooled, 50)),
            "p95": _r(percentile(pooled, 95)),
            "p99": _r(percentile(pooled, 99)),
            "n": len(pooled),
        },
        "samples": samples,
        "note": _NOTE,
    }


def _r(v: float | None, nd: int = 4) -> float | None:
    return round(float(v), nd) if v is not None else None
