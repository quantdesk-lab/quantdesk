from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable

from ..vocab import Action


@dataclass(frozen=True)
class Bar:
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float


@dataclass(frozen=True)
class Decision:
    timestamp: datetime
    symbol: str
    regime: str
    confidence: float
    action: Action


@dataclass(frozen=True)
class Trade:
    timestamp: datetime
    symbol: str
    action: Action
    delta_qty: float   # positive = buy, negative = sell
    price: float
    cost: float


@dataclass
class BacktestResult:
    equity_curve: list[tuple[datetime, float]]
    trades: list[Trade]
    decisions: list[Decision]
    weight_history: list[tuple[datetime, dict[str, float]]]
    granularity: str
    metrics: dict[str, float] = field(default_factory=dict)

    @property
    def final_equity(self) -> float:
        return self.equity_curve[-1][1] if self.equity_curve else 0.0

    @property
    def initial_equity(self) -> float:
        return self.equity_curve[0][1] if self.equity_curve else 0.0


# A signal function takes (now_ts, symbol, history_through_now) and returns
# (regime_label, confidence). It must NOT see bars dated after now_ts.
SignalFn = Callable[[datetime, str, list[Bar]], tuple[str, float]]

# A weight function returns the TARGET portfolio weight for one symbol in
# [0, 1] (fraction of total equity; long/flat spot — no shorts, no leverage),
# or None for "no view" (keep the current position, trade nothing). Same
# no-lookahead contract as SignalFn. This is the Phase-B contract from
# docs/RESEARCH_DISCIPLINE.md that the faithful vol-scaled TSMOM needs — discrete
# regimes cannot express a continuous size.
WeightFn = Callable[[datetime, str, list[Bar]], "float | None"]
