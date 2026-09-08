"""In-sample / holdout split with purge and embargo, block stability, and the
touch-once holdout ledger.

There is no fitted model in the search loop - an expression has no
parameters estimated on the data - so the only leakage boundary that
matters is in-sample -> holdout, and the only leakage mechanism is a forward
return that reaches across it. One split therefore suffices:

    [0, insample_end)  in-sample rows: the selection statistic (one
                       ``board.ic_for`` at horizon 1) is computed here
    [insample_end, holdout_start)  gap = purge + embargo, used by nobody
    [holdout_start, n)  holdout: touched once, through ``HoldoutLedger``

``purge`` is the largest horizon anything reports (24 bars), so no
in-sample row's forward window enters the holdout; ``embargo`` is a further
conservative gap. ``ic_on_range`` slices both the factor series and the
closes, so forward returns can never leave the range they are scored in.
The holdout uses factor values from the full series (a slow factor's first
holdout values legitimately depend on in-sample prices) and forward returns
inside the holdout only.

``blocks`` are ``n_blocks`` contiguous pieces of the in-sample region with
their trailing ``horizon`` rows dropped; per-block ICs are a *stability
observable* (majority sign agreement), never the gate statistic. Rolling
multi-fold evaluation for fitted models stays on the roadmap.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence

from quantdesk.research.board import ic_for


@dataclass(frozen=True)
class Split:
    n: int
    insample_end: int
    holdout_start: int
    purge: int
    embargo: int
    horizon: int
    blocks: tuple[tuple[int, int], ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "n": self.n, "insample_end": self.insample_end, "holdout_start": self.holdout_start,
            "purge": self.purge, "embargo": self.embargo, "horizon": self.horizon,
            "blocks": [list(b) for b in self.blocks],
            "n_holdout": self.n - self.holdout_start,
        }


def split(
    n_bars: int,
    *,
    holdout_frac: float = 0.2,
    purge: int = 24,
    embargo: int = 24,
    n_blocks: int = 3,
    horizon: int = 1,
) -> Split:
    if n_bars < 2:
        raise ValueError("n_bars must be >= 2")
    if not 0.0 < holdout_frac < 1.0:
        raise ValueError("holdout_frac must be in (0, 1)")
    if purge < 0 or embargo < 0 or horizon < 1 or n_blocks < 1:
        raise ValueError("purge/embargo must be >= 0, horizon and n_blocks >= 1")
    n_hold = int(n_bars * holdout_frac)
    holdout_start = n_bars - n_hold
    insample_end = holdout_start - purge - embargo
    if n_hold < 2 or insample_end < n_blocks * (horizon + 2):
        raise ValueError(
            f"{n_bars} bars are too few for holdout_frac={holdout_frac}, purge={purge}, "
            f"embargo={embargo}, n_blocks={n_blocks}")
    edges = [round(insample_end * k / n_blocks) for k in range(n_blocks + 1)]
    blocks = tuple((edges[k], max(edges[k], edges[k + 1] - horizon)) for k in range(n_blocks))
    return Split(n_bars, insample_end, holdout_start, purge, embargo, horizon, blocks)


def ic_on_range(
    series: Sequence[float | None], closes: Sequence[float], start: int, end: int, h: int
) -> dict[str, Any]:
    """``board.ic_for`` on rows ``[start, end)`` of an already-evaluated
    series - the board's gates (30 pairs, ``n_eff``) apply unchanged, and the
    forward returns are formed inside the range only."""
    return ic_for(list(series[start:end]), list(closes[start:end]), h)


class HoldoutSpent(RuntimeError):
    """The holdout has already been touched in this archive."""


class HoldoutLedger:
    """Records the single permitted holdout evaluation."""

    def __init__(self, record: dict[str, Any] | None = None) -> None:
        self.record = dict(record) if record else None

    @property
    def spent(self) -> bool:
        return self.record is not None

    def touch(self, run_id: str, expr_ids: Sequence[str]) -> dict[str, Any]:
        if self.record is not None:
            raise HoldoutSpent(
                f"holdout already touched by run {self.record.get('run_id')!r} "
                f"with {self.record.get('k')} candidate(s); the number is now in-sample")
        self.record = {"run_id": str(run_id), "expr_ids": list(expr_ids), "k": len(expr_ids)}
        return dict(self.record)

    def to_dict(self) -> dict[str, Any] | None:
        return dict(self.record) if self.record else None
