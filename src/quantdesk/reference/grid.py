"""Grid / "Oscillation" reference: ladder of resting buys below and sells above.

A grid is a volatility-harvesting book: every completed buy-low/sell-one-level-
higher pair earns the grid step minus the round-trip cost; a trend fills one
side repeatedly and leaves inventory (long in a down-trend, out of inventory in
an up-trend). The only free parameter that matters at retail cost is the STEP
relative to cost: net per round trip = step_bps - roundtrip_cost_bps.

``simulate_grid`` is a deliberately naive event replay over a price path
(last-price crossing = fill, no queue, no partial fills) — it OVERSTATES fills
exactly like an optimistic paper-fill simulator does, so use it to compare grids against each
other and against cost, never to claim a P&L.
"""

from __future__ import annotations

from dataclasses import dataclass, field


def grid_levels(lower: float, upper: float, n_steps: int, geometric: bool = False) -> list[float]:
    """``n_steps`` equal steps between lower and upper -> n_steps+1 levels."""
    if not (0 < lower < upper):
        raise ValueError("need 0 < lower < upper")
    if n_steps <= 0:
        raise ValueError("n_steps must be >= 1")
    if geometric:
        ratio = (upper / lower) ** (1.0 / n_steps)
        return [lower * ratio**k for k in range(n_steps + 1)]
    step = (upper - lower) / n_steps
    return [lower + step * k for k in range(n_steps + 1)]


def step_bps(levels: list[float]) -> float:
    """Median step between adjacent levels, in bps of the lower level."""
    if len(levels) < 2:
        raise ValueError("need >= 2 levels")
    steps = sorted((b - a) / a * 1e4 for a, b in zip(levels, levels[1:]))
    return steps[len(steps) // 2]


def roundtrip_net_bps(step_bps_: float, roundtrip_cost_bps: float) -> float:
    """Net bps of one completed grid round trip. Negative = the grid pays the
    venue to oscillate."""
    return step_bps_ - roundtrip_cost_bps


@dataclass
class GridResult:
    realized_cash: float  # cash from fills net of fees (negative while holding inventory)
    fees_paid: float
    roundtrips: int
    buys: int
    sells: int
    final_inventory: float
    max_inventory: float
    inventory_mark_at_last: float  # (final_inventory - start_inventory) * last price
    fills: list[tuple[int, str, float]] = field(default_factory=list)

    @property
    def total_pnl(self) -> float:
        """Cash + inventory marked at the last price (fees already deducted)."""
        return self.realized_cash + self.inventory_mark_at_last


def simulate_grid(
    prices: list[float],
    levels: list[float],
    qty_per_level: float,
    *,
    fee_bps_per_side: float = 0.0,
    start_inventory: float = 0.0,
) -> GridResult:
    """Naive grid replay. At start, buys rest at every level below the first
    price and sells at every level above it. A filled buy at level i arms a
    sell at level i+1; a filled sell at level j arms a buy at level j-1. Fills
    happen when the last price crosses the level (taker-optimistic). Fees are
    ``fee_bps_per_side`` of notional per fill (no spread modelled: pass the
    venue's half-spread here as a fee if you want to stand in for it).
    """
    if len(prices) < 2:
        raise ValueError("need >= 2 prices")
    if len(levels) < 2 or any(b <= a for a, b in zip(levels, levels[1:])):
        raise ValueError("levels must be strictly increasing with >= 2 entries")
    if qty_per_level <= 0:
        raise ValueError("qty_per_level must be > 0")
    if fee_bps_per_side < 0:
        raise ValueError("fee must be >= 0")
    n = len(levels)
    p0 = prices[0]
    armed: list[str | None] = [None] * n  # "BUY" | "SELL" | None per level
    for i, lv in enumerate(levels):
        if lv < p0:
            armed[i] = "BUY"
        elif lv > p0:
            armed[i] = "SELL"
    inv = float(start_inventory)
    cash = 0.0
    fees = 0.0
    buys = sells = roundtrips = 0
    max_inv = inv
    fills: list[tuple[int, str, float]] = []
    fee = fee_bps_per_side / 1e4
    for t, px in enumerate(prices[1:], start=1):
        changed = True
        while changed:
            changed = False
            for i in range(n):
                side = armed[i]
                if side == "BUY" and px <= levels[i]:
                    notional = levels[i] * qty_per_level
                    cash -= notional
                    fees += notional * fee
                    inv += qty_per_level
                    buys += 1
                    fills.append((t, "BUY", levels[i]))
                    armed[i] = None
                    if i + 1 < n and armed[i + 1] is None:
                        armed[i + 1] = "SELL"
                    changed = True
                elif side == "SELL" and px >= levels[i]:
                    notional = levels[i] * qty_per_level
                    cash += notional
                    fees += notional * fee
                    inv -= qty_per_level
                    sells += 1
                    fills.append((t, "SELL", levels[i]))
                    armed[i] = None
                    if i - 1 >= 0 and armed[i - 1] is None:
                        armed[i - 1] = "BUY"
                    changed = True
            max_inv = max(max_inv, inv)
    # a round trip = a sell that closes an earlier grid buy
    roundtrips = min(buys, sells)
    last = prices[-1]
    return GridResult(
        realized_cash=cash - fees,
        fees_paid=fees,
        roundtrips=roundtrips,
        buys=buys,
        sells=sells,
        final_inventory=inv,
        max_inventory=max_inv,
        inventory_mark_at_last=(inv - start_inventory) * last,
        fills=fills,
    )
