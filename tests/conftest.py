"""Shared test isolation: the lake root is ALWAYS a temp directory.

A test that forgets to pass ``lake_root`` must read an honest empty lake, not
whatever ``./data/lake`` happens to hold on the developer's machine.
"""
from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _isolated_lake_root(tmp_path, monkeypatch):
    from quantdesk.research import microstructure_lake

    empty = tmp_path / "empty-lake"
    monkeypatch.setenv("QUANTDESK_LAKE_ROOT", str(empty))
    monkeypatch.setattr(microstructure_lake, "_DEFAULT_LAKE_ROOT", empty)
