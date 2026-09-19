#!/usr/bin/env python3
"""Single test entry point for agent-delivery-gate.

Why this exists: several suites exercise CLI scripts that print structured JSON
to stdout. With plain ``python -m unittest discover`` that output interleaves
with the runner's own report, so the ``Ran N tests / OK`` summary is easy to
miss. This runner captures each test module's stdout, prints only the summary,
and exits non-zero on any failure or error.

Usage:
    python run_tests.py            # whole suite, summary only
    python run_tests.py -v         # also stream each module's report
    python run_tests.py --list     # list discovered modules and exit
"""
from __future__ import annotations

import argparse
import contextlib
import io
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent
TESTS_DIR = ROOT / "tests"


def discover_modules() -> list[str]:
    """Return dotted module names for every tests/**/test_*.py file."""
    names = []
    for path in sorted(TESTS_DIR.rglob("test_*.py")):
        rel = path.relative_to(ROOT).with_suffix("")
        names.append(".".join(rel.parts))
    return names


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("-v", "--verbose", action="store_true",
                    help="stream each module's full unittest report")
    ap.add_argument("--list", action="store_true",
                    help="list discovered test modules and exit")
    args = ap.parse_args()

    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))

    modules = discover_modules()
    if args.list:
        for m in modules:
            print(m)
        print(f"\n{len(modules)} test modules")
        return 0

    if not modules:
        print("No test modules found under tests/ - is the working tree complete?")
        return 2

    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    for name in modules:
        try:
            suite.addTests(loader.loadTestsFromName(name))
        except Exception as exc:  # noqa: BLE001 - surface import errors clearly
            print(f"ERROR: could not import {name}: {exc}")
            return 2

    if args.verbose:
        result = unittest.TextTestRunner(verbosity=1).run(suite)
        return 0 if result.wasSuccessful() else 1

    # Quiet mode: swallow test stdout (CLI scripts echo JSON) and print a summary.
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        result = unittest.TextTestRunner(stream=buf, verbosity=1).run(suite)

    ran = result.testsRun
    bad = len(result.failures) + len(result.errors)
    print("=" * 64)
    print(f"agent-delivery-gate test suite")
    print(f"  modules  : {len(modules)}")
    print(f"  tests    : {ran}")
    print(f"  failures : {len(result.failures)}")
    print(f"  errors   : {len(result.errors)}")
    print(f"  skipped  : {len(result.skipped)}")
    print("=" * 64)
    print("RESULT:", "OK" if result.wasSuccessful() else f"FAILED ({bad} problem(s))")

    if not result.wasSuccessful():
        print("\n--- failure detail ---")
        for case, tb in (result.failures + result.errors):
            print(f"\n### {case}")
            print("\n".join(tb.splitlines()[-15:]))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
