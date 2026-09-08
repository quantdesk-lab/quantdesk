"""Gate-set tests (quantdesk.search.gates): kappa calibrated from a small
null run sits near the analytic 1.0, the version digest is stable and
sensitive, the board's sample gates are imported not retyped, and the null
document now carries the samples the calibration reads."""
from __future__ import annotations

import pytest

from quantdesk.research.board import _MIN_IC_EFF, _MIN_IC_PAIRS
from quantdesk.research.null_calibration import null_ic_distribution
from quantdesk.search.gates import Gates, calibrate_gates, kappa_from_samples


@pytest.fixture(scope="module")
def null5():
    return null_ic_distribution(5, 350, seed0=2000)


def test_null_doc_carries_samples(null5):
    assert len(null5["samples"]) == null5["pooled"]["n"]
    assert all(len(s) == 2 and 0.0 <= s[0] <= 1.0 and s[1] >= _MIN_IC_PAIRS for s in null5["samples"])


def test_kappa_is_near_one_on_random_walks(null5):
    g = calibrate_gates(null5)
    assert 0.85 <= g.kappa <= 1.20, g.kappa
    assert g.null_source["kind"] == "empirical" and g.null_source["n_reseeds"] == 5
    assert g.min_ic_pairs == _MIN_IC_PAIRS and g.min_ic_eff == _MIN_IC_EFF
    assert g.q == 0.95 and len(g.version) == 12
    assert isinstance(g, Gates) and g.to_dict()["version"] == g.version


def test_version_is_stable_and_sensitive(null5):
    assert calibrate_gates(null5).version == calibrate_gates(null5).version
    a = calibrate_gates(samples=[(0.05, 300)] * 10)
    b = calibrate_gates(samples=[(0.06, 300)] * 10)
    assert a.version != b.version and a.kappa != b.kappa
    assert calibrate_gates(samples=[(0.05, 300)] * 10, q=0.9).version != a.version


def test_analytic_fallback_and_errors():
    g = calibrate_gates()
    assert g.kappa == 1.0 and g.null_source == {"kind": "analytic", "n_samples": 0}
    assert kappa_from_samples([(0.1, 101)]) == pytest.approx(1.0)
    with pytest.raises(ValueError):
        kappa_from_samples([(0.1, 1)])
    with pytest.raises(ValueError):
        calibrate_gates(q=1.5)
