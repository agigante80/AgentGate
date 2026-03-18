#!/usr/bin/env python3
"""Docs lint script — keeps config documentation in sync.

Checks:
  1. Every env var defined in src/config.py is documented in README.md.
  2. .env.example has no stale entries vs src/config.py.
  3. docker-compose.yml.example has no stale var references.

Exit codes: 0 = all good, 1 = one or more violations found.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROADMAP_FILE = Path("docs/roadmap.md")
CONFIG_FILE = Path("src/config.py")
README_FILE = Path("README.md")
ENV_EXAMPLE_FILE = Path(".env.example")
COMPOSE_EXAMPLE_FILE = Path("docker-compose.yml.example")

_PASSTHROUGH_MARKER = "# passthrough:"
_COMPOSE_VAR_RE = re.compile(r'\b([A-Z][A-Z0-9_]{2,})=')

# Nested BaseSettings fields on Settings / AIConfig — not direct env vars.
_NESTED_CONFIG_FIELDS = {
    "telegram", "github", "log", "bot", "ai", "voice", "slack", "audit",
    "copilot", "codex", "direct", "model_config",
}


def extract_config_env_vars() -> set[str]:
    """Parse src/config.py and return the set of env var names it declares.

    Three sources:
    - ``alias="VAR_NAME"`` → explicit env var alias
    - ``env="VAR_NAME"`` inside Field() → explicit env override
    - Plain field declaration (no alias/env) → field_name.upper()

    Nested BaseSettings sub-config fields (telegram, bot, ai, …) are skipped.
    """
    if not CONFIG_FILE.is_file():
        return set()

    text = CONFIG_FILE.read_text()
    env_vars: set[str] = set()

    # 1. Explicit alias="VAR" or env="VAR"
    env_vars.update(re.findall(r'alias="([A-Z][A-Z0-9_]+)"', text))
    env_vars.update(re.findall(r'\benv="([A-Z][A-Z0-9_]+)"', text))

    # 2. Plain field declarations — 4-space-indented, no alias/env on the same line
    for m in re.finditer(r"^    ([a-z]\w*)\s*:", text, re.MULTILINE):
        name = m.group(1)
        if name in _NESTED_CONFIG_FIELDS:
            continue
        line_end = text.find("\n", m.start())
        line = text[m.start():line_end]
        if 'alias="' not in line and 'env="' not in line:
            env_vars.add(name.upper())

    return env_vars


def check_config_coverage(readme_text: str) -> tuple[list[str], list[str]]:
    """Return (errors, warnings) for env vars missing from README.md."""
    env_vars = extract_config_env_vars()
    if not env_vars:
        return [], []

    errors: list[str] = []
    for var in sorted(env_vars):
        if f"`{var}`" not in readme_text and var not in readme_text:
            errors.append(
                f"[CONFIG DRIFT] {var} is defined in src/config.py but not documented in README.md"
            )
    return errors, []


def _parse_env_example(config_vars: set[str]) -> tuple[set[str], set[str]]:
    """Return (declared_vars, passthrough_vars) from .env.example.

    Accepts the pre-extracted *config_vars* set to avoid redundant calls to
    ``extract_config_env_vars()`` across Check 6 and Check 7.

    Parses both uncommented and commented-out variable lines.  Lines that
    contain ``# passthrough:`` are added to *passthrough_vars* instead of
    *declared_vars* so Check 6 never flags them as stale.

    Passthrough classification only applies to vars genuinely absent from
    config.py — if a var matches ``# passthrough:`` but is a real config var,
    it is treated as declared so stale detection still applies.
    """
    declared: set[str] = set()
    passthroughs: set[str] = set()
    if not ENV_EXAMPLE_FILE.is_file():
        return declared, passthroughs
    for line in ENV_EXAMPLE_FILE.read_text().splitlines():
        stripped = line.strip().lstrip("#").strip()
        if "=" not in stripped:
            continue
        var = stripped.split("=", 1)[0].strip()
        # Skip non-env-var tokens (e.g. section headers that happen to contain "=")
        if not re.match(r'^[A-Z][A-Z0-9_]*$', var):
            continue
        # A passthrough marker on a genuine config var is treated as declared
        # (guards against accidental or malicious marker on a real var).
        if _PASSTHROUGH_MARKER in line and var not in config_vars:
            passthroughs.add(var)
        else:
            declared.add(var)
    return declared, passthroughs


def check_env_example_coverage(config_vars: set[str]) -> tuple[list[str], list[str]]:
    """Check 6: .env.example has no stale entries not present in src/config.py."""
    declared, _passthroughs = _parse_env_example(config_vars)
    errors: list[str] = []
    for var in sorted(declared - config_vars):
        errors.append(
            f"[ENV EXAMPLE STALE] {var} is in .env.example but not in src/config.py "
            "(add '# passthrough: <reason>' if intentional)"
        )
    return errors, []


def check_compose_coverage(config_vars: set[str]) -> tuple[list[str], list[str]]:
    """Check 7: docker-compose.yml.example has no stale variable references.

    Parses ``VAR=`` assignments in the compose file (non-comment lines only)
    and flags any that are unrecognised — i.e. not in *config_vars*, not
    declared in ``.env.example``, and not marked as a passthrough there.
    Comment lines are excluded so that illustrative examples in YAML comments
    do not produce false positives.
    """
    if not COMPOSE_EXAMPLE_FILE.is_file():
        return [], []
    declared, passthroughs = _parse_env_example(config_vars)
    all_known = declared | passthroughs | config_vars
    errors: set[str] = set()
    for line in COMPOSE_EXAMPLE_FILE.read_text().splitlines():
        if line.strip().startswith("#"):
            continue
        for m in _COMPOSE_VAR_RE.finditer(line):
            var = m.group(1)
            if var not in all_known:
                errors.add(
                    f"[COMPOSE STALE] {var} appears in docker-compose.yml.example "
                    "but is not in src/config.py or .env.example — "
                    "add a '# passthrough: <reason>' marker in .env.example if intentional"
                )
    return sorted(errors), []


def main() -> int:
    errors: list[str] = []
    warnings: list[str] = []

    readme_text = README_FILE.read_text() if README_FILE.is_file() else ""

    # ── Check 1: every config.py env var is documented in README.md ─────────
    config_vars = extract_config_env_vars()
    cfg_errors, cfg_warnings = check_config_coverage(readme_text)
    errors.extend(cfg_errors)
    warnings.extend(cfg_warnings)

    # ── Check 2: .env.example has no stale entries ───────────────────────────
    env_errors, _ = check_env_example_coverage(config_vars)
    errors.extend(env_errors)

    # ── Check 3: docker-compose.yml.example has no stale var references ──────
    compose_errors, _ = check_compose_coverage(config_vars)
    errors.extend(compose_errors)

    # ── Report ────────────────────────────────────────────────────────────────
    for w in warnings:
        print(f"⚠  {w}")
    for e in errors:
        print(f"✗  {e}")

    if not errors and not warnings:
        print("✓  docs lint passed — README config coverage complete.")
        return 0

    print(f"\nResult: {len(errors)} error(s), {len(warnings)} warning(s).")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
