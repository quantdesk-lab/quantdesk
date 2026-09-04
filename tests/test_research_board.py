"""Research-board tests (quantdesk/research/board.py).

A fake candle client (no network: get_candles honors granularity with
DISTINCT 1h/1d series, returns string fields like a real venue adapter,
varies volume, and appends a still-forming last bar) drives
build_symbol_factors / compute_factors through the injected-client API. The
metric functions get synthetic known-answer proofs -- most importantly the
perfect-foresight IC alignment canary.
"""
from __future__ import annotations

import math
import random
import time

import pytest

import quantdesk.research.board as fac
from quantdesk.research.board import (
    _closed_bars,
    build_symbol_factors,
    compute_factors,
    corr_matrix,
    decay_for,
    forward_log_returns,
    ic_for,
    self_corr_lag1,
)
from quantdesk.factors.alpha101 import ALPHAS


def _walk(n, *, start=100.0, vol=0.01, seed=7):
    """Deterministic positive random-walk closes, oldest -> newest."""
    rng = random.Random(seed)
    out = [start]
    for _ in range(n - 1):
        out.append(out[-1] * math.exp(vol * rng.gauss(0, 1)))
    return out


class FakeCoinbase:
    """Matches the candle-client surface build_symbol_factors uses.

    Distinct series per granularity, STRING candle fields (the real adapter
    returns strings — coercion is under test), lognormal varying volume (a
    constant volume degenerates the volume-price alphas to None), and a last
    bar whose window still spans `now` (forming: _closed_bars must drop it)."""

    def __init__(self, closes_1h, closes_1d, *, raise_for=None):
        self._series = {"1h": (closes_1h, 3600), "1d": (closes_1d, 86400)}
        self._raise_for = raise_for or set()

    def get_candles(self, symbol, granularity="1h", limit=350):
        if symbol in self._raise_for or "candles" in self._raise_for:
            raise ConnectionError("boom")
        closes, secs = self._series[granularity]
        rng = random.Random(len(closes) * secs)  # deterministic per series
        now = time.time()
        n = len(closes)
        rows = []
        for i, c in enumerate(closes):
            ts = now - (n - i) * secs + secs / 2.0  # last bar: ts + secs > now
            o = closes[i - 1] if i else c
            hi = max(o, c) * (1.0 + 0.002 * rng.random())
            lo = min(o, c) * (1.0 - 0.002 * rng.random())
            volume = 100.0 * math.exp(0.5 * rng.gauss(0, 1))
            rows.append([str(ts), str(o), str(hi), str(lo), str(c), str(volume)])
        return rows

    def close(self):
        pass


class FakeFunding:
    """Funding-history surface only; newest-first rows like the venue."""

    def get_funding_rate_history(self, symbol, page_size=200):
        rng = random.Random(3)
        return [{"fundingRate": str(0.0001 + 0.00005 * rng.gauss(0, 1))}
                for _ in range(60)]

    def close(self):
        pass


# ----------------------------------------------------------------- metrics --
def test_closed_bars_drops_forming_bar():
    now = 1_000_000.0
    candles = [
        ["992800", "100", "101", "99", "100.5", "10"],   # closed
        ["996400", "100.5", "102", "100", "101.5", "12"],  # ts+3600 == now: closed
        ["999000", "101.5", "103", "101", "102.5", "8"],   # forming -> dropped
        ["junk", "1", "2", "3", "4", "5"],                 # unparseable -> dropped
        ["995000"],                                        # short row -> dropped
    ]
    out = _closed_bars(candles, 3600.0, now)
    assert out["c"] == [100.5, 101.5]
    assert out["ts"] == [992800.0, 996400.0]
    assert out["v"] == [10.0, 12.0]
    assert all(len(out[k]) == 2 for k in ("ts", "o", "h", "l", "c", "v"))


def test_forward_log_returns_alignment():
    closes = [100.0, 110.0, 121.0]
    fr = forward_log_returns(closes, 1)
    assert fr[0] == pytest.approx(math.log(1.1))
    assert fr[1] == pytest.approx(math.log(1.1))
    assert fr[2] is None  # future unknown at the last bar
    fr2 = forward_log_returns(closes, 2)
    assert fr2[0] == pytest.approx(math.log(1.21))
    assert fr2[1] is None and fr2[2] is None


def test_ic_perfect_foresight_alignment():
    """factor_t := ln(c_{t+1}/c_t) must score IC(h=1) == 1.0; the SAME factor
    delayed one bar must score materially lower — the alignment-bug canary
    (an off-by-one in forward returns would invert this)."""
    closes = _walk(80, seed=11)
    factor = forward_log_returns(closes, 1)
    r = ic_for(factor, closes, 1)
    assert r["ic"] == pytest.approx(1.0)
    assert r["n"] == 79
    assert r["overlap"] is False and "n_eff" not in r
    delayed = [None] + factor[:-1]
    r2 = ic_for(delayed, closes, 1)
    assert r2["ic"] is not None
    assert abs(r2["ic"]) < 0.5  # iid walk: lag-1 rank autocorr ~ 0
    # overlapping horizon carries the honesty flag
    r24 = ic_for(factor, closes, 24)
    assert r24["overlap"] is True and r24["n_eff"] == r24["n"] // 24


def test_ic_none_below_min_pairs_and_on_degenerate():
    closes = _walk(40, seed=3)
    sparse = [None] * 20 + [float(i) for i in range(20)]
    r = ic_for(sparse, closes, 1)
    assert r["ic"] is None
    assert r["n"] == 19  # n reported even when the IC is refused
    constant = [1.0] * 40
    r2 = ic_for(constant, closes, 1)
    assert r2["ic"] is None  # degenerate ranks: spearman undefined
    assert r2["n"] == 39


def test_ic_overlap_gated_on_n_eff():
    # 40 pairs at h=24 passes the raw-n gate but is ~1 independent
    # observation — the n_eff honesty gate must refuse to print an IC.
    closes = _walk(80, seed=11)
    series = [float(i % 7) for i in range(80)]
    r = ic_for(series, closes, 24)
    assert r["n"] >= 30
    assert r["n_eff"] == r["n"] // 24
    assert r["n_eff"] < 8
    assert r["ic"] is None
    # h=1 (no overlap) on the same data still prints.
    r1 = ic_for(series, closes, 1)
    assert r1["ic"] is not None


def test_degenerate_latest_bar_keeps_row_ok():
    # A factor with real history whose LATEST value is None (e.g. a054 on a
    # high==low candle) must not flip to the warmup shape: statistics stay.
    from quantdesk.research.board import _factor_row

    closes = _walk(120, seed=17)
    series = [float(i % 9) for i in range(119)] + [None]
    row = _factor_row(
        {"id": "x"}, series, closes,
        timeframe="1h", horizons=((1, "1h"),), lags=(1, 2), need=1,
    )
    assert row["ok"] is True
    assert row["value"] is None
    assert row["n_obs"] == 119
    assert "need" not in row
    assert row["ic"] and row["ic"][0]["n"] > 0
    # True warmup (no valid value anywhere) still reports the need gate.
    warm = _factor_row(
        {"id": "y"}, [None] * 120, closes,
        timeframe="1h", horizons=((1, "1h"),), lags=(1, 2), need=95,
    )
    assert warm["ok"] is False and warm["need"] == 95 and warm["ic"] == []


def test_decay_and_turnover_proxy_shapes():
    closes = _walk(120, seed=5)
    factor = [math.sin(i / 5.0) for i in range(120)]
    lags = (1, 2, 3, 4, 6, 12, 24, 48)
    d = decay_for(factor, closes, lags)
    assert d["lags"] == list(lags)
    assert len(d["ic"]) == len(lags) and len(d["n"]) == len(lags)
    assert d["n"][0] > d["n"][-1]  # longer horizon -> fewer pairs
    tp = self_corr_lag1(factor)
    assert tp is not None and tp > 0.9  # smooth factor: rank-persistent
    assert self_corr_lag1([1.0, None, 2.0]) is None  # < 3 pairs


def test_vol_family_matches_prefix_evaluation():
    """Oracle proof for the _vol_family fast path: its vol_pct / vol_z series
    must equal, element for element and to the exact float, the literal prefix
    sweep of the library volatility_regime -- the same-implementation
    guarantee the O(n) shortcut must never silently break. 160 bars exercises
    warmup, growing history, and the lookback-capped (>144 bars) regime."""
    from quantdesk.factors.quant import volatility_regime

    closes = _walk(160, seed=13)
    fast = fac._vol_family(closes)
    naive = fac._prefix_family(
        closes,
        lambda xs: volatility_regime(xs, 24, 120, 24 * 365),
        25,
        {"vol_pct": lambda d: d.get("percentile"), "vol_z": lambda d: d.get("zscore")},
    )
    assert fast["vol_pct"] == naive["vol_pct"]
    assert fast["vol_z"] == naive["vol_z"]


def test_corr_matrix_symmetric_unit_diag_min_overlap():
    x = [float(i % 7) + 0.1 * i for i in range(60)]
    y = [-v for v in x]
    z = [None] * 50 + [float(i) for i in range(10)]  # only 10 joint indices
    m = corr_matrix({"x": x, "y": y, "z": z})
    assert m["ids"] == ["x", "y", "z"]
    mat = m["matrix"]
    assert mat[0][0] == 1.0 and mat[1][1] == 1.0 and mat[2][2] == 1.0
    assert mat[0][1] == pytest.approx(-1.0)
    assert mat[0][1] == mat[1][0]
    assert mat[0][2] is None and mat[2][0] is None  # overlap < 30 -> None cell
    assert mat[1][2] is None and mat[2][1] is None


# ----------------------------------------------------------------- payload --
_EXISTING_IDS = [
    "tsmom_score", "tsmom_s22", "tsmom_s65", "tsmom_s261", "tsmom_vol_ratio",
    "mom_z_6b", "mom_z_24b", "mom_z_72b", "vol_pct", "vol_z", "funding_z",
]


def test_build_symbol_factors_payload_shape(monkeypatch):
    closes_1h, closes_1d = _walk(240), _walk(266, seed=2)  # 265 closed >= 263
    row = build_symbol_factors("BTC-USD", FakeCoinbase(closes_1h, closes_1d))
    assert row["ok"] is True
    assert [r["id"] for r in row["alpha101"]] == [e["id"] for e in ALPHAS]
    for r in row["alpha101"]:
        for key in ("id", "num", "style", "formula", "adaptation", "lookback",
                    "timeframe", "ok", "value", "n_obs", "turnover_proxy",
                    "ic", "decay", "spark"):
            assert key in r, f"{r['id']}: missing {key}"
        assert r["timeframe"] == "1h"
        for entry in r["ic"]:
            assert "n" in entry and "h" in entry and "label" in entry
    assert [r["id"] for r in row["existing"]] == _EXISTING_IDS
    ts_row = row["existing"][0]
    assert ts_row["ok"] is True and ts_row["source"] == "quantdesk/factors/tsmom.py tsmom_score"
    for key in ("s22", "s65", "s261", "sigma_ann", "sigma_fast", "sigma_slow", "vol_ratio"):
        assert key in ts_row["diag"] and ts_row["diag"][key] is not None
    for r in row["existing"]:
        if isinstance(r["ic"], list):
            for entry in r["ic"]:
                assert "n" in entry
    corr = row["correlation"]
    assert "basis" in corr
    assert len(corr["ids"]) == len(corr["matrix"]) == 19 + 5  # alphas + 1h existing
    # envelope: disclaimer / ic_convention / ttl / hoisted bar counts
    out = compute_factors(["BTC-USD"], FakeCoinbase(closes_1h, closes_1d))
    assert out["ttl_s"] == 60 and out["granularity"] == "1h"
    assert out["disclaimer"]["ref"]  # a pointer to the research notes
    assert "observables" in out["disclaimer"]["en"]
    assert "zh" not in out["disclaimer"]
    assert "degenerate" in out["ic_convention"]
    assert out["bars_1h"] == 239 and out["bars_1d"] == 265
    sym = out["symbols"][0]
    assert sym["ok"] is True
    assert "bars_1h" not in sym  # hoisted to the top level
    assert "generated_at" in out
    # research observables only: no action/recommendation anywhere
    assert "recommendation" not in sym and "action" not in sym


def test_insufficient_history_per_factor_isolated():
    row = build_symbol_factors(
        "BTC-USD", FakeCoinbase(_walk(61), _walk(40, seed=2)))  # 60 closed 1h bars
    assert row["ok"] is True  # payload survives; only the long factors gate
    by_id = {r["id"]: r for r in row["alpha101"]}
    for aid in ("a006", "a012", "a101"):
        assert by_id[aid]["ok"] is True and by_id[aid]["value"] is not None
    lookbacks = {e["id"]: e["lookback"] for e in ALPHAS}
    for aid in ("a024", "a032"):
        r = by_id[aid]
        assert r["ok"] is False and r["value"] is None
        assert r["need"] == lookbacks[aid]
        assert r["ic"] == [] and r["decay"] is None
        assert r["n_obs"] == 0


def test_fetch_failure_isolated(monkeypatch):
    good_1h, good_1d = _walk(240), _walk(100, seed=2)
    out = compute_factors(["BTC-USD", "BAD-USD"],
                          FakeCoinbase(good_1h, good_1d, raise_for={"BAD-USD"}))
    rows = {r["symbol"]: r for r in out["symbols"]}
    bad = rows["BAD-USD"]
    assert bad["ok"] is False and bad["error"].startswith("fetch_failed")
    good = rows["BTC-USD"]
    assert good["ok"] is True and len(good["alpha101"]) == 19


def test_daily_tsmom_rows_need_gate():
    row = build_symbol_factors(
        "BTC-USD", FakeCoinbase(_walk(120), _walk(100, seed=2)))  # 99 closed 1d < 263
    tsmom_rows = [r for r in row["existing"] if r["id"].startswith("tsmom")]
    assert len(tsmom_rows) == 5
    for r in tsmom_rows:
        assert r["ok"] is False and r["value"] is None
        assert r["need"] == 263
        assert r["ic"] == [] and r["decay"] is None
    # ok:false diag still carries the keys (values None) — signals.py shape
    diag = tsmom_rows[0]["diag"]
    assert set(diag) == {"s22", "s65", "s261", "sigma_ann",
                         "sigma_fast", "sigma_slow", "vol_ratio"}
    assert all(v is None for v in diag.values())


def test_funding_row_live_value_no_ic():
    row = build_symbol_factors(
        "BTC-USD", FakeCoinbase(_walk(80), _walk(40, seed=2)), funding_client=FakeFunding())
    frow = next(r for r in row["existing"] if r["id"] == "funding_z")
    assert frow["ok"] is True and frow["value"] is not None
    assert frow["timeframe"] == "8h"
    assert frow["ic"] is None and frow["decay"] is None  # 8h series unaligned to 1h bars
    assert frow["n_obs"] == 59  # 60 rates -> 59 history samples
    assert frow["note"]
