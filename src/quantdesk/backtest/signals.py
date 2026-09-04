from __future__ import annotations

import json
import random
from datetime import datetime, timezone
from pathlib import Path

from .types import Bar, SignalFn

_REGIMES = (
    "trend_up",
    "trend_down",
    "range_bound",
    "high_volatility_event",
    "uncertain",
)


def buy_and_hold() -> SignalFn:
    """Always returns trend_up at low confidence -> maintain. Equivalent to no rebalancing."""
    def fn(ts: datetime, symbol: str, history: list[Bar]) -> tuple[str, float]:
        return ("uncertain", 0.0)
    return fn


def random_signal(seed: int = 0) -> SignalFn:
    """Pure-noise baseline. Useful to confirm an alpha signal beats coin-flips."""
    rng = random.Random(seed)

    def fn(ts: datetime, symbol: str, history: list[Bar]) -> tuple[str, float]:
        return (rng.choice(_REGIMES), rng.uniform(0.5, 0.95))
    return fn


def _sma(values: list[float], n: int) -> float | None:
    if len(values) < n:
        return None
    return sum(values[-n:]) / n


def _rsi(values: list[float], n: int = 14) -> float | None:
    if len(values) < n + 1:
        return None
    gains = 0.0
    losses = 0.0
    for i in range(-n, 0):
        d = values[i] - values[i - 1]
        if d > 0:
            gains += d
        else:
            losses -= d
    if losses == 0:
        return 100.0
    rs = (gains / n) / (losses / n)
    return 100.0 - (100.0 / (1.0 + rs))


def momentum_signal(
    short: int = 20,
    long: int = 80,
    rsi_overbought: float = 75.0,
    rsi_oversold: float = 25.0,
) -> SignalFn:
    """Rule-based regime classifier. A sanity baseline, not a trading edge.

    Mapping:
      RSI ≥ overbought         → high_volatility_event (overheat risk-off)
      RSI ≤ oversold AND below long-MA → range_bound (base-building)
      short-MA > long-MA       → trend_up
      short-MA < long-MA       → trend_down
      else / not enough bars   → uncertain
    """
    def fn(ts: datetime, symbol: str, history: list[Bar]) -> tuple[str, float]:
        closes = [b.close for b in history]
        if len(closes) < long + 1:
            return ("uncertain", 0.3)
        s_short = _sma(closes, short)
        s_long = _sma(closes, long)
        rsi = _rsi(closes, 14)
        last = closes[-1]
        if rsi is not None and rsi >= rsi_overbought:
            conf = min(0.95, 0.6 + (rsi - rsi_overbought) / 100.0)
            return ("high_volatility_event", conf)
        if rsi is not None and rsi <= rsi_oversold and s_long is not None and last < s_long:
            conf = min(0.95, 0.6 + (rsi_oversold - rsi) / 100.0)
            return ("range_bound", conf)
        if s_short is not None and s_long is not None and s_short > s_long:
            return ("trend_up", 0.7)
        if s_short is not None and s_long is not None and s_short < s_long:
            return ("trend_down", 0.6)
        return ("uncertain", 0.4)
    return fn


def institutional_signal(ppy: int = 365) -> SignalFn:
    """Vol-scaled multi-horizon TSMOM (MOP 2012 direction; Harvey et al. (2022) crypto
    calibration: EWMA fast com=5 + slow com=180 averaged, t-2 lag, 22d+261d
    blend). Thin adapter over quantdesk/factors/tsmom.py -- the same shared
    implementation the research board reads, so the two paths cannot
    diverge. Keep `momentum_signal` beside it as the
    naive baseline for A/B. Designed for DAILY bars (needs >=263); shorter
    histories fail to uncertain -> hold, never to a default trade."""
    from ..factors.tsmom import tsmom_regime

    def fn(ts: datetime, symbol: str, history: list[Bar]) -> tuple[str, float]:
        try:
            rr = tsmom_regime([b.close for b in history], ppy=ppy)
            return (rr["regime"], rr["confidence"])
        except Exception:
            return ("uncertain", 0.0)  # hygiene: fail-to-uncertain
    return fn


def tsmom_weight(sigma_target: float = 0.10, ppy: int = 365):
    """FAITHFUL vol-scaled TSMOM target-weight strategy (WeightFn).

    w = clip(S * sigma_target / sigma_t, 0, 1) — MOP 2012 position rule with
    the Harvey et al. (2022) crypto calibration (10% target; at crypto vol it holds ~1/8
    notional, passively cutting fee load ~8x). Runs through
    run_weight_backtest, which the discrete 4-regime path cannot express.
    Returns None (no view -> hold) below the 263-bar warmup."""
    from ..factors.tsmom import target_weight, tsmom_score

    def fn(ts: datetime, symbol: str, history: list[Bar]) -> float | None:
        d = tsmom_score([b.close for b in history], ppy=ppy)
        if not d.get("ok"):
            return None
        return target_weight(d["score"], d["sigma_ann"], sigma_target=sigma_target)
    return fn


_DOLLAR_QUOTES = ("USDT", "USDC")


def _canonical_symbol(symbol: str) -> str:
    """Cross-venue product-id shim, used ONLY for replay lookup.

    The lake speaks dash-separated product ids ("BTC-USD"); other candle
    sources speak "BTCUSDT"-style symbols. A decision recorded against
    one must replay against bars keyed by the other, so both sides are
    canonicalized: uppercase, separators (- _ /) dropped, and the stablecoin
    dollar quotes USDT/USDC collapsed to USD — "BTC-USD", "BTCUSDT" and
    "BTC-USDC" all become "BTCUSD". Deliberate adaptation: the USD-vs-USDT
    quote distinction is erased here and nowhere else; different base assets
    can never collide.
    """
    s = symbol.upper().replace("-", "").replace("_", "").replace("/", "")
    for quote in _DOLLAR_QUOTES:
        if s.endswith(quote):
            s = s[: -len(quote)] + "USD"
            break
    return s


def replay_decisions(path: Path | str) -> SignalFn:
    """Replay pre-computed decisions as a backtest signal. Two on-disk formats,
    auto-detected; neither format is altered by this reader:

    1. Flat rows — a JSON list of {timestamp, symbol, regime, confidence}.
       Lookup is by exact (timestamp.isoformat(), symbol) match, so the log's
       granularity must match the bars. Misses fall back to
       (uncertain, 0.0), which the policy table maps to maintain.

    2. Pipeline run documents — the exact shape a decision pipeline writes
       ({"generated_at": ISO8601, "decisions": [{"symbol", "regime_decision",
       "confidence", "action", ...}], ...}), or a JSON list of such documents
       for multi-run replays. Each run fires ONE-SHOT at the first signal bar
       at-or-after its generated_at; every other bar returns
       (uncertain, 0.0) → maintain. Rationale: a pipeline run is a
       point-in-time advisory, and repeating its reduce/reaccumulate at every
       bar would compound trades the pipeline never asked for. When several
       runs precede the same bar, the newest wins and older unfired runs are
       superseded. The stored "action" field is deliberately ignored — the
       engine re-derives the action from (regime_decision, confidence) through
       translate_regime_to_action, keeping policy.py the single source of
       truth. The returned closure is stateful (one-shot consumption; call
       timestamps assumed non-decreasing, which the engine guarantees) — build
       a fresh signal per backtest run.

    Symbols on both sides pass through _canonical_symbol, so decisions on
    "BTC-USD" replay against "BTCUSDT" bars and vice versa. This is the
    intended workflow: run a slow decision process offline once, persist its
    decisions, then sweep parameters in a fast deterministic backtest.
    """
    raw = json.loads(Path(path).read_text())
    if isinstance(raw, dict):
        raw = [raw]
    if not isinstance(raw, list):
        raise ValueError(f"replay {path}: expected a JSON list or a run-document object")

    n_docs = sum(1 for r in raw if isinstance(r, dict) and "decisions" in r)
    if n_docs:
        if n_docs != len(raw):
            raise ValueError(
                f"replay {path}: mixed formats — {n_docs}/{len(raw)} entries are run documents"
            )
        return _replay_pipeline_runs(raw)

    table: dict[tuple[str, str], tuple[str, float]] = {}
    for row in raw:
        key = (row["timestamp"], _canonical_symbol(row["symbol"]))
        table[key] = (row["regime"], float(row["confidence"]))

    def fn(ts: datetime, symbol: str, history: list[Bar]) -> tuple[str, float]:
        key = (ts.isoformat(), _canonical_symbol(symbol))
        return table.get(key, ("uncertain", 0.0))
    return fn


def _replay_pipeline_runs(docs: list[dict]) -> SignalFn:
    """One-shot replay of pipeline-format run documents (see replay_decisions).

    Malformed documents are refused loudly at build time: a replay that
    silently dropped the run you asked for would look valid and answer a
    different question.
    """
    events: dict[str, list[tuple[datetime, str, float]]] = {}
    for doc in docs:
        try:
            at = datetime.fromisoformat(str(doc["generated_at"]))
        except (KeyError, ValueError) as e:
            raise ValueError(f"replay run document: bad generated_at ({e})") from None
        if at.tzinfo is None:
            at = at.replace(tzinfo=timezone.utc)
        for d in doc.get("decisions") or []:
            try:
                sym = _canonical_symbol(str(d["symbol"]))
                regime = str(d["regime_decision"])
                conf = float(d["confidence"])
            except (KeyError, TypeError, ValueError) as e:
                raise ValueError(
                    f"replay decision row needs symbol/regime_decision/confidence ({e})"
                ) from None
            events.setdefault(sym, []).append((at, regime, conf))
    for rows in events.values():
        rows.sort(key=lambda r: r[0])

    consumed: dict[str, int] = {}  # per-symbol count of already-fired runs

    def fn(ts: datetime, symbol: str, history: list[Bar]) -> tuple[str, float]:
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        key = _canonical_symbol(symbol)
        rows = events.get(key)
        if not rows:
            return ("uncertain", 0.0)
        i = consumed.get(key, 0)
        j = i
        while j < len(rows) and rows[j][0] <= ts:
            j += 1
        if j == i:  # nothing new since the last bar: no standing order, hold
            return ("uncertain", 0.0)
        consumed[key] = j
        _, regime, conf = rows[j - 1]  # newest run wins; older unfired are superseded
        return (regime, conf)
    return fn
