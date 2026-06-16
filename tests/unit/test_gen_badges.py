"""Unit tests for scripts/gen_badges.py (shields.io endpoint badge generation)."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

# Load scripts/gen_badges.py (scripts/ is not a package).
_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "gen_badges.py"
_spec = importlib.util.spec_from_file_location("gen_badges", _SCRIPT)
gen_badges = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gen_badges)


def _write(tmp_path: Path, name: str, content: str) -> Path:
    p = tmp_path / name
    p.write_text(content)
    return p


def _junit(tests: int, failures: int = 0, errors: int = 0, skipped: int = 0) -> str:
    return (
        f'<testsuites><testsuite tests="{tests}" failures="{failures}" '
        f'errors="{errors}" skipped="{skipped}"></testsuite></testsuites>'
    )


def _coverage(pct: float) -> str:
    return json.dumps({"totals": {"percent_covered": pct}})


# ── tests_badge ─────────────────────────────────────────────────────────────


def test_tests_badge_shape_and_count(tmp_path: Path) -> None:
    badge = gen_badges.tests_badge(_write(tmp_path, "j.xml", _junit(796)))
    assert badge == {"schemaVersion": 1, "label": "tests", "message": "796 passed", "color": "brightgreen"}


def test_tests_badge_sums_multiple_testsuites(tmp_path: Path) -> None:
    xml = (
        '<testsuites>'
        '<testsuite tests="10" failures="0" errors="0" skipped="1"></testsuite>'
        '<testsuite tests="5" failures="0" errors="0" skipped="0"></testsuite>'
        '</testsuites>'
    )
    badge = gen_badges.tests_badge(_write(tmp_path, "j.xml", xml))
    assert badge["message"] == "14 passed"  # (10+5) - 1 skipped
    assert badge["color"] == "brightgreen"


def test_tests_badge_skipped_only_stays_green(tmp_path: Path) -> None:
    badge = gen_badges.tests_badge(_write(tmp_path, "j.xml", _junit(10, skipped=3)))
    assert badge["message"] == "7 passed"
    assert badge["color"] == "brightgreen"


def test_tests_badge_red_on_failure(tmp_path: Path) -> None:
    assert gen_badges.tests_badge(_write(tmp_path, "j.xml", _junit(10, failures=2)))["color"] == "red"


def test_tests_badge_red_on_errors_only(tmp_path: Path) -> None:
    badge = gen_badges.tests_badge(_write(tmp_path, "j.xml", _junit(10, failures=0, errors=1)))
    assert badge["color"] == "red"


def test_tests_badge_zero_tests_is_error(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="zero tests"):
        gen_badges.tests_badge(_write(tmp_path, "j.xml", _junit(0)))


def test_tests_badge_missing_file(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="input file not found"):
        gen_badges.tests_badge(tmp_path / "nope.xml")


def test_tests_badge_malformed_xml(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="could not parse JUnit XML"):
        gen_badges.tests_badge(_write(tmp_path, "j.xml", "<not valid xml"))


def test_tests_badge_no_testsuite(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="no <testsuite>"):
        gen_badges.tests_badge(_write(tmp_path, "j.xml", "<root></root>"))


# ── coverage_badge ──────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "pct,expected_msg,expected_color",
    [
        (86.0, "86%", "brightgreen"),
        (80.0, "80%", "brightgreen"),  # inclusive lower edge
        (79.0, "79%", "yellow"),
        (60.0, "60%", "yellow"),       # inclusive lower edge
        (59.0, "59%", "red"),
        (40.0, "40%", "red"),
        (85.6, "86%", "brightgreen"),  # fractional rounds up
        (79.5, "80%", "brightgreen"),  # rounds to 80 -> crosses threshold
    ],
)
def test_coverage_badge_thresholds_and_rounding(tmp_path: Path, pct, expected_msg, expected_color) -> None:
    badge = gen_badges.coverage_badge(_write(tmp_path, "c.json", _coverage(pct)))
    assert badge["schemaVersion"] == 1
    assert badge["label"] == "coverage"
    assert badge["message"] == expected_msg
    assert badge["color"] == expected_color


def test_coverage_badge_missing_file(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="input file not found"):
        gen_badges.coverage_badge(tmp_path / "nope.json")


def test_coverage_badge_malformed_json(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="could not parse coverage JSON"):
        gen_badges.coverage_badge(_write(tmp_path, "c.json", "{not json"))


def test_coverage_badge_missing_percent_key(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="missing totals.percent_covered"):
        gen_badges.coverage_badge(_write(tmp_path, "c.json", json.dumps({"totals": {}})))


# ── main() seam ───────────────────────────────────────────────────────────────


def test_main_writes_both_files(tmp_path: Path) -> None:
    junit = _write(tmp_path, "j.xml", _junit(796))
    cov = _write(tmp_path, "c.json", _coverage(86.0))
    out = tmp_path / "out"
    rc = gen_badges.main(["gen_badges.py", str(out), str(junit), str(cov)])
    assert rc == 0
    tests = json.loads((out / "tests.json").read_text())
    coverage = json.loads((out / "coverage.json").read_text())
    assert tests["message"] == "796 passed"
    assert coverage["message"] == "86%"


def test_main_nonzero_exit_on_bad_input(tmp_path: Path) -> None:
    rc = gen_badges.main(["gen_badges.py", str(tmp_path / "out"), str(tmp_path / "missing.xml"), str(tmp_path / "missing.json")])
    assert rc == 1
    assert not (tmp_path / "out" / "tests.json").exists()
