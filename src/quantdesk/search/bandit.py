"""Two-level Thompson sampling over (family, deepen-vs-widen).

Level 1 chooses an expression family, level 2 chooses - per family - whether
to deepen (mutate archived parents) or widen (sample fresh). Every arm is a
Beta(1, 1) prior updated by a binary reward: ``cleared_null``, the judge's own
verdict that a candidate's in-sample |Rank-IC| left the deflated null band.
Nothing softer feeds the bandit, so the sentence "the search policy is
rewarded only by the honesty gate" is literally true.

Determinism: the bandit owns one ``random.Random`` seeded from the run seed;
given the same seed and the same sequence of updates the picks replay
exactly. Exploration comes from posterior updates, not from run-to-run
randomness. ``from_records`` rebuilds the posteriors from archived verdicts,
so a resumed run learns from everything the archive holds - the learning
lives in the archive, not in the object.

Forty-eight pulls over twelve arms (the site defaults) demonstrate the
mechanism, not convergence; ``docs/SEARCH.md`` says so.
"""
from __future__ import annotations

import random
from typing import Any, Iterable, Sequence

from .expr import FAMILIES, stable_seed

MODES: tuple[str, ...] = ("deepen", "widen")


class BetaArm:
    """A Beta posterior on a Bernoulli reward."""

    __slots__ = ("alpha", "beta")

    def __init__(self, alpha: float = 1.0, beta: float = 1.0) -> None:
        if alpha <= 0 or beta <= 0:
            raise ValueError("alpha and beta must be > 0")
        self.alpha = float(alpha)
        self.beta = float(beta)

    def sample(self, rng: random.Random) -> float:
        return rng.betavariate(self.alpha, self.beta)

    def update(self, success: bool) -> None:
        if success:
            self.alpha += 1.0
        else:
            self.beta += 1.0

    @property
    def mean(self) -> float:
        return self.alpha / (self.alpha + self.beta)

    @property
    def n(self) -> int:
        """Observed pulls (the prior counts as zero)."""
        return int(round(self.alpha + self.beta - 2.0))

    def to_dict(self) -> dict[str, float | int]:
        return {"alpha": self.alpha, "beta": self.beta, "mean": round(self.mean, 4), "n": self.n}


class TwoLevelBandit:
    def __init__(self, families: Sequence[str] = FAMILIES, seed: int = 0) -> None:
        if not families:
            raise ValueError("families must not be empty")
        self.families = tuple(families)
        self.rng = random.Random(stable_seed("bandit", seed))
        self.family_arms = {f: BetaArm() for f in self.families}
        self.mode_arms = {(f, m): BetaArm() for f in self.families for m in MODES}

    def choose(self) -> tuple[str, str]:
        """One Thompson draw per arm; ties resolve in declaration order."""
        best_f, best_v = self.families[0], -1.0
        for f in self.families:
            v = self.family_arms[f].sample(self.rng)
            if v > best_v:
                best_f, best_v = f, v
        best_m, best_v = MODES[0], -1.0
        for m in MODES:
            v = self.mode_arms[(best_f, m)].sample(self.rng)
            if v > best_v:
                best_m, best_v = m, v
        return best_f, best_m

    def update(self, family: str, mode: str, success: bool) -> None:
        self.family_arms[family].update(bool(success))
        self.mode_arms[(family, mode)].update(bool(success))

    def snapshot(self) -> dict[str, Any]:
        """Posterior summary in fixed key order (for the archive and the site)."""
        return {
            "families": {f: self.family_arms[f].to_dict() for f in self.families},
            "modes": {f"{f}/{m}": self.mode_arms[(f, m)].to_dict()
                      for f in self.families for m in MODES},
        }

    @classmethod
    def from_records(
        cls, records: Iterable[dict[str, Any]], *, families: Sequence[str] = FAMILIES, seed: int = 0
    ) -> "TwoLevelBandit":
        """Rebuild the posteriors from archived verdicts (records carrying
        ``family``, ``mode`` and ``cleared_null``; others are skipped)."""
        b = cls(families, seed)
        for r in records:
            f, m = r.get("family"), r.get("mode")
            if f in b.family_arms and m in MODES and "cleared_null" in r:
                b.update(f, m, bool(r["cleared_null"]))
        return b
