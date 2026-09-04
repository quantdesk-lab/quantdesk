from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from quantdesk.backtest.signals import (
    buy_and_hold,
    momentum_signal,
    random_signal,
    replay_decisions,
)
from quantdesk.backtest.types import Bar


def _series(prices: list[float]) -> list[Bar]:
    t0 = datetime(2024, 1, 1, tzinfo=timezone.utc)
    return [
        Bar(t0 + timedelta(days=i), p, p, p, p, 1.0)
        for i, p in enumerate(prices)
    ]


def test_buy_and_hold_always_returns_uncertain_noop():
    sig = buy_and_hold()
    regime, conf = sig(datetime.now(timezone.utc), "X", _series([1.0]))
    assert regime == "uncertain"  # -> maintain: no rebalancing, same as before
    assert conf == 0.0


def test_random_signal_is_deterministic_under_same_seed():
    a = random_signal(seed=7)
    b = random_signal(seed=7)
    bars = _series([1.0, 2.0])
    out_a = [a(bars[-1].timestamp, "X", bars) for _ in range(5)]
    out_b = [b(bars[-1].timestamp, "X", bars) for _ in range(5)]
    assert out_a == out_b


def test_momentum_short_history_falls_back_to_uncertain():
    sig = momentum_signal(short=5, long=20)
    bars = _series(list(range(1, 11)))
    regime, _ = sig(bars[-1].timestamp, "X", bars)
    assert regime == "uncertain"


def test_momentum_strong_uptrend_classifies_as_overheat_event():
    # Monotone increase saturates RSI to 100 -> late_bull_reduce
    sig = momentum_signal(short=5, long=20)
    bars = _series([float(i) for i in range(1, 60)])
    regime, conf = sig(bars[-1].timestamp, "X", bars)
    assert regime == "high_volatility_event"
    assert conf >= 0.6


def test_momentum_strong_downtrend_classifies_as_trend_down():
    sig = momentum_signal(short=5, long=20)
    bars = _series([float(60 - i) for i in range(1, 60)])
    regime, _ = sig(bars[-1].timestamp, "X", bars)
    assert regime in {"range_bound", "uncertain"}


def test_replay_decisions_lookup_by_timestamp_and_symbol(tmp_path):
    ts = datetime(2024, 1, 1, tzinfo=timezone.utc)
    log = [
        {"timestamp": ts.isoformat(), "symbol": "BTCUSDT",
         "regime": "high_volatility_event", "confidence": 0.8},
    ]
    path = tmp_path / "decisions.json"
    path.write_text(json.dumps(log))
    sig = replay_decisions(path)
    regime, conf = sig(ts, "BTCUSDT", _series([1.0]))
    assert regime == "high_volatility_event"
    assert conf == 0.8


def test_replay_decisions_missing_entry_falls_back_to_uncertain(tmp_path):
    path = tmp_path / "decisions.json"
    path.write_text("[]")
    sig = replay_decisions(path)
    regime, conf = sig(datetime(2024, 1, 1, tzinfo=timezone.utc), "BTCUSDT", _series([1.0]))
    assert regime == "uncertain"
    assert conf == 0.0


# ---------- institutional_signal: wired into the CLI, previously untested ----------


def test_institutional_short_history_stays_below_the_action_gate() -> None:
    """No evidence must never cross the 0.6 confidence threshold the policy
    table uses to size a real action."""
    from quantdesk.backtest.signals import institutional_signal

    fn = institutional_signal()
    regime, conf = fn(datetime.now(timezone.utc), "BTCUSDT", _series([100.0 + i for i in range(100)]))
    assert regime == "uncertain"
    assert 0.0 <= conf < 0.6


def test_institutional_long_uptrend_is_directional() -> None:
    from math import exp

    from quantdesk.backtest.signals import institutional_signal

    fn = institutional_signal()
    regime, conf = fn(datetime.now(timezone.utc), "BTCUSDT", _series([100.0 * exp(0.002 * i) for i in range(400)]))
    assert regime in {"trend_up", "high_volatility_event", "range_bound"}
    assert 0.0 <= conf <= 1.0


def test_institutional_falls_back_to_uncertain_when_the_factor_raises(monkeypatch) -> None:
    """A factor-library failure must degrade to 'no opinion', never propagate
    into a trading decision."""
    import quantdesk.factors.tsmom as factors
    from quantdesk.backtest.signals import institutional_signal

    monkeypatch.setattr(factors, "tsmom_regime", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    fn = institutional_signal()
    regime, conf = fn(datetime.now(timezone.utc), "BTCUSDT", _series([100.0 + i for i in range(400)]))
    assert regime == "uncertain"
    assert conf == 0.0
