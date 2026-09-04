"""quantdesk.reference: pure math, no venue, no execution import (contract tests)."""

from __future__ import annotations

import importlib
import math
import sys
from pathlib import Path

import pytest

from quantdesk.reference import cost_floor, grid, market_making


# ---------- contract: advisory-only, nothing money-shaped -----------------------


def test_package_is_self_contained() -> None:
    """Static contract: no module in the package imports the rest of quantdesk
    (backtest, research, factors) -- it is a reading room of pure formulas."""
    for mod in ("quantdesk.reference", "quantdesk.reference.cost_floor",
                "quantdesk.reference.market_making", "quantdesk.reference.grid"):
        m = importlib.import_module(mod)
        src = Path(m.__file__).read_text(encoding="utf-8")
        for line in src.splitlines():
            s = line.strip()
            if s.startswith(("import ", "from ")):
                assert not s.startswith(("import quantdesk", "from quantdesk", "from .")), (
                    f"{mod}: {s!r} -- the reference package must stay self-contained"
                )
    assert "quantdesk.reference" in sys.modules


# ---------- cost floor --------------------------------------------------------------


def test_retail_venue_markup_preset_is_about_190_bps() -> None:
    # Illustrative bid/ask pairs carrying a ~190 bps quoted markup: the shape
    # the retail preset in cost_floor.VENUE_PRESETS was derived from. No raw
    # venue quotes are recorded anywhere in this repository.
    assert cost_floor.spread_bps(100.0, 101.91) == pytest.approx(189.2, abs=0.5)
    assert cost_floor.spread_bps(2500.0, 2547.75) == pytest.approx(189.2, abs=0.5)


def test_roundtrip_cost_composition() -> None:
    assert cost_floor.roundtrip_cost_bps(spread_bps=190) == 190
    assert cost_floor.roundtrip_cost_bps(spread_bps=2, fee_bps_per_side=120) == 242
    assert cost_floor.roundtrip_cost_bps(fee_bps_per_side=60, slippage_bps_per_side=5) == 130
    assert cost_floor.maker_roundtrip_cost_bps(60) == 120
    with pytest.raises(ValueError):
        cost_floor.roundtrip_cost_bps(spread_bps=-1)


def test_required_move_uses_safety_multiple() -> None:
    assert cost_floor.required_move_bps(190) == 380
    assert cost_floor.required_move_bps(190, safety_multiple=1.5) == 285


def test_presets_carry_provenance_and_dates() -> None:
    table = dict(cost_floor.cost_table())
    assert table["retail_venue_markup_2026-08"] == 190
    assert table["exchange_intro_taker"] == 242
    for v in cost_floor.VENUE_PRESETS.values():
        assert v.provenance and "measured" in v.provenance


def test_unusable_quote_raises() -> None:
    with pytest.raises(ValueError):
        cost_floor.spread_bps(0, 10)
    with pytest.raises(ValueError):
        cost_floor.spread_bps(11, 10)


# ---------- Avellaneda–Stoikov ------------------------------------------------------


def test_reservation_price_skews_against_inventory() -> None:
    mid = 100.0
    r_flat = market_making.reservation_price(mid, 0.0, gamma=0.1, sigma=2.0, time_left=1.0)
    r_long = market_making.reservation_price(mid, 1.0, gamma=0.1, sigma=2.0, time_left=1.0)
    r_short = market_making.reservation_price(mid, -1.0, gamma=0.1, sigma=2.0, time_left=1.0)
    assert r_flat == mid
    assert r_long == pytest.approx(mid - 0.1 * 4.0)  # q*gamma*sigma^2*T = 0.4
    assert r_short == pytest.approx(mid + 0.4)


def test_optimal_spread_formula_and_limits() -> None:
    gamma, sigma, T, kappa = 0.1, 2.0, 1.0, 1.5
    expected = gamma * sigma**2 * T + (2 / gamma) * math.log(1 + gamma / kappa)
    assert market_making.optimal_spread(gamma, sigma, T, kappa) == pytest.approx(expected)
    # more volatility or longer horizon -> wider; thinner book (smaller kappa) -> wider
    assert market_making.optimal_spread(gamma, 3.0, T, kappa) > expected
    assert market_making.optimal_spread(gamma, sigma, 2.0, kappa) > expected
    assert market_making.optimal_spread(gamma, sigma, T, 0.5) > expected


def test_quotes_straddle_reservation_and_respect_min_spread() -> None:
    q = market_making.avellaneda_stoikov_quotes(
        100.0, 1.0, gamma=0.1, sigma=2.0, time_left=1.0, kappa=1.5, min_spread=0.0
    )
    assert q.bid < q.reservation < q.ask
    assert q.mid == pytest.approx(q.reservation)
    assert q.reservation < 100.0  # long inventory -> skew to sell
    wide = market_making.avellaneda_stoikov_quotes(
        100.0, 0.0, gamma=0.1, sigma=2.0, time_left=1.0, kappa=1.5, min_spread=5.0
    )
    assert wide.spread == 5.0


def test_bad_parameters_raise() -> None:
    with pytest.raises(ValueError):
        market_making.optimal_spread(0.0, 1.0, 1.0, 1.0)
    with pytest.raises(ValueError):
        market_making.reservation_price(100.0, 0.0, gamma=0.1, sigma=1.0, time_left=-1.0)


# ---------- inventory skew -------------------------------------------------------------


def test_inventory_skew_at_target_is_symmetric() -> None:
    # 0.667 BTC + 6000 USDT at 9000 -> 1.3337 BTC-equivalent, target 50% = 0.6668
    bid, ask = market_making.inventory_skew_ratios(0.6668, 6000.0, 9000.0, 0.5, base_range=0.5)
    assert bid == pytest.approx(1.0, abs=1e-3)
    assert ask == pytest.approx(1.0, abs=1e-3)


def test_inventory_skew_below_target_buys_more_and_clamps_at_range_edge() -> None:
    # 0.3 BTC + 9000 USDT at 9000 -> total 1.3 BTC-eq, target 0.65; range 0.7 -> low 0 (clamped)
    bid, ask = market_making.inventory_skew_ratios(0.3, 9000.0, 9000.0, 0.5, base_range=0.7)
    assert bid > 1.0 > ask
    assert bid + ask == pytest.approx(2.0)
    # far below the lower edge -> no sells at all
    bid, ask = market_making.inventory_skew_ratios(0.0, 9000.0, 9000.0, 0.5, base_range=0.1)
    assert (bid, ask) == (2.0, 0.0)


def test_inventory_skew_above_target_sells_more() -> None:
    bid, ask = market_making.inventory_skew_ratios(2.0, 0.0, 9000.0, 0.5, base_range=0.5)
    assert (bid, ask) == (0.0, 2.0)
    bid, ask = market_making.inventory_skew_ratios(1.1, 9000.0, 9000.0, 0.5, base_range=0.5)
    assert ask > 1.0 > bid and bid + ask == pytest.approx(2.0)


# ---------- ladder / anchor / capture arithmetic -------------------------------------


def test_ladder_is_symmetric_and_monotone() -> None:
    bids, asks = market_making.ladder(100.0, 10.0, 5.0, 3)
    assert bids == pytest.approx([99.9, 99.85, 99.8])
    assert asks == pytest.approx([100.1, 100.15, 100.2])


def test_follow_anchor_gap_sign() -> None:
    assert market_making.follow_anchor_gap_bps(100.10, 100.0) == pytest.approx(10.0)
    assert market_making.follow_anchor_gap_bps(99.90, 100.0) == pytest.approx(-10.0)


def test_two_sided_mm_is_negative_at_a_60bps_maker_fee() -> None:
    # ~1 bp half spread, 60 bps maker per side: -118 bps per completed round trip
    assert market_making.spread_capture_net_bps(1.0, 60.0) == pytest.approx(-118.0)
    # break-even half spread at 60 bps maker is 60 bps — nowhere near BTC's book
    assert market_making.spread_capture_net_bps(60.0, 60.0) == 0.0


# ---------- grid ---------------------------------------------------------------------


def test_grid_levels_arithmetic_and_geometric() -> None:
    assert grid.grid_levels(90, 110, 4) == pytest.approx([90, 95, 100, 105, 110])
    g = grid.grid_levels(100, 121, 2, geometric=True)
    assert g == pytest.approx([100, 110, 121])
    assert grid.step_bps([100, 101, 102]) == pytest.approx(100.0, abs=1.5)


def test_grid_roundtrip_net_is_step_minus_cost() -> None:
    assert grid.roundtrip_net_bps(100.0, 190.0) == -90.0
    assert grid.roundtrip_net_bps(300.0, 190.0) == 110.0


def test_grid_simulation_one_oscillation_earns_one_step_minus_fees() -> None:
    levels = [98.0, 99.0, 100.0, 101.0, 102.0]
    # start at 100: buys armed at 98,99; sells at 101,102. Dip to 99 (buy), back to 100 (sell).
    res = grid.simulate_grid([100.0, 99.0, 100.0], levels, qty_per_level=1.0, fee_bps_per_side=0.0)
    assert (res.buys, res.sells, res.roundtrips) == (1, 1, 1)
    assert res.final_inventory == 0.0
    assert res.realized_cash == pytest.approx(1.0)  # bought 99, sold 100
    assert res.total_pnl == pytest.approx(1.0)
    # with a 60 bps fee per side the same oscillation nets 1 - 0.006*(99+100)
    res_fee = grid.simulate_grid([100.0, 99.0, 100.0], levels, qty_per_level=1.0, fee_bps_per_side=60.0)
    assert res_fee.realized_cash == pytest.approx(1.0 - 0.006 * 199.0)


def test_grid_simulation_trend_down_accumulates_inventory() -> None:
    levels = grid.grid_levels(90.0, 110.0, 20)  # 1.0 steps
    res = grid.simulate_grid([100.0, 95.0, 90.0], levels, qty_per_level=0.5)
    assert res.sells == 0
    assert res.buys == 10  # 99..90 all filled
    assert res.final_inventory == pytest.approx(5.0)
    assert res.inventory_mark_at_last == pytest.approx(5.0 * 90.0)
    assert res.total_pnl < 0  # bought the way down


def test_grid_rejects_bad_inputs() -> None:
    with pytest.raises(ValueError):
        grid.simulate_grid([100.0], [99.0, 100.0], 1.0)
    with pytest.raises(ValueError):
        grid.simulate_grid([100.0, 99.0], [100.0, 99.0], 1.0)
    with pytest.raises(ValueError):
        grid.grid_levels(110, 90, 2)
