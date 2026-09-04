# Data: synthetic fixtures and bring-your-own candles

QuantDesk ships **no market data** and **no venue client**. Everything the
demo site shows is computed at build time on synthetic geometric-Brownian-
motion paths. To run the library on real prices you record your own data, in
the layout described below, and point the library at it. This page explains
both halves and the reasoning behind the split.

## 1. Synthetic fixtures (what the site uses)

`quantdesk.demo.fixtures` generates deterministic OHLCV bars from a seeded
geometric Brownian motion:

- symbols `SYN-1`, `SYN-2`, `SYN-3`;
- hourly bars for the alpha board (350 fetched, of which the still-forming
  last bar is dropped, so 349 closed bars - `bars_1h` in `build.json`
  carries the exact count) and daily bars for the momentum rows (enough for
  the 263-bar TSMOM warmup);
- open = previous close, high/low drawn around the open-close path, volume a
  positive lognormal draw - the shape the factor functions expect, with none
  of the microstructure of a real venue;
- fully reproducible from `(seed, symbol)`; the seed is written into
  `site/data/build.json`.

Synthetic bars have **no predictable structure by construction**. Their
purpose is to exercise every code path (warmups, IC gates, decay, the
cost grid, the ticket stream) and to calibrate the empirical null band in
`site/data/null.json`. A factor that reports an IC on synthetic bars is
reporting noise; the null band shows how large that noise is.

Nothing about the fixtures should be mistaken for a market.

## 2. Bring your own 1-minute candles

`quantdesk.backtest.lake_data` and `quantdesk.research.microstructure_lake`
read a hive-partitioned Parquet lake. Point them at it with the environment
variable `QUANTDESK_LAKE_ROOT` or the `--lake-root` flag; the default is
`./data/lake` under the current working directory.

```
python -m quantdesk.backtest --symbols XYZ-USD --granularity 1h \
    --mode weight --lake-root /path/to/lake
```

### Layout (lake_v1)

```
{lake_root}/{venue}/{table}/date=YYYY-MM-DD/{HH}-{writer}.parquet
```

- `venue`: lowercase venue label of your choice (the reader merges across
  every venue directory it finds);
- `date`/`HH`: UTC date and hour of the rows in the file;
- `writer`: any short tag for the process that wrote the file;
- files ending in `.tmp` are treated as in-progress writes and are never
  read - write to `.tmp` and rename atomically when done.

All timestamps are microseconds since the epoch, UTC (`timestamp[us, UTC]`
in Arrow). All prices and sizes are float64. `product_id` is the symbol
string you pass on the command line.

#### Table `candles_1m`

| column | type | notes |
|---|---|---|
| venue | string | |
| product_id | string | |
| ts | timestamp[us, UTC] | candle **open** time |
| open, high, low, close | float64 | |
| volume | float64 | base-asset units |

#### Table `market_trades`

| column | type | notes |
|---|---|---|
| venue | string | |
| product_id | string | |
| ts | timestamp[us, UTC] | event time |
| trade_id | string | venue-native id |
| price | float64 | |
| size | float64 | base-asset units |
| side | string | `BUY` / `SELL` (taker side) |

#### Table `book_top10`

One row per book snapshot.

| column | type | notes |
|---|---|---|
| venue | string | |
| product_id | string | |
| ts | timestamp[us, UTC] | |
| seq | int64 | per-connection sequence number of the last applied message; -1 if unknown |
| bid_px_1..bid_px_10 | float64 | level 1 = best; NaN if depth < N |
| bid_sz_1..bid_sz_10 | float64 | |
| ask_px_1..ask_px_10 | float64 | |
| ask_sz_1..ask_sz_10 | float64 | |

The three Arrow schemas are available programmatically from
`quantdesk.lake.schemas` (`candles_schema()`, `trades_schema()`,
`book_top10_schema()`); pyarrow is imported lazily so the core library stays
dependency-free.

### Reader rules (pinned by tests)

- Rows merge across every venue directory and every file; duplicates by `ts`
  resolve with the last write winning, in sorted-file-path then row order.
- A missing lake root, an unknown product, or an unreadable file yields an
  empty result or a skipped file, never an exception.
- `--start`/`--end` apply to the 1-minute rows **before** resampling.
- Resampling to coarser bars is deterministic: bucket key is
  `floor(epoch_seconds / span)`; open = first row, high = max, low = min,
  close = last row, volume = sum; the emitted timestamp is the bucket start.
- Interior buckets with gaps aggregate whatever minutes exist (their span has
  elapsed, so they are finished bars).
- The **trailing** bucket is emitted only when its final minute is present.
  A partially covered last bucket would present an unfinished bar as
  finished - that is lookahead, and it is refused.

### CSV instead of Parquet

If you do not want pyarrow, load your bars yourself into
`quantdesk.backtest.types.Bar` objects (timestamp, open, high, low, close,
volume) and call `run_backtest` / `run_weight_backtest` directly; the engine
does not care where the bars came from. The factor functions take plain
lists of floats.

## 3. Why no venue fetcher and no recorded data

This repository deliberately contains no code that connects to an exchange
and no data that was recorded from one. The decision follows from the terms
under which public market-data APIs are offered:

- **Coinbase Developer Platform Terms of Service, section 9 ("Use
  Restrictions")** - checked 2026-09-03 at
  <https://www.coinbase.com/legal/developer-platform/terms-of-service>.
  The restrictions in that section, as we read them, prohibit collecting,
  caching, storing, or sharing data obtained through the API beyond the
  purposes the terms permit, and prohibit automated recording of API data.
  Consult the section itself; the summary here is ours, not the venue's.
- **OKX API Agreement, section 9.4** - as we read it, forbids redistribution
  of market data obtained through the API, including data from endpoints
  that require no key.

A library that shipped a recorder for those endpoints, or a lake full of
their output, would be inviting every user to breach those terms and would
itself be redistributing data it has no right to redistribute. So:

- no venue fetcher is included, for any venue;
- no recorded venue data is included, and the demo site is built from
  synthetic fixtures only;
- the lake schema above is a **storage layout**, not a data source.

If you record your own data into this layout, you are responsible for your
venue's terms. Read them before you start a recorder; many permit personal,
non-redistributed use and prohibit sharing the output, which is compatible
with keeping a private lake and incompatible with committing it to a public
repository.

## 4. What the site's JSON files contain

| file | content | source |
|---|---|---|
| `site/data/build.json` | build metadata: package and Python versions, fixture kind and seed, gates, default costs | build script |
| `site/data/board.json` | the research board payload for `SYN-1..3` | `quantdesk.research.board.compute_factors` on synthetic bars |
| `site/data/backtest.json` | equity curves, buy-and-hold, metrics, cost grid, ticket stream | `quantdesk.backtest` on synthetic bars |
| `site/data/null.json` | empirical absolute-Rank-IC null band from reseeded random walks | `quantdesk.research.null_calibration` |

Every file carries a note stating that the figures are synthetic. There is
no venue data anywhere in the tree, and CI scans for venue identifiers to
keep it that way.
