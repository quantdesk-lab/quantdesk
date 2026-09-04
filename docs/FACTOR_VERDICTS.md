# Factor verdicts

An English distillation of the research chain behind this library: which
factor ideas were examined, what the fee arithmetic does to each, and which of
them exist as code today. Every verdict is fee-after. Nothing here is a
recommendation to trade anything.

## 1. The fee-first thesis

The number that governs every verdict is the round-trip cost. On a common
retail spot tier the per-side fee is about **60 bps maker / 120 bps taker**,
so a round trip costs **120-240 bps**. On a retail venue measured in 2026-08
the quoted bid/ask markup alone was about **190 bps round trip** with no
explicit fee. A directional idea is worth discussing only when the typical
|move| over its holding horizon is at least about twice that cost, because
the move is random and partly unrealized while the cost is certain
(`quantdesk.reference.cost_floor.required_move_bps`).

Three consequences follow, and they organize the table below:

1. **Only one idea clears the bar standalone**: time-series momentum at
   weekly-or-slower rebalancing. Four to eight sign flips a year at 120 bps
   per round trip cost roughly 5-10% a year against annualized volatility of
   50-70%; nothing faster survives.
2. **Saving a fee is worth more than any microstructure forecast.**
   Converting a taker fill to a maker fill saves about 60 bps per side,
   deterministically. The predictive edge of any book-shape signal at
   seconds-to-minutes horizons is single-digit bps. So every order-book
   factor is an *execution-layer* input, never a signal.
3. **Volatility targeting shrinks the fee load passively.** A 10% annualized
   volatility target at crypto volatility levels holds roughly 1/8 of
   notional, so the same fee schedule charges roughly 1/8 as much
   (Harvey et al. 2022 make this point about their own, much lower,
   institutional costs; it matters more at retail costs).

Verdict vocabulary:

- **standalone-viable** - can be traded on its own after costs, at the
  stated rebalance frequency.
- **feature-only** - carries information but cannot pay for its own trades;
  used as a regime feature, a gate, or a tilt inside a no-trade band.
- **execution-layer** - decides *how* to trade (maker vs taker, timing,
  quote placement), never *whether*.

## 2. The table

| # | factor | verdict | data needed | strongest public source | status |
|---|---|---|---|---|---|
| F1 | Time-series momentum (TSMOM), volatility-scaled, long/flat, 22d+261d blend | standalone-viable at weekly or slower rebalance | daily closes | Moskowitz-Ooi-Pedersen (2012); Harvey et al. (2022) Exhibit 11 (BTC, 10% vol target, gross of fees); a cross-sectional crypto trend factor is also reported in the journal literature (reference not retained - treat as unverified) | **built**: `factors/tsmom.py` (`tsmom_score`, `target_weight`, `tsmom_regime`), `backtest/signals.py` (`tsmom_weight`, `institutional_signal`), weight-mode engine |
| F2 | Gaussian-mixture regime classifier as a benchmark for labeled regimes | feature-only | daily or 4h panel across 20-50 symbols | Two Sigma regime white paper (2021) - which states the model is not predictive | roadmap |
| F3 | Cross-sectional momentum, residualized on the market factor | feature-only (fees kill it: 36-60 bps/week of turnover cost against a near-zero net edge) | daily closes for 100-200 symbols | Liu-Tsyvinski-Wu (2022); later work with 15 bps costs shows large-cap momentum flat after 2021 | roadmap (it is the intended first calibration factor for a cross-sectional IC pipeline, precisely because its fee-after answer is known) |
| F4 | Market beta and residual decomposition | feature-only (a risk layer, not a signal) | daily returns for 100+ symbols | Two Sigma Factor Lens white paper (2018); Two Sigma crypto risk article (PC1 explains ~47% of variance on 10 coins) | helper **built** (`factors/tsmom.py::ewma_beta`, shrunk toward 1 and clamped); residual pipeline roadmap |
| F5 | Perpetual funding-rate carry, used as a conditioning signal on spot | feature-only (8h settlement cannot clear 120-240 bps standalone; zero marginal cost as a gate) | funding-rate history + open interest from a derivatives venue | BIS Working Paper 1087 (high carry predicts subsequent drawdowns) | z-score function **built** (`factors/quant.py::funding_zscore_summary`); no feed shipped, board row reports value only, no IC |
| F6 | Volatility / dispersion regime features | feature-only | 1m candles; cross-sectional dispersion needs a wider universe | Two Sigma regime white paper (2021); Two Sigma crypto risk article (correlations spike in crashes) | single-symbol realized-vol percentile and z-score **built** (`factors/quant.py::volatility_regime`); dispersion and pairwise-correlation features roadmap |
| F7 | Inventory-skewed maker quoting | execution-layer (zero alpha; taker-to-maker conversion is the entire value) | live top of book + position | Avellaneda-Stoikov (2008); the Hummingbot parameter vocabulary | reference math **built** (`reference/market_making.py`); no quoting loop, by design |
| F8 | Cross-venue fair-value anchor for quote placement | execution-layer (gap is 1-10 bps against a 120-240 bps round trip) | synchronized top-of-book from two or more venues with arrival timestamps | Alexander and Heck, J. Financial Stability 50 (2020) - unregulated derivatives venues lead, spot follows | gap arithmetic **built** (`reference/market_making.py::follow_anchor_gap_bps`); no feed |
| F9 | Cross-sectional low volatility | feature-only (survives only at monthly-or-slower rebalance with a band) | 30-60 day realized vol across a universe | evidence split in the crypto literature; one 2025 preprint reports that at 50 bps costs only volatility timing beats 1/N (reference not retained - treat as unverified) | roadmap |
| F10 | Order-flow imbalance, multi-level book pressure, queue imbalance | execution-layer (10-second direction is predictable; the move is under 10 bps) | top-10 book snapshots and prints | Cont-Kukanov-Stoikov (2014); Xu-Gould-Howison (2019); Gould-Bonart (2016); Silantyev (2019): trade-flow imbalance beats OFI on a crypto book | **built** as observables (`factors/microstructure.py`: `snapshot_ofi`, `book_pressure`, `queue_imbalance`, `trade_flow`); the lake-fed panel labels them execution-layer and attaches no IC |
| F11 | Markout flow-toxicity index | execution-layer (avoids 5-20 bps of adverse maker fills; second-order next to the 60 bps maker/taker gap) | every fill plus mid at +1s/10s/60s/5min | the markout methodology described in public venue-design articles (no specific reference retained - treat as unverified) | roadmap |
| F12 | Stale-quote pickoff surface (mispricing vs latency and quote distance) | execution-layer (parameterizes quote offset and refresh cadence at 5-minute to 4-hour latencies; sub-second grids are irrelevant at retail costs) | book snapshots over weeks | a venue-design white paper's measurement method (reference not retained - treat as unverified); its sub-second numbers do not transfer | roadmap |
| F13 | Cross-venue dispersion / oracle confidence-interval stress | feature-only (modulates sizing or the band; produces no trades) | multi-venue mids or an oracle confidence feed | an oracle white paper describes the aggregation (reference not retained - treat as unverified); no predictive evidence exists | roadmap, gated on a redundancy test against free proxies (realized vol, range, spread) |
| F14 | Stablecoin de-peg stress (unsigned) | feature-only (signed de-risk triggers were disproved by the 2023 episodes; only the unsigned absolute deviation survives as a regime input) | stablecoin/USD candles | a 2025 journal article reports BTC jump probability rising ~5x within 5 minutes of a de-peg (reference not retained - treat as unverified) | roadmap |
| F15 | Lasso factor combiner | execution-layer for the portfolio (it decides weights among validated factors); gated on 5+ IC-validated factors existing | a panel of validated factor series | Two Sigma's Venn documentation on Lasso return attribution | roadmap; today zero factors qualify |

Notes on the table:

- "built" means the function exists in `src/quantdesk/`, has tests, and its
  docstring carries the same verdict as this table. It does not mean the
  factor has been shown to make money; see `docs/HONESTY.md` rule 3.
- The cross-sectional ideas (F3, F4, F9) need a universe of 100+ symbols
  *for estimation only*; published trend results peak in risk-adjusted terms
  at roughly 10-15 coins, and a wider universe adds noise and fees to
  execution.
- The book-flow ideas (F10-F12) are only ever the snapshot-difference form
  here: throttled top-10 snapshots cannot reconstruct event-level order flow,
  and the code says so.

## 3. Evaluation rules that came out of the chain

- **Rank-IC of 0.02-0.05 is a real result.** A return-side R^2 much above
  ~0.01 is leakage until proven otherwise. Contemporaneous impact R^2 (which
  can be 30-70%) and predictive R^2 (~1%) are different quantities.
- **Turnover beside every IC.** Published crypto factor work reports that
  10-16% weekly turnover survives fees while 85% weekly turnover loses about
  half the gross return (the specific reference was not retained - treat the
  numbers as illustrative, the rule as the point).
- **Fit and score per symbol or liquidity tier.** Crypto microstructure
  patterns do not transfer across assets; a pooled model produces phantom IC.
- **Two-stage funnel.** Cheap screen first (z-scores and decile forward
  returns), full walk-forward only for survivors.
- **Trial budget with multiple-testing deflation.** A sweep champion that
  flips under a different seed or a data shuffle is rejected.
- **Short-term reversal is the one classic factor that does not survive
  institutional costs** (AQR's trading-cost work on its own fills). That
  finding names the rule "no fast signal is standalone" used throughout this
  library.

## 4. Honest negatives: sources that do not exist

The research chain searched for the following and found that they do not
exist. Do not cite them.

- **Public alpha research from Two Sigma.** No public material describes
  its production signals, portfolio weights, or execution stack. The Factor
  Lens is a *risk* lens, not an alpha library, and the regime white paper
  states in its own text that the model is not predictive. There is no
  "Two Sigma OFI study".
- **Public research from Jump Trading's traditional-finance business.** The
  corporate site is a recruiting brochure; the crypto side's microstructure
  views can only be inferred from market-structure proposals and an oracle
  design.
- **An engineering or research blog from Citadel or Citadel Securities.**
  Third-party interview sites claim a "Citadel tech blog"; it does not exist.
  The only substantive technical material is a cloud-vendor case study.
- **Signal methodology from Jane Street or Hudson River Trading.** Jane
  Street's blog is about OCaml and engineering; HRT's blog is engineering and
  culture. Neither publishes how it builds signals. Wintermute and Tower
  publish nothing.
- **A crypto paper from AQR.** There is none; only televised commentary.
- **Factor research from Binance Research**, which publishes macro
  narratives and token reports, and **an engineering blog from Binance**,
  which does not exist.
- **A "Two Sigma order-flow-imbalance" result** and **a "Jump-designed
  oracle" claim**: neither appears in the primary documents.

One citation in the original chain was itself wrong and is corrected here:
the cross-venue lead-lag result is Alexander and Heck, *Journal of Financial
Stability* 50 (2020), 100776 - the direction (unregulated derivatives
venues lead, spot follows) stands, the originally cited DOI did not.

## 5. Ideas collected but never verified

The research chain behind this document collected several dozen factor ideas
and verified a fraction of them (merged into F1-F15 above); the exact counts
are an internal tally, not a published figure. The following families were
**not** verified and must not be cited as vetted:

- on-chain / NVT-style metrics (active addresses, network value to
  transactions, stablecoin net flows);
- calendar and day-of-week effects (the crypto literature is split; a likely
  overfitting trap);
- an Amihud-style cross-sectional illiquidity premium (highly collinear with
  low volatility; poor fee-after prospects);
- open-interest change x price change quadrants;
- liquidation-cascade detectors (public liquidation streams are throttled
  and structurally incomplete).
