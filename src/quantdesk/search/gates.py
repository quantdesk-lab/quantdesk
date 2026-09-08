"""A versioned gate set for the search loop, calibrated from the null run.

``Gates`` bundles the research board's fixed sample gates (``min_ic_pairs``,
``min_ic_eff`` - imported, not retyped) with the null-scale factor ``kappa``
that the deflated threshold uses. ``kappa`` is the root-mean-square of
``|IC_i| * sqrt(n_i - 1)`` over the empirical null samples that
``quantdesk.research.null_calibration`` produces (per alpha, per reseeded
random walk); under the null it is about 1.0, and a test pins it to
``[0.85, 1.20]``. The empirical band therefore *checks* the analytic form
the gate uses, instead of being read off a pooled quantile that mixes
different pair counts.

``version`` is a digest of every field, stamped on every archived verdict so
a change of gates is visible in the archive.
"""
from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, dataclass
from typing import Any, Sequence

from quantdesk.research.board import _MIN_IC_EFF, _MIN_IC_PAIRS


@dataclass(frozen=True)
class Gates:
    min_ic_pairs: int
    min_ic_eff: int
    kappa: float
    q: float
    null_source: dict[str, Any]
    version: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _version(fields: dict[str, Any]) -> str:
    blob = json.dumps(fields, sort_keys=True, separators=(",", ":")).encode("ascii")
    return hashlib.sha256(blob).hexdigest()[:12]


def kappa_from_samples(samples: Sequence[Sequence[float]]) -> float:
    """RMS of ``|ic| * sqrt(n - 1)`` over ``[(abs_ic, n), ...]`` samples;
    pairs with ``n < 2`` are skipped."""
    acc, k = 0.0, 0
    for ic, n in samples:
        n = int(n)
        if n < 2:
            continue
        acc += (float(ic) * math.sqrt(n - 1)) ** 2
        k += 1
    if k == 0:
        raise ValueError("no usable null samples")
    return math.sqrt(acc / k)


def calibrate_gates(
    null_doc: dict[str, Any] | None = None,
    *,
    samples: Sequence[Sequence[float]] | None = None,
    q: float = 0.95,
) -> Gates:
    """Build the gate set from a ``null.json`` document (its ``samples`` list)
    or from explicit ``[(abs_ic, n), ...]`` samples. With neither, ``kappa``
    is the analytic 1.0 and the source says so."""
    if not 0.0 < q < 1.0:
        raise ValueError("q must be in (0, 1)")
    if samples is None and null_doc is not None:
        samples = null_doc.get("samples")
    if samples:
        kappa = round(kappa_from_samples(samples), 4)
        source: dict[str, Any] = {"kind": "empirical", "n_samples": len(samples)}
        if null_doc is not None:
            for key in ("n_reseeds", "bars", "horizon", "timeframe"):
                if key in null_doc:
                    source[key] = null_doc[key]
    else:
        kappa, source = 1.0, {"kind": "analytic", "n_samples": 0}
    fields = {
        "min_ic_pairs": int(_MIN_IC_PAIRS), "min_ic_eff": int(_MIN_IC_EFF),
        "kappa": kappa, "q": float(q), "null_source": source,
    }
    return Gates(version=_version(fields), **fields)
