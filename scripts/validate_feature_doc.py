#!/usr/bin/env python3
"""Validate feature documentation.

This script performs basic checks on a feature documentation file to ensure
required sections and metadata are present. It's a placeholder to be expanded
with project-specific rules.
"""

import sys
from pathlib import Path


def main(argv=None):
    argv = argv or sys.argv[1:]
    if not argv:
        print("Usage: validate_feature_doc.py <path-to-doc>")
        return 2

    p = Path(argv[0])
    if not p.exists():
        print(f"File not found: {p}")
        return 2

    text = p.read_text(encoding="utf-8")
    # Sections required by the AgentGate feature doc template
    required_sections = [
        "## Problem Statement",
        "## Implementation Steps",
        "## Test Plan",
        "## Acceptance Criteria",
    ]
    ok = True
    for section in required_sections:
        if section not in text:
            print(f"Missing '{section}' section")
            ok = False

    if ok:
        print("Validation passed")
        return 0
    else:
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
