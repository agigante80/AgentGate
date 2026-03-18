#!/usr/bin/env python3
"""Export docs/features specs into GitHub-issue-ready markdown.

Phase 1 migration utility:
- Reads docs from docs/features/*.md (excluding _template.md)
- Emits issue markdown files under tmp/feature-issue-export/
- Writes deterministic parity-report.json for migration verification
"""

from __future__ import annotations

import argparse
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


def _normalize(value: str) -> str:
    return value.strip().lower().replace(" ", "-")


def _normalize_label(value: str) -> str:
    normalized = NON_LABEL_CHARS_RE.sub("-", value.strip().lower()).strip("-")
    return normalized or "unknown"


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
    status = _normalize(status_match.group(1)) if status_match else "unknown"
    priority = _normalize(status_match.group(2)) if status_match else "unknown"

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


def export_features(features_dir: Path, output_dir: Path) -> dict[str, object]:
    features = sorted(
        p for p in features_dir.glob("*.md") if p.is_file() and p.name != TEMPLATE_NAME
    )

    output_dir.mkdir(parents=True, exist_ok=True)

    manifest_items: list[dict[str, object]] = []
    for source in features:
        doc = parse_feature_doc(source)
        target = output_dir / f"{doc.slug}.md"
        target.write_text(render_issue_markdown(doc), encoding="utf-8")
        manifest_items.append(
            {
                "source": source.as_posix(),
                "output": target.as_posix(),
                "title": doc.title,
                "slug": doc.slug,
                "status": doc.status,
                "priority": doc.priority,
                "labels": doc.labels,
            }
        )

    report = {
        "schema_version": 1,
        "source_count": len(features),
        "export_count": len(manifest_items),
        "items": manifest_items,
    }

    report_path = output_dir / "parity-report.json"
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--features-dir", type=Path, default=Path("docs/features"))
    parser.add_argument("--output-dir", type=Path, default=Path("tmp/feature-issue-export"))
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = export_features(args.features_dir, args.output_dir)
    print(
        "Exported "
        f"{report['export_count']} feature docs to {args.output_dir.as_posix()} "
        f"with parity report: {(args.output_dir / 'parity-report.json').as_posix()}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
