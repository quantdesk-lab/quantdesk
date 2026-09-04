# NOTICE - provenance and attribution

QuantDesk is released under the MIT License (see `LICENSE`). This file records
where the ideas in the code come from, what was re-implemented, and what was
deliberately not copied. Full bibliographic entries are in `CITATIONS.md`.

QuantDesk is an independent open-source project. It is not affiliated with,
endorsed by, or connected to any company, product or platform that uses the
name "QuantDesk" or any name cited below.

## Alpha101-derived factors (`src/quantdesk/factors/alpha101.py`)

The 19 alphas in this module are derived from Zura Kakushadze, "101 Formulaic
Alphas", arXiv:1601.00991 (2016), published in Wilmott Magazine 2016(84).
The paper states that the alphas are proprietary to WorldQuant LLC and were
published with its permission, and the arXiv license under which the paper
appears grants no reuse right over its contents.

Accordingly, this library:

- re-implements **adapted time-series forms** of the ideas behind alphas
  #1, 2, 3, 4, 5, 6, 9, 12, 23, 24, 28, 32, 41, 43, 46, 51, 53, 54 and 101,
  evaluated per symbol over trailing windows rather than cross-sectionally;
- restates each formula in **this library's own operator notation**
  (`ts_rank`, `ts_scale`, `signedpower`, `delta`, `delay`, `sma`, ...), which
  states what the code computes; the paper's text, notation and
  cross-sectional forms are not reproduced, in docstrings or in the
  `ALPHAS` registry. Honest caveat: for the alphas that use no
  cross-sectional operator (#6, 9, 12, 23, 24, 41, 43, 53, 54, 101) the
  time-series restatement necessarily coincides with the paper's arithmetic
  up to the stated proxies and guards - there is only one way to write
  "minus the 10-bar correlation of open and volume";
- cites the paper alpha number (`paper_ref`) for every entry so the lineage is
  traceable, and tags every departure from the paper (`adaptation`).

WorldQuant and WorldQuant LLC are the names of the rights holder named in the
paper; they are used here only for attribution. This project is not affiliated
with, endorsed by, or derived from any WorldQuant product or platform.

## Time-series momentum and volatility (`src/quantdesk/factors/tsmom.py`)

- Time-series momentum direction and the volatility-scaled position rule:
  Moskowitz, Ooi and Pedersen (2012), Journal of Financial Economics 104(2).
- Parameter choices for crypto - zero-mean EWMA variance, a fast (center of
  mass 5 days) and slow (180 days) estimate averaged, the two-bar estimation
  lag, the {22, 65, 261}-day lookbacks and the 22d+261d blend, and the 10%
  annualized volatility target - are the parameters as published in
  Harvey et al. (2022), "An Investor's Guide to Crypto", Journal of Portfolio
  Management 49(1). The functions here are our own implementation of those
  published choices; no code or text from the paper is reproduced.
- Range-based volatility: Yang and Zhang (2000), Journal of Business 73(3);
  Rogers and Satchell (1991), Annals of Applied Probability 1(4). The
  implementation follows the published estimator definitions; the warning
  about demeaning the Rogers-Satchell term follows Molnar (2012).
- Score winsorization at +/-3 and the median/MAD robust z-score: Grinold and
  Kahn, Active Portfolio Management, 2nd edition (2000).
- The EWMA regression beta with shrinkage toward one follows the recipe
  described in Two Sigma's white paper "Introducing the Two Sigma Factor
  Lens" (2018). Only the method is used; no text or data from the paper is
  included.

## Microstructure factors (`src/quantdesk/factors/microstructure.py`)

- Micro-price: Stoikov (2017/2018), "The micro-price: a high-frequency
  estimator of future prices", arXiv:1708.03135.
- Queue imbalance at the best level: Gould and Bonart (2016), Market
  Microstructure and Liquidity 2(2).
- Order-flow imbalance from consecutive top-of-book snapshots: an
  approximation of the event-level quantity defined in Cont, Kukanov and
  Stoikov (2014), Journal of Financial Econometrics 12(1). The code labels it
  as a snapshot-difference approximation, never as the exact event-level OFI.
- Trade-flow imbalance family: motivated by Silantyev (2019), Digital
  Finance 1, which reports trade-flow imbalance outperforming order-flow
  imbalance on a crypto limit order book.
- Price-impact proxy: a Kyle (1985) lambda-flavored ratio of price move to
  gross volume, with the Amihud (2002) illiquidity intuition at trade
  frequency. It is a proxy, not either paper's estimator.

## Reference strategy math (`src/quantdesk/reference/`)

- `market_making.py` re-derives the reservation price and optimal spread of
  Avellaneda and Stoikov (2008), Quantitative Finance 8(3). Parameter
  vocabulary (`bid_spread`, `order_levels`, `order_level_spread`,
  `inventory_target_base_pct`, `inventory_range_multiplier`) and the linear
  inventory-skew rule follow the naming used by the Hummingbot project
  (Apache License 2.0). No Hummingbot source code is included; the functions
  here are independent implementations of publicly described formulas.
- `cost_floor.py` and `grid.py` are original arithmetic. The venue cost
  presets they carry are dated measurements or documented fee schedules,
  labeled with their provenance, and are inputs to arithmetic rather than
  claims about the future.

## Research board and honesty gates (`src/quantdesk/research/`)

- The Rank-IC register (0.02-0.05 as the institutional norm), the turnover
  column beside every IC, and the distinction between contemporaneous and
  predictive R^2 follow widely published research practice; specific
  pointers are listed in `docs/HONESTY.md` and `docs/FACTOR_VERDICTS.md`.
- The no-trade-band turnover control is the standard approach described,
  among others, in Robot Wealth's public articles on managing turnover.

## Data

This repository ships **no recorded market data** and **no venue client**.
The lake schema in `src/quantdesk/lake/schemas.py` and `docs/DATA.md` is a
storage layout for data you record yourself. See `docs/DATA.md` for the
terms-of-service reasoning behind that decision.

## Trademarks

Product and company names mentioned in this file and in `CITATIONS.md` are
trademarks of their respective owners and are used for identification and
attribution only.
