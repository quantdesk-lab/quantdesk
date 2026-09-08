# The search loop

`quantdesk.search` is a deterministic, standard-library-only closed loop: a
seeded mutation designer proposes factor expressions, the library's own
Rank-IC gates judge them, every verdict is archived, the search policy learns
from the archive, and the trailing holdout is touched exactly once. There is
no language model anywhere in it. This page states what the loop does, what
its numbers mean, what it is expected to show on the synthetic fixtures, and
what it does **not** claim.

## The loop

```
seeds (7 expressions, one family each)
   |
   v
bandit.choose() -> (family, deepen | widen)          Thompson sampling, Beta(1,1) arms
   |
   v
designer.propose(mode, family, parents)               widen: grammar sample
   |                                                  deepen: window_step | swap_op |
   |                                                          wrap | subtree | crossover
   v
caps: depth <= 5, size <= 12, <= 2 nested windows, warmup <= 120 bars
   |            (rejected proposals are archived and counted, never repaired)
   v
judge: ONE in-sample Rank-IC at horizon 1 ------> refused (< 30 pairs; not a trial)
   |   |IC| > deflated bar(n, N)?  --------------> noise
   |   |rho| > 0.7 vs an archived survivor? -----> redundant
   |   majority of blocks disagree on sign? -----> unstable
   v                                              candidate
archive.append(record)   ledger.N += 1   bandit.update(family, mode, cleared_null)
   |
   v  (after the last generation)
re-check every candidate at the FINAL N; top 3 touch the holdout ONCE;
fee-after cost grid on the holdout bars; HoldoutSpent on any second touch.
```

Every proposal, including refusals, duplicates and cap rejections, is one
record in the archive (`Archive.to_jsonl`). Records carry `parents` and
`op`, so `Archive.lineage(expr_id)` walks any survivor back to its seed from
the archive alone. `Archive.replay` re-judges every record against the same
bars and gates and returns the ids that differ - empty on a faithful
archive, which is the reproducibility test.

## The numbers

- **In-sample IC**: time-series Spearman between the factor and the next
  bar's log return on the in-sample rows, through `board.ic_for` with its
  30-pair refusal unchanged. The forward return of an in-sample row never
  reaches the holdout: a gap of `purge + embargo` (24 + 24 bars) separates
  the two, and the IC of a range is computed with the returns formed inside
  that range only.
- **The deflated bar.** Under the null a Spearman correlation over `n`
  pairs has standard deviation about `1 / sqrt(n - 1)`. After `N` scored
  trials the family-wise (Sidak, max-of-N) bar at level `q = 0.95` is

  ```
  t(n, N) = kappa * z((1 + q^(1/N)) / 2) / sqrt(n - 1)
  ```

  `kappa` is the root-mean-square of `|IC| * sqrt(n - 1)` over the
  empirical null run (`null.json` `samples`; about 1.0, pinned to
  `[0.85, 1.20]` by test), so the empirical band *checks* the analytic form
  instead of being read off a pooled quantile that mixes pair counts. The bar
  rises with every trial: at 1870 pairs it is about 0.045 after one trial and
  about 0.075 after fifty. Duplicates, refusals and rejections do not raise
  `N`. Candidates are positively dependent, which makes Sidak conservative -
  the bar can only be too strict, never too loose.
- **Blocks and sign agreement.** The in-sample region is cut into three
  contiguous blocks with the trailing horizon row dropped at each edge. A
  candidate whose block ICs disagree in sign with the in-sample IC in the
  majority of printable blocks is `unstable`. Majority, not unanimity: with
  three blocks of about 600 bars (sd about 0.04) a real IC of 0.04 would
  fail an all-agree rule about half the time.
- **Holdout.** The top three candidates that still clear the bar at the
  final `N` are evaluated once on the holdout (factor values from the full
  series, forward returns inside the holdout). The one-sided p-value in the
  direction predicted in-sample is `1 - Phi(ic * sqrt(n - 1))`, adjusted
  for the `k` candidates that competed: `p_adj = 1 - (1 - p)^k`. A candidate
  passes at `p_adj < 0.05` with the predicted sign.
- **Fee-after.** A long/flat position from the sign of the factor on the
  holdout bars, filled at the next open by the package's own weight engine
  (simulated fills at the crossing price, no queue position), at
  0/10/20/40/60/120 bps per side. `dies_at_bps` is the first cost at which
  the net return is not positive; a survivor is `standalone` only if the
  edge outlives twice the default cost, otherwise `feature-only`. A one-hour
  signal trades every bar, so on the planted fixture the edge dies at about
  10 bps per side - which is the honest result and is pinned by test.
- **Reported, never gated**: the horizon-24 IC (with the board's `n_eff`
  gate), the decay sweep, the lag-1 turnover proxy.

## What the fixtures are expected to show

The site runs the loop on two synthetic hourly series of 2400 bars each
(`scripts/build_site.py`: `SEARCH_BARS`, `PLANTED_SEED`, `PLANTED_PHI`):

- **WALK-1**, a seeded geometric Brownian motion. The loop must converge to
  refusal: no candidate clears the final bar, or the ones that do fail the
  holdout. The exporter's site contract fails the build if the random walk
  passes its holdout.
- **PLANTED-1**, the same generator with an AR(1) component on log returns,
  `phi = -0.12`, variance-matched to the walk. The rank correlation of
  `-1 * delta(close, 1)` with the next bar's return is about `0.93 * |phi|`,
  i.e. about 0.11 (sd about 0.023 on 1870 pairs), and decays within two or
  three bars. The loop must recover a one-bar reversal expression whose
  in-sample IC clears the deflated bar, and its single holdout touch must
  pass.

Why the planted effect sits **above** the 0.02-0.05 institutional register:
a real IC of 0.04 needs about `(3.3 / 0.04)^2`, roughly 6800, independent
pairs to clear a fifty-trial deflated bar. At 2400 hourly bars nothing in
the register can be recovered by any honest procedure; a demonstration that
finds nothing on both series would show the gates working but not the loop
learning. The planted IC is therefore chosen so that the loop can recover
it, and the walk is there so the reader can see the same loop refusing.

One holdout is one draw. Across planted seeds 7 to 13 the top finalist
passed its single holdout touch in five of seven runs (`tests/test_search_loop.py`
pins at least three of the five seeds 7-11); the site uses seed 9. A seed
on which the true effect fails a 480-bar holdout is not a bug, it is what
"touch once" means.

The bandit's forty-eight pulls over twelve arms per series demonstrate the
mechanism - posteriors move in the direction of the family that clears the
bar - not convergence.

## Running it on your own bars

```
python -m quantdesk.search --lake-root /path/to/lake --symbol XYZ-USD \
    --granularity 1h --generations 8 --per-generation 6 \
    --archive runs/xyz.jsonl --out runs/xyz.json
python -m quantdesk.search --lake-root /path/to/lake --symbol XYZ-USD \
    --archive runs/xyz.jsonl --resume --generations 4
```

Bars come from the documented Parquet lake (`docs/DATA.md`); an empty lake
fails with an actionable message and there is no network fallback. The
archive is the state that improves across runs: `--resume` continues the
generation and trial numbering, rebuilds the bandit posteriors from the
archived verdicts, and refuses a second holdout touch (exit code 3). Pass
`--null-doc site/data/null.json` to calibrate `kappa` from the empirical
null run instead of using the analytic 1.0. Archives are JSON Lines under
`runs/`, which is git-ignored; the public tree carries no archive.

## What is not claimed

- Not "self-improving on real data": the loop learns from its own archive on
  synthetic data, and on your own lake it will do exactly what the gates
  allow. Nothing on the site was computed on venue data.
- Not bandit convergence.
- Not "alpha": a survivor is a `candidate` that passed one holdout touch and
  a cost grid; `docs/HONESTY.md` rule 5 still applies.
- Not walk-forward cross-validation: one purged and embargoed split with
  block stability is what exists (`docs/ROADMAP.md`).
- Not a deflated Sharpe: the deflation is at the IC level; the fee-after
  evidence is the cost grid and `dies_at_bps`.
- Not a recommendation to trade anything.
