"""Regression guard: the four agent-CLI versions must stay in lock-step between
the ``Dockerfile`` (where they are actually installed) and ``package.json`` (the
Dependabot manifest).

This is a **drift-equality** test. It deliberately does NOT hardcode version
numbers, so a legitimate Dependabot bump (raised as one PR via the ``ai-cli``
group in ``.github/dependabot.yml``) keeps it green. It anchors package *names*
so a silently dropped or swapped backend turns it red.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
DOCKERFILE = REPO_ROOT / "Dockerfile"
PACKAGE_JSON = REPO_ROOT / "package.json"

# Names only — no versions. The set that MUST appear, identically pinned, in both files.
EXPECTED_PACKAGES = frozenset(
    {
        "@github/copilot",
        "@openai/codex",
        "@google/gemini-cli",
        "@anthropic-ai/claude-code",
    }
)

_NPM_INSTALL_RE = re.compile(r"npm install -g\s+(\S+)")
_FLOATING_CHARS = set("^~><*|")


def _split_spec(spec: str) -> tuple[str, str]:
    """Split ``@scope/name@version`` into (name, version) on the LAST ``@``.

    Using rsplit('@', 1) so the leading ``@`` of a scoped package name is not
    mis-split: ``@google/gemini-cli@0.46.0`` -> (``@google/gemini-cli``, ``0.46.0``).
    """
    name, _, version = spec.rpartition("@")
    # rpartition splits on the LAST "@", identical to rsplit("@", 1) for this purpose:
    # "@google/gemini-cli@0.46.0" -> ("@google/gemini-cli", "0.46.0").
    if not name or not version:
        raise AssertionError(f"unparseable npm spec (no version?): {spec!r}")
    return name, version


def _dockerfile_pkgs(text: str) -> dict[str, str]:
    """Parse ``npm install -g <pkg>@<ver>`` specs; raise on a duplicate package line."""
    pkgs: dict[str, str] = {}
    for spec in _NPM_INSTALL_RE.findall(text):
        name, version = _split_spec(spec)
        if name in pkgs:
            raise AssertionError(f"duplicate Dockerfile install line for {name!r}")
        pkgs[name] = version
    return pkgs


def _package_json_pkgs(text: str) -> dict[str, str]:
    return dict(json.loads(text).get("dependencies", {}))


def _is_exact_pin(version: str) -> bool:
    v = version.strip()
    if not v or v in {"latest", "*", "x", "X"}:
        return False
    if _FLOATING_CHARS & set(v) or " - " in v:
        return False
    return bool(re.match(r"^\d+\.\d+\.\d+", v))


def assert_in_sync(dockerfile_text: str, package_json_text: str) -> None:
    """Raise AssertionError unless the two manifests agree on the expected package set."""
    docker = _dockerfile_pkgs(dockerfile_text)  # raises on duplicate
    pkg = _package_json_pkgs(package_json_text)

    # Exactly the expected set in each file (covers count==4, name-anchoring,
    # and set-equality in both directions in one shot).
    assert set(docker) == EXPECTED_PACKAGES, f"Dockerfile packages {set(docker)} != {set(EXPECTED_PACKAGES)}"
    assert set(pkg) == EXPECTED_PACKAGES, f"package.json packages {set(pkg)} != {set(EXPECTED_PACKAGES)}"

    # Versions agree across files (no hardcoded version literals here).
    for name in EXPECTED_PACKAGES:
        assert docker[name] == pkg[name], (
            f"{name}: Dockerfile pins {docker[name]!r} but package.json pins {pkg[name]!r}"
        )

    # Reject floating specs — pins must be exact for reproducible images.
    for name, version in {**docker, **pkg}.items():
        assert _is_exact_pin(version), f"{name} is not an exact pin: {version!r}"


# ── The real repo files ───────────────────────────────────────────────────────


def test_real_files_in_sync() -> None:
    assert_in_sync(DOCKERFILE.read_text(), PACKAGE_JSON.read_text())


def test_real_dockerfile_covers_expected_set() -> None:
    assert set(_dockerfile_pkgs(DOCKERFILE.read_text())) == EXPECTED_PACKAGES


# ── Parser unit proofs ──────────────────────────────────────────────────────────


def test_rsplit_handles_scoped_names() -> None:
    parsed = _dockerfile_pkgs("RUN npm install -g @google/gemini-cli@0.46.0\n")
    assert parsed == {"@google/gemini-cli": "0.46.0"}


def test_unscoped_name_parses() -> None:
    assert _split_spec("copilot@1.2.3") == ("copilot", "1.2.3")


@pytest.mark.parametrize(
    "version,exact",
    [
        ("1.0.61", True),
        ("0.139.0", True),
        ("2.1.177", True),
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


# ── Negative cases on synthetic content (never touches the real files) ──────────

_GOOD_DOCKERFILE = (
    "RUN npm install -g @github/copilot@1.0.61\n"
    "RUN npm install -g @openai/codex@0.139.0\n"
    "RUN npm install -g @google/gemini-cli@0.46.0\n"
    "RUN npm install -g @anthropic-ai/claude-code@2.1.177\n"
)
_GOOD_PKGJSON = json.dumps(
    {
        "dependencies": {
            "@github/copilot": "1.0.61",
            "@openai/codex": "0.139.0",
            "@google/gemini-cli": "0.46.0",
            "@anthropic-ai/claude-code": "2.1.177",
        }
    }
)


def test_synthetic_good_pair_passes() -> None:
    assert_in_sync(_GOOD_DOCKERFILE, _GOOD_PKGJSON)


@pytest.mark.parametrize(
    "dockerfile,pkgjson,reason",
    [
        # package missing from package.json
        (
            _GOOD_DOCKERFILE,
            json.dumps(
                {
                    "dependencies": {
                        "@github/copilot": "1.0.61",
                        "@openai/codex": "0.139.0",
                        "@google/gemini-cli": "0.46.0",
                    }
                }
            ),
            "missing in package.json",
        ),
        # package missing from Dockerfile
        (
            "RUN npm install -g @github/copilot@1.0.61\n"
            "RUN npm install -g @openai/codex@0.139.0\n"
            "RUN npm install -g @google/gemini-cli@0.46.0\n",
            _GOOD_PKGJSON,
            "missing in Dockerfile",
        ),
        # cross-file version mismatch
        (
            _GOOD_DOCKERFILE.replace("@github/copilot@1.0.61", "@github/copilot@1.0.60"),
            _GOOD_PKGJSON,
            "version mismatch",
        ),
        # floating spec in package.json
        (
            _GOOD_DOCKERFILE,
            _GOOD_PKGJSON.replace('"1.0.61"', '"^1.0.61"'),
            "floating spec",
        ),
        # duplicate install line in Dockerfile
        (
            _GOOD_DOCKERFILE + "RUN npm install -g @github/copilot@1.0.61\n",
            _GOOD_PKGJSON,
            "duplicate line",
        ),
        # swapped package keeps count==4 but breaks name set
        (
            _GOOD_DOCKERFILE.replace(
                "@anthropic-ai/claude-code@2.1.177", "@some/other-pkg@1.0.0"
            ),
            _GOOD_PKGJSON,
            "swapped package name",
        ),
    ],
)
def test_synthetic_drift_is_detected(dockerfile: str, pkgjson: str, reason: str) -> None:
    with pytest.raises(AssertionError):
        assert_in_sync(dockerfile, pkgjson)
