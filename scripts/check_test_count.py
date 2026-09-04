#!/usr/bin/env python
"""Check every test count the README states against ``pytest --collect-only``.

docs/HONESTY.md rule 10: a count typed into a document is checked, not
trusted. This script finds every place README.md states a test count (the
shields.io badge ``tests-N%20passing`` and the prose ``N tests``), runs the
collector, and exits 1 if any of them differs from what pytest collects.

    python scripts/check_test_count.py            # check (CI runs this)
    python scripts/check_test_count.py --fix      # rewrite README.md to the collected count

Pure stdlib; pytest must be installed (it is the collector).
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
README = ROOT / "README.md"
_PATTERNS = (
    re.compile(r"tests-(\d+)%20passing"),        # shields.io badge
    re.compile(r"(?<![\w.])(\d+) tests\b"),      # prose: "269 tests"
)


def collected_count(pytest_args: list[str]) -> int:
    cmd = [sys.executable, "-m", "pytest", "--collect-only", "-q", "-p", "no:cacheprovider", *pytest_args]
    run = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace")
    m = re.search(r"(\d+) tests? collected", run.stdout)
    if run.returncode not in (0, 5) or not m:
        sys.stderr.write(run.stdout[-3000:] + run.stderr[-3000:])
        raise SystemExit("check_test_count: pytest collection failed")
    return int(m.group(1))


def stated_counts(text: str) -> list[tuple[str, int]]:
    out: list[tuple[str, int]] = []
    for rx in _PATTERNS:
        out.extend((m.group(0), int(m.group(1))) for m in rx.finditer(text))
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--fix", action="store_true", help="rewrite README.md to the collected count")
    ap.add_argument("pytest_args", nargs="*", help="extra arguments for the collector")
    args = ap.parse_args(argv)
    text = README.read_text(encoding="utf-8")
    stated = stated_counts(text)
    if not stated:
        print("check_test_count: README.md states no test count; nothing to check")
        return 0
    actual = collected_count(args.pytest_args)
    drift = [(s, n) for s, n in stated if n != actual]
    if not drift:
        print(f"check_test_count: README.md states {actual} tests in {len(stated)} place(s); "
              f"collector agrees")
        return 0
    if args.fix:
        for s, n in drift:
            text = text.replace(s, s.replace(str(n), str(actual)))
        README.write_text(text, encoding="utf-8", newline="\n")
        print(f"check_test_count: rewrote {len(drift)} count(s) in README.md to {actual}")
        return 0
    for s, n in drift:
        print(f"check_test_count: README.md says {n} ({s!r}) but pytest collects {actual}",
              file=sys.stderr)
    print("check_test_count: run `python scripts/check_test_count.py --fix`", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
