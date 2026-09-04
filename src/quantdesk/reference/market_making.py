"""Two-sided quoting reference math (what a "market-maker bot" actually computes).

Sources (re-derived, not copied):
  * Avellaneda & Stoikov (2008), "High-frequency trading in a limit order
    book", Quantitative Finance 8(3) — reservation price and optimal spread.
  * Hummingbot (Apache-2.0) pure_market_making / avellaneda_market_making /
    inventory_skew_calculator — parameter vocabulary (``bid_spread``,
    ``order_levels``, ``order_level_spread``, ``inventory_target_base_pct``,
    ``inventory_range_multiplier``) and the linear inventory-skew rule.
  * docs/FACTOR_VERDICTS.md F7 (inventory-skewed maker quoting) and F8
    (cross-venue fair-value anchor) -- the placement of these ideas here:
    execution layer, zero alpha, taker->maker conversion is the only value.

Units: prices in quote currency; ``inventory`` in base units (signed);
``sigma`` is the ABSOLUTE price volatility per sqrt(time unit) and
``time_left`` is in the same time unit; ``gamma`` is risk aversion (1/price);
``kappa`` is the order-arrival decay (1/price). All outputs are prices or
ratios — nothing here is an order.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

# ---------- Avellaneda–Stoikov ------------------------------------------------


def reservation_price(
    mid: float, inventory: float, gamma: float, sigma: float, time_left: float
) -> float:
    """r = s - q * gamma * sigma^2 * (T - t).

    Long inventory (q>0) pushes the reservation price BELOW mid so the quotes
    skew to sell; short inventory pushes it above. gamma -> 0 recovers mid."""
    _check_positive(mid=mid, gamma=gamma, sigma=sigma)
    if time_left < 0:
        raise ValueError("time_left must be >= 0")
    return mid - inventory * gamma * sigma * sigma * time_left


def optimal_spread(gamma: float, sigma: float, time_left: float, kappa: float) -> float:
    """Total spread delta_a + delta_b = gamma*sigma^2*(T-t) + (2/gamma)*ln(1+gamma/kappa).

    The first term is inventory-risk compensation (grows with volatility and
    horizon); the second is the liquidity term (thin books -> small kappa ->
    wider spread)."""
    _check_positive(gamma=gamma, sigma=sigma, kappa=kappa)
    if time_left < 0:
        raise ValueError("time_left must be >= 0")
    return gamma * sigma * sigma * time_left + (2.0 / gamma) * math.log(1.0 + gamma / kappa)


@dataclass(frozen=True)
class Quotes:
    bid: float
    ask: float
    reservation: float
    spread: float

    @property
    def mid(self) -> float:
        return (self.bid + self.ask) / 2.0


def avellaneda_stoikov_quotes(
    mid: float,
    inventory: float,
    *,
    gamma: float,
    sigma: float,
    time_left: float,
    kappa: float,
    min_spread: float = 0.0,
) -> Quotes:
    """Bid/ask around the reservation price; ``min_spread`` (absolute) is a
    hard floor like hummingbot's ``min_spread`` (expressed there in % of mid)."""
    r = reservation_price(mid, inventory, gamma, sigma, time_left)
    spread = max(optimal_spread(gamma, sigma, time_left, kappa), float(min_spread))
    return Quotes(bid=r - spread / 2.0, ask=r + spread / 2.0, reservation=r, spread=spread)


# ---------- linear inventory skew (hummingbot-style) --------------------------


def inventory_skew_ratios(
    base_amount: float,
    quote_amount: float,
    price: float,
    target_base_pct: float,
    base_range: float,
) -> tuple[float, float]:
    """(bid_ratio, ask_ratio) multipliers in [0, 2] that sum to 2.

    Portfolio value is measured in BASE units (base + quote/price). When the
    base share is below target the bid multiplier rises linearly toward 2 and
    the ask toward 0 at ``target - base_range``; symmetric above target.
    ``base_range`` = hummingbot's ``inventory_range_multiplier * order_amount``.
    """
    _check_positive(price=price)
    if base_amount < 0 or quote_amount < 0:
        raise ValueError("amounts must be >= 0")
    if not 0.0 <= target_base_pct <= 1.0:
        raise ValueError("target_base_pct must be in [0, 1]")
    if base_range < 0:
        raise ValueError("base_range must be >= 0")
    total_base = base_amount + quote_amount / price
    if total_base <= 0:
        return (1.0, 1.0)
    target_base = total_base * target_base_pct
    low = max(target_base - base_range, 0.0)
    high = target_base + base_range
    if base_amount < target_base:
        if base_amount <= low or target_base - low <= 0:
            return (2.0, 0.0)
        f = (target_base - base_amount) / (target_base - low)
        return (1.0 + f, 1.0 - f)
    if base_amount > target_base:
        if base_amount >= high or high - target_base <= 0:
            return (0.0, 2.0)
        f = (base_amount - target_base) / (high - target_base)
        return (1.0 - f, 1.0 + f)
    return (1.0, 1.0)


# ---------- ladder ("Spread Depth" / order_levels) ------------------------------


def ladder(
    mid: float, first_spread_bps: float, level_spread_bps: float, levels: int
) -> tuple[list[float], list[float]]:
    """Symmetric price ladder: level k sits at first_spread + k*level_spread bps
    from mid on each side. Returns (bids descending, asks ascending)."""
    _check_positive(mid=mid)
    if levels <= 0:
        raise ValueError("levels must be >= 1")
    if first_spread_bps < 0 or level_spread_bps < 0:
        raise ValueError("spreads must be >= 0")
    bids, asks = [], []
    for k in range(levels):
        off = (first_spread_bps + k * level_spread_bps) / 1e4
        bids.append(mid * (1.0 - off))
        asks.append(mid * (1.0 + off))
    return bids, asks


# ---------- reference-price following ("Strict/Combined Follow", F8) -------------


def follow_anchor_gap_bps(venue_mid: float, external_mid: float) -> float:
    """Signed gap of this venue's mid vs an external fair-value anchor, in bps
    of the anchor. Positive = venue rich. Used to PLACE quotes relative to the
    anchor, never as a standalone signal (docs/FACTOR_VERDICTS.md F8: 1-10 bp
    gaps vs 120-240 bp round trips)."""
    _check_positive(venue_mid=venue_mid, external_mid=external_mid)
    return (venue_mid - external_mid) / external_mid * 1e4


# ---------- the arithmetic that kills two-sided MM at retail fees ---------------


def spread_capture_net_bps(
    half_spread_bps: float,
    maker_fee_bps_per_side: float,
    adverse_selection_bps: float = 0.0,
) -> float:
    """Net capture of ONE completed round trip (buy at bid, sell at ask):
    2*half_spread - 2*maker_fee - adverse_selection. With a 60 bps maker fee
    and a ~1 bp half spread this is about -118 bps (docs/FACTOR_VERDICTS.md F7:
    two-sided market making is dead at retail fee tiers). On a retail venue
    with ~190 bps round-trip measured in 2026-08 there is no maker role at
    all -- every fill pays the markup."""
    if min(half_spread_bps, maker_fee_bps_per_side, adverse_selection_bps) < 0:
        raise ValueError("inputs must be >= 0")
    return 2.0 * half_spread_bps - 2.0 * maker_fee_bps_per_side - adverse_selection_bps


def _check_positive(**kw: float) -> None:
    for k, v in kw.items():
        if not (v > 0):
            raise ValueError(f"{k} must be > 0, got {v}")
