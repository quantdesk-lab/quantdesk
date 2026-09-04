from __future__ import annotations

from typing import Final

# Action interpretation: how each Action label maps to a portfolio mutation.
REDUCE_10_KEEP: Final = 0.90      # reduce_10_percent → keep 90% of position
REDUCE_25_KEEP: Final = 0.75      # reduce_25_percent → keep 75% of position
REACCUMULATE_RATE: Final = 0.05   # reaccumulate_small → spend 5% of equity per event

# Target-weight actions: absolute targets as fractions of the per-symbol
# weight cap (TARGET_WEIGHT_CAP). Shared by the engine and any consumer that
# sizes from the same table so sizing cannot drift:
TARGET_FRACTIONS: Final = {
    "target_weight_100": 1.0,
    "target_weight_60": 0.6,
    "target_weight_30": 0.3,
    "target_weight_20": 0.2,
    "flat_position": 0.0,
}
HALVE_KEEP: Final = 0.5           # halve_position → keep 50% of position
TARGET_WEIGHT_CAP: Final = 0.10   # per-symbol weight cap (fraction of equity)

# Per-side trading costs. Typical crypto spot taker is 0.10%; default slippage is conservative.
TRADING_COST_BPS: Final = 10.0
SLIPPAGE_BPS: Final = 5.0

# Annualization factor per granularity. Crypto is 24/7 so we use 365 instead of 252.
PERIODS_PER_YEAR: Final[dict[str, int]] = {
    "1day": 365,
    "12h": 365 * 2,
    "6h": 365 * 4,
    "4h": 365 * 6,
    "1h": 365 * 24,
    # Lake-resample labels (quantdesk/backtest/lake_data.py GRANULARITY_SECONDS).
    "1d": 365,
    "30m": 365 * 48,
    "15m": 365 * 96,
    "5m": 365 * 288,
    "1m": 365 * 1440,
}

RF_ANNUAL: Final = 0.0
DEFAULT_INITIAL_CAPITAL: Final = 10_000.0
