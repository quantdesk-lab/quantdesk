"""quantdesk.search - a deterministic, stdlib-only closed-loop factor search.

The loop proposes expressions over the operator library in
``quantdesk.factors.alpha101``, judges them with the research board's own
Rank-IC gates against a null threshold that rises with the number of trials,
archives every verdict, touches the trailing holdout exactly once, and runs
the fee-after cost grid on what survives. There is no language model anywhere
in this package; the designer is a seeded mutation operator and the judge is
the library itself. See ``docs/SEARCH.md``.

Modules: ``expr`` (expression trees), ``designer`` (mutation / sampling),
``bandit`` (two-level Thompson sampling), ``ledger`` (trial counts and the
deflated threshold), ``gates`` (versioned gate set calibrated from the null
run), ``walkforward`` (purged in-sample / holdout split, touch-once ledger),
``judge`` (verdicts), ``archive`` (append-only records, lineage, replay),
``loop`` (the run), ``cli`` (``python -m quantdesk.search``).
"""
