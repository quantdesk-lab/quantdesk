"""Expression trees over the alpha101 operator library - the search loop's genome.

A candidate factor is an immutable nested tuple ``(op, *children, *params)``:
``("close",)`` is a terminal, ``("delta", ("close",), 1)`` a lagged op,
``("mul", a, b)`` a binary op, ``("correlation", a, b, 10)`` a windowed op
over two children. ``evaluate`` dispatches every node to the *existing*
functions in ``quantdesk.factors.alpha101`` (``delay``, ``delta``, ``sma``,
``ts_rank``, ``correlation``, ``signedpower``, ``returns``, ``vwap_proxy``,
``div_s``, ...) - this module adds no numerics of its own, so the
no-lookahead property of the operator library (element t depends only on
elements <= t) is inherited and re-asserted by a property test over random
trees in ``tests/test_search_expr.py``.

``to_text`` prints a tree in the registry's own notation (``-1 * delta(close,
1)``, ``(close - open) / (high - low)``), ``parse`` reads it back, and
``expr_id`` is a stable digest of the canonical text so an archive can be
de-duplicated and a lineage reconstructed from text alone. No constant nodes
exist: ``div_s`` is already guarded, and a learned ``+ 0.001`` would be a
dollar-scale artefact.

``FAMILIES`` / ``GRAMMAR`` / ``SEEDS`` are the designer's vocabulary. A
family is assigned by lineage (a seed carries its family; a child inherits
its first parent's), never inferred from the tree.

Pure stdlib. Illustrative research tooling; nothing here is a signal.
"""
from __future__ import annotations

import hashlib
import random
import re
from typing import Any, Iterator, Sequence

from quantdesk.factors.alpha101 import (
    abs_s,
    add_s,
    correlation,
    delay,
    delta,
    div_s,
    log_s,
    mul_s,
    returns,
    sign_s,
    signedpower,
    sma,
    stddev,
    sub_s,
    ts_argmax,
    ts_max,
    ts_min,
    ts_rank,
    ts_scale,
    ts_sum,
    vwap_proxy,
)

Node = tuple
Series = list  # list[float | None], oldest -> newest

TERMINALS: tuple[str, ...] = ("open", "high", "low", "close", "volume", "returns", "vwap")
LAGS: tuple[int, ...] = (1, 2, 3, 5, 10)
WINDOWS: tuple[int, ...] = (5, 10, 20, 40, 60)
POWERS: tuple[float, ...] = (0.5, 2.0)


def _neg(x: Sequence[float | None]) -> Series:
    return [None if v is None else -v for v in x]


_UNARY = {"neg": _neg, "abs": abs_s, "sign": sign_s, "log": log_s}
_BINARY = {"add": add_s, "sub": sub_s, "mul": mul_s, "div": div_s}
_LAGGED = {"delay": delay, "delta": delta}
_WINDOWED = {
    "sma": sma, "ts_sum": ts_sum, "ts_min": ts_min, "ts_max": ts_max, "ts_argmax": ts_argmax,
    "ts_rank": ts_rank, "ts_scale": ts_scale, "stddev": stddev,
}
_FN: dict[str, Any] = {**_UNARY, **_BINARY, **_LAGGED, **_WINDOWED,
                       "correlation": correlation, "signedpower": signedpower}

#: op -> (number of children, parameter kind). Parameter kinds: None, "lag",
#: "window", "power". Windowed ops and correlation cost ``w - 1`` bars of warmup.
OPS: dict[str, tuple[int, str | None]] = {
    **{k: (1, None) for k in _UNARY},
    "signedpower": (1, "power"),
    **{k: (2, None) for k in _BINARY},
    **{k: (1, "lag") for k in _LAGGED},
    **{k: (1, "window") for k in _WINDOWED},
    "correlation": (2, "window"),
}
#: Operator classes for ``swap_op``: an op may only be swapped within its class.
OP_CLASSES: tuple[tuple[str, ...], ...] = (
    tuple(k for k in _UNARY if k != "neg"), tuple(_BINARY), tuple(_LAGGED), tuple(_WINDOWED),
)
_PARAM_CHOICES = {"lag": LAGS, "window": WINDOWS, "power": POWERS}
_SYMBOL = {"add": "+", "sub": "-", "mul": "*", "div": "/"}
_PREC = {"add": 1, "sub": 1, "mul": 2, "div": 2, "neg": 2}

FAMILIES: tuple[str, ...] = ("reversal", "volume_price", "volatility", "range")
#: Per-family grammar for ``widen``: terminal and operator subsets.
GRAMMAR: dict[str, dict[str, tuple[str, ...]]] = {
    "reversal": {
        "terminals": ("close", "returns", "vwap"),
        "ops": ("neg", "delta", "delay", "sma", "ts_min", "ts_max", "ts_rank", "ts_scale", "sub", "div"),
    },
    "volume_price": {
        "terminals": ("open", "close", "volume", "returns"),
        "ops": ("neg", "correlation", "ts_rank", "sma", "delta", "div", "mul", "log"),
    },
    "volatility": {
        "terminals": ("returns", "close", "high", "low"),
        "ops": ("stddev", "abs", "ts_max", "ts_min", "neg", "div", "sub", "sma", "signedpower"),
    },
    "range": {
        "terminals": ("open", "high", "low", "close"),
        "ops": ("sub", "div", "neg", "ts_rank", "sma", "delta", "abs"),
    },
}
#: Seed expressions (text, family) in registry notation. Not a re-derivation of
#: the 19 registered alphas; the registry entries remain the reference.
SEEDS: tuple[tuple[str, str], ...] = (
    ("-1 * delta(close, 1)", "reversal"),
    ("-1 * (close - sma(close, 10))", "reversal"),
    ("-1 * correlation(open, volume, 10)", "volume_price"),
    ("ts_rank(volume / sma(volume, 20), 20)", "volume_price"),
    ("stddev(returns, 20)", "volatility"),
    ("(close - open) / (high - low)", "range"),
    ("(high - low) / close", "range"),
)


def stable_seed(*parts: Any) -> int:
    """Process-independent integer seed from arbitrary parts (``hash`` of a
    str is salted per process, so it cannot seed a reproducible run)."""
    key = "|".join(str(p) for p in parts).encode("utf-8")
    return int.from_bytes(hashlib.sha256(key).digest()[:8], "big")


# --------------------------------------------------------------------------- #
# structure
# --------------------------------------------------------------------------- #
def is_terminal(node: Node) -> bool:
    return node[0] in TERMINALS


def children(node: Node) -> tuple[Node, ...]:
    if is_terminal(node):
        return ()
    return tuple(node[1:1 + OPS[node[0]][0]])


def param(node: Node) -> Any:
    """The op's parameter (lag, window or power), ``None`` when it has none."""
    if is_terminal(node) or OPS[node[0]][1] is None:
        return None
    return node[-1]


def make(op: str, kids: Sequence[Node], p: Any = None) -> Node:
    """Build a node, validating arity and parameter presence."""
    if op in TERMINALS:
        if kids or p is not None:
            raise ValueError(f"terminal {op!r} takes no children")
        return (op,)
    if op not in OPS:
        raise ValueError(f"unknown op {op!r}")
    nch, kind = OPS[op]
    if len(kids) != nch:
        raise ValueError(f"{op} takes {nch} children, got {len(kids)}")
    if kind is None:
        if p is not None:
            raise ValueError(f"{op} takes no parameter")
        return (op, *kids)
    if p is None:
        raise ValueError(f"{op} needs a {kind} parameter")
    if kind == "power":
        return (op, *kids, float(p))
    if int(p) != p or int(p) < 1:
        raise ValueError(f"{op} {kind} must be a positive integer, got {p!r}")
    return (op, *kids, int(p))


def size(node: Node) -> int:
    return 1 + sum(size(c) for c in children(node))


def depth(node: Node) -> int:
    """Levels on the longest root-to-leaf path; a bare terminal is 1."""
    kids = children(node)
    return 1 + (max(depth(c) for c in kids) if kids else 0)


def nesting(node: Node) -> int:
    """Windowed ops (incl. correlation) on the deepest root-to-leaf path."""
    kids = children(node)
    here = 1 if (not is_terminal(node) and OPS[node[0]][1] == "window") else 0
    return here + (max(nesting(c) for c in kids) if kids else 0)


def warmup(node: Node) -> int:
    """Bars before the first value can exist on a clean input: ``returns`` 1,
    ``delay``/``delta`` add ``d``, windowed ops add ``w - 1``, binaries take
    the max. An upper bound on the first non-None index (asserted by test)."""
    if is_terminal(node):
        return 1 if node[0] == "returns" else 0
    op = node[0]
    kind = OPS[op][1]
    base = max(warmup(c) for c in children(node))
    if kind == "lag":
        return base + int(node[-1])
    if kind == "window":
        return base + int(node[-1]) - 1
    return base


def terminals_of(node: Node) -> set[str]:
    if is_terminal(node):
        return {node[0]}
    out: set[str] = set()
    for c in children(node):
        out |= terminals_of(c)
    return out


def subtrees(node: Node, path: tuple[int, ...] = ()) -> Iterator[tuple[tuple[int, ...], Node]]:
    """Every subtree with its path (child indices from the root), pre-order."""
    yield path, node
    for i, c in enumerate(children(node)):
        yield from subtrees(c, path + (i,))


def replace_at(node: Node, path: tuple[int, ...], new: Node) -> Node:
    """A copy of ``node`` with the subtree at ``path`` replaced by ``new``."""
    if not path:
        return new
    i, rest = path[0], path[1:]
    kids = list(children(node))
    kids[i] = replace_at(kids[i], rest, new)
    return make(node[0], kids, param(node))


def validate(
    node: Node,
    *,
    max_depth: int = 5,
    max_size: int = 12,
    max_nesting: int = 2,
    max_warmup: int = 120,
) -> str | None:
    """Reason a tree is out of bounds, or ``None`` when it is acceptable.
    Reasons: ``bare_terminal``, ``too_deep``, ``too_big``, ``too_nested``,
    ``warmup`` (would eat more than ``max_warmup`` bars)."""
    if is_terminal(node):
        return "bare_terminal"
    if depth(node) > max_depth:
        return "too_deep"
    if size(node) > max_size:
        return "too_big"
    if nesting(node) > max_nesting:
        return "too_nested"
    if warmup(node) > max_warmup:
        return "warmup"
    return None


# --------------------------------------------------------------------------- #
# evaluation
# --------------------------------------------------------------------------- #
def evaluate(
    node: Node,
    opens: Sequence[float | None],
    highs: Sequence[float | None],
    lows: Sequence[float | None],
    closes: Sequence[float | None],
    volumes: Sequence[float | None],
) -> Series:
    """Evaluate a tree on aligned OHLCV columns through the alpha101 operator
    functions. Shared subtrees are computed once per call. Returns a series
    aligned to the input bars (``None`` marks warmup / guarded values)."""
    cols = {
        "open": list(opens), "high": list(highs), "low": list(lows),
        "close": list(closes), "volume": list(volumes),
    }
    memo: dict[Node, Series] = {}

    def ev(nd: Node) -> Series:
        hit = memo.get(nd)
        if hit is not None:
            return hit
        op = nd[0]
        if op in TERMINALS:
            if op == "returns":
                out = returns(cols["close"])
            elif op == "vwap":
                out = vwap_proxy(cols["high"], cols["low"], cols["close"])
            else:
                out = cols[op]
        else:
            nch, kind = OPS[op]
            kids = [ev(c) for c in nd[1:1 + nch]]
            out = _FN[op](*kids) if kind is None else _FN[op](*kids, nd[-1])
        memo[nd] = out
        return out

    return ev(node)


# --------------------------------------------------------------------------- #
# text form (registry notation) and its parser
# --------------------------------------------------------------------------- #
def _prec(node: Node) -> int:
    return _PREC.get(node[0], 3)


def _fmt_param(kind: str | None, p: Any) -> str:
    return repr(float(p)) if kind == "power" else str(int(p))


def to_text(node: Node) -> str:
    """Canonical infix text: ``-1 * x`` for negation, ``a - b`` / ``a / b``
    for binaries (a right operand of equal precedence is always
    parenthesised, so the text is unambiguous), ``f(x, w)`` for calls."""
    op = node[0]
    if op in TERMINALS:
        return op
    if op == "neg":
        inner = to_text(node[1])
        return f"-1 * ({inner})" if _prec(node[1]) <= 2 else f"-1 * {inner}"
    if op in _BINARY:
        p = _PREC[op]
        left, right = node[1], node[2]
        lt = to_text(left)
        rt = to_text(right)
        if _prec(left) < p:
            lt = f"({lt})"
        if _prec(right) <= p:
            rt = f"({rt})"
        return f"{lt} {_SYMBOL[op]} {rt}"
    nch, kind = OPS[op]
    args = [to_text(c) for c in node[1:1 + nch]]
    if kind is not None:
        args.append(_fmt_param(kind, node[-1]))
    return f"{op}({', '.join(args)})"


def expr_id(node: Node) -> str:
    """Stable 12-hex digest of the canonical text."""
    return hashlib.sha256(to_text(node).encode("ascii")).hexdigest()[:12]


_TOKEN = re.compile(r"\s*(?:(\d+\.\d+|\d+)|([A-Za-z_][A-Za-z0-9_]*)|([-+*/(),]))")


def _tokenize(text: str) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    pos = 0
    text = text.strip()
    while pos < len(text):
        m = _TOKEN.match(text, pos)
        if not m or m.end() == pos:
            raise ValueError(f"cannot tokenize {text[pos:pos + 20]!r}")
        pos = m.end()
        if m.group(1) is not None:
            out.append(("num", m.group(1)))
        elif m.group(2) is not None:
            out.append(("id", m.group(2)))
        else:
            out.append(("sym", m.group(3)))
    return out


class _Parser:
    def __init__(self, text: str) -> None:
        self.toks = _tokenize(text)
        self.i = 0
        self.text = text

    def peek(self, k: int = 0) -> tuple[str, str] | None:
        j = self.i + k
        return self.toks[j] if j < len(self.toks) else None

    def take(self, kind: str | None = None, val: str | None = None) -> tuple[str, str]:
        tok = self.peek()
        if tok is None or (kind and tok[0] != kind) or (val and tok[1] != val):
            want = val or kind or "token"
            raise ValueError(f"expected {want!r} at token {self.i} in {self.text!r}")
        self.i += 1
        return tok

    def expr(self) -> Node:
        node = self.term()
        while self.peek() in (("sym", "+"), ("sym", "-")):
            sym = self.take()[1]
            node = make("add" if sym == "+" else "sub", [node, self.term()])
        return node

    def term(self) -> Node:
        node = self.factor()
        while self.peek() in (("sym", "*"), ("sym", "/")):
            sym = self.take()[1]
            node = make("mul" if sym == "*" else "div", [node, self.factor()])
        return node

    def factor(self) -> Node:
        tok = self.peek()
        if tok == ("sym", "-"):
            self.take()
            if self.take("num")[1] != "1":
                raise ValueError("negation must be written -1 * x")
            self.take("sym", "*")
            return make("neg", [self.factor()])
        if tok == ("sym", "("):
            self.take()
            node = self.expr()
            self.take("sym", ")")
            return node
        if tok is not None and tok[0] == "id":
            name = self.take()[1]
            if self.peek() == ("sym", "("):
                return self.call(name)
            if name not in TERMINALS:
                raise ValueError(f"unknown terminal {name!r}")
            return (name,)
        raise ValueError(f"unexpected token {tok!r} in {self.text!r}")

    def call(self, name: str) -> Node:
        if name not in OPS or name == "neg":
            raise ValueError(f"unknown function {name!r}")
        self.take("sym", "(")
        args: list[Any] = []
        while True:
            tok = self.peek()
            if tok is not None and tok[0] == "num" and self.peek(1) in (("sym", ","), ("sym", ")")):
                self.take()
                args.append(float(tok[1]) if "." in tok[1] else int(tok[1]))
            else:
                args.append(self.expr())
            if self.peek() == ("sym", ","):
                self.take()
                continue
            self.take("sym", ")")
            break
        nch, kind = OPS[name]
        want = nch + (1 if kind else 0)
        if len(args) != want:
            raise ValueError(f"{name} takes {want} arguments, got {len(args)}")
        kids = args[:nch]
        if any(not isinstance(k, tuple) for k in kids):
            raise ValueError(f"{name}: child arguments must be expressions")
        if kind is None:
            return make(name, kids)
        p = args[-1]
        if isinstance(p, tuple):
            raise ValueError(f"{name}: last argument must be a number")
        return make(name, kids, p)


def parse(text: str) -> Node:
    """Registry-notation text -> tree. Raises ``ValueError`` on anything the
    grammar does not cover (``where``, ``sqrt``, ``^``, constants, ...)."""
    p = _Parser(text)
    node = p.expr()
    if p.peek() is not None:
        raise ValueError(f"trailing tokens in {text!r}")
    return node


def seed_nodes() -> list[tuple[Node, str]]:
    """``SEEDS`` parsed: ``[(node, family), ...]``."""
    return [(parse(text), fam) for text, fam in SEEDS]


# --------------------------------------------------------------------------- #
# grammar sampling (the designer's ``widen``)
# --------------------------------------------------------------------------- #
def random_param(rng: random.Random, kind: str | None) -> Any:
    return None if kind is None else rng.choice(_PARAM_CHOICES[kind])


def sample(
    rng: random.Random,
    *,
    terminals: Sequence[str] = TERMINALS,
    ops: Sequence[str] = tuple(OPS),
    max_depth: int = 4,
    leaf_prob: float = 0.35,
) -> Node:
    """A random tree from a grammar: the root is always an operator, deeper
    positions become terminals with ``leaf_prob`` or at ``max_depth``.
    Deterministic for a given ``rng`` state."""
    if max_depth < 2:
        raise ValueError("max_depth must be >= 2")

    def build(d: int) -> Node:
        if d >= max_depth or (d > 1 and rng.random() < leaf_prob):
            return (rng.choice(list(terminals)),)
        op = rng.choice(list(ops))
        nch, kind = OPS[op]
        kids = [build(d + 1) for _ in range(nch)]
        return make(op, kids, random_param(rng, kind))

    return build(1)
