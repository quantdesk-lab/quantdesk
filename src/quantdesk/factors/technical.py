"""Compact technical summaries from ticker / order-book / trade / candle rows.

Pure stdlib. Inputs are the plain venue shapes (dicts and lists of strings or
numbers); every function returns a flat dict and never raises on empty input.
"""
from __future__ import annotations

import statistics
from typing import Any


# ---------- Ticker helpers ----------


def _ticker_price(ticker: dict) -> float:
    # "last"/"close"/"price" are neutral names; "lastPr" is an example of a
    # venue-specific ticker field name and is accepted for convenience.
    for key in ("last", "close", "price", "lastPr"):
        v = ticker.get(key)
        if v:
            try:
                return float(v)
            except (TypeError, ValueError):
                pass
    return 0.0


def _ticker_change_24h_pct(ticker: dict) -> float | None:
    """24h change is expected as a decimal (e.g. 0.0675 for +6.75%). "change_24h"
    is the neutral name; the camelCase keys are example venue field names."""
    for key in ("change_24h", "change24h", "changeUtc24h"):
        v = ticker.get(key)
        if v is None or v == "":
            continue
        try:
            return round(float(v) * 100.0, 4)
        except (TypeError, ValueError):
            pass
    return None


def portfolio_to_contexts(
    positions: list[dict], tickers_by_symbol: dict[str, dict]
) -> dict[str, dict[str, Any]]:
    """Map (positions, per-symbol ticker dict) → per-symbol context.

    Each context includes qty, price_usdt, value_usdt, weight_pct,
    and (if available) change_24h_pct for anomaly-detection heuristics.
    """
    enriched = []
    total_value = 0.0
    for pos in positions:
        sym = pos["symbol"]
        qty = float(pos["quantity"])
        ticker = tickers_by_symbol.get(sym) or {}
        price = _ticker_price(ticker)
        value = qty * price
        total_value += value
        enriched.append((sym, qty, price, value, _ticker_change_24h_pct(ticker)))

    out: dict[str, dict[str, Any]] = {}
    for sym, qty, price, value, change in enriched:
        weight = (value / total_value * 100.0) if total_value else 0.0
        entry: dict[str, Any] = {
            "qty": qty,
            "price_usdt": round(price, 6),
            "value_usdt": round(value, 2),
            "weight_pct": round(weight, 2),
        }
        if change is not None:
            entry["change_24h_pct"] = change
        out[sym] = entry
    return out


# ---------- Orderbook ----------


def orderbook_to_summary(orderbook: dict, top_n: int = 10) -> dict[str, Any]:
    bids = orderbook.get("bids") or []
    asks = orderbook.get("asks") or []
    bids = bids[:top_n]
    asks = asks[:top_n]
    if not bids or not asks:
        return {}
    bid_depth = sum(float(level[1]) for level in bids)
    ask_depth = sum(float(level[1]) for level in asks)
    total = bid_depth + ask_depth
    pressure_ratio = bid_depth / total if total else 0.5
    top_bid = float(bids[0][0])
    top_ask = float(asks[0][0])
    spread_pct = ((top_ask - top_bid) / top_bid * 100.0) if top_bid else 0.0
    return {
        "top_n": top_n,
        "bid_depth": round(bid_depth, 4),
        "ask_depth": round(ask_depth, 4),
        "pressure_ratio": round(pressure_ratio, 3),
        "top_bid": top_bid,
        "top_ask": top_ask,
        "spread_pct": round(spread_pct, 4),
    }


# ---------- Recent trades ----------


def _side_sign(side: str) -> int:
    s = side.lower()
    if s in ("buy", "b", "bid"):
        return 1
    if s in ("sell", "s", "ask"):
        return -1
    return 0


def trades_to_summary(trades: list[dict]) -> dict[str, Any]:
    if not trades:
        return {}
    buy_size = 0.0
    sell_size = 0.0
    sizes: list[float] = []
    signed: list[float] = []
    for t in trades:
        size = float(t.get("size") or t.get("fillQty") or 0.0)
        sign = _side_sign(t.get("side") or "")
        sizes.append(size)
        signed.append(sign * size)
        if sign > 0:
            buy_size += size
        elif sign < 0:
            sell_size += size

    total = buy_size + sell_size
    n = len(sizes)
    avg_size = sum(sizes) / n if n else 0.0
    large_threshold = avg_size * 3.0
    large_count = sum(1 for s in sizes if s > large_threshold)

    # CVD: cumulative volume delta across the trade stream.
    # Positive = net aggressive buying; negative = net aggressive selling.
    cvd = sum(signed)
    cvd_normalized = (cvd / avg_size) if avg_size else 0.0

    return {
        "trades_used": n,
        "aggressive_buy_pct": round(buy_size / total * 100.0, 2) if total else 0.0,
        "aggressive_sell_pct": round(sell_size / total * 100.0, 2) if total else 0.0,
        "avg_trade_size": round(avg_size, 4),
        "large_trades_count": large_count,
        "cvd": round(cvd, 4),
        "cvd_normalized": round(cvd_normalized, 3),
    }


# ---------- Candle technicals ----------


def _rsi_wilder(closes: list[float], period: int = 14) -> float | None:
    if len(closes) < period + 1:
        return None
    gains: list[float] = []
    losses: list[float] = []
    for i in range(1, len(closes)):
        diff = closes[i] - closes[i - 1]
        gains.append(max(diff, 0.0))
        losses.append(max(-diff, 0.0))
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    for g, l in zip(gains[period:], losses[period:]):
        avg_gain = (avg_gain * (period - 1) + g) / period
        avg_loss = (avg_loss * (period - 1) + l) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - 100.0 / (1.0 + rs)


def _ema(series: list[float], period: int) -> list[float]:
    """Standard EMA: seeded with SMA of first `period` values, then recursive."""
    if len(series) < period:
        return []
    k = 2.0 / (period + 1)
    ema_series = [sum(series[:period]) / period]
    for i in range(period, len(series)):
        ema_series.append(series[i] * k + ema_series[-1] * (1 - k))
    return ema_series


def _ema_cross_state(closes: list[float], fast: int = 9, slow: int = 21) -> dict[str, Any]:
    """Returns current EMA values and cross state.

    `state`: 'bullish' (fast > slow), 'bearish' (fast < slow), 'flat' (equal), or None.
    `recent_cross`: 'golden' / 'death' if the sign flipped within the last 3 candles, else None.
    """
    if len(closes) < slow + 1:
        return {"ema_fast": None, "ema_slow": None, "state": None, "recent_cross": None}

    ema_fast_series = _ema(closes, fast)
    ema_slow_series = _ema(closes, slow)
    # Align tails to the same length (they are of length len(closes)-fast+1 and len(closes)-slow+1).
    tail_len = min(len(ema_fast_series), len(ema_slow_series))
    ema_fast_tail = ema_fast_series[-tail_len:]
    ema_slow_tail = ema_slow_series[-tail_len:]

    fast_last = ema_fast_tail[-1]
    slow_last = ema_slow_tail[-1]
    if fast_last > slow_last:
        state = "bullish"
    elif fast_last < slow_last:
        state = "bearish"
    else:
        state = "flat"

    recent_cross = None
    lookback = min(5, tail_len - 1)
    for i in range(1, lookback + 1):
        prev_fast, prev_slow = ema_fast_tail[-(i + 1)], ema_slow_tail[-(i + 1)]
        cur_fast, cur_slow = ema_fast_tail[-i], ema_slow_tail[-i]
        if prev_fast <= prev_slow and cur_fast > cur_slow:
            recent_cross = "golden"
            break
        if prev_fast >= prev_slow and cur_fast < cur_slow:
            recent_cross = "death"
            break

    return {
        "ema_fast": round(fast_last, 6),
        "ema_slow": round(slow_last, 6),
        "state": state,
        "recent_cross": recent_cross,
    }


def candles_to_technical(candles: list[list]) -> dict[str, Any]:
    """Venue candle row: [ts, open, high, low, close, baseVol, quoteVol]. Old → new."""
    if not candles or len(candles) < 2:
        return {}
    closes = [float(c[4]) for c in candles]
    highs = [float(c[2]) for c in candles]
    lows = [float(c[3]) for c in candles]

    first_close = closes[0]
    last_close = closes[-1]
    change_pct = ((last_close - first_close) / first_close * 100.0) if first_close else 0.0

    lo = min(lows)
    hi = max(highs)
    range_pct = ((hi - lo) / lo * 100.0) if lo else 0.0

    returns = [
        (closes[i] - closes[i - 1]) / closes[i - 1]
        for i in range(1, len(closes))
        if closes[i - 1]
    ]
    realized_vol_pct = (statistics.pstdev(returns) * 100.0) if len(returns) > 1 else 0.0

    rsi = _rsi_wilder(closes, period=14)
    ema = _ema_cross_state(closes, fast=9, slow=21)

    return {
        "candles_used": len(candles),
        "first_close": first_close,
        "last_close": last_close,
        "change_pct": round(change_pct, 2),
        "range_pct": round(range_pct, 2),
        "realized_vol_pct": round(realized_vol_pct, 3),
        "rsi_14": round(rsi, 2) if rsi is not None else None,
        "ema_9": ema["ema_fast"],
        "ema_21": ema["ema_slow"],
        "ema_trend": ema["state"],
        "ema_recent_cross": ema["recent_cross"],
    }
