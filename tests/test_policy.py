"""Policy-table contract: the market-state vocabulary maps to target-weight
actions; the legacy vocabulary keeps its frozen mapping forever so previously
recorded decisions replay unchanged."""

from __future__ import annotations

import pytest

from quantdesk.policy import translate_regime_to_action


@pytest.mark.parametrize(
    ("regime", "confidence", "expected"),
    [
        # trend_up tiers
        ("trend_up", 0.80, "target_weight_100"),
        ("trend_up", 0.70, "target_weight_100"),  # boundary
        ("trend_up", 0.69, "target_weight_60"),
        ("trend_up", 0.50, "target_weight_60"),  # boundary
        ("trend_up", 0.49, "maintain"),
        # trend_down tiers (symmetric exit — the old vocabulary's missing half)
        ("trend_down", 0.80, "flat_position"),
        ("trend_down", 0.70, "flat_position"),  # boundary
        ("trend_down", 0.69, "target_weight_20"),
        ("trend_down", 0.50, "target_weight_20"),  # boundary
        ("trend_down", 0.49, "maintain"),
        # range_bound
        ("range_bound", 0.60, "target_weight_30"),
        ("range_bound", 0.50, "target_weight_30"),  # boundary
        ("range_bound", 0.49, "maintain"),
        # high_volatility_event: risk-off
        ("high_volatility_event", 0.80, "halve_position"),
        ("high_volatility_event", 0.50, "halve_position"),  # boundary
        ("high_volatility_event", 0.49, "maintain"),
        # uncertain: never acts
        ("uncertain", 0.99, "maintain"),
        ("uncertain", 0.00, "maintain"),
    ],
)
def test_regime_to_action_table(regime: str, confidence: float, expected: str) -> None:
    assert translate_regime_to_action(regime, confidence) == expected


@pytest.mark.parametrize(
    ("regime", "confidence", "expected"),
    [
        # Legacy vocabulary: frozen semantics, bit-for-bit the pre-redesign table.
        ("late_bull_reduce", 0.80, "reduce_25_percent"),
        ("late_bull_reduce", 0.70, "reduce_25_percent"),
        ("late_bull_reduce", 0.69, "reduce_10_percent"),
        ("late_bull_reduce", 0.50, "reduce_10_percent"),
        ("late_bull_reduce", 0.49, "stop_adding"),
        ("trend_continuation_hold", 0.99, "hold"),
        ("deep_bear_reaccumulate", 0.80, "reaccumulate_small"),
        ("deep_bear_reaccumulate", 0.60, "reaccumulate_small"),
        ("deep_bear_reaccumulate", 0.59, "hold"),
        ("uncertain_need_more_info", 0.99, "hold"),
    ],
)
def test_legacy_vocabulary_mapping_is_frozen(regime: str, confidence: float, expected: str) -> None:
    assert translate_regime_to_action(regime, confidence) == expected


def test_unknown_regime_falls_back_to_maintain() -> None:
    assert translate_regime_to_action("garbage_string", 0.99) == "maintain"
