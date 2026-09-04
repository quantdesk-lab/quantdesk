"""Cost floor arithmetic — the first filter every "high-frequency" idea meets.

A retail account pays the venue's spread and/or fee on BOTH legs. Before any
signal is discussed, the round-trip cost in bps is the bar the typical move
over the holding horizon must clear — by a margin, because the move is random
and the cost is not.

Measured / documented presets live in ``VENUE_PRESETS`` with provenance; they
are inputs to arithmetic, not claims about the future.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class VenueCost:
    """One venue's cost model for a MARKET (taker) round trip, in bps.

    ``spread_bps`` is the full quoted bid/ask spread (buy at ask, sell at bid
    pays the whole spread over a round trip). ``fee_bps_per_side`` is charged
    on each leg. ``provenance`` says where the number came from and when.
    """

    name: str
    spread_bps: float
    fee_bps_per_side: float
    provenance: str

    def roundtrip_bps(self, slippage_bps_per_side: float = 0.0) -> float:
        return roundtrip_cost_bps(
            spread_bps=self.spread_bps,
            fee_bps_per_side=self.fee_bps_per_side,
            slippage_bps_per_side=slippage_bps_per_side,
        )


def spread_bps(bid: float, ask: float) -> float:
    """Full quoted spread in bps of mid. Raises on an unusable quote."""
    if bid <= 0 or ask <= 0 or ask < bid:
        raise ValueError(f"unusable quote bid={bid} ask={ask}")
    mid = (bid + ask) / 2.0
    return (ask - bid) / mid * 1e4


def roundtrip_cost_bps(
    *,
    spread_bps: float = 0.0,
    fee_bps_per_side: float = 0.0,
    slippage_bps_per_side: float = 0.0,
) -> float:
    """Cost of buy-then-sell at market: the whole spread once, fees and
    slippage twice (once per leg)."""
    if min(spread_bps, fee_bps_per_side, slippage_bps_per_side) < 0:
        raise ValueError("costs must be non-negative")
    return spread_bps + 2.0 * fee_bps_per_side + 2.0 * slippage_bps_per_side


def maker_roundtrip_cost_bps(maker_fee_bps_per_side: float) -> float:
    """Resting limit orders on both legs pay no spread (they EARN it if filled
    at the quote) but pay the maker fee twice. Fill risk is not a cost here —
    it is the reason maker strategies can fail silently (unfilled legs)."""
    if maker_fee_bps_per_side < 0:
        raise ValueError("fee must be non-negative")
    return 2.0 * maker_fee_bps_per_side


def required_move_bps(roundtrip_bps: float, safety_multiple: float = 2.0) -> float:
    """The typical |move| over the holding horizon a directional idea needs
    before it is worth discussing. ``safety_multiple`` encodes that the move
    is random and partly unrealized while the cost is certain; 2x is the
    fee-first convention of this toolkit (docs/RESEARCH_DISCIPLINE.md), not a law."""
    if roundtrip_bps < 0 or safety_multiple <= 0:
        raise ValueError("bad inputs")
    return roundtrip_bps * safety_multiple


#: Documented / measured venue presets. Dates matter: spreads move.
VENUE_PRESETS: dict[str, VenueCost] = {
    # A retail venue whose quoted bid/ask markup alone was ~190 bps round trip
    # (five spot pairs, all 189-191 bps) when measured in 2026-08, with no
    # explicit fee. Derived measurement only: no raw quotes are recorded here.
    "retail_venue_markup_2026-08": VenueCost(
        name="Retail crypto venue (~190 bps round-trip quote markup, measured 2026-08)",
        spread_bps=190.0,
        fee_bps_per_side=0.0,
        provenance=(
            "retail venue quote markup, ~190 bps round trip across five spot pairs, "
            "measured 2026-08; re-measure before relying on it"
        ),
    ),
    # A public exchange's published entry fee tier (taker 120 / maker 60 bps per
    # side) -- re-verify the fee table before relying on it.
    "exchange_intro_taker": VenueCost(
        name="Public exchange (entry tier, taker both legs)",
        spread_bps=2.0,
        fee_bps_per_side=120.0,
        provenance=(
            "published entry-tier taker fee 120 bps per side; "
            "book spread of roughly 0-2 bps measured 2026-08"
        ),
    ),
}


def cost_table(slippage_bps_per_side: float = 0.0) -> list[tuple[str, float]]:
    """(preset_name, roundtrip_bps) for every preset — for docs and tests."""
    return [(k, v.roundtrip_bps(slippage_bps_per_side)) for k, v in VENUE_PRESETS.items()]
