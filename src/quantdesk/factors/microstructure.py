"""High-frequency microstructure factors — computed from order book + trades.

Sources (formula provenance in docs/FACTOR_VERDICTS.md):
- Micro-price: Stoikov (2017), "The micro-price" (arXiv 1708.03135) — the
  imbalance-weighted fair price; its deviation from mid predicts the next
  mid move direction over seconds-to-minutes.
- Queue imbalance at BBO: Gould & Bonart (2016) — best-level size imbalance
  predicts the next mid move; predictive power dies within ~2 mid changes.
- Order-book slope / multi-level pressure: depth-weighted imbalance across
  levels (Cont-Kukanov-Stoikov impact framework; MLOFI lineage).
- Trade-flow imbalance / CVD: signed taker volume (Silantyev 2019 found TFI
  outperforms OFI on crypto LOBs).
- Snapshot-diff OFI: Cont-Kukanov-Stoikov (2014, arXiv 1011.6402) e_n terms
  approximated from consecutive top-of-book snapshots (throttled top-of-book
  snapshot feeds -- the common case for public WebSocket data -- are NOT
  event-level; this is the honest approximation).

USE-CLASS HONESTY (per the verified fee arithmetic): at 60-120bps/side these
are NEVER standalone alpha — horizon is seconds-to-minutes, capturable edge is
single-digit bps. They are (a) execution-layer timing for maker placement,
(b) hour-aggregated regime FEATURES, (c) Rank-IC pipeline candidates. Label
them as such wherever displayed.

Pure stdlib; inputs are venue-normalized shapes: orderbook {bids:[[px,sz],...], asks:[[px,sz],...]} and trades
[{price, size, side}, ...]. Every function returns None/{} on bad input.
"""
from __future__ import annotations

from typing import Any, Sequence


def _levels(book: dict, side: str, n: int) -> list[tuple[float, float]]:
    out = []
    for lvl in (book.get(side) or [])[:n]:
        try:
            px, sz = float(lvl[0]), float(lvl[1])
        except (TypeError, ValueError, IndexError):
            continue
        if px > 0 and sz >= 0:
            out.append((px, sz))
    return out


# --------------------------------------------------------------------------- #
# Book-shape factors
# --------------------------------------------------------------------------- #
def micro_price(book: dict) -> dict[str, float] | None:
    """Stoikov micro-price: P_micro = (P_ask*Q_bid + P_bid*Q_ask)/(Q_bid+Q_ask).

    The size-imbalance-weighted mid — when bids are heavy the fair price sits
    nearer the ask. Returns micro, mid, and the deviation in bps (positive =
    micro above mid = short-horizon upward pressure)."""
    bids, asks = _levels(book, "bids", 1), _levels(book, "asks", 1)
    if not bids or not asks:
        return None
    (pb, qb), (pa, qa) = bids[0], asks[0]
    if qb + qa <= 0 or pa <= 0 or pb <= 0 or pa < pb:
        return None
    mid = (pa + pb) / 2.0
    micro = (pa * qb + pb * qa) / (qb + qa)
    return {"micro": micro, "mid": mid,
            "deviation_bps": (micro - mid) / mid * 1e4}


def queue_imbalance(book: dict) -> float | None:
    """BBO queue imbalance I = (Q_bid - Q_ask)/(Q_bid + Q_ask) in [-1, 1]
    (Gould-Bonart). Positive = bid queue heavier = next mid move up more
    likely. Decays within ~2 mid changes — positioning signal, not prediction."""
    bids, asks = _levels(book, "bids", 1), _levels(book, "asks", 1)
    if not bids or not asks:
        return None
    qb, qa = bids[0][1], asks[0][1]
    return (qb - qa) / (qb + qa) if (qb + qa) > 0 else None


def book_pressure(book: dict, n: int = 10, decay: float = 0.5) -> dict[str, float] | None:
    """Multi-level depth imbalance with geometric distance decay.

    pressure = sum_i w_i*(bid_sz_i - ask_sz_i) / sum_i w_i*(bid_sz_i + ask_sz_i),
    w_i = decay^i — near levels dominate (deep quotes are cheap to fake).
    Also returns the plain top-n depth ratio for comparison."""
    bids, asks = _levels(book, "bids", n), _levels(book, "asks", n)
    if not bids or not asks:
        return None
    num = den = 0.0
    for i in range(max(len(bids), len(asks))):
        w = decay ** i
        qb = bids[i][1] if i < len(bids) else 0.0
        qa = asks[i][1] if i < len(asks) else 0.0
        num += w * (qb - qa)
        den += w * (qb + qa)
    if den <= 0:
        return None
    depth_b = sum(q for _, q in bids)
    depth_a = sum(q for _, q in asks)
    return {"pressure": num / den,
            "depth_ratio": depth_b / (depth_b + depth_a) if depth_b + depth_a > 0 else 0.5}


def spread_bps(book: dict) -> float | None:
    """Relative bid-ask spread in bps — the instantaneous cost-of-immediacy.
    An execution-layer input: cross only when the signal beats the spread."""
    bids, asks = _levels(book, "bids", 1), _levels(book, "asks", 1)
    if not bids or not asks or bids[0][0] <= 0:
        return None
    return (asks[0][0] - bids[0][0]) / bids[0][0] * 1e4


def snapshot_ofi(prev: dict, curr: dict, n: int = 1) -> float | None:
    """Snapshot-diff Order Flow Imbalance (CKS 2014, snapshot approximation).

    Per side: bid contributes +ΔQ_bid if bid price >= previous (adds/holds),
    else -previous depth (level lost); mirrored for asks. Positive = net
    buying pressure between snapshots. HONESTY: a throttled snapshot feed
    yields the snapshot-diff approximation, never the event-level e_n --
    do not present it as exact CKS."""
    pb, cb = _levels(prev, "bids", n), _levels(curr, "bids", n)
    pa, ca = _levels(prev, "asks", n), _levels(curr, "asks", n)
    if not (pb and cb and pa and ca):
        return None
    ofi = 0.0
    # bid side
    if cb[0][0] > pb[0][0]:
        ofi += cb[0][1]
    elif cb[0][0] == pb[0][0]:
        ofi += cb[0][1] - pb[0][1]
    else:
        ofi -= pb[0][1]
    # ask side (mirror)
    if ca[0][0] < pa[0][0]:
        ofi -= ca[0][1]
    elif ca[0][0] == pa[0][0]:
        ofi -= ca[0][1] - pa[0][1]
    else:
        ofi += pa[0][1]
    return ofi


# --------------------------------------------------------------------------- #
# Trade-flow factors
# --------------------------------------------------------------------------- #
def _signed(trades: Sequence[dict]) -> list[float]:
    out = []
    for t in trades:
        try:
            sz = float(t.get("size") or 0.0)
        except (TypeError, ValueError):
            continue
        side = str(t.get("side") or "").lower()
        if sz <= 0:
            continue
        if side in ("buy", "b", "bid"):
            out.append(sz)
        elif side in ("sell", "s", "ask"):
            out.append(-sz)
    return out


def trade_flow(trades: Sequence[dict]) -> dict[str, float] | None:
    """Trade-flow imbalance family (TFI — Silantyev: beats OFI on crypto).

    tfi        : net signed volume / gross volume, in [-1, 1]
    cvd        : net signed volume (cumulative volume delta over the window)
    accel      : TFI(second half) - TFI(first half) — flow acceleration
    intensity  : trade count (activity clock proxy)
    large_share: fraction of gross volume from trades > 3x mean size
                 (institutional-print proxy)."""
    signed = _signed(trades)
    if not signed:
        return None
    gross = sum(abs(s) for s in signed)
    if gross <= 0:
        return None
    half = len(signed) // 2
    def _tfi(seg: list[float]) -> float:
        g = sum(abs(s) for s in seg)
        return (sum(seg) / g) if g > 0 else 0.0
    mean_sz = gross / len(signed)
    large = sum(abs(s) for s in signed if abs(s) > 3.0 * mean_sz)
    return {
        "tfi": sum(signed) / gross,
        "cvd": sum(signed),
        "accel": _tfi(signed[half:]) - _tfi(signed[:half]) if half >= 1 else 0.0,
        "intensity": float(len(signed)),
        "large_share": large / gross,
    }


def kyle_lambda_proxy(trades: Sequence[dict]) -> float | None:
    """Price-impact proxy (Kyle's lambda flavor): |first->last price move| per
    unit of gross volume, in bps per unit. High = thin/illiquid tape (Amihud
    intuition at trade frequency). Execution-layer input: size down when high."""
    px = []
    gross = 0.0
    for t in trades:
        try:
            p, s = float(t.get("price") or 0), float(t.get("size") or 0)
        except (TypeError, ValueError):
            continue
        if p > 0 and s > 0:
            px.append(p)
            gross += s
    if len(px) < 2 or gross <= 0 or px[0] <= 0:
        return None
    return abs(px[-1] - px[0]) / px[0] * 1e4 / gross


def microstructure_bundle(book: dict, trades: Sequence[dict]) -> dict[str, Any]:
    """One-call bundle for a board: every factor, failure-isolated.
    USE-CLASS: execution-timing / hour-aggregated features — never standalone
    alpha at 60-120bps/side (documented in module docstring)."""
    out: dict[str, Any] = {}
    try:
        mp = micro_price(book)
        if mp:
            out["micro_dev_bps"] = round(mp["deviation_bps"], 3)
        qi = queue_imbalance(book)
        if qi is not None:
            out["queue_imbalance"] = round(qi, 3)
        bp = book_pressure(book)
        if bp:
            out["book_pressure"] = round(bp["pressure"], 3)
            out["depth_ratio"] = round(bp["depth_ratio"], 3)
        sp = spread_bps(book)
        if sp is not None:
            out["spread_bps"] = round(sp, 3)
    except Exception:  # noqa: BLE001 — book factors independent of flow factors
        pass
    try:
        tf = trade_flow(trades)
        if tf:
            out["tfi"] = round(tf["tfi"], 3)
            out["flow_accel"] = round(tf["accel"], 3)
            out["large_share"] = round(tf["large_share"], 3)
            out["intensity"] = tf["intensity"]
        kl = kyle_lambda_proxy(trades)
        if kl is not None:
            out["impact_bps_per_unit"] = round(kl, 4)
    except Exception:  # noqa: BLE001
        pass
    return out
