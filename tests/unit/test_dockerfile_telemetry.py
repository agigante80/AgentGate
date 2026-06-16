"""Regression guard for the default-deny telemetry posture (issue #83).

Asserts the Dockerfile keeps the bundled agent CLIs' on-by-default usage telemetry
disabled. The only genuinely on-by-default channel is gemini's
``privacy.usageStatisticsEnabled`` (defaults to ``true``); the others are off or
export only to a configured OTLP collector (which we never set).

The checks are intentionally strict — a wrong var name, a path mismatch, malformed
gemini JSON, or an accidental OTLP exporter must FAIL here, not pass green.
"""
from __future__ import annotations

import json
import re
import shlex
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
DOCKERFILE = REPO_ROOT / "Dockerfile"

GEMINI_SETTINGS_PATH = "/etc/gemini-cli/settings.json"


class TelemetryPostureError(AssertionError):
    pass


def _join_continuations(text: str) -> list[str]:
    """Collapse backslash-newline line continuations into single logical lines."""
    logical: list[str] = []
    buf = ""
    for raw in text.splitlines():
        stripped = raw.rstrip()
        if stripped.endswith("\\"):
            buf += stripped[:-1] + " "
        else:
            logical.append(buf + stripped)
            buf = ""
    if buf:
        logical.append(buf)
    return logical


def parse_env(text: str) -> dict[str, str]:
    """Parse ENV directives into {KEY: value}, quote-stripped, multi-var aware.

    Handles ``ENV K=V``, ``ENV K=V K2=V2`` (multi-var), and legacy ``ENV K V``.
    Raises on a duplicate key with a *conflicting* value.
    """
    env: dict[str, str] = {}

    def _set(key: str, value: str) -> None:
        if key in env and env[key] != value:
            raise TelemetryPostureError(
                f"ENV {key} defined twice with conflicting values: {env[key]!r} vs {value!r}"
            )
        env[key] = value

    for line in _join_continuations(text):
        s = line.strip()
        if not s.startswith("ENV "):
            continue
        rest = s[4:].strip()
        tokens = shlex.split(rest)  # shlex strips surrounding quotes -> normalization
        if "=" not in rest and len(tokens) >= 2:
            _set(tokens[0], " ".join(tokens[1:]))  # legacy `ENV K V`
            continue
        for tok in tokens:
            if "=" in tok:
                k, v = tok.split("=", 1)
                _set(k, v)
    return env


def extract_gemini_write(text: str) -> tuple[str, str]:
    """Return (write_target_path, json_payload) from the gemini-settings RUN.

    Also enforces mkdir-before-write ordering inside that RUN.
    """
    for line in _join_continuations(text):
        if GEMINI_SETTINGS_PATH not in line or "printf" not in line:
            continue
        m = re.search(r"printf\s+'%s'\s+'(?P<payload>.*?)'\s*>\s*(?P<target>\S+)", line)
        if not m:
            raise TelemetryPostureError(f"could not parse gemini settings write: {line!r}")
        if "mkdir" in line and line.index("mkdir") > line.index("printf"):
            raise TelemetryPostureError("gemini settings RUN writes before `mkdir -p` (build-unsafe)")
        if "mkdir" not in line:
            raise TelemetryPostureError("gemini settings RUN lacks `mkdir -p` before write")
        return m.group("target"), m.group("payload")
    raise TelemetryPostureError("no gemini settings RUN found")


def assert_telemetry_posture(text: str) -> None:
    env = parse_env(text)

    # 1. Baseline controls present.
    if env.get("DO_NOT_TRACK") != "1":
        raise TelemetryPostureError("DO_NOT_TRACK=1 not set")
    if env.get("CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC") != "1":
        raise TelemetryPostureError("CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1 not set")

    # 2. Gemini system-settings path is set and matches the RUN write target.
    env_path = env.get("GEMINI_CLI_SYSTEM_SETTINGS_PATH")
    if not env_path:
        raise TelemetryPostureError("GEMINI_CLI_SYSTEM_SETTINGS_PATH not set")
    write_target, payload = extract_gemini_write(text)
    if env_path != write_target:
        raise TelemetryPostureError(
            f"ENV path {env_path!r} != RUN write target {write_target!r} (silent re-enable risk)"
        )

    # 3. The written JSON actually disables usage stats.
    try:
        data = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise TelemetryPostureError(f"gemini settings payload is not valid JSON: {payload!r}") from exc
    if data.get("privacy", {}).get("usageStatisticsEnabled") is not False:
        raise TelemetryPostureError(f"usageStatisticsEnabled is not false: {payload!r}")

    # 4. Settings RUN must precede `USER` (botuser cannot write /etc).
    run_pos = text.index(GEMINI_SETTINGS_PATH)
    user_match = re.search(r"^\s*USER\s+\S+", text, re.MULTILINE)
    if user_match and run_pos > user_match.start():
        raise TelemetryPostureError("gemini settings RUN appears after USER (botuser cannot write /etc)")

    # 5. No outward OTLP exporter endpoint set as an ENV (comments mentioning it are fine).
    otlp_keys = [k for k in env if k == "OTEL_EXPORTER_OTLP_ENDPOINT" or k.endswith("_OTLP_ENDPOINT")]
    if otlp_keys:
        raise TelemetryPostureError(f"OTLP exporter endpoint set via ENV {otlp_keys} — would enable OTEL export")


# ── Real Dockerfile ───────────────────────────────────────────────────────────


def test_real_dockerfile_has_telemetry_posture() -> None:
    assert_telemetry_posture(DOCKERFILE.read_text())


# ── Parser unit proofs ──────────────────────────────────────────────────────────


def test_parse_env_strips_quotes_and_handles_multivar() -> None:
    env = parse_env('ENV PATH="/x:$PATH"\nENV A=1 B=2\nENV C 3\n')
    assert env == {"PATH": "/x:$PATH", "A": "1", "B": "2", "C": "3"}


def test_parse_env_rejects_conflicting_duplicate() -> None:
    with pytest.raises(TelemetryPostureError):
        parse_env("ENV DO_NOT_TRACK=1\nENV DO_NOT_TRACK=0\n")


# ── Synthetic negative cases ────────────────────────────────────────────────────

_GOOD = (
    "ENV DO_NOT_TRACK=1\n"
    "ENV CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1\n"
    "ENV GEMINI_CLI_SYSTEM_SETTINGS_PATH=/etc/gemini-cli/settings.json\n"
    "RUN mkdir -p /etc/gemini-cli && "
    "printf '%s' '{\"privacy\":{\"usageStatisticsEnabled\":false}}' > /etc/gemini-cli/settings.json\n"
    "USER botuser\n"
)


def test_synthetic_good_passes() -> None:
    assert_telemetry_posture(_GOOD)


@pytest.mark.parametrize(
    "text,reason",
    [
        (_GOOD.replace("ENV DO_NOT_TRACK=1\n", ""), "missing DO_NOT_TRACK"),
        (
            _GOOD.replace(
                "ENV GEMINI_CLI_SYSTEM_SETTINGS_PATH=/etc/gemini-cli/settings.json",
                "ENV GEMINI_CLI_SYSTEM_SETTINGS_PATH=/etc/other/settings.json",
            ),
            "ENV<->RUN path mismatch",
        ),
        (
            _GOOD.replace('usageStatisticsEnabled\":false', 'usageStatisticsEnabled\":true'),
            "usage stats enabled",
        ),
        (_GOOD.replace('{"privacy"', "{not-json"), "malformed JSON"),
        (
            "USER botuser\n" + _GOOD.replace("USER botuser\n", ""),
            "settings RUN after USER",
        ),
        (
            _GOOD.replace(
                "RUN mkdir -p /etc/gemini-cli && printf",
                "RUN printf",
            ),
            "printf without mkdir",
        ),
        (_GOOD + "ENV DO_NOT_TRACK=0\n", "duplicate conflicting ENV"),
        (_GOOD + "ENV OTEL_EXPORTER_OTLP_ENDPOINT=http://collector:4317\n", "OTLP exporter set"),
        (
            _GOOD.replace(
                "ENV GEMINI_CLI_SYSTEM_SETTINGS_PATH=/etc/gemini-cli/settings.json",
                'ENV GEMINI_CLI_SYSTEM_SETTINGS_PATH="/etc/other/settings.json"',
            ),
            "quoted ENV pointing to different path still mismatches",
        ),
    ],
)
def test_synthetic_violations_detected(text: str, reason: str) -> None:
    with pytest.raises(AssertionError):
        assert_telemetry_posture(text)
