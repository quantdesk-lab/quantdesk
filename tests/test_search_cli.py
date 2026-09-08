"""CLI and packaging tests (quantdesk.search.cli): the package imports
without pyarrow, an empty lake is refused with an actionable message, and a
synthetic lake runs end to end with archive, resume and the holdout refusal."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

import quantdesk


def test_search_package_imports_without_pyarrow():
    code = ("import sys; import quantdesk.search.loop, quantdesk.search.cli; "
            "assert 'pyarrow' not in sys.modules, 'pyarrow leaked'; print('ok')")
    env = {**os.environ, "PYTHONPATH": str(Path(quantdesk.__file__).resolve().parents[1])}
    run = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=env)
    assert run.returncode == 0 and run.stdout.strip() == "ok", run.stderr


def test_empty_lake_is_refused(tmp_path, capsys):
    pytest.importorskip("pyarrow")
    from quantdesk.search.cli import main

    rc = main(["--lake-root", str(tmp_path / "nolake"), "--symbol", "SYN-1", "--generations", "1"])
    assert rc == 2
    assert "no network fallback" in capsys.readouterr().err


def test_synthetic_lake_end_to_end(tmp_path, capsys):
    pytest.importorskip("pyarrow")
    from quantdesk.demo.fixtures import write_synthetic_lake
    from quantdesk.search.cli import main

    write_synthetic_lake(tmp_path / "lake", "SYN-1", 40, seed=0)   # 40 days -> 960 hourly bars
    archive = tmp_path / "runs" / "a.jsonl"
    out = tmp_path / "runs" / "a.json"
    rc = main(["--lake-root", str(tmp_path / "lake"), "--symbol", "SYN-1", "--granularity", "1h",
               "--generations", "1", "--per-generation", "3", "--archive", str(archive), "--out", str(out)])
    assert rc == 0
    text = capsys.readouterr().out
    assert "trials" in text and "best in-sample |IC|" in text
    doc = json.loads(out.read_text(encoding="utf-8"))
    assert doc["symbol"] == "SYN-1" and doc["n_bars"] == 960 and doc["kind"] == "lake:1h"
    assert archive.exists()
    # without --resume an existing archive is refused
    assert main(["--lake-root", str(tmp_path / "lake"), "--symbol", "SYN-1", "--archive", str(archive)]) == 2
    rc2 = main(["--lake-root", str(tmp_path / "lake"), "--symbol", "SYN-1", "--generations", "1",
                "--per-generation", "2", "--archive", str(archive), "--resume"])
    assert rc2 in (0, 3)  # 3 = the holdout was already touched by the first run
    if rc2 == 3:
        assert "holdout already touched" in capsys.readouterr().err
