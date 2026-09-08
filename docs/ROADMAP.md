# Roadmap

Everything on this page is **NOT BUILT**. None of it exists in
`src/quantdesk/` today, none of it has tests, and nothing elsewhere in the
documentation may describe any of it in the present tense
(`docs/HONESTY.md`, rule 12). Items are listed in the order they would
unlock each other; no dates are attached because none are known.

Built since 0.1.0 and therefore removed from this page: the closed-loop
factor search with a local judge, the trial ledger with multiple-testing
deflation, and the touch-once holdout enforced in code (`docs/SEARCH.md`,
`quantdesk.search`).

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

## NOT BUILT: what remains of walk-forward evaluation

The search loop has a single purged and embargoed in-sample / holdout split,
block stability, a trial ledger and IC-level deflation (`docs/SEARCH.md`).
What it does not have:

- **rolling multi-fold evaluation for fitted models** - purging and
  embargo between every train and evaluation window once a model with
  parameters estimated on the data exists (today no such model exists; an
  expression has no fitted parameters, so one boundary suffices);
- a **deflated Sharpe** (Bailey and Lopez de Prado 2014) on the fee-after
  backtest of a survivor - on a few hundred holdout bars the standard error
  of an annualized Sharpe is several units, so the number would be
  indefensible; the cost grid and `dies_at_bps` stand in for it;
- rejection of a sweep winner that flips sign under a **different random
  seed or a shuffled start date** - the loop reports block-level sign
  agreement, not a perturbation test.

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

## NOT BUILT: a language-model designer behind the search loop

The loop's designer is a seeded mutation operator by design, so the
repository keeps its "no language model anywhere" property and every run
replays exactly. A model-backed designer would plug into the same
`propose(mode, family, parents)` surface and be judged by the same local
gates; it is not built, and if it ever is, it will live behind an optional
interface with no model call in this package.

Depends on: nothing; deliberately not started.

## NOT BUILT: in-browser recompute via Pyodide

The demo site today renders JSON files computed at build time. Because the
core library is pure standard-library Python, it could run inside the
browser under Pyodide so a reader can change a seed, a cost, a band width,
or a lookback and see the board, the backtest and the search recompute
locally, with no server and no data leaving the page. Not started; the
build-time JSON remains the only site data path.

Depends on: nothing beyond packaging work, but it is deliberately last -
it makes the site more interesting without making the library more honest.

## Explicitly out of scope (not roadmap)

These will not be built in this repository:

- venue clients, recorders, or backfills for any exchange
  (`docs/DATA.md`, section 3);
- order management, execution, approvals, or any path that places orders;
- equity or other non-crypto data feeds;
- performance claims or accelerated implementations.
