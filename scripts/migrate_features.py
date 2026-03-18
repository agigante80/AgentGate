#!/usr/bin/env python3
"""Export docs/features specs into GitHub-issue-ready markdown.

Phase 1 migration utility:
- Reads docs from docs/features/*.md (excluding _template.md)
- Emits issue markdown files under tmp/feature-issue-export/
- Writes deterministic parity-report.json for migration verification
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path

TEMPLATE_NAME = "_template.md"
STATUS_RE = re.compile(
    r"^>\s*Status:\s*\*{0,2}(.+?)\*{0,2}\s*\|\s*Priority:\s*([A-Za-z]+)",
    re.IGNORECASE | re.MULTILINE,
)
H2_RE = re.compile(r"^##\s+(.+)$", re.MULTILINE)
NON_LABEL_CHARS_RE = re.compile(r"[^a-z0-9]+")
SHA256_HEX_RE = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True)
class FeatureDoc:
    source_path: Path
    title: str
    status: str
    priority: str
    intro: str
    sections: dict[str, str]

    @property
    def slug(self) -> str:
        return self.source_path.stem

    @property
    def labels(self) -> list[str]:
        labels = ["type:feature", f"status:{_normalize_label(self.status)}"]
        if self.priority:
            labels.append(f"priority:{_normalize_label(self.priority)}")
        labels.append("review:pending")
        return labels


def _clean_title(line: str) -> str:
    title = line.strip().lstrip("#").strip()
    return re.sub(r"\s+", " ", title)


def _normalize_label(value: str) -> str:
    normalized = NON_LABEL_CHARS_RE.sub("-", value.strip().lower()).strip("-")
    return normalized or "unknown"


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _extract_intro(text: str) -> str:
    body = text.split("\n", 1)[1] if "\n" in text else ""
    for marker in ("\n---", "\n## "):
        if marker in body:
            body = body.split(marker, 1)[0]
            break
    lines = [line.rstrip() for line in body.splitlines()]
    filtered = [line for line in lines if line.strip() and not line.strip().startswith("> Status:")]
    intro = "\n".join(filtered).strip()
    return intro or "No summary provided in source document."


def split_h2_sections(text: str) -> dict[str, str]:
    """Return a mapping of H2 heading -> section body."""
    sections: dict[str, str] = {}
    matches = list(H2_RE.finditer(text))
    for idx, match in enumerate(matches):
        heading = match.group(1).strip()
        start = match.end()
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(text)
        body = text[start:end].strip()
        sections[heading] = body
    return sections


def parse_feature_doc(path: Path) -> FeatureDoc:
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    title_line = next((line for line in lines if line.strip()), "")
    if not title_line.startswith("# "):
        raise ValueError(f"{path}: missing top-level title heading")

    title = _clean_title(title_line)
    status_match = STATUS_RE.search(text)
    status = _normalize_label(status_match.group(1)) if status_match else "unknown"
    priority = _normalize_label(status_match.group(2)) if status_match else "unknown"

    return FeatureDoc(
        source_path=path,
        title=title,
        status=status,
        priority=priority,
        intro=_extract_intro(text),
        sections=split_h2_sections(text),
    )


def _first_nonempty(*values: str) -> str:
    for value in values:
        if value and value.strip():
            return value.strip()
    return ""


def render_issue_markdown(doc: FeatureDoc) -> str:
    sections = doc.sections
    problem = _first_nonempty(sections.get("Problem Statement"), "Not specified in source doc.")
    solution = _first_nonempty(sections.get("Recommended Solution"), sections.get("Design Space"), "Not specified in source doc.")
    steps = _first_nonempty(sections.get("Implementation Steps"), "Not specified in source doc.")
    acceptance = _first_nonempty(sections.get("Acceptance Criteria"), "- [ ] Define acceptance criteria.")
    security = _first_nonempty(
        sections.get("Security Considerations (Phase 2 Threat Model)"),
        sections.get("Security Considerations"),
        "No explicit security notes in source doc.",
    )
    open_questions = _first_nonempty(sections.get("Edge Cases and Open Questions"), "None listed.")

    lines = [
        f"# {doc.title}",
        "",
        "## Summary",
        "",
        doc.intro,
        "",
        "## Problem Statement",
        "",
        problem,
        "",
        "## Recommended Solution",
        "",
        solution,
        "",
        "## Implementation Steps",
        "",
        steps,
        "",
        "## Acceptance Criteria",
        "",
        acceptance,
        "",
        "## Security Notes",
        "",
        security,
        "",
        "## Open Questions",
        "",
        open_questions,
        "",
        "## Source Spec",
        "",
        f"- Source doc: `{doc.source_path.as_posix()}`",
        f"- Source status: `{doc.status}`",
        f"- Source priority: `{doc.priority}`",
        f"- Suggested labels: `{', '.join(doc.labels)}`",
        "",
    ]
    return "\n".join(lines)


def _feature_sources(features_dir: Path) -> list[Path]:
    return sorted(
        p for p in features_dir.glob("*.md") if p.is_file() and p.name != TEMPLATE_NAME
    )


def export_features(features_dir: Path, output_dir: Path) -> dict[str, object]:
    features = _feature_sources(features_dir)

    output_dir.mkdir(parents=True, exist_ok=True)

    manifest_items: list[dict[str, object]] = []
    for source in features:
        doc = parse_feature_doc(source)
        target = output_dir / f"{doc.slug}.md"
        issue_md = render_issue_markdown(doc)
        target.write_text(issue_md, encoding="utf-8")
        source_text = source.read_text(encoding="utf-8")
        manifest_items.append(
            {
                "source": source.as_posix(),
                "output": target.as_posix(),
                "title": doc.title,
                "slug": doc.slug,
                "status": doc.status,
                "priority": doc.priority,
                "labels": doc.labels,
                "source_sha256": _sha256_text(source_text),
                "output_sha256": _sha256_text(issue_md),
            }
        )

    report = {
        "schema_version": 2,
        "source_count": len(features),
        "export_count": len(manifest_items),
        "items": manifest_items,
    }

    report_path = output_dir / "parity-report.json"
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return report


def _read_utf8_file(path: Path, index: int, role: str, errors: list[str]) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        errors.append(
            f"item {index}: unable to read {role} file as UTF-8 "
            f"{path.as_posix()} ({exc})"
        )
        return None


def verify_parity_report(features_dir: Path, output_dir: Path) -> list[str]:
    report_path = output_dir / "parity-report.json"
    if not report_path.exists():
        return [f"missing parity report: {report_path.as_posix()}"]

    try:
        report = json.loads(report_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return [f"invalid parity report: malformed JSON ({exc.msg})"]
    if not isinstance(report, dict):
        return ["invalid parity report: top-level JSON must be an object"]
    items = report.get("items")
    if not isinstance(items, list):
        return ["invalid parity report: `items` must be a list"]

    features_root = features_dir.resolve()
    output_root = output_dir.resolve()
    expected_sources = {path.resolve() for path in _feature_sources(features_dir)}
    reported_sources: set[Path] = set()
    reported_outputs: set[Path] = set()
    errors: list[str] = []

    schema_version = report.get("schema_version")
    source_count = report.get("source_count")
    export_count = report.get("export_count")

    if not isinstance(schema_version, int):
        errors.append("invalid parity report: `schema_version` must be an integer")
    elif schema_version != 2:
        errors.append(
            f"unexpected schema_version: expected 2, got {schema_version!r}"
        )
    if not isinstance(source_count, int):
        errors.append("invalid parity report: `source_count` must be an integer")
    elif source_count != len(expected_sources):
        errors.append(
            "source_count mismatch: "
            f"expected {len(expected_sources)}, got {source_count!r}"
        )
    if not isinstance(export_count, int):
        errors.append("invalid parity report: `export_count` must be an integer")
    elif export_count != len(items):
        errors.append(
            f"export_count mismatch: expected {len(items)}, got {export_count!r}"
        )

    for index, item in enumerate(items):
        if not isinstance(item, dict):
            errors.append(f"invalid item at index {index}: expected object")
            continue

        source_raw = item.get("source")
        output_raw = item.get("output")
        source_hash = item.get("source_sha256")
        output_hash = item.get("output_sha256")
        title = item.get("title")
        slug = item.get("slug")
        status = item.get("status")
        priority = item.get("priority")
        labels = item.get("labels")
        if not all(isinstance(value, str) for value in (source_raw, output_raw, source_hash, output_hash)):
            errors.append(f"item {index}: missing required string fields")
            continue
        metadata_valid = (
            isinstance(title, str)
            and isinstance(slug, str)
            and isinstance(status, str)
            and isinstance(priority, str)
            and isinstance(labels, list)
            and all(isinstance(label, str) for label in labels)
        )
        if not metadata_valid:
            errors.append(f"item {index}: malformed metadata fields")
            continue
        source_hash_valid = bool(SHA256_HEX_RE.fullmatch(source_hash))
        output_hash_valid = bool(SHA256_HEX_RE.fullmatch(output_hash))
        if not source_hash_valid:
            errors.append(f"item {index}: malformed source_sha256 for {source_raw}")
        if not output_hash_valid:
            errors.append(f"item {index}: malformed output_sha256 for {output_raw}")

        source = Path(source_raw)
        output = Path(output_raw)
        source_resolved = source.resolve()
        output_resolved = output.resolve()
        expected_output: Path | None = None
        parsed_doc: FeatureDoc | None = None

        if source_resolved in reported_sources:
            errors.append(
                f"item {index}: duplicate source entry for {source.as_posix()}"
            )
        else:
            reported_sources.add(source_resolved)
        if output_resolved in reported_outputs:
            errors.append(
                f"item {index}: duplicate output entry for {output.as_posix()}"
            )
        else:
            reported_outputs.add(output_resolved)

        try:
            source_resolved.relative_to(features_root)
        except ValueError:
            errors.append(
                f"item {index}: source path escapes features dir: {source.as_posix()}"
            )
            continue
        try:
            output_resolved.relative_to(output_root)
        except ValueError:
            errors.append(
                f"item {index}: output path escapes output dir: {output.as_posix()}"
            )
            continue

        if not source.exists():
            errors.append(f"item {index}: missing source file {source.as_posix()}")
        else:
            try:
                parsed_doc = parse_feature_doc(source)
            except (OSError, UnicodeDecodeError, ValueError) as exc:
                errors.append(
                    f"item {index}: unable to parse source doc "
                    f"{source.as_posix()} ({exc})"
                )
            else:
                expected_output = output_dir / f"{parsed_doc.slug}.md"
                if source_resolved != parsed_doc.source_path.resolve():
                    errors.append(
                        f"item {index}: source path mismatch for {source.as_posix()}"
                    )
                if title != parsed_doc.title:
                    errors.append(
                        f"item {index}: title mismatch for {source.as_posix()}"
                    )
                if slug != parsed_doc.slug:
                    errors.append(
                        f"item {index}: slug mismatch for {source.as_posix()}"
                    )
                if status != parsed_doc.status:
                    errors.append(
                        f"item {index}: status mismatch for {source.as_posix()}"
                    )
                if priority != parsed_doc.priority:
                    errors.append(
                        f"item {index}: priority mismatch for {source.as_posix()}"
                    )
                if labels != parsed_doc.labels:
                    errors.append(
                        f"item {index}: labels mismatch for {source.as_posix()}"
                    )
            source_text = _read_utf8_file(source, index, "source", errors)
            if source_hash_valid and source_text is not None:
                actual_source_hash = _sha256_text(source_text)
                if actual_source_hash != source_hash:
                    errors.append(
                        f"item {index}: source hash mismatch for {source.as_posix()}"
                    )

        if not output.exists():
            errors.append(f"item {index}: missing output file {output.as_posix()}")
        else:
            if expected_output and output_resolved != expected_output.resolve():
                errors.append(
                    "item "
                    f"{index}: output path mismatch for {source.as_posix()} "
                    f"(expected {expected_output.as_posix()}, got {output.as_posix()})"
                )
            output_text = _read_utf8_file(output, index, "output", errors)
            if output_text is not None:
                actual_output_hash = _sha256_text(output_text)
                if output_hash_valid and actual_output_hash != output_hash:
                    errors.append(
                        f"item {index}: output hash mismatch for {output.as_posix()}"
                    )
                if parsed_doc:
                    expected_render_hash = _sha256_text(render_issue_markdown(parsed_doc))
                    if actual_output_hash != expected_render_hash:
                        errors.append(
                            f"item {index}: output render mismatch for {output.as_posix()}"
                        )

        if source_resolved not in expected_sources:
            errors.append(
                f"item {index}: unexpected source not found under features dir: {source.as_posix()}"
            )

    missing_from_report = expected_sources - reported_sources
    for missing_source in sorted(missing_from_report):
        errors.append(f"missing parity item for source: {missing_source.as_posix()}")

    return errors


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--features-dir", type=Path, default=Path("docs/features"))
    parser.add_argument("--output-dir", type=Path, default=Path("tmp/feature-issue-export"))
    parser.add_argument(
        "--verify",
        action="store_true",
        help="verify existing parity-report.json and exported markdown hashes",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.verify:
        errors = verify_parity_report(args.features_dir, args.output_dir)
        if errors:
            print("Parity verification failed:")
            for error in errors:
                print(f"- {error}")
            return 1
        print(
            "Parity verification passed for "
            f"{args.features_dir.as_posix()} against "
            f"{(args.output_dir / 'parity-report.json').as_posix()}"
        )
        return 0

    report = export_features(args.features_dir, args.output_dir)
    print(
        "Exported "
        f"{report['export_count']} feature docs to {args.output_dir.as_posix()} "
        f"with parity report: {(args.output_dir / 'parity-report.json').as_posix()}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
