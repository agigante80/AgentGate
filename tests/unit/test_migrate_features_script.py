from __future__ import annotations

import hashlib
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
    assert parity["schema_version"] == 2
    assert len(parity["items"][0]["source_sha256"]) == 64
    assert len(parity["items"][0]["output_sha256"]) == 64


def test_parity_report_hashes_match_source_and_export(tmp_path):
    module = _load_module()
    features_dir = tmp_path / "docs" / "features"
    output_dir = tmp_path / "tmp" / "feature-issue-export"
    features_dir.mkdir(parents=True)

    source = features_dir / "hash.md"
    source.write_text(
        "\n".join(
            [
                "# Hash Check",
                "",
                "> Status: **Planned** | Priority: Low | Last reviewed: 2026-03-18",
                "",
                "Summary.",
            ]
        ),
        encoding="utf-8",
    )

    module.export_features(features_dir, output_dir)
    parity = json.loads((output_dir / "parity-report.json").read_text(encoding="utf-8"))
    item = parity["items"][0]
    output_text = (output_dir / "hash.md").read_text(encoding="utf-8")

    assert item["source_sha256"] == hashlib.sha256(
        source.read_text(encoding="utf-8").encode("utf-8")
    ).hexdigest()
    assert item["output_sha256"] == hashlib.sha256(output_text.encode("utf-8")).hexdigest()


def test_verify_parity_report_passes_roundtrip(tmp_path):
    module = _load_module()
    features_dir = tmp_path / "docs" / "features"
    output_dir = tmp_path / "tmp" / "feature-issue-export"
    features_dir.mkdir(parents=True)

    source = features_dir / "ok.md"
    source.write_text(
        "\n".join(
            [
                "# Verify OK",
                "",
                "> Status: **Planned** | Priority: Medium | Last reviewed: 2026-03-18",
                "",
                "Summary.",
            ]
        ),
        encoding="utf-8",
    )

    module.export_features(features_dir, output_dir)

    assert module.verify_parity_report(features_dir, output_dir) == []


def test_verify_parity_report_detects_tampered_export(tmp_path):
    module = _load_module()
    features_dir = tmp_path / "docs" / "features"
    output_dir = tmp_path / "tmp" / "feature-issue-export"
    features_dir.mkdir(parents=True)

    source = features_dir / "tamper.md"
    source.write_text(
        "\n".join(
            [
                "# Verify Tamper",
                "",
                "> Status: **Planned** | Priority: Medium | Last reviewed: 2026-03-18",
                "",
                "Summary.",
            ]
        ),
        encoding="utf-8",
    )

    module.export_features(features_dir, output_dir)
    (output_dir / "tamper.md").write_text("tampered", encoding="utf-8")

    errors = module.verify_parity_report(features_dir, output_dir)

    assert any("output hash mismatch" in error for error in errors)


def test_verify_parity_report_detects_metadata_drift(tmp_path):
    module = _load_module()
    features_dir = tmp_path / "docs" / "features"
    output_dir = tmp_path / "tmp" / "feature-issue-export"
    features_dir.mkdir(parents=True)

    source = features_dir / "meta.md"
    source.write_text(
        "\n".join(
            [
                "# Verify Metadata",
                "",
                "> Status: **Planned** | Priority: Medium | Last reviewed: 2026-03-18",
                "",
                "Summary.",
            ]
        ),
        encoding="utf-8",
    )

    module.export_features(features_dir, output_dir)
    report_path = output_dir / "parity-report.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    report["items"][0]["labels"] = ["type:feature", "status:wrong", "priority:medium", "review:pending"]
    report["items"][0]["title"] = "Wrong Title"
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    errors = module.verify_parity_report(features_dir, output_dir)

    assert any("title mismatch" in error for error in errors)
    assert any("labels mismatch" in error for error in errors)


def test_verify_parity_report_detects_tampered_export_with_updated_hash(tmp_path):
    module = _load_module()
    features_dir = tmp_path / "docs" / "features"
    output_dir = tmp_path / "tmp" / "feature-issue-export"
    features_dir.mkdir(parents=True)

    source = features_dir / "render.md"
    source.write_text(
        "\n".join(
            [
                "# Verify Render",
                "",
                "> Status: **Planned** | Priority: Medium | Last reviewed: 2026-03-18",
                "",
                "Summary.",
            ]
        ),
        encoding="utf-8",
    )

    module.export_features(features_dir, output_dir)
    output_path = output_dir / "render.md"
    output_path.write_text("# Totally different\n", encoding="utf-8")

    report_path = output_dir / "parity-report.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    report["items"][0]["output_sha256"] = hashlib.sha256(
        output_path.read_text(encoding="utf-8").encode("utf-8")
    ).hexdigest()
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    errors = module.verify_parity_report(features_dir, output_dir)

    assert any("output render mismatch" in error for error in errors)


def test_verify_parity_report_rejects_source_path_escape(tmp_path):
    module = _load_module()
    features_dir = tmp_path / "docs" / "features"
    output_dir = tmp_path / "tmp" / "feature-issue-export"
    features_dir.mkdir(parents=True)
    output_dir.mkdir(parents=True)

    source = features_dir / "safe.md"
    source.write_text(
        "\n".join(
            [
                "# Safe",
                "",
                "> Status: **Planned** | Priority: Medium | Last reviewed: 2026-03-18",
            ]
        ),
        encoding="utf-8",
    )
    output = output_dir / "safe.md"
    output.write_text(module.render_issue_markdown(module.parse_feature_doc(source)), encoding="utf-8")

    outside_source = tmp_path / "outside.md"
    outside_source.write_text("# Outside\n", encoding="utf-8")
    report = {
        "schema_version": 2,
        "source_count": 1,
        "export_count": 1,
        "items": [
            {
                "source": outside_source.as_posix(),
                "output": output.as_posix(),
                "title": "Outside",
                "slug": "outside",
                "status": "planned",
                "priority": "medium",
                "labels": ["type:feature", "status:planned", "priority:medium", "review:pending"],
                "source_sha256": hashlib.sha256(
                    outside_source.read_text(encoding="utf-8").encode("utf-8")
                ).hexdigest(),
                "output_sha256": hashlib.sha256(
                    output.read_text(encoding="utf-8").encode("utf-8")
                ).hexdigest(),
            }
        ],
    }
    (output_dir / "parity-report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    errors = module.verify_parity_report(features_dir, output_dir)
    assert any("source path escapes features dir" in error for error in errors)


def test_verify_parity_report_rejects_output_path_escape(tmp_path):
    module = _load_module()
    features_dir = tmp_path / "docs" / "features"
    output_dir = tmp_path / "tmp" / "feature-issue-export"
    features_dir.mkdir(parents=True)
    output_dir.mkdir(parents=True)

    source = features_dir / "safe.md"
    source.write_text(
        "\n".join(
            [
                "# Safe",
                "",
                "> Status: **Planned** | Priority: Medium | Last reviewed: 2026-03-18",
            ]
        ),
        encoding="utf-8",
    )
    outside_output = tmp_path / "outside-output.md"
    outside_output.write_text("tamper", encoding="utf-8")

    report = {
        "schema_version": 2,
        "source_count": 1,
        "export_count": 1,
        "items": [
            {
                "source": source.as_posix(),
                "output": outside_output.as_posix(),
                "title": "Safe",
                "slug": "safe",
                "status": "planned",
                "priority": "medium",
                "labels": ["type:feature", "status:planned", "priority:medium", "review:pending"],
                "source_sha256": hashlib.sha256(
                    source.read_text(encoding="utf-8").encode("utf-8")
                ).hexdigest(),
                "output_sha256": hashlib.sha256(
                    outside_output.read_text(encoding="utf-8").encode("utf-8")
                ).hexdigest(),
            }
        ],
    }
    (output_dir / "parity-report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    errors = module.verify_parity_report(features_dir, output_dir)
    assert any("output path escapes output dir" in error for error in errors)


def test_verify_parity_report_rejects_duplicate_entries(tmp_path):
    module = _load_module()
    features_dir = tmp_path / "docs" / "features"
    output_dir = tmp_path / "tmp" / "feature-issue-export"
    features_dir.mkdir(parents=True)

    source = features_dir / "dup.md"
    source.write_text(
        "\n".join(
            [
                "# Duplicate",
                "",
                "> Status: **Planned** | Priority: Medium | Last reviewed: 2026-03-18",
            ]
        ),
        encoding="utf-8",
    )

    module.export_features(features_dir, output_dir)
    report_path = output_dir / "parity-report.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    report["items"].append(dict(report["items"][0]))
    report["export_count"] = len(report["items"])
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    errors = module.verify_parity_report(features_dir, output_dir)

    assert any("duplicate source entry" in error for error in errors)
    assert any("duplicate output entry" in error for error in errors)


def test_verify_parity_report_rejects_malformed_hash_fields(tmp_path):
    module = _load_module()
    features_dir = tmp_path / "docs" / "features"
    output_dir = tmp_path / "tmp" / "feature-issue-export"
    features_dir.mkdir(parents=True)

    source = features_dir / "hash-format.md"
    source.write_text(
        "\n".join(
            [
                "# Hash Format",
                "",
                "> Status: **Planned** | Priority: Medium | Last reviewed: 2026-03-18",
            ]
        ),
        encoding="utf-8",
    )

    module.export_features(features_dir, output_dir)
    report_path = output_dir / "parity-report.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    report["items"][0]["source_sha256"] = "ZZ"
    report["items"][0]["output_sha256"] = "123"
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    errors = module.verify_parity_report(features_dir, output_dir)

    assert any("malformed source_sha256" in error for error in errors)
    assert any("malformed output_sha256" in error for error in errors)


def test_verify_parity_report_rejects_malformed_json(tmp_path):
    module = _load_module()
    features_dir = tmp_path / "docs" / "features"
    output_dir = tmp_path / "tmp" / "feature-issue-export"
    features_dir.mkdir(parents=True)
    output_dir.mkdir(parents=True)

    (output_dir / "parity-report.json").write_text("{not-json", encoding="utf-8")

    errors = module.verify_parity_report(features_dir, output_dir)

    assert any("malformed JSON" in error for error in errors)


def test_verify_parity_report_rejects_non_object_top_level(tmp_path):
    module = _load_module()
    features_dir = tmp_path / "docs" / "features"
    output_dir = tmp_path / "tmp" / "feature-issue-export"
    features_dir.mkdir(parents=True)
    output_dir.mkdir(parents=True)

    (output_dir / "parity-report.json").write_text(
        json.dumps(["not", "an", "object"]) + "\n",
        encoding="utf-8",
    )

    errors = module.verify_parity_report(features_dir, output_dir)

    assert errors == ["invalid parity report: top-level JSON must be an object"]


def test_verify_parity_report_rejects_malformed_header_field_types(tmp_path):
    module = _load_module()
    features_dir = tmp_path / "docs" / "features"
    output_dir = tmp_path / "tmp" / "feature-issue-export"
    features_dir.mkdir(parents=True)

    source = features_dir / "header.md"
    source.write_text(
        "\n".join(
            [
                "# Header",
                "",
                "> Status: **Planned** | Priority: Medium | Last reviewed: 2026-03-18",
            ]
        ),
        encoding="utf-8",
    )

    module.export_features(features_dir, output_dir)
    report_path = output_dir / "parity-report.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    report["schema_version"] = "2"
    report["source_count"] = "1"
    report["export_count"] = None
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    errors = module.verify_parity_report(features_dir, output_dir)

    assert any("`schema_version` must be an integer" in error for error in errors)
    assert any("`source_count` must be an integer" in error for error in errors)
    assert any("`export_count` must be an integer" in error for error in errors)


def test_verify_parity_report_rejects_malformed_metadata_fields(tmp_path):
    module = _load_module()
    features_dir = tmp_path / "docs" / "features"
    output_dir = tmp_path / "tmp" / "feature-issue-export"
    features_dir.mkdir(parents=True)

    source = features_dir / "meta-format.md"
    source.write_text(
        "\n".join(
            [
                "# Metadata Format",
                "",
                "> Status: **Planned** | Priority: Medium | Last reviewed: 2026-03-18",
            ]
        ),
        encoding="utf-8",
    )

    module.export_features(features_dir, output_dir)
    report_path = output_dir / "parity-report.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    report["items"][0]["title"] = None
    report["items"][0]["slug"] = 42
    report["items"][0]["status"] = {"bad": "type"}
    report["items"][0]["priority"] = []
    report["items"][0]["labels"] = ["type:feature", 99]
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    errors = module.verify_parity_report(features_dir, output_dir)

    assert any("malformed metadata fields" in error for error in errors)


def test_verify_parity_report_rejects_unparseable_source_doc(tmp_path):
    module = _load_module()
    features_dir = tmp_path / "docs" / "features"
    output_dir = tmp_path / "tmp" / "feature-issue-export"
    features_dir.mkdir(parents=True)
    output_dir.mkdir(parents=True)

    source = features_dir / "bad.md"
    source.write_text(
        "\n".join(
            [
                "not-a-heading",
                "",
                "> Status: **Planned** | Priority: Medium | Last reviewed: 2026-03-18",
            ]
        ),
        encoding="utf-8",
    )
    output = output_dir / "bad.md"
    output.write_text("# Placeholder\n", encoding="utf-8")

    report = {
        "schema_version": 2,
        "source_count": 1,
        "export_count": 1,
        "items": [
            {
                "source": source.as_posix(),
                "output": output.as_posix(),
                "title": "Bad",
                "slug": "bad",
                "status": "planned",
                "priority": "medium",
                "labels": ["type:feature", "status:planned", "priority:medium", "review:pending"],
                "source_sha256": hashlib.sha256(
                    source.read_text(encoding="utf-8").encode("utf-8")
                ).hexdigest(),
                "output_sha256": hashlib.sha256(
                    output.read_text(encoding="utf-8").encode("utf-8")
                ).hexdigest(),
            }
        ],
    }
    (output_dir / "parity-report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    errors = module.verify_parity_report(features_dir, output_dir)

    assert any("unable to parse source doc" in error for error in errors)


def test_verify_parity_report_rejects_non_utf8_output_file(tmp_path):
    module = _load_module()
    features_dir = tmp_path / "docs" / "features"
    output_dir = tmp_path / "tmp" / "feature-issue-export"
    features_dir.mkdir(parents=True)
    output_dir.mkdir(parents=True)

    source = features_dir / "non-utf8.md"
    source.write_text(
        "\n".join(
            [
                "# Non UTF8",
                "",
                "> Status: **Planned** | Priority: Medium | Last reviewed: 2026-03-18",
            ]
        ),
        encoding="utf-8",
    )
    output = output_dir / "non-utf8.md"
    output.write_bytes(b"\xff\xfe\x00\x00")

    report = {
        "schema_version": 2,
        "source_count": 1,
        "export_count": 1,
        "items": [
            {
                "source": source.as_posix(),
                "output": output.as_posix(),
                "title": "Non UTF8",
                "slug": "non-utf8",
                "status": "planned",
                "priority": "medium",
                "labels": ["type:feature", "status:planned", "priority:medium", "review:pending"],
                "source_sha256": hashlib.sha256(
                    source.read_text(encoding="utf-8").encode("utf-8")
                ).hexdigest(),
                "output_sha256": "0" * 64,
            }
        ],
    }
    (output_dir / "parity-report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    errors = module.verify_parity_report(features_dir, output_dir)

    assert any("unable to read output file as UTF-8" in error for error in errors)


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
