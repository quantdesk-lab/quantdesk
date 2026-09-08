"""The search loop: propose -> judge -> archive -> learn, then one holdout touch.

``run_search`` wires the pieces in a fixed order per proposal - bandit
chooses (family, mode), designer proposes, ledger counts, judge scores on
in-sample rows, archive appends, bandit updates - so a run is a pure function
of (bars, seed, gates, parameters, prior archive). No wall clock is read
anywhere; the payload is byte-identical across rebuilds.

Generation 0 scores the seed expressions (the archive's roots). Each later
generation scores ``per_generation`` proposals. After the last generation
every scored candidate is re-checked against the deflated threshold at the
FINAL trial count (an early lucky candidate must not be selected under a
looser bar than the one the site draws), the top ``top_k`` finalists touch
the holdout exactly once through ``HoldoutLedger`` (a second run on the same
archive raises ``HoldoutSpent``), and the fee-after cost grid runs on the
holdout bars for each of them.

Resuming (``resume=True`` with a non-empty archive) continues the generation
and trial numbering, rebuilds the bandit posteriors from the archived
verdicts, and refuses a second holdout touch. The archive is the state that
improves across runs.

Expected outcomes on the synthetic fixtures (``docs/SEARCH.md``): on a seeded
random walk the loop converges to refusal - no finalist, or finalists that
fail the holdout; on the planted-AR(1) fixture a one-bar reversal expression
clears the deflated bar in-sample and its single holdout touch is reported
with its Sidak-adjusted p-value and the cost at which the edge dies.
Illustrative only; nothing here is a trading recommendation.
"""
from __future__ import annotations

from typing import Any, Sequence

from quantdesk.demo.fixtures import split_ohlcv

from .archive import Archive
from .bandit import TwoLevelBandit
from .designer import Designer
from .expr import FAMILIES, expr_id, parse, seed_nodes, stable_seed, to_text
from .gates import Gates, calibrate_gates
from .judge import DEFAULT_COST_GRID, evaluate_cols, fee_after, holdout_ic, judge
from .ledger import TrialLedger, deflated_threshold, holdout_p_value
from .walkforward import HoldoutLedger, split

HOLDOUT_ALPHA = 0.05

_NOTE = (
    "Deterministic closed-loop search on synthetic bars: a seeded mutation designer "
    "proposes expressions over the alpha101 operator library, the research board's own "
    "Rank-IC gates judge them in-sample against a null threshold that rises with the "
    "trial count, every verdict is archived, the trailing holdout is touched once, and "
    "the fee-after cost grid runs on what survives. No language model anywhere. Nothing "
    "here is a trading recommendation."
)


def _ledger_from(archive: Archive) -> TrialLedger:
    lg = TrialLedger()
    for r in archive.records:
        v = r.get("verdict")
        if v in ("noise", "redundant", "unstable", "candidate"):
            lg.record_scored(str(r.get("family")))
        elif v == "refused":
            lg.record_refused()
        elif v == "duplicate":
            lg.record_duplicate()
        elif v == "rejected":
            lg.record_rejected(str(r.get("reason")))
    return lg


def _best_so_far(archive: Archive, n_trials: int, gates: Gates, n_ref: int) -> dict[str, Any]:
    """Best in-sample |IC| so far, the bar it faces at the current trial
    count, and ``threshold_ref`` - the same bar for a reference pair count
    (the full in-sample row count), which is what the site draws because it
    depends on the trial count alone."""
    best: dict[str, Any] = {"expr_id": None, "abs_ic": None, "n": None, "threshold": None}
    for r in archive.scored():
        a = r["insample"]["abs_ic"]
        if a is not None and (best["abs_ic"] is None or a > best["abs_ic"]):
            best = {"expr_id": r["expr_id"], "abs_ic": a, "n": r["insample"]["n"], "threshold": None}
    n_trials = max(1, n_trials)
    if best["n"] is not None:
        best["threshold"] = round(
            deflated_threshold(int(best["n"]), n_trials, kappa=gates.kappa, q=gates.q), 4)
    best["n_trials"] = n_trials
    best["threshold_ref"] = round(deflated_threshold(n_ref, n_trials, kappa=gates.kappa, q=gates.q), 4)
    return best


def run_search(
    rows: Sequence[Sequence[float]],
    *,
    symbol: str,
    seed: int = 7,
    gates: Gates | None = None,
    generations: int = 8,
    per_generation: int = 6,
    holdout_frac: float = 0.2,
    purge: int = 24,
    embargo: int = 24,
    n_blocks: int = 3,
    top_k: int = 3,
    cost_grid: Sequence[float] = DEFAULT_COST_GRID,
    archive: Archive | None = None,
    resume: bool = False,
    kind: str = "synthetic",
) -> dict[str, Any]:
    """Run the loop on numeric ``[ts, o, h, l, c, v]`` rows (closed bars,
    oldest -> newest). Returns the ``search.json`` block for this series;
    ``archive`` (if given) is mutated in place and can be persisted with
    ``Archive.to_jsonl``."""
    if generations < 0 or per_generation < 1 or top_k < 1:
        raise ValueError("generations >= 0, per_generation >= 1, top_k >= 1")
    gates = gates or calibrate_gates()
    cols = split_ohlcv([list(r) for r in rows])
    closes = cols["c"]
    sp = split(len(closes), holdout_frac=holdout_frac, purge=purge, embargo=embargo,
               n_blocks=n_blocks, horizon=1)

    archive = archive if archive is not None else Archive()
    if len(archive) and not resume:
        raise ValueError("archive is not empty; pass resume=True to continue it")
    if resume and archive.meta:
        if archive.meta.get("symbol") not in (None, symbol):
            raise ValueError("archive belongs to a different symbol")
        if archive.meta.get("gates_version") not in (None, gates.version):
            raise ValueError("archive was judged under a different gate version")
    gen0 = int(archive.meta.get("generations_done", 0))
    holdout = HoldoutLedger(archive.meta.get("holdout"))
    ledger = _ledger_from(archive)
    bandit = TwoLevelBandit.from_records(archive.records, families=FAMILIES, seed=seed)
    designer = Designer(stable_seed(seed, gen0))
    run_id = f"{symbol}-seed{seed}-gen{gen0}"
    n_ref = sp.insample_end - 1  # pair count of a warmup-free factor in-sample

    series_by_id: dict[str, list] = {}

    def series_of(r: dict[str, Any]) -> list:
        s = series_by_id.get(r["expr_id"])
        if s is None:
            s = evaluate_cols(parse(r["text"]), cols)
            series_by_id[r["expr_id"]] = s
        return s

    def survivors_series() -> list[tuple[str, list]]:
        return [(r["expr_id"], series_of(r)) for r in archive.survivors()]

    def score(node, family: str, mode: str, op: str, parents: list[str], gen: int,
              extra: dict[str, Any] | None = None) -> dict[str, Any]:
        eid = expr_id(node)
        base = {"generation": gen, "family": family, "mode": mode, "op": op, "parents": parents,
                "trial_no": None, **(extra or {})}
        if archive.has(eid):
            ledger.record_duplicate()
            rec = {"expr_id": eid, "text": to_text(node), "verdict": "duplicate", **base}
            archive.append(rec)
            return rec
        series = evaluate_cols(node, cols)
        rec = judge(node, cols, sp, gates, ledger.n_trials + 1, survivors_series(), series=series)
        rec.update(base)
        if rec["verdict"] == "refused":
            ledger.record_refused()
        else:
            rec["trial_no"] = ledger.record_scored(family)
            series_by_id[eid] = series
            if mode in ("deepen", "widen"):
                bandit.update(family, mode, rec["cleared_null"])
        archive.append(rec)
        return rec

    gens_out: list[dict[str, Any]] = []
    best_curve: list[dict[str, Any]] = []
    lineage_edges: list[dict[str, str]] = []

    # ---- generation 0: the seeds -------------------------------------------- #
    if gen0 == 0:
        ids = []
        for node, fam in seed_nodes():
            rec = score(node, fam, "seed", "seed", [], 0)
            ids.append(rec["expr_id"])
        gens_out.append({"gen": 0, "picks": [], "bandit": bandit.snapshot(), "candidates": ids})
        best_curve.append({"gen": 0, **_best_so_far(archive, ledger.n_trials, gates, n_ref)})
        gen0 = 1

    # ---- later generations -------------------------------------------------- #
    for gen in range(gen0, gen0 + generations):
        picks: list[dict[str, Any]] = []
        ids = []
        for _ in range(per_generation):
            family, mode = bandit.choose()
            parents_rec = archive.by_family(family, top=3)
            parent_nodes = archive.nodes_of(parents_rec)
            node, op, reason, used = designer.propose(mode, family, parent_nodes)
            used_ids = [parents_rec[parent_nodes.index(u)]["expr_id"] for u in used]
            fallback = mode == "deepen" and not parent_nodes
            picks.append({"family": family, "mode": mode, "mode_fallback": fallback, "op": op})
            if reason is not None:
                ledger.record_rejected(reason)
                rec = {"expr_id": expr_id(node), "text": to_text(node), "verdict": "rejected",
                       "reason": reason, "generation": gen, "family": family, "mode": mode,
                       "op": op, "parents": used_ids, "trial_no": None, "mode_fallback": fallback}
                archive.append(rec)
                ids.append(rec["expr_id"])
                continue
            rec = score(node, family, mode, op, used_ids, gen, {"mode_fallback": fallback})
            ids.append(rec["expr_id"])
            for pid in used_ids:
                lineage_edges.append({"child": rec["expr_id"], "parent": pid, "op": op})
        gens_out.append({"gen": gen, "picks": picks, "bandit": bandit.snapshot(), "candidates": ids})
        best_curve.append({"gen": gen, **_best_so_far(archive, ledger.n_trials, gates, n_ref)})
    generations_done = gen0 + generations

    # ---- final re-check at N_final, then the single holdout touch ---------- #
    n_final = max(1, ledger.n_trials)
    for r in archive.scored():
        thr = deflated_threshold(int(r["insample"]["n"]), n_final, kappa=gates.kappa, q=gates.q)
        r["threshold_final"] = round(thr, 4)
        r["cleared_final"] = abs(float(r["insample"]["ic"])) > thr
    finalists = [r for r in archive.survivors() if r.get("cleared_final")]
    finalists.sort(key=lambda r: (-r["insample"]["abs_ic"], r["expr_id"]))
    finalists = finalists[:top_k]

    holdout_out: dict[str, Any] = {"touched": False, "k": 0, "run_id": None, "results": []}
    if finalists:
        touch = holdout.touch(run_id, [r["expr_id"] for r in finalists])  # raises HoldoutSpent
        holdout_out.update({"touched": True, "k": touch["k"], "run_id": run_id})
        for r in finalists:
            series = series_of(r)
            sign =1.0 if float(r["insample"]["ic"]) >= 0 else -1.0
            hic = holdout_ic(series, closes, sp)
            res: dict[str, Any] = {"expr_id": r["expr_id"], "text": r["text"], "ic": hic["ic"],
                                   "n": hic["n"], "p": None, "p_adj": None, "passed": False,
                                   "fee_after": None}
            if hic["ic"] is not None:
                p, p_adj = holdout_p_value(float(hic["ic"]), int(hic["n"]), sign, touch["k"])
                res.update({"p": round(p, 4), "p_adj": round(p_adj, 4),
                            "passed": p_adj < HOLDOUT_ALPHA and (float(hic["ic"]) > 0) == (sign > 0)})
                res["fee_after"] = fee_after(series, rows, sp, sign, cost_grid=cost_grid, symbol=symbol)
            r["holdout"] = {k: v for k, v in res.items() if k not in ("expr_id", "text")}
            holdout_out["results"].append(res)
        archive.meta["holdout"] = holdout.to_dict()

    archive.meta.update({
        "symbol": symbol, "seed": seed, "kind": kind, "gates_version": gates.version,
        "split": sp.to_dict(), "generations_done": generations_done,
    })
    counts = ledger.counts()
    return {
        "symbol": symbol,
        "kind": kind,
        "seed": seed,
        "n_bars": len(closes),
        "gates": gates.to_dict(),
        "split": sp.to_dict(),
        "generations": gens_out,
        "best_so_far": best_curve,
        "lineage": lineage_edges,
        "records": [dict(r) for r in archive.records],
        "holdout": holdout_out,
        "ledger": counts,
        "trial_count": counts["n_trials"],
        "note": _NOTE,
    }
