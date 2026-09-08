"""``python -m quantdesk.search`` - run the closed-loop search on your own bars.

    python -m quantdesk.search --lake-root /path/to/lake --symbol XYZ-USD \
        --granularity 1h --generations 8 --per-generation 6 \
        --archive runs/xyz.jsonl --out runs/xyz.json [--resume]

Bars come from the documented Parquet lake (``docs/DATA.md``); an empty lake
fails with an actionable message and there is no network fallback of any
kind. The archive is JSON Lines and is the state a later ``--resume``
continues; a second holdout touch on the same archive is refused. The gate
set is the analytic one (``kappa = 1``) unless ``--null-doc`` points at a
``null.json`` produced by ``scripts/build_site.py``.

The lake reader (pyarrow) is imported inside ``main`` so importing this
package never requires pyarrow.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from .archive import Archive
from .gates import calibrate_gates
from .loop import run_search
from .walkforward import HoldoutSpent


def _parse_date(s: str | None) -> datetime | None:
    if not s:
        return None
    return datetime.fromisoformat(s).replace(tzinfo=timezone.utc)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m quantdesk.search",
                                 description=__doc__.split("\n\n")[0])
    ap.add_argument("--lake-root", required=True, help="Parquet lake root (docs/DATA.md)")
    ap.add_argument("--symbol", required=True, help="product id as recorded in the lake")
    ap.add_argument("--granularity", default="1h", help="resample label, e.g. 1h or 1d")
    ap.add_argument("--start", default=None, help="ISO date, inclusive")
    ap.add_argument("--end", default=None, help="ISO date, exclusive")
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--generations", type=int, default=8)
    ap.add_argument("--per-generation", type=int, default=6)
    ap.add_argument("--holdout-frac", type=float, default=0.2)
    ap.add_argument("--purge", type=int, default=24)
    ap.add_argument("--embargo", type=int, default=24)
    ap.add_argument("--top-k", type=int, default=3)
    ap.add_argument("--archive", default=None, help="JSON Lines archive to write (and resume)")
    ap.add_argument("--resume", action="store_true", help="continue the archive at --archive")
    ap.add_argument("--null-doc", default=None, help="null.json to calibrate the gates from")
    ap.add_argument("--out", default=None, help="write the run payload as JSON here")
    args = ap.parse_args(argv)

    from quantdesk.backtest.lake_data import load_lake_candles  # pyarrow, lazily

    bars = load_lake_candles(args.symbol, args.granularity, lake_root=args.lake_root,
                             start=_parse_date(args.start), end=_parse_date(args.end))
    if not bars:
        print(f"no {args.granularity} bars for {args.symbol} under {args.lake_root}: record "
              f"1-minute candles into the lake first (docs/DATA.md); there is no network fallback.",
              file=sys.stderr)
        return 2
    rows = [[b.timestamp.timestamp(), b.open, b.high, b.low, b.close, b.volume] for b in bars]

    null_doc = json.loads(Path(args.null_doc).read_text(encoding="utf-8")) if args.null_doc else None
    gates = calibrate_gates(null_doc)
    archive = Archive()
    if args.archive and Path(args.archive).exists():
        if not args.resume:
            print(f"{args.archive} exists; pass --resume to continue it", file=sys.stderr)
            return 2
        archive = Archive.from_jsonl(args.archive)
    try:
        out = run_search(
            rows, symbol=args.symbol, seed=args.seed, gates=gates, generations=args.generations,
            per_generation=args.per_generation, holdout_frac=args.holdout_frac, purge=args.purge,
            embargo=args.embargo, top_k=args.top_k, archive=archive, resume=args.resume,
            kind=f"lake:{args.granularity}",
        )
    except HoldoutSpent as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 3
    if args.archive:
        archive.to_jsonl(args.archive)
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(json.dumps(out, indent=1, sort_keys=True), encoding="utf-8")

    lg = out["ledger"]
    print(f"{args.symbol}: {out['n_bars']} bars, {lg['n_trials']} trials "
          f"({lg['n_duplicates']} duplicates, {lg['n_refused']} refused, {lg['n_rejected']} rejected), "
          f"gates {out['gates']['version']}")
    best = out["best_so_far"][-1]
    print(f"best in-sample |IC| {best['abs_ic']} vs deflated bar {best['threshold']} "
          f"after {best['n_trials']} trials")
    h = out["holdout"]
    if not h["touched"]:
        print("holdout: not touched (no candidate cleared the final bar)")
    for r in h["results"]:
        fa = r["fee_after"] or {}
        print(f"holdout {r['expr_id']} {r['text']}: ic {r['ic']} n {r['n']} p_adj {r['p_adj']} "
              f"passed {r['passed']}; dies at {fa.get('dies_at_bps')} bps -> {fa.get('label')}")
        chain = archive.lineage(r["expr_id"])
        print("  lineage: " + " <- ".join(f"{c['op']}:{c['text']}" for c in chain))
    return 0
