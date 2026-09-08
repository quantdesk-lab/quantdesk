"""Append-only verdict archive: records, lineage, JSON Lines, replay.

Every proposal the loop makes becomes one record - scored candidates,
refusals, duplicates and cap rejections alike - because a refusal is a
result the next round must see, not noise to hide. A record's ``parents``
(expression ids, host first) and ``op`` encode the lineage, so
``lineage(expr_id)`` walks back to a seed from the archive alone.

The on-disk form is JSON Lines: the first line is ``{"_meta": true, ...}``
(symbol, seed, gates version, split, generations done, the holdout touch),
every further line one record. The extension is ``.jsonl`` by convention and
run artefacts are git-ignored; the public tree carries no archive.

``replay`` re-judges every scored record against the same bars, split and
gates at its recorded trial count and returns the ids whose in-sample IC or
threshold differ - the reproducibility check (empty on a faithful archive).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable, Sequence

from .expr import Node, parse
from .gates import Gates
from .walkforward import Split

SCORED = ("noise", "redundant", "unstable", "candidate")


class Archive:
    def __init__(self, records: Iterable[dict[str, Any]] = (), meta: dict[str, Any] | None = None) -> None:
        self.records: list[dict[str, Any]] = [dict(r) for r in records]
        self.meta: dict[str, Any] = dict(meta or {})
        self._ids = {r["expr_id"] for r in self.records if "expr_id" in r}

    # ---- basic ------------------------------------------------------------ #
    def __len__(self) -> int:
        return len(self.records)

    def append(self, record: dict[str, Any]) -> None:
        self.records.append(dict(record))
        if "expr_id" in record:
            self._ids.add(record["expr_id"])

    def has(self, expr_id: str) -> bool:
        return expr_id in self._ids

    def get(self, expr_id: str) -> dict[str, Any] | None:
        for r in self.records:
            if r.get("expr_id") == expr_id:
                return r
        return None

    def scored(self) -> list[dict[str, Any]]:
        return [r for r in self.records if r.get("verdict") in SCORED]

    def survivors(self) -> list[dict[str, Any]]:
        return [r for r in self.records if r.get("verdict") == "candidate"]

    def by_family(self, family: str, top: int = 3) -> list[dict[str, Any]]:
        """Top scored records of ``family`` by in-sample |IC| (not survivors
        only - deepen must be able to try, and fail, on a random walk)."""
        rows = [r for r in self.scored() if r.get("family") == family
                and (r.get("insample") or {}).get("abs_ic") is not None]
        rows.sort(key=lambda r: (-r["insample"]["abs_ic"], r["expr_id"]))
        return rows[:top]

    def nodes_of(self, records: Sequence[dict[str, Any]]) -> list[Node]:
        return [parse(r["text"]) for r in records]

    def lineage(self, expr_id: str) -> list[dict[str, Any]]:
        """Child-first chain of records following the first parent up to a
        seed (a record with no parents). Empty when the id is unknown."""
        out: list[dict[str, Any]] = []
        seen: set[str] = set()
        cur = self.get(expr_id)
        while cur is not None and cur["expr_id"] not in seen:
            seen.add(cur["expr_id"])
            out.append(cur)
            parents = cur.get("parents") or []
            cur = self.get(parents[0]) if parents else None
        return out

    # ---- persistence ------------------------------------------------------ #
    def to_jsonl(self, path: str | Path) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        lines = [json.dumps({"_meta": True, **self.meta}, sort_keys=True, ensure_ascii=True)]
        lines += [json.dumps(r, sort_keys=True, ensure_ascii=True) for r in self.records]
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return path

    @classmethod
    def from_jsonl(cls, path: str | Path) -> "Archive":
        meta: dict[str, Any] = {}
        records: list[dict[str, Any]] = []
        for line in Path(path).read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            if row.get("_meta") is True:
                row.pop("_meta")
                meta = row
            else:
                records.append(row)
        return cls(records, meta)

    # ---- reproducibility -------------------------------------------------- #
    def replay(self, cols: dict[str, Sequence[float]], sp: Split, gates: Gates) -> list[str]:
        """Ids of scored records whose re-judged in-sample IC / threshold /
        verdict-independent statistics differ from what was archived."""
        from .judge import judge  # local import: judge imports nothing from here

        bad: list[str] = []
        for r in self.scored():
            fresh = judge(parse(r["text"]), cols, sp, gates, int(r["n_trials_at_verdict"]))
            if (fresh["insample"]["ic"] != r["insample"]["ic"]
                    or fresh["insample"]["threshold"] != r["insample"]["threshold"]
                    or fresh["cleared_null"] != r["cleared_null"]):
                bad.append(r["expr_id"])
        return bad
