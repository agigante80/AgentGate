#!/usr/bin/env python3
"""Synchronize exported feature markdown to GitHub issues via gh CLI.

Phase 2 migration utility:
- Reads tmp/feature-issue-export/parity-report.json
- Optionally creates missing issues and/or updates existing mapped issues
- Maintains tmp/feature-issue-export/issue-map.json
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent


GH_SUBCOMMANDS = {"create", "edit", "view", "list"}
MAP_SCHEMA_VERSION = 1


class SyncError(RuntimeError):
    """Raised when sync preconditions or gh operations fail."""


class _TokenRedactor:
    def __init__(self, token: str) -> None:
        self._token = token

    def redact(self, text: str) -> str:
        if not text:
            return text
        redacted = text
        if self._token:
            redacted = redacted.replace(self._token, "[REDACTED]")
        redacted = re.sub(r"gh[pors]_[A-Za-z0-9]{20,}", "[REDACTED]", redacted)
        redacted = re.sub(r"github_pat_[A-Za-z0-9_]{20,}", "[REDACTED]", redacted)
        return redacted


class _NoopAudit:
    def __init__(self) -> None:
        self.records: list[dict[str, object]] = []

    def record(self, *, action: str, detail: dict[str, object], status: str = "ok") -> None:
        self.records.append({"action": action, "detail": detail, "status": status})


@dataclass(frozen=True)
class ParityItem:
    source: Path
    output: Path
    title: str
    labels: list[str]


@dataclass(frozen=True)
class MapEntry:
    source: Path
    issue_number: int


def _load_parity_items(export_dir: Path) -> list[ParityItem]:
    report_path = export_dir / "parity-report.json"
    if not report_path.exists():
        raise SyncError(f"missing parity report: {report_path.as_posix()}")
    try:
        report = json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SyncError(f"invalid parity report: {exc}") from exc

    items = report.get("items") if isinstance(report, dict) else None
    if not isinstance(items, list):
        raise SyncError("invalid parity report: `items` must be a list")

    parity_items: list[ParityItem] = []
    for index, raw in enumerate(items):
        if not isinstance(raw, dict):
            raise SyncError(f"invalid parity report item at index {index}: expected object")
        source_raw = raw.get("source")
        output_raw = raw.get("output")
        title = raw.get("title")
        labels = raw.get("labels")
        if (
            not isinstance(source_raw, str)
            or not isinstance(output_raw, str)
            or not isinstance(title, str)
            or not isinstance(labels, list)
            or not all(isinstance(label, str) for label in labels)
        ):
            raise SyncError(f"invalid parity report item at index {index}: malformed fields")
        parity_items.append(
            ParityItem(
                source=Path(source_raw),
                output=Path(output_raw),
                title=title,
                labels=labels,
            )
        )

    parity_items.sort(key=lambda item: item.source.as_posix())
    return parity_items


def _validate_source_boundary(path: Path, role: str) -> None:
    repo_root = _SCRIPT_DIR.parent.resolve()
    resolved = path.resolve()
    try:
        resolved.relative_to(repo_root)
    except ValueError as exc:
        raise SyncError(
            f"invalid {role} source path escapes repo root: {path.as_posix()}"
        ) from exc


def _load_issue_map(map_path: Path) -> dict[Path, MapEntry]:
    if not map_path.exists():
        return {}
    try:
        data = json.loads(map_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SyncError(f"invalid issue map: {exc}") from exc

    if not isinstance(data, dict):
        raise SyncError("invalid issue map: top-level JSON must be an object")
    if data.get("schema_version") != MAP_SCHEMA_VERSION:
        raise SyncError(
            "invalid issue map: unsupported schema_version "
            f"{data.get('schema_version')!r}"
        )

    items = data.get("items")
    if not isinstance(items, list):
        raise SyncError("invalid issue map: `items` must be a list")

    entries: dict[Path, MapEntry] = {}
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            raise SyncError(f"invalid issue map item at index {index}: expected object")
        source_raw = item.get("source")
        issue_number = item.get("issue_number")
        if not isinstance(source_raw, str) or not isinstance(issue_number, int) or isinstance(issue_number, bool):
            raise SyncError(f"invalid issue map item at index {index}: malformed fields")
        source = Path(source_raw)
        _validate_source_boundary(source, "issue-map")
        resolved = source.resolve()
        if resolved in entries:
            raise SyncError(f"invalid issue map: duplicate source entry {source.as_posix()}")
        entries[resolved] = MapEntry(source=source, issue_number=issue_number)

    return entries


def _write_issue_map(map_path: Path, items: list[ParityItem], mapping: dict[Path, int]) -> None:
    map_path.parent.mkdir(parents=True, exist_ok=True)
    payload_items: list[dict[str, object]] = []
    for item in items:
        issue_number = mapping.get(item.source.resolve())
        if issue_number is None:
            continue
        payload_items.append(
            {
                "source": item.source.as_posix(),
                "issue_number": issue_number,
            }
        )
    payload = {
        "schema_version": MAP_SCHEMA_VERSION,
        "items": payload_items,
    }
    map_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _allowed_gh_argv(argv: list[str]) -> bool:
    if len(argv) < 3:
        return False
    if argv[0] != "gh" or argv[1] != "issue":
        return False
    subcmd = argv[2]
    if subcmd not in GH_SUBCOMMANDS:
        return False
    if subcmd == "create":
        return "--title" in argv and "--body-file" in argv
    if subcmd == "edit":
        has_body = "--body-file" in argv
        has_title = "--title" in argv
        return has_body or has_title
    if subcmd == "view":
        return len(argv) >= 4 and "--json" in argv
    if subcmd == "list":
        return "--json" in argv
    return False


def _run_gh(argv: list[str], *, token: str, redactor: _TokenRedactor) -> tuple[int, str, str]:
    if not _allowed_gh_argv(argv):
        raise SyncError(f"blocked gh argv (not allowlisted): {argv!r}")

    env = os.environ.copy()
    env["GH_TOKEN"] = token
    proc = subprocess.run(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env)
    stdout = redactor.redact(proc.stdout)
    stderr = redactor.redact(proc.stderr)
    return proc.returncode, stdout, stderr


def _parse_issue_number_from_create(stdout: str) -> int:
    text = stdout.strip()
    match = re.search(r"/issues/(\d+)\s*$", text)
    if not match:
        raise SyncError(f"unable to parse created issue number from gh output: {text!r}")
    return int(match.group(1))


def _build_list_argv() -> list[str]:
    return ["gh", "issue", "list", "--state", "all", "--limit", "500", "--json", "number"]


def _build_view_argv(issue_number: int) -> list[str]:
    return ["gh", "issue", "view", str(issue_number), "--json", "title,body,labels"]


def _build_create_argv(title: str, body_file: str, labels: list[str]) -> list[str]:
    argv = ["gh", "issue", "create", "--title", title, "--body-file", body_file]
    for label in labels:
        argv.extend(["--label", label])
    return argv


def _build_edit_argv(
    issue_number: int,
    title: str,
    body_file: str,
    add_labels: list[str],
    remove_labels: list[str],
) -> list[str]:
    argv = [
        "gh",
        "issue",
        "edit",
        str(issue_number),
        "--title",
        title,
        "--body-file",
        body_file,
    ]
    for label in add_labels:
        argv.extend(["--add-label", label])
    for label in remove_labels:
        argv.extend(["--remove-label", label])
    return argv


def _load_issue_state(issue_number: int, *, token: str, redactor: _TokenRedactor) -> dict[str, object]:
    rc, stdout, stderr = _run_gh(_build_view_argv(issue_number), token=token, redactor=redactor)
    if rc != 0:
        raise SyncError(
            f"gh issue view failed for #{issue_number}: {stderr.strip() or stdout.strip()}"
        )
    try:
        return json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise SyncError(f"gh issue view returned malformed JSON for #{issue_number}") from exc


def _issue_labels_from_view(payload: dict[str, object]) -> list[str]:
    labels_payload = payload.get("labels")
    if not isinstance(labels_payload, list):
        return []
    names: list[str] = []
    for label in labels_payload:
        if isinstance(label, dict) and isinstance(label.get("name"), str):
            names.append(label["name"])
    return sorted(set(names))


def _load_existing_issue_numbers(*, token: str, redactor: _TokenRedactor) -> list[int]:
    rc, stdout, stderr = _run_gh(_build_list_argv(), token=token, redactor=redactor)
    if rc != 0:
        raise SyncError(f"gh issue list failed: {stderr.strip() or stdout.strip()}")
    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise SyncError("gh issue list returned malformed JSON") from exc
    if not isinstance(payload, list):
        raise SyncError("gh issue list returned non-list payload")
    numbers: list[int] = []
    for item in payload:
        if isinstance(item, dict) and isinstance(item.get("number"), int):
            numbers.append(item["number"])
    return sorted(numbers)


def _read_issue_body(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise SyncError(f"unable to read issue body markdown: {path.as_posix()} ({exc})") from exc


def _run_gh_with_body(
    argv_builder,
    *,
    issue_body: str,
    token: str,
    redactor: _TokenRedactor,
) -> tuple[int, str, str]:
    body_file_path: str | None = None
    try:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False) as handle:
            handle.write(issue_body)
            handle.flush()
            body_file_path = handle.name
        argv = argv_builder(body_file_path)
        return _run_gh(argv, token=token, redactor=redactor)
    finally:
        if body_file_path:
            try:
                Path(body_file_path).unlink()
            except FileNotFoundError:
                pass


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=Path("tmp/feature-issue-export"))
    parser.add_argument("--dry-run", action="store_true", help="preview operations without mutating GitHub")
    parser.add_argument("--create-missing", action="store_true", help="create issues for parity items missing from issue-map.json")
    parser.add_argument("--update-existing", action="store_true", help="update mapped issues when title/body/labels drift")
    return parser.parse_args()


def run_sync(args: argparse.Namespace) -> int:
    do_create = args.create_missing
    do_update = args.update_existing
    if not do_create and not do_update:
        if args.dry_run:
            do_create = True
            do_update = True
        else:
            raise SyncError("select at least one mode: --create-missing and/or --update-existing")

    token = os.environ.get("GITHUB_REPO_TOKEN", "").strip()
    if not token:
        raise SyncError("missing required env var: GITHUB_REPO_TOKEN")

    parity_items = _load_parity_items(args.output_dir)
    map_path = args.output_dir / "issue-map.json"
    loaded_map = _load_issue_map(map_path)
    issue_map: dict[Path, int] = {
        source: entry.issue_number for source, entry in loaded_map.items()
    }

    redactor = _TokenRedactor(token)
    audit = _NoopAudit()

    existing_numbers = _load_existing_issue_numbers(token=token, redactor=redactor)
    predicted_next = (max(existing_numbers) + 1) if existing_numbers else 1

    changes = 0

    for item in parity_items:
        source_key = item.source.resolve()
        mapped_number = issue_map.get(source_key)
        body_text = _read_issue_body(item.output)

        if mapped_number is None and do_create:
            if args.dry_run:
                print(
                    "DRY-RUN create "
                    f"source={item.source.as_posix()} "
                    f"issue=#{predicted_next} "
                    f"title={item.title!r} "
                    f"labels={','.join(item.labels)}"
                )
                predicted_next += 1
                changes += 1
                continue

            rc, stdout, stderr = _run_gh_with_body(
                lambda body_file: _build_create_argv(item.title, body_file, item.labels),
                issue_body=body_text,
                token=token,
                redactor=redactor,
            )
            if rc != 0:
                raise SyncError(
                    "gh issue create failed for "
                    f"{item.source.as_posix()}: {stderr.strip() or stdout.strip()}"
                )
            issue_number = _parse_issue_number_from_create(stdout)
            issue_map[source_key] = issue_number
            audit.record(
                action="github_issue_create",
                detail={
                    "source": item.source.as_posix(),
                    "issue_number": issue_number,
                    "title": redactor.redact(item.title),
                },
                status="ok",
            )
            print(f"created issue #{issue_number} for {item.source.as_posix()}")
            changes += 1
            continue

        if mapped_number is not None and do_update:
            current = _load_issue_state(mapped_number, token=token, redactor=redactor)
            current_title = current.get("title") if isinstance(current.get("title"), str) else ""
            current_body = current.get("body") if isinstance(current.get("body"), str) else ""
            current_labels = _issue_labels_from_view(current)
            desired_labels = sorted(set(item.labels))

            title_drift = current_title != item.title
            body_drift = current_body != body_text
            add_labels = sorted(set(desired_labels) - set(current_labels))
            remove_labels = sorted(set(current_labels) - set(desired_labels))
            has_drift = title_drift or body_drift or bool(add_labels) or bool(remove_labels)

            if not has_drift:
                print(
                    "no-op "
                    f"source={item.source.as_posix()} issue=#{mapped_number}"
                )
                continue

            drift_parts: list[str] = []
            if title_drift:
                drift_parts.append("title")
            if body_drift:
                drift_parts.append("body")
            if add_labels:
                drift_parts.append(f"add_labels={','.join(add_labels)}")
            if remove_labels:
                drift_parts.append(f"remove_labels={','.join(remove_labels)}")
            drift_summary = "; ".join(drift_parts)

            if args.dry_run:
                print(
                    "DRY-RUN update "
                    f"source={item.source.as_posix()} "
                    f"issue=#{mapped_number} "
                    f"diff={drift_summary}"
                )
                changes += 1
                continue

            rc, stdout, stderr = _run_gh_with_body(
                lambda body_file: _build_edit_argv(
                    mapped_number,
                    item.title,
                    body_file,
                    add_labels,
                    remove_labels,
                ),
                issue_body=body_text,
                token=token,
                redactor=redactor,
            )
            if rc != 0:
                raise SyncError(
                    f"gh issue edit failed for #{mapped_number}: {stderr.strip() or stdout.strip()}"
                )
            audit.record(
                action="github_issue_update",
                detail={
                    "source": item.source.as_posix(),
                    "issue_number": mapped_number,
                    "diff": redactor.redact(drift_summary),
                },
                status="ok",
            )
            print(
                f"updated issue #{mapped_number} for {item.source.as_posix()} "
                f"({drift_summary})"
            )
            changes += 1

    if not args.dry_run:
        _write_issue_map(map_path, parity_items, issue_map)
        print(f"wrote issue map: {map_path.as_posix()}")

    print(f"sync complete (changes={changes}, dry_run={args.dry_run})")
    return 0


def main() -> int:
    try:
        return run_sync(parse_args())
    except SyncError as exc:
        print(f"sync failed: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
