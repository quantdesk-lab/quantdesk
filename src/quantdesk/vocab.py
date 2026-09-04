"""Shared vocabulary: market-state and action labels plus the policy-table
confidence thresholds.

Pure Python (typing only). The regime -> action mapping itself lives in
quantdesk.policy; the backtest engine and the research board import these
labels so every path speaks one vocabulary.
"""
from __future__ import annotations

from typing import Final, Literal

# Market-STATE vocabulary: states describe the market only -- no action is
# baked into any name. Actions live exclusively in the policy table
# (quantdesk/policy.py).
Regime = Literal[
    "trend_up",
    "trend_down",
    "range_bound",
    "high_volatility_event",
    "uncertain",
]

# Target-weight action vocabulary: absolute targets are fractions of a
# per-symbol weight cap (TARGET_WEIGHT_CAP in quantdesk.backtest.config for
# the discrete engine; the ticket builder in quantdesk.research.tickets
# runs the same table with cap 1.0 and says so).
# "maintain" is the no-order action (and the fallback for unknown regimes).
Action = Literal[
    "target_weight_100",
    "target_weight_60",
    "target_weight_30",
    "target_weight_20",
    "flat_position",
    "halve_position",
    "maintain",
]

#: Legacy vocabulary, kept so previously recorded decisions replay unchanged.
LEGACY_REGIMES = (
    "late_bull_reduce",
    "trend_continuation_hold",
    "deep_bear_reaccumulate",
    "uncertain_need_more_info",
)
LEGACY_ACTIONS = (
    "hold",
    "stop_adding",
    "reduce_10_percent",
    "reduce_25_percent",
    "reaccumulate_small",
)

# Policy-table confidence thresholds: one generic pair for the market-state
# vocabulary, plus the frozen legacy pair.
HIGH_CONFIDENCE: Final = 0.70
MED_CONFIDENCE: Final = 0.50

# Legacy thresholds -- consulted for the legacy regime strings only.
LATE_BULL_HIGH_CONFIDENCE: Final = 0.70
LATE_BULL_MED_CONFIDENCE: Final = 0.50
DEEP_BEAR_HIGH_CONFIDENCE: Final = 0.60
