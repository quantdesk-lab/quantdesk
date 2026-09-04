# Roadmap

Everything on this page is **NOT BUILT**. None of it exists in
`src/quantdesk/` today, none of it has tests, and nothing elsewhere in the
documentation may describe any of it in the present tense
(`docs/HONESTY.md`, rule 12). Items are listed in the order they would
unlock each other; no dates are attached because none are known.

## NOT BUILT: cross-sectional Rank-IC with breadth gates

Today the research board computes **time-series** Spearman IC per symbol
and refuses to compute a cross-sectional IC because a rank over a handful of
symbols is meaningless. The cross-sectional version would:

- take a panel of factor values across N symbols at each timestamp, rank
  within the timestamp, and correlate with next-period returns residualized
  on the market factor (F4 in `docs/FACTOR_VERDICTS.md`);
- **refuse to run below a minimum breadth** (a hard gate on N per
  timestamp, on the order of 30+ symbols, and a hard gate on the number of
  timestamps) the same way the time-series board refuses below 30 pairs;
- report the IC series, its mean and standard error, decile spreads, and a
  turnover column beside every number;
- use residualized momentum (F3) as its first calibration factor precisely
  because that factor's fee-after answer is already known to be "no".

Depends on: a user-supplied panel of 100+ symbols of daily bars. The library
will not fetch them (see `docs/DATA.md`).

## NOT BUILT: walk-forward evaluation with purged cross-validation

Today the backtester runs a single window. The walk-forward protocol would
add:

- rolling train/evaluation splits with **purging** (drop training samples
  whose label horizon overlaps the evaluation window) and an **embargo**
  after each evaluation window;
- a **touch-once holdout** enforced in code: the most recent window is
  evaluated once per signal family and the fact is recorded in the output;
- a **trial ledger**: every run of a signal family increments a counter that
  is printed beside the result, with a deflated-Sharpe style adjustment;
- rejection of any sweep winner that flips sign under a different random
  seed or a shuffled start date.

Depends on: nothing external; this is pure library work.

## NOT BUILT: market-residualized momentum

A cross-sectional momentum factor computed on returns **after** removing
each symbol's exposure to the market factor, so a ranking does not collapse
into a ranking by beta. The EWMA beta helper exists
(`quantdesk.factors.tsmom.ewma_beta`); the residual series, the panel
plumbing, and the factor itself do not. Its expected verdict is
**feature-only** (fee arithmetic in `docs/FACTOR_VERDICTS.md`, F3); it is
worth building as the calibration case for the cross-sectional IC pipeline,
not as a signal.

Depends on: the cross-sectional IC pipeline above.

## NOT BUILT: platform-agnostic factor-search loop with a local judge

The sibling project `alpha-evolve-loop` searches over factor expressions
with a language-model designer and an **external** simulator as the judge.
The corresponding loop for this library would replace the external judge
with a **local** one built from the pieces here:

- candidate expressions over the 23-operator time-series library;
- the research board's time-series Rank-IC, decay, and turnover proxy as the
  scoring function, with the same refusal gates;
- the empirical null band (`quantdesk.research.null_calibration`) as the
  acceptance threshold: a candidate is "interesting" only when its |IC|
  leaves the band a random walk produces;
- the fee-after backtest as the final filter.

The designer may be a language model or a plain mutation operator; the
judge must be deterministic and local. Not started.

Depends on: walk-forward evaluation (so the loop cannot overfit to a single
window) and user-supplied data.

## NOT BUILT: in-browser recompute via Pyodide

The demo site today renders JSON files computed at build time. Because the
core library is pure standard-library Python, it could run inside the
browser under Pyodide so a reader can change a seed, a cost, a band width,
or a lookback and see the board and the backtest recompute locally, with no
server and no data leaving the page. Not started; the build-time JSON
remains the only site data path.

Depends on: nothing beyond packaging work, but it is deliberately last -
it makes the site more interesting without making the library more honest.

## Explicitly out of scope (not roadmap)

These will not be built in this repository:

- venue clients, recorders, or backfills for any exchange
  (`docs/DATA.md`, section 3);
- order management, execution, approvals, or any path that places orders;
- equity or other non-crypto data feeds;
- performance claims or accelerated implementations.
