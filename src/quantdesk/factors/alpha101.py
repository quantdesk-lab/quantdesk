"""Alpha101-style factor engine: 19 formulaic alphas in single-symbol time-series form.

Reference: Zura Kakushadze, "101 Formulaic Alphas", arXiv:1601.00991 (2016);
Wilmott 2016(84), 72-81. The paper states its alphas are proprietary to their
publisher. This module does not reproduce the paper's text, notation or
cross-sectional forms: each docstring and registry entry states the ADAPTED
time-series expression this module actually computes, in this library's own
operator notation, and carries a ``paper_ref`` naming the alpha number so a
reader with the paper can compare. Honest caveat: for the alphas that use no
cross-sectional operator (#6, 9, 12, 23, 24, 41, 43, 53, 54, 101) the
time-series restatement necessarily coincides with the paper's arithmetic up
to the stated proxies (vwap, adv) and guards -- there is only one way to
write "minus the 10-bar correlation of open and volume".

DEPARTURE FROM THE PAPER (stated once, tagged per alpha): the paper's alphas
are cross-sectional -- rank()/scale() operate across thousands of equities at
one instant. A small universe makes that cross-section degenerate (a rank
over a handful of values carries almost no information), so every alpha is
evaluated per-symbol in single-symbol TIME-SERIES form under these global
adaptations:

- A-rank:    rank(x) -> ts_pct_rank via ts_rank(x, RANK_WINDOW=60): trailing
             60-bar percentile rank of the current value, midrank ties,
             output in (0, 1].
- A-scale:   scale(x) (paper: rescale so sum|x| = 1 across the book) ->
             ts_scale(x, SCALE_WINDOW=60) = x_t / mean(|x|) over the trailing
             60 bars (sign-preserving magnitude normalization).
- A-vwap:    spot candles carry no vwap -> proxy (high+low+close)/3
             (typical price), tagged per affected alpha.
- A-adv:     adv{d} (average daily dollar volume) -> sma(volume, d) in base
             units; per-symbol time-series IC is scale-free, so the unit
             change is harmless.
- A-returns: per-bar simple close-to-close return.
- A-bars:    evaluated on CLOSED bars (forming bar dropped); every lookback
             below is a bar count, not days.
- A-guard:   zero/invalid denominator or log(<=0) -> None at that index,
             never an exception.

Notation used in the adapted expressions: ``where(cond, a, b)`` is the
elementwise conditional, ``sma``/``ts_sum``/``ts_min``/``ts_max``/``ts_argmax``/
``ts_rank``/``ts_scale``/``stddev``/``correlation`` are the trailing-window
operators defined below, ``delay``/``delta`` are lags and lag differences,
``x^p`` is a plain power and ``signedpower`` is sign(x) * |x|**p.

HONESTY (docs/RESEARCH_DISCIPLINE.md): at a 60-120bps/side retail fee schedule,
formulaic micro-alphas are NOT standalone-viable -- a 1h-frequency signal
cannot clear a 120-240bps round trip. These series are research observables
for an IC/decay/correlation board, not trading signals; nothing here emits an
action or a recommendation.

Series convention: Series = list[float | None], oldest -> newest, aligned to
the input bars. None marks warmup/invalid; any window containing None ->
None. Element t depends only on elements <= t, so composition is
lookahead-free by construction (proven per-alpha by the prefix-determinism
test in tests/test_alpha101.py).

decay_linear / covariance / ts_argmin are deliberately NOT implemented: the
curated 19 never use them, and speculative operators are dead weight.

Pure stdlib (math/statistics), list-in/list-out -- the quantdesk/factors/tsmom.py
pattern; importable by both the research board and the backtest plane.
"""
from __future__ import annotations

import math
import statistics
from typing import Any, Callable, Sequence

Series = list  # list[float | None], oldest -> newest, aligned to input bars

# ---- constants (adaptations in the module docstring) ------------------------
RANK_WINDOW = 60   # A-rank: trailing percentile-rank window (bars)
SCALE_WINDOW = 60  # A-scale: trailing mean-|x| normalization window (bars)
_EPS = 1e-12       # A-guard: |denominator| below this -> None

_GUARDED = (ValueError, OverflowError, ZeroDivisionError)  # A-guard net


# --------------------------------------------------------------------------- #
# elementwise operators (warmup 0: element t maps element t)
# --------------------------------------------------------------------------- #
def _finite(v: float | None) -> float | None:
    return v if v is not None and math.isfinite(v) else None


def _map1(x: Sequence[float | None], f: Callable[[float], float | None]) -> Series:
    """Apply f elementwise; None propagates, guarded errors become None."""
    out: Series = []
    for v in x:
        if v is None:
            out.append(None)
            continue
        try:
            out.append(_finite(f(v)))
        except _GUARDED:
            out.append(None)
    return out


def _map2(
    x: Sequence[float | None],
    y: Sequence[float | None],
    f: Callable[[float, float], float | None],
) -> Series:
    """Apply f pairwise; None in either input propagates, errors become None."""
    out: Series = []
    for a, b in zip(x, y):
        if a is None or b is None:
            out.append(None)
            continue
        try:
            out.append(_finite(f(a, b)))
        except _GUARDED:
            out.append(None)
    return out


def sign_s(x: Sequence[float | None]) -> Series:
    """Elementwise sign: -1.0 / 0.0 / +1.0."""
    return _map1(x, lambda v: float((v > 0) - (v < 0)))


def abs_s(x: Sequence[float | None]) -> Series:
    """Elementwise absolute value."""
    return _map1(x, abs)


def log_s(x: Sequence[float | None]) -> Series:
    """Elementwise natural log; None on x <= 0 (A-guard)."""
    return _map1(x, lambda v: math.log(v) if v > 0 else None)


def signedpower(x: Sequence[float | None], p: float) -> Series:
    """Sign-preserving power: sign(x) * |x|**p."""
    return _map1(x, lambda v: float((v > 0) - (v < 0)) * abs(v) ** p)


def add_s(x: Sequence[float | None], y: Sequence[float | None]) -> Series:
    return _map2(x, y, lambda a, b: a + b)


def sub_s(x: Sequence[float | None], y: Sequence[float | None]) -> Series:
    return _map2(x, y, lambda a, b: a - b)


def mul_s(x: Sequence[float | None], y: Sequence[float | None]) -> Series:
    return _map2(x, y, lambda a, b: a * b)


def div_s(x: Sequence[float | None], y: Sequence[float | None]) -> Series:
    """Elementwise division; None where |denominator| < 1e-12 (A-guard)."""
    return _map2(x, y, lambda a, b: a / b if abs(b) >= _EPS else None)


def _neg(x: Sequence[float | None]) -> Series:
    """-1 * x — the paper's most-used prefix, worth a private helper."""
    return [None if v is None else -v for v in x]


# --------------------------------------------------------------------------- #
# time-series operators
# Warmup on a clean (None-free) input: delay/delta -> d leading None;
# window ops -> w-1 leading None. None anywhere in a window -> None output.
# --------------------------------------------------------------------------- #
def delay(x: Sequence[float | None], d: int) -> Series:
    """x shifted back d bars: out[t] = x[t-d]; first d entries None."""
    n = len(x)
    return [None if t < d else x[t - d] for t in range(n)]


def delta(x: Sequence[float | None], d: int) -> Series:
    """out[t] = x[t] - x[t-d]; None if either operand is None; first d None."""
    n = len(x)
    out: Series = [None] * n
    for t in range(d, n):
        a, b = x[t], x[t - d]
        if a is not None and b is not None:
            out[t] = a - b
    return out


def _rolling(
    x: Sequence[float | None], w: int, f: Callable[[list], float | None]
) -> Series:
    """Trailing-window map: out[t] = f(x[t-w+1 .. t]); incomplete window or any
    None in the window -> None. Guarded errors become None (A-guard)."""
    n = len(x)
    out: Series = [None] * n
    if w < 1:
        return out
    for t in range(w - 1, n):
        win = list(x[t - w + 1: t + 1])
        if any(v is None for v in win):
            continue
        try:
            out[t] = _finite(f(win))
        except (*_GUARDED, statistics.StatisticsError):
            out[t] = None
    return out


def ts_sum(x: Sequence[float | None], w: int) -> Series:
    """Trailing-window sum over w bars; warmup w-1."""
    return _rolling(x, w, math.fsum)


def sma(x: Sequence[float | None], w: int) -> Series:
    """Trailing simple moving average over w bars; warmup w-1."""
    return _rolling(x, w, lambda win: math.fsum(win) / w)


def ts_min(x: Sequence[float | None], w: int) -> Series:
    """Trailing-window minimum; warmup w-1."""
    return _rolling(x, w, min)


def ts_max(x: Sequence[float | None], w: int) -> Series:
    """Trailing-window maximum; warmup w-1."""
    return _rolling(x, w, max)


def ts_argmax(x: Sequence[float | None], w: int) -> Series:
    """Position of the window max, 1..w with w = max is the CURRENT bar
    (1 = oldest bar in the window; ties -> first/oldest occurrence)."""
    return _rolling(x, w, lambda win: float(win.index(max(win)) + 1))


def ts_rank(x: Sequence[float | None], w: int) -> Series:
    """Trailing percentile rank of x[t] within the last w values.

    Midrank ties: rank = (#less + (#equal + 1)/2) / w, output in (0, 1]
    (strict window max -> 1.0; even an all-tied window stays > 0). This is
    the A-rank stand-in for the paper's cross-sectional rank."""
    def _pct(win: list) -> float:
        cur = win[-1]
        less = sum(1 for v in win if v < cur)
        equal = sum(1 for v in win if v == cur)
        return (less + (equal + 1) / 2.0) / w
    return _rolling(x, w, _pct)


def ts_scale(x: Sequence[float | None], w: int = SCALE_WINDOW) -> Series:
    """A-scale stand-in for the paper's scale(x): x_t / mean(|x|) over the
    trailing w bars (sign-preserving); all-zero window -> None (A-guard)."""
    def _scaled(win: list) -> float | None:
        denom = math.fsum(abs(v) for v in win) / w
        return win[-1] / denom if denom >= _EPS else None
    return _rolling(x, w, _scaled)


def stddev(x: Sequence[float | None], w: int) -> Series:
    """Trailing sample standard deviation (ddof=1 — repo convention); w >= 2."""
    return _rolling(x, w, statistics.stdev)


def correlation(
    x: Sequence[float | None], y: Sequence[float | None], w: int
) -> Series:
    """Rolling Pearson correlation over trailing w bars; None on zero variance
    in either leg (A-guard), clamped to [-1, 1] against float drift."""
    n = min(len(x), len(y))
    out: Series = [None] * n
    if w < 2:
        return out
    for t in range(w - 1, n):
        xs = list(x[t - w + 1: t + 1])
        ys = list(y[t - w + 1: t + 1])
        if any(v is None for v in xs) or any(v is None for v in ys):
            continue
        mx = math.fsum(xs) / w
        my = math.fsum(ys) / w
        sxx = math.fsum((a - mx) ** 2 for a in xs)
        syy = math.fsum((b - my) ** 2 for b in ys)
        if sxx < _EPS or syy < _EPS:
            continue
        sxy = math.fsum((a - mx) * (b - my) for a, b in zip(xs, ys))
        out[t] = max(-1.0, min(1.0, sxy / math.sqrt(sxx * syy)))
    return out


# --------------------------------------------------------------------------- #
# input builders
# --------------------------------------------------------------------------- #
def rank(x: Sequence[float | None], w: int = RANK_WINDOW) -> Series:
    """A-rank: the paper's cross-sectional rank(x) as a trailing time-series
    percentile rank (see module docstring)."""
    return ts_rank(x, w)


def returns(closes: Sequence[float | None]) -> Series:
    """A-returns: per-bar simple close-to-close return r[t] = c[t]/c[t-1] - 1;
    warmup 1; degenerate previous close -> None (A-guard)."""
    n = len(closes)
    out: Series = [None] * n
    for t in range(1, n):
        prev, cur = closes[t - 1], closes[t]
        if prev is None or cur is None or abs(prev) < _EPS:
            continue
        out[t] = cur / prev - 1.0
    return out


def vwap_proxy(
    highs: Sequence[float | None],
    lows: Sequence[float | None],
    closes: Sequence[float | None],
) -> Series:
    """A-vwap: typical price (high+low+close)/3 -- spot candles carry no
    vwap, and the typical price is the standard bar-level stand-in."""
    out: Series = []
    for h, l, c in zip(highs, lows, closes):
        out.append(None if h is None or l is None or c is None else (h + l + c) / 3.0)
    return out


def adv(volumes: Sequence[float | None], d: int) -> Series:
    """A-adv: the paper's adv{d} as sma(volume, d) in base units."""
    return sma(volumes, d)


# --------------------------------------------------------------------------- #
# shared alpha fragments
# --------------------------------------------------------------------------- #
def _accel_per_close(closes: Sequence[float | None]) -> Series:
    """#46/#51 shared acceleration term, DIVIDED BY close (adaptation): the
    paper compares a raw 10-bar acceleration of close against fixed
    thresholds, which is price-scale-dependent; normalizing by close makes
    the thresholds scale-free."""
    d20 = delay(closes, 20)
    d10 = delay(closes, 10)
    n = len(closes)
    out: Series = [None] * n
    for t in range(n):
        a, b, c = d20[t], d10[t], closes[t]
        if a is None or b is None or c is None or abs(c) < _EPS:
            continue
        out[t] = ((a - b) / 10.0 - (b - c) / 10.0) / c
    return out


# --------------------------------------------------------------------------- #
# the 19 alphas -- uniform signature, adapted expression stated per docstring
# --------------------------------------------------------------------------- #
def alpha001(opens, highs, lows, closes, volumes) -> Series:
    """#1 (adapted time-series form):
        ts_rank(ts_argmax(signedpower(where(returns(close) < 0, stddev(returns(close), 20),
        close), 2.0), 5), 60) - 0.5
    [A-rank, A-returns]

    Reversal keyed on where vol-of-losses (down bars) vs price level (up bars)
    peaked in the last 5 bars; the -0.5 centers the (0,1] rank at ~0."""
    ret = returns(closes)
    sd20 = stddev(ret, 20)
    n = len(closes)
    cond: Series = [None] * n
    for t in range(n):
        r = ret[t]
        if r is None:
            continue
        cond[t] = sd20[t] if r < 0 else closes[t]
    rk = rank(ts_argmax(signedpower(cond, 2.0), 5))
    return [None if v is None else v - 0.5 for v in rk]


def alpha002(opens, highs, lows, closes, volumes) -> Series:
    """#2 (adapted time-series form):
        -1 * correlation(ts_rank(delta(log(volume), 2), 60), ts_rank((close - open) / open,
        60), 6)
    [A-rank, A-guard]

    Volume-shock vs intrabar-return divergence over a 6-bar window."""
    r_vol = rank(delta(log_s(volumes), 2))
    r_bar = rank(div_s(sub_s(closes, opens), opens))
    return _neg(correlation(r_vol, r_bar, 6))


def alpha003(opens, highs, lows, closes, volumes) -> Series:
    """#3 (adapted time-series form):
        -1 * correlation(ts_rank(open, 60), ts_rank(volume, 60), 10)
    [A-rank]

    Fade price/volume co-trending: high when open level and volume decouple."""
    return _neg(correlation(rank(opens), rank(volumes), 10))


def alpha004(opens, highs, lows, closes, volumes) -> Series:
    """#4 (adapted time-series form):
        -1 * ts_rank(ts_rank(low, 60), 9)
    [A-rank on the inner rank; the outer ts_rank is native time-series]

    Low-price percentile reversal: recent lows near their 60-bar top rank ->
    most negative output."""
    return _neg(ts_rank(rank(lows), 9))


def alpha005(opens, highs, lows, closes, volumes) -> Series:
    """#5 (adapted time-series form):
        ts_rank(open - sma(vwap, 10), 60) * (-1 * abs(ts_rank(close - vwap, 60))); vwap =
        (high + low + close) / 3
    [A-rank, A-vwap]

    Open-vs-trailing-vwap deviation, damped by how stretched close sits from
    the current bar's vwap proxy."""
    vw = vwap_proxy(highs, lows, closes)
    left = rank(sub_s(opens, sma(vw, 10)))
    right = _neg(abs_s(rank(sub_s(closes, vw))))
    return mul_s(left, right)


def alpha006(opens, highs, lows, closes, volumes) -> Series:
    """#6 (adapted time-series form):
        -1 * correlation(open, volume, 10)
    [no adaptation: already a pure time-series expression]"""
    return _neg(correlation(opens, volumes, 10))


def alpha009(opens, highs, lows, closes, volumes) -> Series:
    """#9 (adapted time-series form):
        where(ts_min(delta(close, 1), 5) > 0 or ts_max(delta(close, 1), 5) < 0, delta(close,
        1), -1 * delta(close, 1))
    [no adaptation]

    Conditional momentum: ride a clean 5-bar run (all deltas one sign),
    fade the last move when the run is mixed."""
    dc = delta(closes, 1)
    lo5 = ts_min(dc, 5)
    hi5 = ts_max(dc, 5)
    n = len(closes)
    out: Series = [None] * n
    for t in range(n):
        d, lo, hi = dc[t], lo5[t], hi5[t]
        if d is None or lo is None or hi is None:
            continue
        out[t] = d if (lo > 0 or hi < 0) else -d
    return out


def alpha012(opens, highs, lows, closes, volumes) -> Series:
    """#12 (adapted time-series form):
        sign(delta(volume, 1)) * (-1 * delta(close, 1))
    [no adaptation]

    Volume-flip reversal: fade the price move when volume rose, follow it
    when volume fell."""
    return mul_s(sign_s(delta(volumes, 1)), _neg(delta(closes, 1)))


def alpha023(opens, highs, lows, closes, volumes) -> Series:
    """#23 (adapted time-series form):
        where(sma(high, 20) < high, -1 * delta(high, 2), 0)
    [no adaptation]

    Breakout fade: only active while the high prints above its 20-bar mean."""
    m20 = sma(highs, 20)
    d2 = delta(highs, 2)
    n = len(closes)
    out: Series = [None] * n
    for t in range(n):
        m, h = m20[t], highs[t]
        if m is None or h is None:
            continue
        if m < h:
            out[t] = None if d2[t] is None else -d2[t]
        else:
            out[t] = 0.0
    return out


def alpha024(opens, highs, lows, closes, volumes) -> Series:
    """#24 (adapted time-series form):
        where(delta(sma(close, 100), 100) / delay(close, 100) <= 0.05, -1 * (close -
        ts_min(close, 100)), -1 * delta(close, 3))
    [no adaptation; the inclusive threshold is implemented as <=]

    Slow-regime reversal: in a flat 100-bar regime fade distance from the
    100-bar low, otherwise fade the 3-bar move."""
    chg = div_s(delta(sma(closes, 100), 100), delay(closes, 100))
    lo100 = ts_min(closes, 100)
    d3 = delta(closes, 3)
    n = len(closes)
    out: Series = [None] * n
    for t in range(n):
        r = chg[t]
        if r is None:
            continue
        if r <= 0.05:
            lo, c = lo100[t], closes[t]
            out[t] = None if lo is None or c is None else -(c - lo)
        else:
            out[t] = None if d3[t] is None else -d3[t]
    return out


def alpha028(opens, highs, lows, closes, volumes) -> Series:
    """#28 (adapted time-series form):
        ts_scale(correlation(sma(volume, 20), low, 5) + (high + low) / 2 - close, 60)
    [A-scale, A-adv]

    Range-midpoint mean reversion, tilted by how the low tracks average
    volume over the last 5 bars."""
    c5 = correlation(adv(volumes, 20), lows, 5)
    mid = _map2(highs, lows, lambda h, l: (h + l) / 2.0)
    return ts_scale(sub_s(add_s(c5, mid), closes))


def alpha032(opens, highs, lows, closes, volumes) -> Series:
    """#32 (adapted time-series form):
        ts_scale(sma(close, 7) - close, 60) + 20 * ts_scale(correlation(vwap, delay(close,
        5), 230), 60); vwap = (high + low + close) / 3
    [A-scale, A-vwap]

    Short mean-reversion leg plus a slow vwap/close lead-lag leg. LOW-N: the
    230-bar correlation + 60-bar scale warmup leaves only ~55 observations on
    a 350-bar feed — consumers must carry n_obs next to any statistic."""
    leg_mr = ts_scale(sub_s(sma(closes, 7), closes))
    vw = vwap_proxy(highs, lows, closes)
    leg_ll = ts_scale(correlation(vw, delay(closes, 5), 230))
    return add_s(leg_mr, [None if v is None else 20.0 * v for v in leg_ll])


def alpha041(opens, highs, lows, closes, volumes) -> Series:
    """#41 (adapted time-series form):
        sqrt(high * low) - vwap; vwap = (high + low + close) / 3
    [A-vwap]

    Geometric bar midpoint minus the vwap proxy — a 1-bar structure read."""
    gm = _map2(highs, lows, lambda h, l: math.sqrt(h * l))
    return sub_s(gm, vwap_proxy(highs, lows, closes))


def alpha043(opens, highs, lows, closes, volumes) -> Series:
    """#43 (adapted time-series form):
        ts_rank(volume / sma(volume, 20), 20) * ts_rank(-1 * delta(close, 7), 8)
    [A-adv; otherwise already a pure time-series expression]

    Volume-surge percentile times 7-bar reversal percentile."""
    surge = ts_rank(div_s(volumes, adv(volumes, 20)), 20)
    rev = ts_rank(_neg(delta(closes, 7)), 8)
    return mul_s(surge, rev)


def alpha046(opens, highs, lows, closes, volumes) -> Series:
    """#46 (adapted time-series form):
        accel = ((delay(close, 20) - delay(close, 10)) / 10 - (delay(close, 10) - close) /
        10) / close; where(accel > 0.25, -1, where(accel < 0, 1, -1 * delta(close, 1)))
    [acceleration term divided by close: fixed thresholds on a raw price difference are
     dollar-scale-dependent; see _accel_per_close]

    Honest note: with close-normalized acceleration the +/-0.25 branch rarely
    fires at 1h crypto scale, so this usually degenerates to -delta(close,1)."""
    accel = _accel_per_close(closes)
    d1 = delta(closes, 1)
    n = len(closes)
    out: Series = [None] * n
    for t in range(n):
        a = accel[t]
        if a is None:
            continue
        if a > 0.25:
            out[t] = -1.0
        elif a < 0:
            out[t] = 1.0
        else:
            out[t] = None if d1[t] is None else -d1[t]
    return out


def alpha051(opens, highs, lows, closes, volumes) -> Series:
    """#51 (adapted time-series form):
        accel as #46; where(accel < -0.05, 1, -1 * delta(close, 1))
    [acceleration normalized by close, exactly as #46]

    #49 is deliberately OMITTED from the curated set: it differs from #51
    only in the threshold, and a near-duplicate would pollute the
    correlation matrix."""
    accel = _accel_per_close(closes)
    d1 = delta(closes, 1)
    n = len(closes)
    out: Series = [None] * n
    for t in range(n):
        a = accel[t]
        if a is None:
            continue
        if a < -0.05:
            out[t] = 1.0
        else:
            out[t] = None if d1[t] is None else -d1[t]
    return out


def alpha053(opens, highs, lows, closes, volumes) -> Series:
    """#53 (adapted time-series form):
        -1 * delta(((close - low) - (high - close)) / (close - low), 9)
    [A-guard: close == low -> None at that index]

    9-bar shift in where the close sits inside the bar's range."""
    pos = []
    for h, l, c in zip(highs, lows, closes):
        if h is None or l is None or c is None or abs(c - l) < _EPS:
            pos.append(None)
        else:
            pos.append(((c - l) - (h - c)) / (c - l))
    return _neg(delta(pos, 9))


def alpha054(opens, highs, lows, closes, volumes) -> Series:
    """#54 (adapted time-series form):
        (-1 * (low - close) * open^5) / ((low - high) * close^5)
    [A-guard: high == low (or degenerate close^5) -> None]

    Bar-body position weighted by open/close level asymmetry — 1-bar read."""
    def _a054(o: float, h: float, l: float, c: float) -> float | None:
        denom = (l - h) * c ** 5
        if abs(denom) < _EPS:
            return None
        return (-1.0 * (l - c) * o ** 5) / denom

    out: Series = []
    for o, h, l, c in zip(opens, highs, lows, closes):
        if o is None or h is None or l is None or c is None:
            out.append(None)
            continue
        try:
            out.append(_finite(_a054(o, h, l, c)))
        except _GUARDED:
            out.append(None)
    return out


def alpha101(opens, highs, lows, closes, volumes) -> Series:
    """#101 (adapted time-series form):
        (close - open) / ((high - low) + 0.001)
    [the 0.001 epsilon is kept: a dollar-scale constant, negligible at high prices and
     harmless at any price]

    Candle-body momentum: signed body over range."""
    out: Series = []
    for o, h, l, c in zip(opens, highs, lows, closes):
        if o is None or h is None or l is None or c is None:
            out.append(None)
        else:
            out.append((c - o) / ((h - l) + 0.001))
    return out


# --------------------------------------------------------------------------- #
# registry -- drives the research board, the payload builder, and the tests.
# lookback = documented worst-case warmup in bars (observed first-valid index
# is asserted <= lookback by tests/test_alpha101.py).
# --------------------------------------------------------------------------- #
ALPHAS: tuple[dict[str, Any], ...] = (
    {"id": "a001", "num": 1, "fn": alpha001, "style": "reversal_vol",
     "formula": ("ts_rank(ts_argmax(signedpower(where(returns(close) < 0, "
                 "stddev(returns(close), 20), close), 2.0), 5), 60) - 0.5"),
     "paper_ref": "Kakushadze (2016), alpha #1",
     "adaptation": "rank->trailing 60-bar pct rank", "lookback": 85},
    {"id": "a002", "num": 2, "fn": alpha002, "style": "volume_price",
     "formula": ("-1 * correlation(ts_rank(delta(log(volume), 2), 60), ts_rank((close - "
                 "open) / open, 60), 6)"),
     "paper_ref": "Kakushadze (2016), alpha #2",
     "adaptation": "rank->trailing 60-bar pct rank; log/div guarded", "lookback": 68},
    {"id": "a003", "num": 3, "fn": alpha003, "style": "volume_price",
     "formula": "-1 * correlation(ts_rank(open, 60), ts_rank(volume, 60), 10)",
     "paper_ref": "Kakushadze (2016), alpha #3",
     "adaptation": "rank->trailing 60-bar pct rank", "lookback": 70},
    {"id": "a004", "num": 4, "fn": alpha004, "style": "reversal",
     "formula": "-1 * ts_rank(ts_rank(low, 60), 9)",
     "paper_ref": "Kakushadze (2016), alpha #4",
     "adaptation": "inner rank->trailing 60-bar pct rank; outer ts_rank native", "lookback": 69},
    {"id": "a005", "num": 5, "fn": alpha005, "style": "vwap_dev",
     "formula": ("ts_rank(open - sma(vwap, 10), 60) * (-1 * abs(ts_rank(close - vwap, "
                 "60))); vwap = (high + low + close) / 3"),
     "paper_ref": "Kakushadze (2016), alpha #5",
     "adaptation": "rank->trailing 60-bar pct rank; vwap->(h+l+c)/3", "lookback": 70},
    {"id": "a006", "num": 6, "fn": alpha006, "style": "volume_price",
     "formula": "-1 * correlation(open, volume, 10)",
     "paper_ref": "Kakushadze (2016), alpha #6",
     "adaptation": "none (pure time-series already)", "lookback": 10},
    {"id": "a009", "num": 9, "fn": alpha009, "style": "cond_momentum",
     "formula": ("where(ts_min(delta(close, 1), 5) > 0 or ts_max(delta(close, 1), 5) < 0, "
                 "delta(close, 1), -1 * delta(close, 1))"),
     "paper_ref": "Kakushadze (2016), alpha #9",
     "adaptation": "none", "lookback": 6},
    {"id": "a012", "num": 12, "fn": alpha012, "style": "volume_flip_reversal",
     "formula": "sign(delta(volume, 1)) * (-1 * delta(close, 1))",
     "paper_ref": "Kakushadze (2016), alpha #12",
     "adaptation": "none", "lookback": 2},
    {"id": "a023", "num": 23, "fn": alpha023, "style": "breakout_fade",
     "formula": "where(sma(high, 20) < high, -1 * delta(high, 2), 0)",
     "paper_ref": "Kakushadze (2016), alpha #23",
     "adaptation": "none", "lookback": 20},
    {"id": "a024", "num": 24, "fn": alpha024, "style": "slow_regime_reversal",
     "formula": ("where(delta(sma(close, 100), 100) / delay(close, 100) <= 0.05, -1 * "
                 "(close - ts_min(close, 100)), -1 * delta(close, 3))"),
     "paper_ref": "Kakushadze (2016), alpha #24",
     "adaptation": "inclusive threshold condition implemented as <= 0.05", "lookback": 200},
    {"id": "a028", "num": 28, "fn": alpha028, "style": "range_mid_mr",
     "formula": "ts_scale(correlation(sma(volume, 20), low, 5) + (high + low) / 2 - close, 60)",
     "paper_ref": "Kakushadze (2016), alpha #28",
     "adaptation": "scale->ts_scale(60); adv20->sma(volume, 20)", "lookback": 85},
    {"id": "a032", "num": 32, "fn": alpha032, "style": "mr_leadlag",
     "formula": ("ts_scale(sma(close, 7) - close, 60) + 20 * ts_scale(correlation(vwap, "
                 "delay(close, 5), 230), 60); vwap = (high + low + close) / 3"),
     "paper_ref": "Kakushadze (2016), alpha #32",
     "adaptation": "scale->ts_scale(60); vwap->(h+l+c)/3; LOW-N ~55 obs on 350 bars",
     "lookback": 295},
    {"id": "a041", "num": 41, "fn": alpha041, "style": "geo_mid_vs_vwap",
     "formula": "sqrt(high * low) - vwap; vwap = (high + low + close) / 3",
     "paper_ref": "Kakushadze (2016), alpha #41",
     "adaptation": "vwap->(h+l+c)/3", "lookback": 1},
    {"id": "a043", "num": 43, "fn": alpha043, "style": "volsurge_x_reversal",
     "formula": "ts_rank(volume / sma(volume, 20), 20) * ts_rank(-1 * delta(close, 7), 8)",
     "paper_ref": "Kakushadze (2016), alpha #43",
     "adaptation": "adv20->sma(volume, 20); pure time-series already", "lookback": 40},
    {"id": "a046", "num": 46, "fn": alpha046, "style": "trend_accel_reversal",
     "formula": ("accel = ((delay(close, 20) - delay(close, 10)) / 10 - (delay(close, 10) "
                 "- close) / 10) / close; where(accel > 0.25, -1, where(accel < 0, 1, -1 * "
                 "delta(close, 1)))"),
     "paper_ref": "Kakushadze (2016), alpha #46",
     "adaptation": "accel divided by close (paper thresholds are dollar-scale); "
                   "branch rarely fires, usually degenerates to -delta(close,1)",
     "lookback": 21},
    {"id": "a051", "num": 51, "fn": alpha051, "style": "trend_accel_reversal",
     "formula": "accel as #46; where(accel < -0.05, 1, -1 * delta(close, 1))",
     "paper_ref": "Kakushadze (2016), alpha #51",
     "adaptation": "accel/close as #46; #49 omitted (near-duplicate, only threshold differs)",
     "lookback": 21},
    {"id": "a053", "num": 53, "fn": alpha053, "style": "intrabar_pos_delta",
     "formula": "-1 * delta(((close - low) - (high - close)) / (close - low), 9)",
     "paper_ref": "Kakushadze (2016), alpha #53",
     "adaptation": "guard close==low -> None", "lookback": 10},
    {"id": "a054", "num": 54, "fn": alpha054, "style": "body_range_pos",
     "formula": "(-1 * (low - close) * open^5) / ((low - high) * close^5)",
     "paper_ref": "Kakushadze (2016), alpha #54",
     "adaptation": "guard high==low -> None", "lookback": 1},
    {"id": "a101", "num": 101, "fn": alpha101, "style": "candle_body_momentum",
     "formula": "(close - open) / ((high - low) + 0.001)",
     "paper_ref": "Kakushadze (2016), alpha #101",
     "adaptation": "0.001 epsilon kept (dollar-scale constant, negligible at high prices)",
     "lookback": 1},
)
