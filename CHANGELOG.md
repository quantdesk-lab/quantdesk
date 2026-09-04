# Changelog

All notable changes to QuantDesk are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/).

## [0.1.0] - 2026-09-03

Initial public release.

### Added

- `quantdesk.vocab`: the frozen market-state and target-weight action
  vocabularies plus the five confidence thresholds the policy table reads.
- `quantdesk.policy`: the deterministic regime x confidence -> target-weight
  policy table (legacy vocabulary keeps its frozen mapping).
- `quantdesk.factors.alpha101`: 19 alphas derived from Kakushadze (2016),
  re-cast as single-symbol time-series forms with every adaptation stated,
  over a 23-operator time-series library. Formulas are restated in this
  library's own operator notation; the paper's text, notation and
  cross-sectional forms are not reproduced (`NOTICE.md` states the caveat
  for the alphas that have no cross-sectional operator).
- `quantdesk.factors.tsmom`: time-series momentum with EWMA volatility
  scaling (parameters as published in Harvey et al. 2022), Yang-Zhang and
  Rogers-Satchell range volatility, robust median/MAD z-scores, an EWMA beta
  helper, and the state -> confidence mapping.
- `quantdesk.factors.quant`: multi-horizon momentum z-scores, realized
  volatility regime, funding-rate z-score summary.
- `quantdesk.factors.microstructure`: seven order-book and trade-flow factors
  (micro-price, queue imbalance, book pressure, spread, snapshot-diff OFI,
  trade-flow imbalance family, price-impact proxy), labeled execution-layer
  observables.
- `quantdesk.factors.technical`: RSI (Wilder), EMA cross state, order-book and
  trade summaries.
- `quantdesk.backtest`: two-mode event backtester (discrete actions via the
  policy table; continuous target weights with a no-trade band), per-fill
  fee + slippage model, 24/7 annualization, buy-and-hold / random / naive
  momentum baselines, equity-curve metrics, Spearman Rank-IC, and a
  bring-your-own-1m-candles lake reader with deterministic resampling.
- `quantdesk.research.board`: the factor research board (time-series Rank-IC,
  IC decay, lag-1 self-correlation turnover proxy, correlation matrix) with
  honesty gates (30 pairs minimum, n_eff >= 8 on overlapping horizons).
- `quantdesk.research.microstructure_lake`: lake-fed microstructure panel
  with a first-class empty state.
- `quantdesk.research.tickets`: deterministic decision-ticket stream that
  explains every backtest decision from the numbers and the policy table
  (no language model anywhere).
- `quantdesk.research.null_calibration`: empirical |Rank-IC| null band from
  reseeded random walks.
- `quantdesk.lake.schemas`: the three lake_v1 Arrow schemas (pyarrow imported
  lazily).
- `quantdesk.reference`: cost-floor arithmetic, grid replay, and
  Avellaneda-Stoikov quoting math as reference strategies.
- `quantdesk.demo.fixtures`: synthetic geometric-Brownian-motion fixtures.
- `scripts/build_site.py` and a static GitHub Pages site computed entirely
  from synthetic fixtures at build time.
- Documentation: `docs/HONESTY.md`, `docs/DATA.md`,
  `docs/RESEARCH_DISCIPLINE.md`, `docs/FACTOR_VERDICTS.md`, `docs/ROADMAP.md`,
  `NOTICE.md`, `CITATIONS.md`.

### Not included (by design)

- No venue clients, fetchers, or recorders, and no recorded venue data
  (see `docs/DATA.md` for the terms-of-service reasoning).
- No order management, execution, approvals, or broker adapters. Nothing in
  this package places, routes, or simulates real orders against a venue.
- No equity data feeds, no cross-sectional IC, no walk-forward CV
  (see `docs/ROADMAP.md`).
