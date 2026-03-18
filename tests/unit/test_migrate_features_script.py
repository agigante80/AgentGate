from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


def _load_module():
    script_path = Path("scripts/migrate_features.py")
    spec = importlib.util.spec_from_file_location("migrate_features", script_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_parse_feature_doc_sections(tmp_path):
    module = _load_module()
    doc_path = tmp_path / "sample.md"
    doc_path.write_text(
        "\n".join(
            [
                "# Sample Feature",
                "",
                "> Status: **Planned** | Priority: High | Last reviewed: 2026-03-17",
                "",
                "One line summary.",
                "",
                "## Problem Statement",
                "",
                "Pain point.",
                "",
                "## Implementation Steps",
                "",
                "Step 1",
                "",
                "## Acceptance Criteria",
                "",
                "- [ ] Done",
                "",
            ]
        ),
        encoding="utf-8",
    )

    parsed = module.parse_feature_doc(doc_path)

    assert parsed.title == "Sample Feature"
    assert parsed.status == "planned"
    assert parsed.priority == "high"
    assert parsed.sections["Problem Statement"] == "Pain point."
    assert parsed.sections["Implementation Steps"] == "Step 1"


def test_generate_github_issue_md_format():
    module = _load_module()
    doc = module.FeatureDoc(
        source_path=Path("docs/features/sample.md"),
        title="Sample Feature",
        status="planned",
        priority="high",
        intro="Short intro.",
        sections={
            "Problem Statement": "Pain point.",
            "Recommended Solution": "Do X.",
            "Implementation Steps": "1. Build it.",
            "Acceptance Criteria": "- [ ] Works",
            "Security Considerations": "No new secrets.",
            "Edge Cases and Open Questions": "None.",
        },
    )

    output = module.render_issue_markdown(doc)

    assert output.startswith("# Sample Feature")
    assert "## Summary" in output
    assert "## Problem Statement" in output
    assert "## Source Spec" in output
    assert "Suggested labels: `type:feature, status:planned, priority:high, review:pending`" in output


def test_parse_feature_doc_edge_cases(tmp_path):
    module = _load_module()
    doc_path = tmp_path / "edge.md"
    doc_path.write_text(
        "\n".join(
            [
                "",
                "",
                "# Edge Case Feature",
                "",
                "No status metadata line here.",
                "",
                "## Problem Statement",
                "",
                "Only one section exists.",
            ]
        ),
        encoding="utf-8",
    )

    parsed = module.parse_feature_doc(doc_path)
    rendered = module.render_issue_markdown(parsed)

    assert parsed.title == "Edge Case Feature"
    assert parsed.status == "unknown"
    assert parsed.priority == "unknown"
    assert parsed.sections["Problem Statement"] == "Only one section exists."
    assert "Not specified in source doc." in rendered


def test_parse_feature_doc_status_priority_are_strictly_normalized(tmp_path):
    module = _load_module()
    doc_path = tmp_path / "labels.md"
    doc_path.write_text(
        "\n".join(
            [
                "# Labels Feature",
                "",
                "> Status: **In Progress (Phase 1 on `develop`)** | Priority: High ! | Last reviewed: 2026-03-18",
            ]
        ),
        encoding="utf-8",
    )

    parsed = module.parse_feature_doc(doc_path)

    assert parsed.status == "in-progress-phase-1-on-develop"
    assert parsed.priority == "high"


def test_parse_adversarial_content_literal_passthrough(tmp_path):
    module = _load_module()
    features_dir = tmp_path / "docs" / "features"
    output_dir = tmp_path / "tmp" / "feature-issue-export"
    features_dir.mkdir(parents=True)

    source = features_dir / "evil.md"
    source.write_text(
        "\n".join(
            [
                "# Adversarial Spec",
                "",
                "> Status: **Planned** | Priority: Medium | Last reviewed: 2026-03-17",
                "",
                "Summary text.",
                "",
                "## Problem Statement",
                "",
                "Contains $(rm -rf /) and `<script>alert(1)</script>` and `echo pwned`.",
                "",
                "## Acceptance Criteria",
                "",
                "- [ ] Keep text literal.",
            ]
        ),
        encoding="utf-8",
    )

    report = module.export_features(features_dir, output_dir)
    issue_text = (output_dir / "evil.md").read_text(encoding="utf-8")
    parity = json.loads((output_dir / "parity-report.json").read_text(encoding="utf-8"))

    assert "$(rm -rf /)" in issue_text
    assert "<script>alert(1)</script>" in issue_text
    assert "`echo pwned`" in issue_text
    assert report["export_count"] == 1
    assert parity["items"][0]["labels"] == [
        "type:feature",
        "status:planned",
        "priority:medium",
        "review:pending",
    ]


def test_label_values_are_sanitized():
    module = _load_module()
    doc = module.FeatureDoc(
        source_path=Path("docs/features/sample.md"),
        title="Sample Feature",
        status="in-progress-(phase-1-implemented-on-`develop`)",
        priority="High !",
        intro="Short intro.",
        sections={},
    )

    assert doc.labels == [
        "type:feature",
        "status:in-progress-phase-1-implemented-on-develop",
        "priority:high",
        "review:pending",
    ]
