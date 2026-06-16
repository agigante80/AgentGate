"""Regression guard for the agent-CLI versions.

Since the single-source-of-truth change, ``package.json`` is the ONLY place the
four agent-CLI versions are pinned; the ``Dockerfile`` installs exactly those
pins via ``npm install -g $(node -p ... require('/tmp/package.json') ...)``.
That removes the old Dockerfile↔manifest drift entirely (Dependabot's ``ai-cli``
group updates package.json and the image just follows).

This test therefore guards:
  1. package.json declares exactly the four expected CLI packages (name-anchored,
     no hardcoded versions here so legit Dependabot bumps stay green),
  2. every pin is exact (no ranges — reproducible images),
  3. the Dockerfile actually sources versions FROM package.json and does NOT
     reintroduce a hardcoded ``npm install -g <pkg>@<version>`` (which would bring
     back the drift this design removes).
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
DOCKERFILE = REPO_ROOT / "Dockerfile"
PACKAGE_JSON = REPO_ROOT / "package.json"

EXPECTED_PACKAGES = frozenset(
    {
        "@github/copilot",
        "@openai/codex",
        "@google/gemini-cli",
        "@anthropic-ai/claude-code",
    }
)

_FLOATING_CHARS = set("^~><*|")
# A hardcoded versioned global install of one of our CLIs would reintroduce drift.
_HARDCODED_CLI_INSTALL = re.compile(
    r"npm install -g\s+@(?:github/copilot|openai/codex|google/gemini-cli|anthropic-ai/claude-code)@",
)
# The single-source install must read versions from package.json.
_SINGLE_SOURCE_MARKER = "require('/tmp/package.json')"


def _package_json_pkgs(text: str) -> dict[str, str]:
    return dict(json.loads(text).get("dependencies", {}))


def _is_exact_pin(version: str) -> bool:
    v = version.strip()
    if not v or v in {"latest", "*", "x", "X"}:
        return False
    if _FLOATING_CHARS & set(v) or " - " in v:
        return False
    return bool(re.match(r"^\d+\.\d+\.\d+", v))


def assert_package_json_pins(package_json_text: str) -> None:
    pkgs = _package_json_pkgs(package_json_text)
    assert set(pkgs) == EXPECTED_PACKAGES, f"package.json packages {set(pkgs)} != {set(EXPECTED_PACKAGES)}"
    for name, version in pkgs.items():
        assert _is_exact_pin(version), f"{name} is not an exact pin: {version!r}"


def assert_dockerfile_single_source(dockerfile_text: str) -> None:
    assert _SINGLE_SOURCE_MARKER in dockerfile_text, (
        "Dockerfile must install CLI versions from package.json "
        f"(expected marker {_SINGLE_SOURCE_MARKER!r})"
    )
    hit = _HARDCODED_CLI_INSTALL.search(dockerfile_text)
    assert hit is None, (
        f"Dockerfile reintroduces a hardcoded CLI version install ({hit.group(0) if hit else ''!r}) "
        "— versions must come only from package.json"
    )


# ── Real repo files ───────────────────────────────────────────────────────────


def test_real_package_json_pins() -> None:
    assert_package_json_pins(PACKAGE_JSON.read_text())


def test_real_dockerfile_is_single_source() -> None:
    assert_dockerfile_single_source(DOCKERFILE.read_text())


# ── Exact-pin unit proofs ───────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "version,exact",
    [
        ("1.0.63", True),
        ("0.140.0", True),
        ("^1.0.0", False),
        ("~1.0.0", False),
        (">=1.0.0", False),
        ("1.x", False),
        ("*", False),
        ("latest", False),
        ("1.0.0 - 2.0.0", False),
    ],
)
def test_exact_pin_detection(version: str, exact: bool) -> None:
    assert _is_exact_pin(version) is exact


# ── Synthetic negative cases ────────────────────────────────────────────────────

_GOOD_PKGJSON = json.dumps(
    {
        "dependencies": {
            "@github/copilot": "1.0.63",
            "@openai/codex": "0.140.0",
            "@google/gemini-cli": "0.46.0",
            "@anthropic-ai/claude-code": "2.1.178",
        }
    }
)


def test_synthetic_good_package_json_passes() -> None:
    assert_package_json_pins(_GOOD_PKGJSON)


@pytest.mark.parametrize(
    "pkgjson,reason",
    [
        (
            json.dumps({"dependencies": {"@github/copilot": "1.0.63", "@openai/codex": "0.140.0", "@google/gemini-cli": "0.46.0"}}),
            "missing a package",
        ),
        (_GOOD_PKGJSON.replace('"1.0.63"', '"^1.0.63"'), "floating spec"),
        (_GOOD_PKGJSON.replace('"@anthropic-ai/claude-code"', '"@some/other-pkg"'), "swapped package name"),
    ],
)
def test_synthetic_package_json_violations(pkgjson: str, reason: str) -> None:
    with pytest.raises(AssertionError):
        assert_package_json_pins(pkgjson)


def test_dockerfile_single_source_detects_hardcoded_install() -> None:
    bad = "COPY package.json /tmp/package.json\nRUN npm install -g @openai/codex@0.140.0\n"
    with pytest.raises(AssertionError):
        assert_dockerfile_single_source(bad)


def test_dockerfile_single_source_requires_marker() -> None:
    with pytest.raises(AssertionError):
        assert_dockerfile_single_source("RUN echo no install here\n")
