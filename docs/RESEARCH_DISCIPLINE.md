# Research discipline

Purpose: find factors and parameters that survive an untouched window - not
to produce a flattering backtest. The library's job is honest evidence; the
alpha, if any, is yours.

## The loop

1. **Hypothesis first.** Write down what should work and why (a regime
   effect, a microstructure mechanism, a flow imbalance) *before* touching
   data. A hypothesis written after the sweep is a description of the noise
   the sweep found.

2. **Run it** on your own recorded bars (see `docs/DATA.md`):

   ```
   python -m quantdesk.backtest --symbols XYZ-USD --granularity 1d \
       --mode discrete --signal institutional \
       --start 2024-01-01 --end 2025-06-30 \
       --cost-bps 10 --slippage-bps 5 --lake-root /path/to/lake \
       --out runs/xyz_institutional.json
   ```

   Weight mode runs the volatility-scaled TSMOM target-weight rule with a
   sweepable no-trade band:

   ```
   python -m quantdesk.backtest --symbols XYZ-USD --granularity 1d \
       --mode weight --no-trade-band 0.10 --sigma-target 0.10 \
       --cost-bps 10 --slippage-bps 5 --lake-root /path/to/lake
   ```

   An empty lake fails with an actionable message; there is no network
   fallback of any kind.

3. **Always run the two built-in baselines on the same window**:
   `--signal buy_and_hold` and `--signal random`. A candidate that does not
   beat buy-and-hold **net of costs** is dead. Do not rationalize it.

4. **Report the trial count.** "Sharpe 1.2 on attempt #1" and "best of 40
   attempts" are different results. Keep a running log (a
   `research/experiments.md` in your own workspace is enough): date, config,
   window, metrics, and the attempt number *for that signal family*. Two
   "different ideas" that are the same hypothesis in different clothes share
   one budget.

5. **Parameter sensitivity: +/-20%.** Neighbors of the chosen parameters at
   +/-20% must not flip the sign of the result. A spike surrounded by losses
   is curve fitting - reject it. The volatility target in TSMOM is a special
   case: it changes notional and fee load, not Sharpe; sweeping it "for
   Sharpe" means the harness is broken.

6. **Costs are not optional, and 2x is the fragility test.** Decide the
   venue's real per-side cost (60 bps maker / 120 bps taker is a common
   retail tier; a retail venue measured in 2026-08 quoted ~190 bps round trip
   as markup) and run the candidate again at **twice** that cost. Any edge
   that dies at 2x assumed costs is too fragile to trade on paper, let alone
   live. The site's cost grid (0/10/20/40/60/120 bps) is the same test
   applied to the demo.

7. **Touch-once holdout.** Hold out the most recent window. Evaluate each
   signal family on it exactly once, and record that you did. If you tuned
   on it, say so and treat the holdout as spent - the number is now
   in-sample.

## Hard honesty rules

- Never present an in-sample number as the result.
- Never tune on the holdout. If you did, say so and invalidate it.
- Paper fills are optimistic (no queue position, immediate fill at the
  crossing price). Any paper-versus-backtest comparison must state this.
- Rank-IC 0.02-0.05 is the register of a real time-series factor. A much
  larger |IC| on a short sample is noise or leakage until it survives a fresh
  window; the empirical null band on the demo site shows what a random walk
  produces.
- Contemporaneous R^2 and predictive R^2 are different quantities. Never
  report one as the other.
- No cross-sectional IC on a tiny universe. The board computes time-series
  IC per symbol and says so.
- Decision replay exists so that a set of recorded decisions can be swept
  deterministically across cost and band parameters instead of being
  regenerated per parameter combination (`--signal replay --replay-path`).
  Use it; it keeps the trial count honest.

## What a result write-up must contain

| field | why |
|---|---|
| hypothesis (written before the run) | rule 1 |
| window, symbols, granularity | reproducibility |
| costs assumed, and the 2x-cost result | rule 6 |
| both baselines on the same window | rule 3 |
| trial number within the signal family | rule 4 |
| +/-20% neighbors | rule 5 |
| whether the holdout was touched, and when | rule 7 |
| turnover beside every IC or Sharpe | fees are paid on turnover, not on IC |
| a sentence saying fills are simulated | paper optimism |

A result missing any row is not a result yet.
