"""Split and holdout-ledger tests (quantdesk.search.walkforward)."""
from __future__ import annotations

import pytest

from quantdesk.demo.fixtures import gbm_bars, split_ohlcv
from quantdesk.factors.alpha101 import delta
from quantdesk.research.board import ic_for
from quantdesk.search.walkforward import HoldoutLedger, HoldoutSpent, ic_on_range, split


def test_split_geometry():
    s = split(2400, holdout_frac=0.2, purge=24, embargo=24, n_blocks=3, horizon=1)
    assert s.holdout_start == 1920 and s.insample_end == 1872
    assert s.holdout_start - s.insample_end == s.purge + s.embargo
    # no in-sample row's forward window (<= purge bars) reaches the holdout
    assert s.insample_end - 1 + s.purge < s.holdout_start
    assert len(s.blocks) == 3
    for (a, b), (c, _) in zip(s.blocks, s.blocks[1:]):
        assert a < b and b + s.horizon == c   # trailing horizon rows dropped at each edge
    assert s.blocks[0][0] == 0 and s.blocks[-1][1] + s.horizon == s.insample_end
    assert s.to_dict()["n_holdout"] == 480


def test_split_rejects_impossible_geometry():
    for kw in ({"n_bars": 1}, {"n_bars": 100, "holdout_frac": 0.9, "purge": 24, "embargo": 24},
               {"n_bars": 100, "holdout_frac": 1.0}, {"n_bars": 100, "purge": -1},
               {"n_bars": 100, "n_blocks": 0}, {"n_bars": 100, "horizon": 0}):
        with pytest.raises(ValueError):
            split(**kw)


def test_ic_on_range_keeps_forward_returns_inside_the_range():
    c = split_ohlcv(gbm_bars(600, seed=2, sigma=0.01))["c"]
    series = [None if v is None else -v for v in delta(c, 1)]
    whole = ic_on_range(series, c, 0, 600, 1)
    assert whole == ic_for(series, c, 1)
    part = ic_on_range(series, c, 100, 400, 1)
    assert part["n"] == 299  # 300 rows, the last has no forward return inside the range
    # refusal passes through: a range too short for the board's gate prints no IC
    assert ic_on_range(series, c, 0, 20, 1)["ic"] is None


def test_holdout_ledger_is_touch_once():
    lg = HoldoutLedger()
    assert not lg.spent and lg.to_dict() is None
    rec = lg.touch("run-1", ["abc", "def"])
    assert rec == {"run_id": "run-1", "expr_ids": ["abc", "def"], "k": 2} and lg.spent
    with pytest.raises(HoldoutSpent):
        lg.touch("run-2", ["xyz"])
    again = HoldoutLedger(lg.to_dict())
    assert again.spent
    with pytest.raises(HoldoutSpent):
        again.touch("run-3", [])
