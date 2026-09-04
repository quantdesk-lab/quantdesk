"""Time-series momentum and volatility factor library -- one implementation of the
signal math shared by every consumer.

Replaces the retail SMA-cross/RSI baseline with methodology from the canonical
literature, every constant traceable to its source:

- Time-series momentum with ex-ante vol scaling:
    Moskowitz, Ooi & Pedersen (2012), "Time Series Momentum", JFE 104(2)
    (sign of trailing return; position = sigma_target / sigma_t, EWMA vol).
- Crypto parameter choices follow Harvey et al. (2022), "An Investor's Guide
  to Crypto", Journal of Portfolio Management 49(1): EWMA vol on ZERO-MEAN
  squared returns, fast com=5d + slow com=180d averaged, estimate LAGGED t-2
  (footnotes 20/24/25), lookbacks {22, 65, 261}d, 22d+261d blend. The paper's
  own gross-of-fees performance exhibits are not reproduced here.
- Range-based volatility: Yang & Zhang (2000) J.Business 73(3)
  (V = V_o + k·V_c + (1-k)·V_RS, k = 0.34/(1.34+(n+1)/(n-1)));
  Rogers & Satchell (1991) — drift-independent, the 24/7-crypto workhorse.
- Score→confidence and robust scoring: Grinold & Kahn, Active Portfolio
  Management 2e (alpha = IC·vol·score; z-scores winsorized at ±3, MAD scale).

Conventions (mistakes here are the classic implementation bugs):
- Crypto trades 24/7: annualize DAILY bars with 365, HOURLY with 8760 — never 252.
- Log returns for signal/vol math (additive => sqrt-time scaling is coherent).
- EWMA is the zero-mean population form seeded with the mean of the first
  `seed_n` squared returns; lambda = com/(com+1) (CENTER-OF-MASS convention —
  not half-life, not span; mislabeling stretches the window ~2.4x).
- Vol used at decision time t is estimated through t-2 (Harvey et al. (2022)): sizing must
  never depend on the bar being traded into.
- Insufficient history fails to ("uncertain", low confidence),
  never to a default trade.

Pure stdlib (math/statistics). Imported by both the backtest plane
(quantdesk/backtest/signals.py) and the research board so every consumer
shares one implementation.
"""
from __future__ import annotations

import math
import statistics
from typing import Any, Sequence

# ---- constants (sources in the docstring) ----------------------------------
PPY_DAILY = 365            # crypto trades 24/7
PPY_HOURLY = 24 * 365
COM_FAST_D = 5.0           # Harvey et al. (2022) fast EWMA center-of-mass (days)
COM_SLOW_D = 180.0         # Harvey et al. (2022) slow EWMA center-of-mass (days)
TSMOM_LOOKBACKS = (22, 65, 261)   # Harvey et al. (2022) 1m/3m/12m weekday-count windows
TSMOM_BLEND = {22: 0.5, 261: 0.5}  # momAvg(22d,261d) — Exhibit 11 winner; 65d logged only
VOL_FLOOR_ANN = 0.05       # sigma floor: no division blow-ups after quiet regimes
SEED_N = 20                # EWMA seed: mean of first 20 squared returns
THETA = 0.15               # score deadband (hysteresis against 120-240bps round trips)
VOL_OVERHEAT_RATIO = 1.25  # fast/slow vol ratio marking an overheated trend
MIN_BARS_DAILY = 263       # 261d lookback + 1 + t-2 lag
CONF_FLOOR, CONF_DIR_BASE, CONF_DIR_SPAN = 0.30, 0.50, 0.45  # calibrated to frozen gates
WINSOR_Z = 3.0             # Grinold-Kahn ±3 clip
MAD_CONSISTENCY = 1.4826   # MAD -> stdev consistency constant (normal)


def _log_returns(closes: Sequence[float]) -> list[float]:
    out = []
    for i in range(1, len(closes)):
        a, b = closes[i - 1], closes[i]
        if a > 0 and b > 0:
            out.append(math.log(b / a))
    return out


# --------------------------------------------------------------------------- #
# EWMA volatility (Harvey et al. (2022) / RiskMetrics zero-mean form)
# --------------------------------------------------------------------------- #
def ewma_vol_annual(
    closes: Sequence[float],
    *,
    com: float,
    ppy: int,
    seed_n: int = SEED_N,
) -> float | None:
    """Annualized EWMA vol of log returns. lambda = com/(com+1) (center of mass).

    Zero-mean squared returns (Harvey et al. (2022) footnote 24: demeaning short crypto
    windows injects mean-estimation noise). Seeded with the plain mean of the
    first `seed_n` squared returns (population form — no n-1 correction; a
    sample-variance seed would bias the small-sample start high). Returns None
    below warmup — callers must fail to uncertain, not to a default.
    """
    rets = _log_returns(closes)
    if len(rets) < seed_n + 1:
        return None
    lam = com / (com + 1.0)
    v = statistics.fmean(r * r for r in rets[:seed_n])
    for r in rets[seed_n:]:
        v = lam * v + (1.0 - lam) * r * r
    return math.sqrt(v * ppy)


# --------------------------------------------------------------------------- #
# Range-based (OHLC) volatility — Yang-Zhang / Rogers-Satchell
# --------------------------------------------------------------------------- #
def rogers_satchell_var(opens, highs, lows, closes) -> float | None:
    """Per-bar Rogers-Satchell variance (drift-independent), NOT annualized.
    Terms are NOT demeaned and average with 1/n (demeaning RS is the classic
    implementation bug — Yang-Zhang 2000 / Molnar 2012)."""
    n = len(closes)
    if n < 2 or not (len(opens) == len(highs) == len(lows) == n):
        return None
    total = 0.0
    for o, h, l, c in zip(opens, highs, lows, closes):
        if min(o, h, l, c) <= 0 or h < max(o, c) or l > min(o, c):
            return None  # bad bar: fail closed rather than silently skew
        u = math.log(h / o)
        d = math.log(l / o)
        cc = math.log(c / o)
        total += u * (u - cc) + d * (d - cc)
    return total / n


def yang_zhang_vol_annual(opens, highs, lows, closes, *, ppy: int) -> float | None:
    """Yang-Zhang (2000) annualized vol over the whole window.

    V = V_o + k·V_c + (1-k)·V_RS with k = 0.34/(1.34 + (n+1)/(n-1)).
    V_o (close->open gap) and V_c (open->close) are DEMEANED sample variances
    (n-1); V_RS is the 1/n Rogers-Satchell term. On 24/7 crypto the gap term is
    ~0 (open == prev close) and YZ degenerates toward the RS blend — kept
    because it harmlessly captures data holes / outage gaps. `n` in k is the
    WINDOW LENGTH, never periods-per-year."""
    n = len(closes)
    if n < 3 or not (len(opens) == len(highs) == len(lows) == n):
        return None
    o_terms, c_terms = [], []
    for i in range(1, n):
        if min(opens[i], closes[i - 1], closes[i]) <= 0:
            return None
        o_terms.append(math.log(opens[i] / closes[i - 1]))
        c_terms.append(math.log(closes[i] / opens[i]))
    rs = rogers_satchell_var(opens[1:], highs[1:], lows[1:], closes[1:])
    if rs is None:
        return None
    m = len(o_terms)  # = n-1 effective bars
    if m < 2:
        return None
    v_o = statistics.variance(o_terms)
    v_c = statistics.variance(c_terms)
    k = 0.34 / (1.34 + (m + 1) / (m - 1))
    var = v_o + k * v_c + (1.0 - k) * rs
    if var <= 0:
        return None
    return math.sqrt(var * ppy)


# --------------------------------------------------------------------------- #
# Robust cross-sectional scoring (Grinold-Kahn)
# --------------------------------------------------------------------------- #
def winsorize(x: float, lo: float = -WINSOR_Z, hi: float = WINSOR_Z) -> float:
    return min(hi, max(lo, x))


def robust_zscores(values: Sequence[float]) -> list[float]:
    """Cross-sectional z with median/MAD location-scale (Grinold-Kahn ch.10-11
    refinement), winsorized ONCE at ±3 (no re-standardize loop). MAD scale uses
    the 1.4826 normal-consistency constant; degenerate MAD falls back to sample
    stdev; a fully degenerate cross-section returns all zeros. For N<5 a
    unit-variance rank score is statistically saner — callers choose."""
    n = len(values)
    if n < 2:
        return [0.0] * n
    med = statistics.median(values)
    mad = statistics.median(abs(v - med) for v in values)
    scale = MAD_CONSISTENCY * mad
    if scale < 1e-12:
        try:
            scale = statistics.stdev(values)  # ddof=1 everywhere by convention
        except statistics.StatisticsError:
            scale = 0.0
    if scale < 1e-12:
        return [0.0] * n
    return [winsorize((v - med) / scale) for v in values]


def rank_scores(values: Sequence[float]) -> list[float]:
    """Unit-variance rank scores (N<5 fallback): (rank - (N+1)/2)/sqrt((N²-1)/12)."""
    n = len(values)
    if n < 2:
        return [0.0] * n
    order = sorted(range(n), key=lambda i: values[i])
    ranks = [0.0] * n
    for pos, idx in enumerate(order, start=1):
        ranks[idx] = float(pos)
    denom = math.sqrt((n * n - 1) / 12.0)
    return [(r - (n + 1) / 2.0) / denom for r in ranks]


def ewma_beta(
    asset_rets: Sequence[float],
    bench_rets: Sequence[float],
    *,
    halflife: float = 60.0,
    shrink_to_one: float = 1.0 / 3.0,
    lo: float = 0.0,
    hi: float = 3.0,
    min_obs: int = 90,
) -> float:
    """EWMA regression beta vs a benchmark (Two Sigma Factor Lens recipe),
    Vasicek/Blume-shrunk toward 1 and clamped — a bad beta poisons every
    downstream residual. Returns 1.0 when history is insufficient (fail-safe:
    residual defaults to market-neutral-nothing rather than a fake tilt)."""
    n = min(len(asset_rets), len(bench_rets))
    if n < min_obs:
        return 1.0
    lam = 0.5 ** (1.0 / halflife)
    cov = var = 0.0
    seeded = False
    for i in range(n):
        a, b = asset_rets[i], bench_rets[i]
        if not seeded:
            cov, var, seeded = a * b, b * b, True
            continue
        cov = lam * cov + (1 - lam) * a * b
        var = lam * var + (1 - lam) * b * b
    if var <= 1e-18:
        return 1.0
    raw = cov / var
    return min(hi, max(lo, (1 - shrink_to_one) * raw + shrink_to_one * 1.0))


# --------------------------------------------------------------------------- #
# TSMOM core (MOP 2012 direction x Harvey et al. (2022) vol machinery)
# --------------------------------------------------------------------------- #
def tsmom_score(closes: Sequence[float], *, ppy: int = PPY_DAILY) -> dict[str, Any]:
    """Multi-horizon vol-normalized trend score in [-1, 1] + diagnostics.

    For L in {22, 65, 261}: z_L = ln(P_t/P_{t-L}) / (sigma_used * sqrt(L/ppy)),
    s_L = tanh(z_L / 2); blend S = 0.5*s_22 + 0.5*s_261 (65d computed and
    logged for the Rank-IC pipeline, not blended — Harvey et al. (2022) Exhibit 11).
    sigma_used = mean of fast(com 5) and slow(com 180) annualized EWMA vols,
    estimated on closes THROUGH t-2 (t-2 lag), floored at 5% annualized.
    Deterministic pure function of its prefix — no state, no lookahead.
    """
    n = len(closes)
    if n < MIN_BARS_DAILY:
        return {"ok": False, "n": n, "need": MIN_BARS_DAILY}
    vol_closes = closes[:-2]  # t-2 lag: sizing never sees the decision bar
    sf = ewma_vol_annual(vol_closes, com=COM_FAST_D, ppy=ppy)
    ss = ewma_vol_annual(vol_closes, com=COM_SLOW_D, ppy=ppy)
    if sf is None or ss is None:
        return {"ok": False, "n": n, "need": MIN_BARS_DAILY}
    sigma = max(VOL_FLOOR_ANN, 0.5 * (sf + ss))
    s: dict[int, float] = {}
    for lb in TSMOM_LOOKBACKS:
        p0, p1 = closes[-1 - lb], closes[-1]
        if p0 <= 0 or p1 <= 0:
            return {"ok": False, "n": n, "need": MIN_BARS_DAILY}
        r = math.log(p1 / p0)
        z = r / (sigma * math.sqrt(lb / ppy))
        s[lb] = math.tanh(z / 2.0)
    score = sum(TSMOM_BLEND[lb] * s[lb] for lb in TSMOM_BLEND)
    return {
        "ok": True, "n": n,
        "score": score, "s22": s[22], "s65": s[65], "s261": s[261],
        "sigma_ann": sigma, "sigma_fast": sf, "sigma_slow": ss,
        "vol_ratio": (sf / ss) if ss > 0 else 1.0,
    }


def target_weight(score: float, sigma_ann: float, *, sigma_target: float = 0.10) -> float:
    """MOP position rule on long/flat spot: w = clip(S * target/sigma, 0, 1).
    10% target is the Harvey et al. (2022) crypto calibration — at crypto vol it holds ~1/8
    notional, passively shrinking fee load ~8x (footnote 25). The target never
    changes Sharpe, only notional/fees (sweeping it 'for Sharpe' = broken harness)."""
    if sigma_ann <= 0:
        return 0.0
    return min(1.0, max(0.0, score * sigma_target / sigma_ann))


def tsmom_regime(closes: Sequence[float], *, ppy: int = PPY_DAILY) -> dict[str, Any]:
    """Map the TSMOM state onto the market-state vocabulary + confidence.

    The mapping (theta = THETA deadband, vr = fast/slow vol ratio):
      S >= theta AND vr > VOL_OVERHEAT_RATIO -> high_volatility_event (trend, overheated)
      S >= theta                             -> trend_up
      S <= -theta                            -> trend_down
      s261 < 0 AND s22 >= theta              -> range_bound (base-building: slow window
                                                still bearish, fast window positive)
      otherwise                              -> range_bound (|S| inside the deadband)
      insufficient history                   -> uncertain at CONF_FLOOR
    Confidence: the first four branches are directional, 0.50 + 0.45*min(|S|, 1)
    (the 0.70 high-confidence gate needs |S| >= 0.44; the 0.50 medium gate is met
    at any |S|, so the base-building branch reaches an action -- the policy table
    answers range_bound with target_weight_30 -- even when |S| is small). The
    deadband branch is capped below 0.50 (CONF_FLOOR + 0.19*(1 - |S|/theta)), so
    a measured no-trend never crosses an action gate. RSI gates are deliberately
    NOT mixed back in: horizon disagreement (s22 vs s261) plus the vol ratio
    provide the overbought/capitulation structure with provenance.
    """
    d = tsmom_score(closes, ppy=ppy)
    if not d.get("ok"):
        return {
            "regime": "uncertain", "confidence": CONF_FLOOR,
            "why": (f"insufficient daily history ({d.get('n', 0)}/"
                    f"{d.get('need', MIN_BARS_DAILY)} bars): "
                    "261d lookback + t-2 lag not met"),
            "diag": d,
        }
    S, s22, s261, vr = d["score"], d["s22"], d["s261"], d["vol_ratio"]
    sigma = d["sigma_ann"]
    base = (f"TSMOM {S:+.2f} (22d {s22:+.2f} / 261d {s261:+.2f}); "
            f"sigma {sigma:.0%}; fast/slow vol ratio {vr:.2f}")
    # State/action vocabulary: states carry no action. S <= -theta is
    # trend_down, and vol overheat is its own risk-off state.
    if S >= THETA and vr > VOL_OVERHEAT_RATIO:
        regime = "high_volatility_event"
        why = (base + " - trend positive but fast/slow vol ratio overheated "
               "(vol targeting is shrinking the position)")
    elif S >= THETA:
        regime = "trend_up"
        why = base + " - two-window blended trend positive (MOP 2012 direction, momAvg blend)"
    elif S <= -THETA:
        regime = "trend_down"
        why = base + " - two-window blended trend negative"
    elif s261 < 0.0 and s22 >= THETA:
        regime = "range_bound"
        why = (base + " - slow window still bearish, fast window turned positive: "
               "base-building range structure")
    else:
        regime = "range_bound"
        why = (base + f" - |S| inside the {THETA} deadband: no measured trend; "
               "confidence capped below the action gates")
        conf = CONF_FLOOR + 0.19 * (1.0 - min(abs(S), THETA) / THETA)
        return {"regime": regime, "confidence": round(conf, 2), "why": why, "diag": d}
    conf = CONF_DIR_BASE + CONF_DIR_SPAN * min(abs(S), 1.0)
    return {"regime": regime, "confidence": round(conf, 2), "why": why, "diag": d}
