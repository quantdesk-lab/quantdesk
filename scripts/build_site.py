#!/usr/bin/env python
"""Build ``site/data/{build,board,backtest,null}.json`` from SYNTHETIC fixtures.

Every number the static site shows comes from this script running the
library on seeded geometric-Brownian-motion bars (``quantdesk.demo.fixtures``)
at build time. No venue data is read, stored, or redistributed.

    python scripts/build_site.py                # -> site/data/
    python scripts/build_site.py --out /tmp/x --seed 11 --symbols SYN-1,SYN-2 --reseeds 5

Robustness contract: a module that raises does NOT abort the build -- its
file is written as ``{"ok": false, "error": "..."}`` so a partial site still
deploys and renders the failure honestly. The exit code is 0 unless the
output directory itself cannot be written.
"""
from __future__ import annotations

import argparse
import json
import math
import platform
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = "quantdesk-site/1"
NOTE = (
    "All figures on this site are computed on synthetic geometric-Brownian-motion "
    "bars at build time. No venue data is stored, displayed, or redistributed."
)
COST_GRID = (0, 10, 20, 40, 60, 120)          # per-side bps swept by the backtest page
GATES_DEFAULT = {"min_ic_pairs": 30, "min_ic_eff": 8}
BOARD_BARS = 350                               # the board's own fetch limit (1h and 1d)
BACKTEST_BARS_1D = 760                         # ~2y of daily bars: 263 warmup + ~500 decisions


def _import_quantdesk():
    """``import quantdesk`` from the installed package, else from ``src/``."""
    try:
        import quantdesk  # noqa: F401
    except ImportError:
        sys.path.insert(0, str(ROOT / "src"))
        import quantdesk  # noqa: F401
    return sys.modules["quantdesk"]


def _scrub(text: str) -> str:
    """Keep machine paths out of the public tree."""
    return text.replace(str(ROOT), "<repo>").replace(str(Path.home()), "~")


def _guard(label: str, fn: Callable[[], Any]) -> Any:
    """Run ``fn``; on any exception return an ``ok:false`` document instead of
    crashing, so the other files (and the site) still ship."""
    t0 = time.perf_counter()
    try:
        out = fn()
        print(f"  {label:9s} ok      {time.perf_counter() - t0:6.1f}s")
        return out
    except Exception as exc:  # noqa: BLE001 -- the whole point is to survive
        traceback.print_exc(limit=4, file=sys.stderr)
        print(f"  {label:9s} FAILED  {type(exc).__name__}: {_scrub(str(exc))[:200]}", file=sys.stderr)
        return {"ok": False, "error": _scrub(f"{type(exc).__name__}: {exc}")[:600]}


def _clean(obj: Any) -> Any:
    """JSON-safe copy: NaN/inf -> null, tuples -> lists, datetimes -> ISO."""
    if isinstance(obj, float):
        return obj if math.isfinite(obj) else None
    if isinstance(obj, dict):
        return {str(k): _clean(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_clean(v) for v in obj]
    if isinstance(obj, datetime):
        return obj.isoformat()
    return obj


def _write(out: Path, name: str, doc: Any) -> int:
    path = out / name
    text = json.dumps(_clean(doc), separators=(",", ":"), allow_nan=False, ensure_ascii=True)
    path.write_text(text + "\n", encoding="utf-8")
    size = path.stat().st_size
    print(f"  wrote {name:14s} {size:>10,d} bytes")
    return size


def _closed_rows(rows: list[list[Any]], bar_seconds: float, now: float) -> list[list[Any]]:
    """Drop the still-forming last bar (open + length > now) and junk rows."""
    keep = []
    for row in rows or []:
        try:
            ts = float(row[0])
        except (TypeError, ValueError, IndexError):
            continue
        if ts + bar_seconds <= now:
            keep.append(row)
    return keep


# --------------------------------------------------------------------------- #
def build_board(qd_symbols: list[str], client: Any, now: float) -> dict[str, Any]:
    from quantdesk.research.board import compute_factors

    return compute_factors(qd_symbols, client, now=now, with_funding=False)


def build_backtest(qd_symbols: list[str], client: Any, now: float) -> dict[str, Any]:
    from quantdesk.research import tickets as tk

    symbols: dict[str, Any] = {}
    for sym in qd_symbols:
        rows = _closed_rows(client.get_candles(sym, "1d", limit=BACKTEST_BARS_1D), 86400.0, now)
        symbols[sym] = _guard(
            f"bt:{sym}",
            lambda sym=sym, rows=rows: tk.backtest_summary(sym, rows, cost_grid=COST_GRID),
        )
    band = getattr(tk, "DEFAULT_BAND", 0.10)
    return {
        "symbols": symbols,
        "signal": getattr(tk, "SIGNAL_NAMES", {}).get("policy", "tsmom_policy"),
        "weight_mode": "policy",
        "band": float(band),
        "note": getattr(tk, "_NOTE", NOTE),
    }


def build_null(reseeds: int, bars: int, seed: int) -> dict[str, Any]:
    from quantdesk.research.null_calibration import null_ic_distribution

    return null_ic_distribution(reseeds, bars, seed0=1000 + seed)


def gates_from_board() -> dict[str, int]:
    try:
        from quantdesk.research import board

        return {
            "min_ic_pairs": int(getattr(board, "_MIN_IC_PAIRS", GATES_DEFAULT["min_ic_pairs"])),
            "min_ic_eff": int(getattr(board, "_MIN_IC_EFF", GATES_DEFAULT["min_ic_eff"])),
        }
    except Exception:  # noqa: BLE001 -- the stamp must still be written
        return dict(GATES_DEFAULT)


def cost_defaults() -> dict[str, float]:
    try:
        from quantdesk.backtest.config import SLIPPAGE_BPS, TRADING_COST_BPS

        return {"trading": float(TRADING_COST_BPS), "slippage": float(SLIPPAGE_BPS)}
    except Exception:  # noqa: BLE001
        return {"trading": 10.0, "slippage": 5.0}


# --------------------------------------------------------------------------- #
def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--out", default=str(ROOT / "site" / "data"), help="output directory")
    ap.add_argument("--seed", type=int, default=7, help="fixture seed (default 7)")
    ap.add_argument("--symbols", default="SYN-1,SYN-2,SYN-3", help="comma-separated synthetic symbols")
    ap.add_argument("--reseeds", type=int, default=20, help="random walks for the empirical null")
    ap.add_argument("--null-bars", type=int, default=BOARD_BARS, help="bars per null random walk")
    args = ap.parse_args(argv)

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    symbols = [s.strip() for s in args.symbols.split(",") if s.strip()]
    if not symbols:
        print("no symbols given", file=sys.stderr)
        return 2

    t_start = time.perf_counter()
    qd = _import_quantdesk()
    now = float(int(time.time()))
    print(f"quantdesk {getattr(qd, '__version__', '?')} | python {platform.python_version()} | seed {args.seed} | {symbols}")

    client = _guard("fixture", lambda: _make_client(args.seed, now))
    if isinstance(client, dict):  # fixture itself failed: every data file records why
        board = backtest = dict(client)
    else:
        board = _guard("board", lambda: build_board(symbols, client, now))
        backtest = _guard("backtest", lambda: build_backtest(symbols, client, now))
    null = _guard("null", lambda: build_null(args.reseeds, args.null_bars, args.seed))

    board_ok = isinstance(board, dict) and board.get("ok", True) is not False
    build = {
        "schema": SCHEMA,
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "package_version": getattr(qd, "__version__", None),
        "python_version": platform.python_version(),
        "fixture": {
            "kind": "synthetic-gbm",
            "seed": args.seed,
            "symbols": symbols,
            "bars_1h": board.get("bars_1h") if board_ok else None,
            "bars_1d": board.get("bars_1d") if board_ok else None,
            "backtest_bars_1d": BACKTEST_BARS_1D,
            "null_reseeds": args.reseeds,
        },
        "gates": gates_from_board(),
        "cost_bps_default": cost_defaults(),
        "status": {
            "board": board_ok,
            "backtest": isinstance(backtest, dict) and backtest.get("ok", True) is not False,
            "null": isinstance(null, dict) and null.get("ok", True) is not False,
        },
        "note": NOTE,
    }

    print("output:", _scrub(str(out)))
    total = 0
    for name, doc in (("build.json", build), ("board.json", board), ("backtest.json", backtest), ("null.json", null)):
        total += _write(out, name, doc)
    failed = [k for k, v in build["status"].items() if not v]
    print(f"total {total:,d} bytes in {time.perf_counter() - t_start:.1f}s"
          + (f" | FAILED: {', '.join(failed)} (written as ok:false)" if failed else " | all ok"))
    return 0


def _make_client(seed: int, now: float) -> Any:
    from quantdesk.demo.fixtures import SyntheticClient

    # max_bars covers the backtest's longer daily request; the board's own
    # limit=350 slices the same recent tail, so both views share the bars.
    return SyntheticClient(seed=seed, now=now, max_bars=max(BACKTEST_BARS_1D, BOARD_BARS) + 1)


if __name__ == "__main__":
    sys.exit(main())
