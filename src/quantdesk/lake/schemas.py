"""Lake table schemas (pyarrow), imported lazily so the core package stays stdlib-only.

Layout: ``{lake_root}/{venue}/{table}/date=YYYY-MM-DD/{HH}-{writer}.parquet``;
files ending ``.tmp`` are in-progress writes and are never read. The column
contracts below are frozen -- readers in quantdesk.backtest.lake_data and
quantdesk.research.microstructure_lake depend on them. See docs/DATA.md.

``TRADES_SCHEMA`` / ``CANDLES_SCHEMA`` / ``BOOK_TOP10_SCHEMA`` are resolved on
first attribute access (PEP 562), so ``from quantdesk.lake.schemas import
CANDLES_SCHEMA`` works whenever pyarrow is installed and importing this
module never requires it. They are deliberately absent from ``__all__``
(a static checker cannot see PEP 562 names); import them by name.
"""
from __future__ import annotations

from typing import Any

__all__ = ["trades_schema", "candles_schema", "book_top10_schema"]


def trades_schema() -> Any:
    """market_trades: one taker print per row."""
    import pyarrow as pa

    return pa.schema(
        [
            ("venue", pa.string()),
            ("product_id", pa.string()),
            ("ts", pa.timestamp("us", tz="UTC")),
            ("trade_id", pa.string()),
            ("price", pa.float64()),
            ("size", pa.float64()),
            ("side", pa.string()),
        ]
    )


def candles_schema() -> Any:
    """candles_1m: ``ts`` is the candle OPEN time; volume in base units."""
    import pyarrow as pa

    return pa.schema(
        [
            ("venue", pa.string()),
            ("product_id", pa.string()),
            ("ts", pa.timestamp("us", tz="UTC")),
            ("open", pa.float64()),
            ("high", pa.float64()),
            ("low", pa.float64()),
            ("close", pa.float64()),
            ("volume", pa.float64()),
        ]
    )


def book_top10_schema() -> Any:
    """book_top10: ten price/size levels per side, best first; missing depth is NaN."""
    import pyarrow as pa

    fields: list[tuple[str, Any]] = [
        ("venue", pa.string()),
        ("product_id", pa.string()),
        ("ts", pa.timestamp("us", tz="UTC")),
        ("seq", pa.int64()),
    ]
    for side in ("bid", "ask"):
        for kind in ("px", "sz"):
            fields.extend((f"{side}_{kind}_{i}", pa.float64()) for i in range(1, 11))
    return pa.schema(fields)


_LAZY = {
    "TRADES_SCHEMA": trades_schema,
    "CANDLES_SCHEMA": candles_schema,
    "BOOK_TOP10_SCHEMA": book_top10_schema,
}


def __getattr__(name: str) -> Any:
    fn = _LAZY.get(name)
    if fn is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    return fn()
