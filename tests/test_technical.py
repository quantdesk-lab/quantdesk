from __future__ import annotations

from quantdesk.factors.technical import (
    candles_to_technical,
    orderbook_to_summary,
    portfolio_to_contexts,
    trades_to_summary,
)


def test_portfolio_to_contexts_basic_weights() -> None:
    positions = [
        {"symbol": "BTCUSDT", "quantity": 0.05},
        {"symbol": "ETHUSDT", "quantity": 2.0},
    ]
    tickers = {
        "BTCUSDT": {"lastPr": "100000", "change24h": "0.0675"},
        "ETHUSDT": {"lastPr": "2500", "change24h": "-0.0120"},
    }
    out = portfolio_to_contexts(positions, tickers)
    # BTC value = 5000, ETH value = 5000, total = 10000. Each 50%.
    assert out["BTCUSDT"]["value_usdt"] == 5000.0
    assert out["ETHUSDT"]["value_usdt"] == 5000.0
    assert out["BTCUSDT"]["weight_pct"] == 50.0
    assert out["ETHUSDT"]["weight_pct"] == 50.0
    # change_24h_pct surfaced from ticker (venue returns decimal -> we x 100)
    assert out["BTCUSDT"]["change_24h_pct"] == 6.75
    assert out["ETHUSDT"]["change_24h_pct"] == -1.20


def test_portfolio_to_contexts_missing_ticker_is_zero_and_omits_change() -> None:
    positions = [{"symbol": "WEIRDUSDT", "quantity": 100}]
    out = portfolio_to_contexts(positions, {})
    assert out["WEIRDUSDT"]["value_usdt"] == 0.0
    assert out["WEIRDUSDT"]["weight_pct"] == 0.0
    assert "change_24h_pct" not in out["WEIRDUSDT"]


def test_portfolio_to_contexts_empty_inputs() -> None:
    assert portfolio_to_contexts([], {}) == {}


def test_orderbook_to_summary_bid_heavy() -> None:
    # 3 bid levels total qty 30, 3 ask levels total qty 10 -> pressure 0.75
    ob = {
        "bids": [["100", "10"], ["99", "10"], ["98", "10"]],
        "asks": [["101", "4"], ["102", "3"], ["103", "3"]],
    }
    s = orderbook_to_summary(ob, top_n=3)
    assert s["bid_depth"] == 30.0
    assert s["ask_depth"] == 10.0
    assert s["pressure_ratio"] == 0.75
    assert s["top_bid"] == 100.0
    assert s["top_ask"] == 101.0


def test_orderbook_to_summary_empty_side_returns_empty() -> None:
    assert orderbook_to_summary({"bids": [], "asks": [["100", "1"]]}) == {}


def test_trades_to_summary_aggressive_split() -> None:
    trades = [
        {"size": "1", "side": "buy"},
        {"size": "1", "side": "buy"},
        {"size": "2", "side": "sell"},
    ]
    s = trades_to_summary(trades)
    assert s["aggressive_buy_pct"] == 50.0
    assert s["aggressive_sell_pct"] == 50.0
    assert s["trades_used"] == 3


def test_trades_to_summary_large_trades_flagged() -> None:
    # avg = 1.0, large threshold = 3.0; one trade at size 10 should be flagged.
    trades = [{"size": "1", "side": "buy"}] * 9 + [{"size": "10", "side": "sell"}]
    s = trades_to_summary(trades)
    assert s["large_trades_count"] == 1


def test_candles_to_technical_change_and_rsi_consistency() -> None:
    # Monotonically rising closes -> change_pct > 0, rsi close to 100.
    n = 30
    candles = [[i, 100 + i - 0.5, 100 + i + 0.5, 100 + i - 1, 100 + i, 10, 1000] for i in range(n)]
    s = candles_to_technical(candles)
    assert s["change_pct"] > 0
    assert s["rsi_14"] is not None and s["rsi_14"] > 90  # rising -> RSI near 100


def test_candles_to_technical_insufficient_data_returns_empty() -> None:
    assert candles_to_technical([]) == {}
    assert candles_to_technical([[0, 1, 1, 1, 1, 0, 0]]) == {}


def test_candles_to_technical_rsi_none_when_too_short() -> None:
    # Only 10 candles; need 15 for RSI(14).
    candles = [[i, i, i + 1, i - 1, i + 0.5, 1, 10] for i in range(10)]
    s = candles_to_technical(candles)
    assert s["rsi_14"] is None


# ---------- EMA 9/21 cross tests ----------


def test_ema_cross_bullish_on_rising_series() -> None:
    # Rising closes: EMA-9 > EMA-21 => bullish trend
    candles = [[i, 100 + i, 101 + i, 99 + i, 100 + i, 10, 1000] for i in range(40)]
    s = candles_to_technical(candles)
    assert s["ema_trend"] == "bullish"
    assert s["ema_9"] is not None and s["ema_21"] is not None
    assert s["ema_9"] > s["ema_21"]


def test_ema_cross_bearish_on_falling_series() -> None:
    # Falling closes: EMA-9 < EMA-21 => bearish
    candles = [[i, 200 - i, 201 - i, 199 - i, 200 - i, 10, 1000] for i in range(40)]
    s = candles_to_technical(candles)
    assert s["ema_trend"] == "bearish"
    assert s["ema_9"] < s["ema_21"]


def test_ema_golden_cross_flagged_on_recent_reversal() -> None:
    # 22 flat candles (EMAs stacked), then a sharp 3-candle spike ->
    # fast EMA crosses above slow within the lookback window => "golden".
    flat = [100.0] * 22
    spike = [110.0, 120.0, 130.0]
    closes = flat + spike
    candles = [[i, c, c + 0.5, c - 0.5, c, 10, 1000] for i, c in enumerate(closes)]
    s = candles_to_technical(candles)
    assert s["ema_recent_cross"] == "golden"
    assert s["ema_trend"] == "bullish"


def test_ema_fields_none_when_insufficient_candles() -> None:
    # Fewer than slow(21)+1 = 22 candles => EMA fields should be None
    candles = [[i, 100, 101, 99, 100, 10, 1000] for i in range(20)]
    s = candles_to_technical(candles)
    assert s["ema_9"] is None
    assert s["ema_21"] is None
    assert s["ema_trend"] is None
    assert s["ema_recent_cross"] is None


# ---------- CVD tests ----------


def test_cvd_positive_when_buys_dominate() -> None:
    trades = [{"size": "2", "side": "buy"}] * 10 + [{"size": "1", "side": "sell"}] * 5
    s = trades_to_summary(trades)
    # 20 buy - 5 sell = +15 net volume
    assert s["cvd"] == 15.0
    assert s["cvd_normalized"] > 0


def test_cvd_negative_when_sells_dominate() -> None:
    trades = [{"size": "1", "side": "buy"}] * 3 + [{"size": "5", "side": "sell"}] * 4
    s = trades_to_summary(trades)
    # 3 buy - 20 sell = -17
    assert s["cvd"] == -17.0
    assert s["cvd_normalized"] < 0


def test_cvd_zero_when_perfectly_balanced() -> None:
    trades = [{"size": "1", "side": "buy"}, {"size": "1", "side": "sell"}]
    s = trades_to_summary(trades)
    assert s["cvd"] == 0.0
