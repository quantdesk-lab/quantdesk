"""The designer: a seeded, deterministic mutation operator over expression trees.

No language model is consulted. ``widen`` samples a fresh tree from a
family's grammar; ``deepen`` mutates or crosses archived parents with one of
five named operators so the archive can record exactly what was done:

- ``window_step``  one lag/window parameter moves one step along ``LAGS`` /
                   ``WINDOWS`` (the +/-20-50 percent neighbour rule of
                   ``docs/RESEARCH_DISCIPLINE.md``, in the library's grid);
- ``swap_op``      one operator is replaced by another of the same class;
- ``wrap``         a single-child operator from the family grammar is applied
                   on top of a random subtree;
- ``subtree``      a random subtree is replaced by a fresh grammar sample;
- ``crossover``    a subtree of a second parent is grafted into the first.

Proposals outside the caps (depth, size, windowed-op nesting, warmup) are
returned with a rejection reason instead of being silently repaired, so the
ledger can count them as rejections rather than trials. Illustrative.
"""
from __future__ import annotations

import random
from typing import Sequence

from .expr import (
    GRAMMAR,
    LAGS,
    OP_CLASSES,
    OPS,
    WINDOWS,
    Node,
    children,
    make,
    param,
    replace_at,
    sample,
    stable_seed,
    subtrees,
    terminals_of,
    validate,
)

MUTATIONS: tuple[str, ...] = ("window_step", "swap_op", "wrap", "subtree", "crossover")
MODES: tuple[str, ...] = ("deepen", "widen")


class Designer:
    """Seeded proposer. Same seed and same call sequence -> same proposals."""

    def __init__(
        self,
        seed: int,
        *,
        max_depth: int = 5,
        max_size: int = 12,
        max_nesting: int = 2,
        max_warmup: int = 120,
    ) -> None:
        self.rng = random.Random(stable_seed("designer", seed))
        self.caps = dict(max_depth=max_depth, max_size=max_size,
                         max_nesting=max_nesting, max_warmup=max_warmup)

    # ---- widen ------------------------------------------------------------ #
    def widen(self, family: str, *, attempts: int = 12) -> Node:
        """A fresh grammar sample for ``family``; up to ``attempts`` draws to
        find one inside the caps (the last draw is returned regardless, and
        ``propose`` reports its rejection reason). A ``volume_price`` sample
        always contains the ``volume`` terminal."""
        g = GRAMMAR[family]
        node: Node = ("close",)
        for _ in range(max(1, attempts)):
            node = sample(self.rng, terminals=g["terminals"], ops=g["ops"],
                          max_depth=min(4, self.caps["max_depth"]))
            if family == "volume_price" and "volume" not in terminals_of(node):
                leaves = [p for p, s in subtrees(node) if len(s) == 1]
                node = replace_at(node, self.rng.choice(leaves), ("volume",))
            if validate(node, **self.caps) is None:
                return node
        return node

    # ---- deepen ----------------------------------------------------------- #
    def deepen(self, parents: Sequence[Node], family: str) -> tuple[Node, str, list[Node]]:
        """Mutate one archived parent (or cross two). Returns ``(child, op,
        parents_used)`` - one parent, or two for ``crossover`` (first = host)."""
        if not parents:
            raise ValueError("deepen needs at least one parent")
        ops = list(MUTATIONS) if len(parents) >= 2 else [m for m in MUTATIONS if m != "crossover"]
        op = self.rng.choice(ops)
        parent = self.rng.choice(list(parents))
        used = [parent]
        if op == "window_step":
            child = self._window_step(parent)
        elif op == "swap_op":
            child = self._swap_op(parent)
        elif op == "wrap":
            child = self._wrap(parent, family)
        elif op == "subtree":
            child = self._subtree(parent, family)
        else:
            others = [p for p in parents if p != parent] or list(parents)
            donor = self.rng.choice(others)
            used = [parent, donor]
            child = self._crossover(parent, donor)
        if child is None:  # the chosen operator had nothing to act on
            child, op, used = self._wrap(parent, family), "wrap", [parent]
        return child, op, used

    def propose(
        self, mode: str, family: str, parents: Sequence[Node]
    ) -> tuple[Node, str, str | None, list[Node]]:
        """``(node, op_name, rejection_reason, parents_used)``; ``op_name`` is
        ``"sample"`` and ``parents_used`` empty for a widened proposal. A
        ``deepen`` request with no parents falls back to ``widen`` (the loop
        records ``mode_fallback``)."""
        if mode not in MODES:
            raise ValueError(f"mode must be one of {MODES}, got {mode!r}")
        if family not in GRAMMAR:
            raise ValueError(f"unknown family {family!r}")
        if mode == "deepen" and parents:
            node, op, used = self.deepen(parents, family)
        else:
            node, op, used = self.widen(family), "sample", []
        return node, op, validate(node, **self.caps), used

    # ---- mutation operators ---------------------------------------------- #
    def _window_step(self, node: Node) -> Node | None:
        spots = [(p, s) for p, s in subtrees(node)
                 if len(s) > 1 and OPS[s[0]][1] in ("lag", "window")]
        if not spots:
            return None
        path, sub = self.rng.choice(spots)
        grid = LAGS if OPS[sub[0]][1] == "lag" else WINDOWS
        cur = int(param(sub))
        # snap to the nearest grid point, then step one place (inward at the ends)
        k = min(range(len(grid)), key=lambda i: (abs(grid[i] - cur), i))
        step = self.rng.choice((-1, 1))
        if k + step < 0 or k + step >= len(grid):
            step = -step
        new_p = grid[k + step] if grid[k + step] != cur else grid[k]
        if new_p == cur:  # a one-point grid cannot move; try the other way
            new_p = grid[min(len(grid) - 1, max(0, k - step))]
        return replace_at(node, path, make(sub[0], children(sub), new_p))

    def _swap_op(self, node: Node) -> Node | None:
        spots = []
        for p, s in subtrees(node):
            if len(s) == 1:
                continue
            cls = next((c for c in OP_CLASSES if s[0] in c), None)
            if cls and len(cls) > 1:
                spots.append((p, s, cls))
        if not spots:
            return None
        path, sub, cls = self.rng.choice(spots)
        new_op = self.rng.choice([o for o in cls if o != sub[0]])
        return replace_at(node, path, make(new_op, children(sub), param(sub)))

    def _wrap(self, node: Node, family: str) -> Node:
        unary_ops = [o for o in GRAMMAR[family]["ops"] if OPS[o][0] == 1]
        op = self.rng.choice(unary_ops)
        path = self.rng.choice([p for p, _ in subtrees(node)])
        target = _at(node, path)
        kind = OPS[op][1]
        p = None if kind is None else self.rng.choice(LAGS if kind == "lag" else WINDOWS if kind == "window" else (0.5, 2.0))
        return replace_at(node, path, make(op, [target], p))

    def _subtree(self, node: Node, family: str) -> Node:
        g = GRAMMAR[family]
        paths = [p for p, _ in subtrees(node)]
        path = self.rng.choice(paths)
        fresh = sample(self.rng, terminals=g["terminals"], ops=g["ops"], max_depth=3)
        return replace_at(node, path, fresh)

    def _crossover(self, a: Node, b: Node) -> Node:
        donor = self.rng.choice([s for _, s in subtrees(b)])
        path = self.rng.choice([p for p, _ in subtrees(a)])
        return replace_at(a, path, donor)


def _at(node: Node, path: tuple[int, ...]) -> Node:
    for i in path:
        node = children(node)[i]
    return node
