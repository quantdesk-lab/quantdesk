from __future__ import annotations

from .vocab import (
    DEEP_BEAR_HIGH_CONFIDENCE,
    HIGH_CONFIDENCE,
    LATE_BULL_HIGH_CONFIDENCE,
    LATE_BULL_MED_CONFIDENCE,
    MED_CONFIDENCE,
)
from .vocab import Action, Regime


def translate_regime_to_action(regime: Regime | str, confidence: float) -> Action | str:
    """Regime x confidence -> target-weight policy table.

    Deterministic mapping from (market state, confidence) to a bounded action.
    States carry NO action in their names; actions are target weights
    (fractions of a per-symbol weight cap: TARGET_WEIGHT_CAP = 0.10 in the
    discrete backtest engine, 1.0 in the ticket builder -- each consumer
    states its cap), symmetric on entry and exit, with an explicit risk-off
    action for volatility events. Any process that produces a (regime,
    confidence) pair -- a rule, a model, a replayed log -- goes through this
    one table, so no two consumers can disagree about what a state means.

    Legacy regime strings keep their original mapping forever so previously
    recorded decisions replay unchanged.
    """
    regime = str(regime)
    confidence = float(confidence)

    # ---- current vocabulary: market states → target-weight actions ----
    if regime == "trend_up":
        if confidence >= HIGH_CONFIDENCE:
            return "target_weight_100"
        if confidence >= MED_CONFIDENCE:
            return "target_weight_60"
        return "maintain"
    if regime == "trend_down":
        if confidence >= HIGH_CONFIDENCE:
            return "flat_position"
        if confidence >= MED_CONFIDENCE:
            return "target_weight_20"
        return "maintain"
    if regime == "range_bound":
        if confidence >= MED_CONFIDENCE:
            return "target_weight_30"
        return "maintain"
    if regime == "high_volatility_event":
        if confidence >= MED_CONFIDENCE:
            return "halve_position"
        return "maintain"
    if regime == "uncertain":
        return "maintain"

    # ---- legacy vocabulary (frozen semantics for old rows) ----
    if regime == "late_bull_reduce":
        if confidence >= LATE_BULL_HIGH_CONFIDENCE:
            return "reduce_25_percent"
        if confidence >= LATE_BULL_MED_CONFIDENCE:
            return "reduce_10_percent"
        return "stop_adding"
    if regime == "deep_bear_reaccumulate":
        if confidence >= DEEP_BEAR_HIGH_CONFIDENCE:
            return "reaccumulate_small"
        return "hold"
    if regime == "trend_continuation_hold":
        return "hold"
    if regime == "uncertain_need_more_info":
        return "hold"

    # unknown regime → safety fallback (no order)
    return "maintain"
