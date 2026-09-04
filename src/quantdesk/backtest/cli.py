from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from .engine import run_backtest, run_weight_backtest
from .lake_data import default_lake_root, load_lake_candles
from .metrics import compute_metrics
from .signals import (
    buy_and_hold,
    institutional_signal,
    momentum_signal,
    random_signal,
    replay_decisions,
    tsmom_weight,
)
from .types import SignalFn


def _parse_date(s: str | None) -> datetime | None:
    if not s:
        return None
    return datetime.fromisoformat(s).replace(tzinfo=timezone.utc)


def _build_signal(name: str, replay_path: str | None) -> SignalFn:
    if name == "buy_and_hold":
        return buy_and_hold()
    if name == "random":
        return random_signal(seed=42)
    if name == "momentum":
        return momentum_signal()
    if name == "institutional":
        return institutional_signal()
    if name == "replay":
        if not replay_path:
            raise SystemExit("--signal replay requires --replay-path")
        return replay_decisions(replay_path)
    raise SystemExit(f"unknown signal: {name}")


def _pct(x: float) -> str:
    return f"{x * 100:+.2f}%"


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m quantdesk.backtest")
    p.add_argument(
        "--symbols", required=True,
        help="comma-separated venue-native product ids (BTC-USD,ETH-USD)",
    )
    p.add_argument(
        "--granularity", default="1h",
        help="resample target for the 1m lake, e.g. 1h/4h/1d (default 1h)",
    )
    p.add_argument(
        "--lake-root", default=None,
        help="parquet lake root (default: $QUANTDESK_LAKE_ROOT or ./data/lake)",
    )
    p.add_argument("--start", default=None, help="ISO date, e.g. 2023-01-01")
    p.add_argument("--end", default=None)
    p.add_argument(
        "--mode",
        default="discrete",
        choices=["discrete", "weight"],
        help="discrete: (regime, confidence) -> one of the policy table's "
             "target-weight actions, sized as fractions of TARGET_WEIGHT_CAP. "
             "weight: continuous vol-scaled target weights with a no-trade band.",
    )
    p.add_argument(
        "--signal",
        default=None,
        choices=["buy_and_hold", "random", "momentum", "institutional", "replay"],
        help="discrete mode only (default: buy_and_hold)",
    )
    p.add_argument("--replay-path", default=None)
    p.add_argument("--initial-capital", type=float, default=10_000.0)
    p.add_argument("--cost-bps", type=float, default=10.0)
    p.add_argument("--slippage-bps", type=float, default=5.0)
    p.add_argument(
        "--rebalance-every", type=int, default=None,
        help="bars between decisions (default: 1 discrete, 7 weight)",
    )
    p.add_argument(
        "--no-trade-band", type=float, default=0.10,
        help="weight mode only: skip rebalances smaller than this weight delta",
    )
    p.add_argument(
        "--sigma-target", type=float, default=0.10,
        help="weight mode only: annualized volatility target",
    )
    p.add_argument("--out", default=None, help="optional JSON dump of full result")
    args = p.parse_args(argv)

    if args.mode == "weight":
        if args.signal or args.replay_path:
            raise SystemExit(
                "--signal/--replay-path apply to --mode discrete; weight mode runs the "
                "vol-scaled TSMOM target-weight rule (quantdesk.factors.tsmom.target_weight)"
            )
    elif args.no_trade_band != 0.10 or args.sigma_target != 0.10:
        raise SystemExit("--no-trade-band/--sigma-target apply only to --mode weight")

    rebalance_every = args.rebalance_every
    if rebalance_every is None:
        rebalance_every = 7 if args.mode == "weight" else 1

    symbols = [s.strip() for s in args.symbols.split(",") if s.strip()]
    start = _parse_date(args.start)
    end = _parse_date(args.end)

    prices = {}
    for sym in symbols:
        try:
            bars = load_lake_candles(
                sym,
                args.granularity,
                lake_root=args.lake_root,
                start=start,
                end=end,
            )
        except Exception as e:  # noqa: BLE001 — surface per-symbol failures and keep going
            print(f"[error] {sym}: {e}", file=sys.stderr)
            continue
        if not bars:
            # The lake reader is honest-empty by contract; at the CLI that must
            # become an actionable failure, not a silently empty backtest.
            root = args.lake_root or default_lake_root()
            print(
                f"[error] lake empty for {sym} under {root} -- bring your own 1m "
                f"candles (see docs/DATA.md)",
                file=sys.stderr,
            )
            continue
        if len(bars) < 2:
            print(f"[warn] {sym}: only {len(bars)} bars available, skipping", file=sys.stderr)
            continue
        prices[sym] = bars

    if not prices:
        print("no usable price data", file=sys.stderr)
        return 2

    if args.mode == "weight":
        result = run_weight_backtest(
            prices=prices,
            weight_fn=tsmom_weight(sigma_target=args.sigma_target),
            initial_capital=args.initial_capital,
            cost_bps=args.cost_bps,
            slippage_bps=args.slippage_bps,
            rebalance_every_n_bars=rebalance_every,
            no_trade_band=args.no_trade_band,
            granularity=args.granularity,
        )
        label = (
            f"weight (vol-scaled TSMOM, band={args.no_trade_band:.2f}, "
            f"sigma*={args.sigma_target:.2f})"
        )
    else:
        result = run_backtest(
            prices=prices,
            signal_fn=_build_signal(args.signal or "buy_and_hold", args.replay_path),
            initial_capital=args.initial_capital,
            cost_bps=args.cost_bps,
            slippage_bps=args.slippage_bps,
            rebalance_every_n_bars=rebalance_every,
            granularity=args.granularity,
        )
        label = args.signal or "buy_and_hold"

    # MERGE, do not assign: run_weight_backtest pre-seeds target_rebalances and
    # a plain assignment would silently destroy it.
    engine_metrics = dict(result.metrics or {})
    result.metrics = compute_metrics(result)
    result.metrics.update(engine_metrics)
    m = result.metrics

    print()
    print(f"Signal     : {label}")
    print(f"Symbols    : {', '.join(prices.keys())}")
    print(f"Period     : {result.equity_curve[0][0].date()} -> {result.equity_curve[-1][0].date()}  "
          f"({len(result.equity_curve)} bars @ {args.granularity})")
    print(f"Capital    : ${args.initial_capital:,.2f}  ->  ${result.final_equity:,.2f}")
    print()
    print(f"  total return   {_pct(m['total_return'])}")
    print(f"  CAGR           {_pct(m['cagr'])}")
    print(f"  ann. vol       {_pct(m['ann_vol'])}")
    print(f"  Sharpe         {m['sharpe']:+.3f}")
    print(f"  Sortino        {m['sortino']:+.3f}")
    print(f"  max DD         {_pct(m['max_drawdown'])}")
    print(f"  Calmar         {m['calmar']:+.3f}")
    print(f"  trades         {int(m['n_trades'])}")
    print(f"  turnover       {m['turnover']:.2f}x")
    print()

    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        dump = {
            "metrics": m,
            "equity_curve": [(ts.isoformat(), v) for ts, v in result.equity_curve],
            "trades": [
                {
                    "timestamp": t.timestamp.isoformat(),
                    "symbol": t.symbol,
                    "action": t.action,
                    "delta_qty": t.delta_qty,
                    "price": t.price,
                    "cost": t.cost,
                }
                for t in result.trades
            ],
            "decisions": [
                {
                    "timestamp": d.timestamp.isoformat(),
                    "symbol": d.symbol,
                    "regime": d.regime,
                    "confidence": d.confidence,
                    "action": d.action,
                }
                for d in result.decisions
            ],
        }
        out_path.write_text(json.dumps(dump, indent=2))
        print(f"wrote {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
