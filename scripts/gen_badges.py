#!/usr/bin/env python3
"""Generate shields.io ``endpoint`` JSON badges (tests, coverage) from CI artifacts.

Reads a JUnit XML (``pytest --junitxml``) and a coverage JSON (``pytest
--cov-report=json``) and writes ``tests.json`` / ``coverage.json`` (shields.io
``endpoint`` schema) into an output directory.

XML is parsed with ``defusedxml`` (XXE / billion-laughs hardened) even though the
JUnit file is produced by our own pytest run in the same CI job — defence in depth,
no reliance on the input being trusted.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from xml.etree.ElementTree import ParseError

from defusedxml.ElementTree import parse as _parse_xml

# Literal error-message prefixes — pinned so tests and implementation agree.
ERR_MISSING = "input file not found"
ERR_MALFORMED_XML = "could not parse JUnit XML"
ERR_NO_SUITE = "no <testsuite> element in JUnit XML"
ERR_ZERO_TESTS = "JUnit reports zero tests (run is broken)"
ERR_MALFORMED_JSON = "could not parse coverage JSON"
ERR_NO_COVERAGE_KEY = "coverage JSON missing totals.percent_covered"


def _coverage_color(pct: int) -> str:
    """Inclusive thresholds: >=80 brightgreen, >=60 yellow, else red."""
    if pct >= 80:
        return "brightgreen"
    if pct >= 60:
        return "yellow"
    return "red"


def tests_badge(junit_xml_path: str | Path) -> dict:
    """Build the shields endpoint dict for the test count.

    Sums tests/failures/errors/skipped across every ``<testsuite>`` (robust to a
    multi-suite ``<testsuites>`` root). ``passed = tests - failures - errors -
    skipped``; colour is brightgreen only when failures+errors == 0.
    """
    path = Path(junit_xml_path)
    if not path.is_file():
        raise FileNotFoundError(f"{ERR_MISSING}: {path}")
    try:
        root = _parse_xml(path).getroot()
    except ParseError as exc:
        raise ValueError(f"{ERR_MALFORMED_XML}: {path}") from exc

    total = failures = errors = skipped = 0
    found = False
    for suite in root.iter("testsuite"):
        found = True
        total += int(suite.get("tests", 0))
        failures += int(suite.get("failures", 0))
        errors += int(suite.get("errors", 0))
        skipped += int(suite.get("skipped", 0))
    if not found:
        raise ValueError(f"{ERR_NO_SUITE}: {path}")
    if total == 0:
        raise ValueError(f"{ERR_ZERO_TESTS}: {path}")

    passed = total - failures - errors - skipped
    color = "brightgreen" if (failures + errors) == 0 else "red"
    return {"schemaVersion": 1, "label": "tests", "message": f"{passed} passed", "color": color}


def coverage_badge(coverage_json_path: str | Path) -> dict:
    """Build the shields endpoint dict for line coverage (rounded percent)."""
    path = Path(coverage_json_path)
    if not path.is_file():
        raise FileNotFoundError(f"{ERR_MISSING}: {path}")
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        raise ValueError(f"{ERR_MALFORMED_JSON}: {path}") from exc
    try:
        pct_raw = data["totals"]["percent_covered"]
    except (KeyError, TypeError) as exc:
        raise ValueError(f"{ERR_NO_COVERAGE_KEY}: {path}") from exc

    pct = round(float(pct_raw))  # banker's rounding to nearest int
    return {"schemaVersion": 1, "label": "coverage", "message": f"{pct}%", "color": _coverage_color(pct)}


def main(argv: list[str]) -> int:
    out_dir = argv[1] if len(argv) > 1 else "."
    junit_path = argv[2] if len(argv) > 2 else "test-results.xml"
    cov_path = argv[3] if len(argv) > 3 else "coverage.json"
    try:
        tests = tests_badge(junit_path)
        coverage = coverage_badge(cov_path)
    except (FileNotFoundError, ValueError) as exc:
        print(f"gen_badges: {exc}", file=sys.stderr)
        return 1
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "tests.json").write_text(json.dumps(tests) + "\n")
    (out / "coverage.json").write_text(json.dumps(coverage) + "\n")
    print(f"gen_badges: wrote tests.json ({tests['message']}) and coverage.json ({coverage['message']}) to {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
