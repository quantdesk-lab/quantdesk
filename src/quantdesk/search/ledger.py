"""Trial ledger and multiple-testing deflation (docs/HONESTY.md rule 14).

Every candidate the loop *scores* increments the ledger; duplicates
(an ``expr_id`` already archived), gate refusals (too few pairs to print an
IC) and cap rejections are tallied separately and do not raise the trial
count, because a candidate that cannot win cannot inflate the maximum.

``deflated_threshold`` is the null bar a candidate must clear after ``N``
trials. Under the null a Spearman rank correlation over ``n`` independent
pairs has standard deviation about ``1 / sqrt(n - 1)``; the family-wise
(Sidak, max-of-N) two-sided threshold at level ``q`` is

    t(n, N) = kappa * z((1 + q ** (1 / N)) / 2) / sqrt(n - 1)

with ``kappa`` calibrated from the empirical null run (``quantdesk.search.
gates``; about 1.0). It rises with every trial and falls with the candidate's
own pair count. Candidates are positively dependent (a window-step neighbour
is nearly the same series), which makes Sidak conservative, never loose;
no effective number of tests is estimated because it would be a number
nobody can defend.

``holdout_p_value`` is the one-sided p-value of a single holdout touch (the
sign was predicted in-sample) adjusted for the ``k`` candidates that competed
for the holdout. Pure stdlib (``statistics.NormalDist``).
"""
from __future__ import annotations

import math
from collections import Counter
from statistics import NormalDist
from typing import Any

_N = NormalDist()


class TrialLedger:
    def __init__(self) -> None:
        self.n_trials = 0
        self.n_duplicates = 0
        self.n_refused = 0
        self.n_rejected = 0
        self.per_family: Counter[str] = Counter()
        self.rejections: Counter[str] = Counter()

    def record_scored(self, family: str) -> int:
        """A candidate produced a printable in-sample IC: count it. Returns
        the trial number within ``family``."""
        self.n_trials += 1
        self.per_family[family] += 1
        return self.per_family[family]

    def record_duplicate(self) -> None:
        self.n_duplicates += 1

    def record_refused(self) -> None:
        self.n_refused += 1

    def record_rejected(self, reason: str) -> None:
        self.n_rejected += 1
        self.rejections[reason] += 1

    def counts(self) -> dict[str, Any]:
        return {
            "n_trials": self.n_trials,
            "n_duplicates": self.n_duplicates,
            "n_refused": self.n_refused,
            "n_rejected": self.n_rejected,
            "per_family": dict(sorted(self.per_family.items())),
            "rejections": dict(sorted(self.rejections.items())),
        }


def deflated_threshold(n_pairs: int, n_trials: int, *, kappa: float = 1.0, q: float = 0.95) -> float:
    """The |Rank-IC| a candidate with ``n_pairs`` pairs must exceed after
    ``n_trials`` scored trials (see the module docstring)."""
    if n_pairs < 2:
        raise ValueError("n_pairs must be >= 2")
    if n_trials < 1:
        raise ValueError("n_trials must be >= 1")
    if not 0.0 < q < 1.0:
        raise ValueError("q must be in (0, 1)")
    if kappa <= 0:
        raise ValueError("kappa must be > 0")
    z = _N.inv_cdf((1.0 + q ** (1.0 / n_trials)) / 2.0)
    return kappa * z / math.sqrt(n_pairs - 1)


def holdout_p_value(ic_hold: float, n_hold: int, sign_insample: float, k: int) -> tuple[float, float]:
    """``(p, p_adj)``: one-sided p-value that a null Spearman correlation over
    ``n_hold`` pairs lands at or beyond ``ic_hold`` in the direction predicted
    in-sample, and its Sidak adjustment for ``k`` holdout competitors."""
    if n_hold < 2:
        raise ValueError("n_hold must be >= 2")
    if k < 1:
        raise ValueError("k must be >= 1")
    s = 1.0 if sign_insample >= 0 else -1.0
    z = float(ic_hold) * s * math.sqrt(n_hold - 1)
    p = 1.0 - _N.cdf(z)
    p = min(1.0, max(0.0, p))
    p_adj = 1.0 - (1.0 - p) ** k
    return p, min(1.0, max(0.0, p_adj))
