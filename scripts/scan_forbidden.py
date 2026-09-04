#!/usr/bin/env python3
"""Refuse-on-hit content scanner for the public QuantDesk tree.

Walks a directory and reports every line that matches a forbidden pattern.
The detectors built into this file are GENERIC and identify nobody:

- CJK ideographs / fullwidth punctuation (allowed only in the site's zh i18n
  dictionary, ``site/*.js``);
- absolute personal-path shapes (a Windows user-profile path, a WSL mount, a
  POSIX home directory);
- credential-shaped strings (common API-token prefixes, PEM private keys);
- dotenv file names (the ``.gitignore`` may list them; nothing else may);
- files whose extension or path marks them as build artefacts or data
  (bytecode, Parquet, JSONL, databases, archives, PDFs).

Project-specific words (internal product names, venue names, vendor names,
environment-variable prefixes, ...) are deliberately NOT stored in this file.
They live in a private pattern file that is not part of the public repository
and is supplied with ``--private-patterns FILE`` or the environment variable
``SCAN_PRIVATE_PATTERNS`` (CI mounts it from a secret; without it the generic
detectors still run).

Private pattern file format, one entry per line; blank lines and ``#``
comments are ignored:

    plain-regex                        # searched case-sensitively
    {"name": "x", "re": "...", "flags": "i", "exempt": ["NOTICE.md"]}

The JSON form adds a display name, ``flags`` (``i`` = case-insensitive) and
``exempt`` basenames the pattern does not apply to.

Usage:
    python scripts/scan_forbidden.py [ROOT] [--private-patterns FILE] [--strict] [--quiet]

By default tool caches that are gitignored anyway (``__pycache__``,
``.ruff_cache``, ``.pytest_cache``, virtualenvs, ``build``, ``*.egg-info``)
are skipped so a local run after ``pytest`` or ``pip install -e .`` stays
meaningful; ``--strict`` scans them too and refuses any ``__pycache__`` or
bytecode file it finds (the export gate and CI run in strict mode).

Exit status 0 when clean, 1 on any hit (each hit is printed as
``path:line:pattern``). Pure stdlib.

The generic regexes below are assembled from fragments so that this file
does not itself contain the shapes it refuses (otherwise the scanner would
flag its own source).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

# --------------------------------------------------------------------------- #
# generic detectors (assembled from fragments: see the docstring)
# --------------------------------------------------------------------------- #
_WIN_PROFILE = "C:" + r"\\{1,2}" + "Users"                 # a Windows user-profile path
_WSL_MOUNT = "/mnt" + "/c"                                 # a WSL drive mount
_POSIX_HOME = "/Us" + "ers/"                               # a macOS home directory
_TOKEN_SK = "sk" + "-[A-Za-z0-9_-]{16,}"                   # common API-token prefix
_TOKEN_GH = "gh[pousr]" + "_[A-Za-z0-9]{36}"               # GitHub token shapes
_PEM_KEY = "BEGIN" + " [A-Z ]*PRIVATE" + " KEY"
_DOTENV = r"(?<![\w.])\." + "env" + r"\b(?!\.example)"     # dotenv names (the *.example form is fine)

# (name, regex, flags, basenames exempt from the pattern)
_GENERIC_PATTERNS: tuple[tuple[str, str, int, frozenset[str]], ...] = (
    ("abs-path-windows-profile", _WIN_PROFILE, 0, frozenset()),
    ("abs-path-wsl-mount", _WSL_MOUNT, 0, frozenset()),
    ("abs-path-posix-home", _POSIX_HOME, 0, frozenset()),
    ("secret-token-sk", _TOKEN_SK, 0, frozenset()),
    ("secret-token-gh", _TOKEN_GH, 0, frozenset()),
    ("secret-private-key", _PEM_KEY, 0, frozenset()),
    ("dotenv-file", _DOTENV, 0, frozenset({".gitignore", ".dockerignore"})),
)

_CJK_PATTERNS = ("cjk-ideograph", "cjk-punctuation-or-fullwidth")


def _cjk_exempt(rel: str) -> bool:
    """The ONE place CJK is allowed: the zh i18n dictionary inside the site's
    JavaScript. Nothing else in the tree may carry it."""
    return rel.startswith("site/") and rel.endswith(".js")


FORBIDDEN_EXTENSIONS = {".pyc", ".pyo", ".parquet", ".jsonl", ".db", ".sqlite", ".zip", ".pdf"}
FORBIDDEN_PATH_SEGMENTS = {"__pycache__"}
_BINARY_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".ico", ".woff", ".woff2", ".ttf", ".otf", ".webp"}
# Always skipped: version control. Skipped unless --strict: gitignored tool caches.
_ALWAYS_SKIP_DIRS = {".git"}
_CACHE_DIRS = {
    "__pycache__", ".ruff_cache", ".pytest_cache", ".mypy_cache", ".tox", ".nox",
    ".venv", "venv", "build", "node_modules", ".eggs",
}

Pattern = tuple[str, "re.Pattern[str]", frozenset[str]]


def build_patterns() -> list[Pattern]:
    """(name, compiled regex, basenames exempt from this pattern)."""
    pats: list[Pattern] = [
        ("cjk-ideograph", re.compile(r"[\u4e00-\u9fff]"), frozenset()),
        ("cjk-punctuation-or-fullwidth", re.compile(r"[\u3000-\u303f\uff00-\uffef]"), frozenset()),
    ]
    for name, rx, flags, exempt in _GENERIC_PATTERNS:
        pats.append((name, re.compile(rx, flags), exempt))
    return pats


def _flags(spec: str) -> int:
    flags = 0
    for ch in spec:
        if ch == "i":
            flags |= re.IGNORECASE
        elif ch == "m":
            flags |= re.MULTILINE
        else:
            raise ValueError(f"unknown regex flag {ch!r}")
    return flags


def load_private_patterns(path: Path | None) -> list[Pattern]:
    """Plain regex or JSON-object lines (see the module docstring). Missing
    file -> []. A malformed line is an error: a silently dropped pattern is
    a scanner that lies."""
    if path is None or not path.is_file():
        return []
    out: list[Pattern] = []
    for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        if s.startswith("{"):
            try:
                spec = json.loads(s)
                rx = re.compile(spec["re"], _flags(str(spec.get("flags", ""))))
            except (ValueError, KeyError, re.error) as exc:
                raise SystemExit(f"{path}:{i}: bad private pattern line: {exc}") from exc
            name = str(spec.get("name") or f"private:{i}")
            exempt = frozenset(str(b) for b in spec.get("exempt", ()))
            out.append((name, rx, exempt))
        else:
            try:
                out.append((f"private:{i}", re.compile(s), frozenset()))
            except re.error as exc:
                raise SystemExit(f"{path}:{i}: bad private pattern line: {exc}") from exc
    return out


def default_private_pattern_file() -> Path | None:
    """``SCAN_PRIVATE_PATTERNS`` when set, else a sibling file that exists only
    in the private repository (a public checkout has none -> generic only)."""
    env = os.environ.get("SCAN_PRIVATE_PATTERNS")
    if env:
        return Path(env)
    return Path(__file__).resolve().with_name("export_private_patterns.txt")


# --------------------------------------------------------------------------- #
# scanning
# --------------------------------------------------------------------------- #
def _skip_dir(name: str, strict: bool) -> bool:
    if name in _ALWAYS_SKIP_DIRS:
        return True
    if strict:
        return False
    return name in _CACHE_DIRS or name.endswith(".egg-info")


def iter_files(root: Path, strict: bool = False):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if not _skip_dir(d, strict))
        for name in sorted(filenames):
            yield Path(dirpath) / name


def scan_tree(
    root: Path, private_file: Path | None = None, *, strict: bool = False
) -> list[tuple[str, int, str]]:
    """Return [(relative path, line number, pattern name)], sorted."""
    patterns = build_patterns() + load_private_patterns(private_file)
    hits: list[tuple[str, int, str]] = []
    root = root.resolve()
    for path in iter_files(root, strict):
        relpath = path.relative_to(root)
        rel = relpath.as_posix()
        if set(relpath.parts) & FORBIDDEN_PATH_SEGMENTS:
            hits.append((rel, 0, "forbidden-path-segment"))
            continue
        suffix = path.suffix.lower()
        if suffix in FORBIDDEN_EXTENSIONS:
            hits.append((rel, 0, f"forbidden-extension:{suffix}"))
            continue
        if suffix in _BINARY_EXTENSIONS:
            continue
        try:
            raw = path.read_bytes()
        except OSError as exc:
            hits.append((rel, 0, f"unreadable:{exc.__class__.__name__}"))
            continue
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            hits.append((rel, 0, "not-utf8"))
            text = raw.decode("utf-8", errors="replace")
        base = path.name
        cjk_ok = _cjk_exempt(rel)
        for lineno, line in enumerate(text.splitlines(), start=1):
            for name, rx, exempt in patterns:
                if base in exempt or (cjk_ok and name in _CJK_PATTERNS):
                    continue
                if rx.search(line):
                    hits.append((rel, lineno, name))
    hits.sort()
    return hits


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("root", nargs="?", default=".", help="directory to scan (default: cwd)")
    ap.add_argument("--private-patterns", default=None,
                    help="private pattern file (default: $SCAN_PRIVATE_PATTERNS, else none)")
    ap.add_argument("--strict", action="store_true",
                    help="scan gitignored tool caches too and refuse any bytecode/__pycache__")
    ap.add_argument("--quiet", action="store_true", help="print only the summary line")
    args = ap.parse_args(argv)
    root = Path(args.root)
    if not root.is_dir():
        print(f"scan_forbidden: not a directory: {root}", file=sys.stderr)
        return 2
    private = Path(args.private_patterns) if args.private_patterns else default_private_pattern_file()
    n_private = len(load_private_patterns(private))
    hits = scan_tree(root, private, strict=args.strict)
    if not args.quiet:
        for rel, lineno, name in hits:
            print(f"{rel}:{lineno}:{name}")
    n_files = sum(1 for _ in iter_files(root, args.strict))
    mode = "strict" if args.strict else "default"
    private_note = f"{n_private} private pattern(s)" if n_private else "generic detectors only"
    if hits:
        print(f"scan_forbidden: {len(hits)} hit(s) in {root} ({n_files} files scanned, {mode}, "
              f"{private_note}) -> REFUSED", file=sys.stderr)
        return 1
    print(f"scan_forbidden: clean ({n_files} files scanned under {root}, {mode}, {private_note})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
