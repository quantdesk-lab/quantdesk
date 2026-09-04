# Honesty checklist

Every number this repository prints, every sentence in its docs, and every
pull request that touches a factor or a metric is held to the rules below.
They are not aspirations; most of them are enforced in code (the section
"Where it is enforced" names the gate). If a rule cannot be met, the payload
says so instead of printing a number.

## 1. The Rank-IC register is 0.02-0.05

A time-series Spearman rank correlation between a factor and forward log
returns of 0.02-0.05 is a normal, institutionally respectable result. Anything
much larger on a small sample is treated as noise or leakage until it
survives a fresh, untouched window. The research board says this in its
`disclaimer` field, and `docs/FACTOR_VERDICTS.md` uses this register for every
verdict.

Where it is enforced: `quantdesk.research.board` refuses to print an IC below
`_MIN_IC_PAIRS = 30` aligned pairs (it still reports `n`), and refuses
overlapping-horizon ICs whose effective sample `n_eff = n // h` is below
`_MIN_IC_EFF = 8`. `quantdesk.backtest.metrics.spearman_rank_ic` returns
`None` below 3 pairs or on constant inputs. The empirical null band in
`site/data/null.json` shows what |IC| a random walk produces, so a reader can
see when a reported IC is indistinguishable from noise.

## 2. Contemporaneous R^2 is not predictive R^2

Order-flow imbalance explains a large share of the *same-interval* mid move
(the published contemporaneous R^2 is tens of percent). The *next-interval*
predictive R^2 is a different quantity, roughly two orders of magnitude
smaller. Never present one as the other. The microstructure module labels
its outputs as execution-layer observables and the lake-fed panel carries the
string "observables only; no IC evaluation yet" precisely so no one mistakes
a book-shape number for a forecast.

## 3. Verdicts are fee-after, never fee-before

A factor's verdict is decided after the round-trip cost of the venue it
would trade on. At 60 bps maker / 120 bps taker per side, a round trip costs
120-240 bps; at a retail venue with a measured ~190 bps round-trip markup
the bar is similar. A signal whose typical move over its holding horizon is
below twice that number is not discussed as a trading signal. The backtester
charges `cost_bps + slippage_bps` on every fill, and the site's cost grid
re-runs the same strategy at 0/10/20/40/60/120 bps so the reader sees where
the edge dies.

## 4. Paper fills are optimistic

The event backtester and the grid replay fill at the crossing price with no
queue position, no partial fills, and no adverse selection. They overstate
maker fill rates and understate slippage on thin books. Any comparison
between a simulated fill and a real one must say this. The docstrings of
`quantdesk.backtest.engine` and `quantdesk.reference.grid` say it; repeat it
in any write-up.

## 5. Words that are banned

- "zero-copy" - Parquet decoding and memory transfers are real work.
- "fully autonomous" and "24/7" as a claim about a system - nothing here
  runs unattended, and the 24/7 in this repository refers only to the
  365-day annualization of crypto returns.
- "real-time" without a measured latency figure beside it.
- "alpha" as a noun for anything that has not cleared rule 3 on an untouched
  window.

## 6. No unmeasured speedups

Do not write "10x faster" or "GPU-accelerated" about anything that has not
been timed on a named machine with a named input, with the timing script in
the repository. QuantDesk is pure standard-library Python with no performance
claims at all; it is intended to be correct and readable, not fast.

## 7. Report trial counts

"Sharpe 1.2 on the first attempt" and "Sharpe 1.2, best of forty attempts"
are different results, and only the second one is likely. Every reported
backtest carries a `trial_count`; the site fixtures carry `trial_count: 1`
because they are a single deterministic run on synthetic data. Keep a running
log of attempts per signal family (see `docs/RESEARCH_DISCIPLINE.md`) and
deflate expectations accordingly.

## 8. Touch-once holdout

Hold out the most recent window and evaluate a signal family on it exactly
once. If the holdout was used for tuning, the result is in-sample - say so,
and treat the holdout as spent. Never present an in-sample number as the
result.

## 9. No cross-sectional IC on tiny universes

A rank over three symbols carries about 1.6 bits of information; a
cross-sectional IC over such a universe is a coin flip dressed as a
statistic. The research board computes **time-series** IC per symbol only and
states that convention in `ic_convention`. Cross-sectional Rank-IC with
breadth gates is a roadmap item and will refuse to run below a minimum
breadth when it exists.

## 10. Counts are generated or checked, never merely typed

Bar counts, symbol lists, IC sample sizes, gate values and every number the
site shows are produced by `scripts/build_site.py` at build time and read
from `site/data/*.json`; the page never carries a typed-in number. The test
count in the README is stamped by the release build and then **checked, not
trusted**: `scripts/check_test_count.py` runs `pytest --collect-only`, finds
every test count the README states (badge and prose), and fails CI when any
of them drifts from the collector. Prose numbers in the docs that are not
produced by a build (a bar count in `DATA.md`, a fee tier) name the artefact
or source that carries the authoritative value. A number typed by hand into a
document with no check behind it is a number that will be wrong within a
month.

## 11. Honest negatives are results

A factor that fails, a source that turns out not to exist, a premise that is
disproved: each is recorded with the same care as a success.
`docs/FACTOR_VERDICTS.md` keeps a list of sources that were searched for and
do not exist, so nobody cites them again.

## 12. Roadmap items are labeled NOT BUILT

`docs/ROADMAP.md` lists what this library does not do. Nothing in that file
may be described elsewhere in the present tense. If a doc or a docstring
describes a capability, the capability exists and has a test.

## 13. Not investment advice

Nothing in this repository is investment advice, a recommendation, or an
offer to trade. The policy table maps a labeled market state and a
confidence number to a target weight for the purpose of backtesting and
explanation. It does not know your situation, your venue, your tax position,
or the future. All figures on the demo site are computed on synthetic
geometric-Brownian-motion paths and have no relationship to any real asset.

## Where it is enforced

| rule | mechanism |
|---|---|
| IC refusals (1, 9) | `quantdesk.research.board` gates `_MIN_IC_PAIRS`, `_MIN_IC_EFF`; `spearman_rank_ic` returns `None` on < 3 pairs |
| no lookahead | prefix-determinism tests over every alpha in `tests/test_alpha101.py`; the weight backtester decides on close(t) and fills at open(t+1); the lake resampler drops the trailing partial bucket |
| fee-after (3) | `cost_bps` + `slippage_bps` charged per fill in both engine modes; site cost grid |
| paper optimism (4) | stated in engine and grid docstrings; every ticket outcome that carries a fill carries `fill_kind: "simulated"` and the site drawer labels it |
| execution-layer labels (2) | `use_class` string in the microstructure payload |
| synthetic-only site (13) | `site/data/build.json` names the fixture kind and seed; no venue data exists in the tree |
| forbidden claims (5, 6) | reviewers check this file |
| hand-carried counts (10) | `scripts/check_test_count.py` in CI compares the README's test counts with `pytest --collect-only` |
| leaked identifiers | CI runs `scripts/scan_forbidden.py --strict`: generic detectors (CJK, personal-path shapes, secret shapes, bytecode and data artefacts) plus a private word list supplied through the `SCAN_PRIVATE_PATTERNS` secret - the public scanner deliberately carries no list of names; locally, run it after `git clean -fdX` or accept that gitignored caches are skipped by default |
