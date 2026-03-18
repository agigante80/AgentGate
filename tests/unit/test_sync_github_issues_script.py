from __future__ import annotations

import importlib.util
import json
import sys
from argparse import Namespace
from pathlib import Path

import pytest


def _load_module():
    script_path = Path("scripts/sync_github_issues.py")
    spec = importlib.util.spec_from_file_location("sync_github_issues", script_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _write_parity(output_dir: Path, source: Path, output: Path, title: str, labels: list[str]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    report = {
        "schema_version": 2,
        "source_count": 1,
        "export_count": 1,
        "items": [
            {
                "source": source.as_posix(),
                "output": output.as_posix(),
                "title": title,
                "slug": source.stem,
                "status": "planned",
                "priority": "high",
                "labels": labels,
                "source_sha256": "0" * 64,
                "output_sha256": "1" * 64,
            }
        ],
    }
    (output_dir / "parity-report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def test_build_create_argv_is_exact_and_allowlisted():
    module = _load_module()

    argv = module._build_create_argv("T", "/tmp/body.md", ["type:feature", "priority:high"])

    assert argv == [
        "gh",
        "issue",
        "create",
        "--title",
        "T",
        "--body-file",
        "/tmp/body.md",
        "--label",
        "type:feature",
        "--label",
        "priority:high",
    ]
    assert module._allowed_gh_argv(argv)


def test_malicious_title_is_literal_argv_element():
    module = _load_module()

    title = "evil; $(rm -rf /) && echo pwn"
    argv = module._build_create_argv(title, "/tmp/body.md", ["status:planned"])

    assert argv[4] == title
    assert module._allowed_gh_argv(argv)


def test_run_sync_rejects_missing_token(tmp_path, monkeypatch):
    module = _load_module()
    features_dir = tmp_path / "docs" / "features"
    output_dir = tmp_path / "tmp" / "feature-issue-export"
    features_dir.mkdir(parents=True)
    source = features_dir / "sample.md"
    output = output_dir / "sample.md"
    source.write_text("# Sample\n", encoding="utf-8")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("# Body\n", encoding="utf-8")
    _write_parity(output_dir, source, output, "Sample", ["type:feature", "status:planned"])

    monkeypatch.delenv("GITHUB_REPO_TOKEN", raising=False)

    args = Namespace(
        features_dir=features_dir,
        output_dir=output_dir,
        dry_run=True,
        create_missing=True,
        update_existing=False,
    )

    with pytest.raises(module.SyncError, match="missing required env var"):
        module.run_sync(args)


def test_issue_map_rejects_source_path_escape(tmp_path):
    module = _load_module()
    features_dir = tmp_path / "docs" / "features"
    features_dir.mkdir(parents=True)
    map_path = tmp_path / "tmp" / "feature-issue-export" / "issue-map.json"
    map_path.parent.mkdir(parents=True, exist_ok=True)

    outside = tmp_path / "outside.md"
    outside.write_text("# outside\n", encoding="utf-8")
    map_payload = {
        "schema_version": 1,
        "items": [
            {
                "source": outside.as_posix(),
                "issue_number": 10,
            }
        ],
    }
    map_path.write_text(json.dumps(map_payload) + "\n", encoding="utf-8")

    with pytest.raises(module.SyncError, match="source path escapes repo root"):
        module._load_issue_map(map_path)


def test_body_tempfile_deleted_on_gh_failure(monkeypatch):
    module = _load_module()
    created_paths: list[Path] = []

    def _fake_run_gh(argv, *, token, redactor):
        body_file = Path(argv[argv.index("--body-file") + 1])
        created_paths.append(body_file)
        return 1, "", "failure"

    monkeypatch.setattr(module, "_run_gh", _fake_run_gh)

    rc, _stdout, _stderr = module._run_gh_with_body(
        lambda body_file: module._build_create_argv("Title", body_file, ["type:feature"]),
        issue_body="# Body\n",
        token="github_pat_example_token_1234567890",
        redactor=module._TokenRedactor("github_pat_example_token_1234567890"),
    )

    assert rc == 1
    assert created_paths, "tempfile path should be captured"
    assert not created_paths[0].exists()


def test_run_gh_redacts_stdout_and_stderr(monkeypatch):
    module = _load_module()
    token = "github_pat_abcdefghijklmnopqrstuvwxyz123456"

    class _Proc:
        returncode = 0
        stdout = f"ok {token}"
        stderr = f"err {token}"

    monkeypatch.setattr(module.subprocess, "run", lambda *_a, **_k: _Proc())

    rc, stdout, stderr = module._run_gh(
        module._build_list_argv(),
        token=token,
        redactor=module._TokenRedactor(token),
    )

    assert rc == 0
    assert token not in stdout
    assert token not in stderr
    assert "[REDACTED]" in stdout
    assert "[REDACTED]" in stderr


def test_parse_args_rejects_unsupported_flag(monkeypatch):
    module = _load_module()
    monkeypatch.setattr(sys, "argv", ["sync_github_issues.py", "--unsupported"])

    with pytest.raises(SystemExit):
        module.parse_args()


def test_run_sync_create_and_idempotent_update_flow(tmp_path, monkeypatch):
    module = _load_module()
    features_dir = tmp_path / "docs" / "features"
    output_dir = tmp_path / "tmp" / "feature-issue-export"
    features_dir.mkdir(parents=True)
    output_dir.mkdir(parents=True)

    source = features_dir / "sample.md"
    output = output_dir / "sample.md"
    source.write_text("# Sample\n", encoding="utf-8")
    output.write_text("# Body\n", encoding="utf-8")
    _write_parity(
        output_dir,
        source,
        output,
        "Sample",
        ["type:feature", "status:planned", "review:pending"],
    )

    (output_dir / "issue-map.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "items": [
                    {
                        "source": source.as_posix(),
                        "issue_number": 12,
                    }
                ],
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    monkeypatch.setenv("GITHUB_REPO_TOKEN", "github_pat_example_token_1234567890")
    monkeypatch.setattr(module, "_SCRIPT_DIR", tmp_path / "scripts")

    calls: list[list[str]] = []

    class _Proc:
        def __init__(self, returncode: int, stdout: str, stderr: str = ""):
            self.returncode = returncode
            self.stdout = stdout
            self.stderr = stderr

    def _fake_subprocess_run(argv, **_kwargs):
        calls.append(argv)
        if argv[:3] == ["gh", "issue", "list"]:
            return _Proc(0, json.dumps([{"number": 12}]))
        if argv[:3] == ["gh", "issue", "view"]:
            return _Proc(
                0,
                json.dumps(
                    {
                        "title": "Sample",
                        "body": "# Body\n",
                        "labels": [
                            {"name": "type:feature"},
                            {"name": "status:planned"},
                            {"name": "review:pending"},
                        ],
                    }
                ),
            )
        raise AssertionError(f"unexpected argv: {argv}")

    monkeypatch.setattr(module.subprocess, "run", _fake_subprocess_run)

    args = Namespace(
        features_dir=features_dir,
        output_dir=output_dir,
        dry_run=False,
        create_missing=False,
        update_existing=True,
    )

    rc = module.run_sync(args)

    assert rc == 0
    assert calls and calls[0][:3] == ["gh", "issue", "list"]
    assert any(call[:3] == ["gh", "issue", "view"] for call in calls)


def test_run_sync_dry_run_predicts_issue_number(tmp_path, monkeypatch, capsys):
    module = _load_module()
    features_dir = tmp_path / "docs" / "features"
    output_dir = tmp_path / "tmp" / "feature-issue-export"
    features_dir.mkdir(parents=True)

    source = features_dir / "new.md"
    output = output_dir / "new.md"
    source.write_text("# New\n", encoding="utf-8")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("# Body\n", encoding="utf-8")
    _write_parity(output_dir, source, output, "New", ["type:feature", "status:planned"])

    monkeypatch.setenv("GITHUB_REPO_TOKEN", "github_pat_example_token_1234567890")

    class _Proc:
        returncode = 0
        stdout = json.dumps([{"number": 42}])
        stderr = ""

    monkeypatch.setattr(module.subprocess, "run", lambda *_a, **_k: _Proc())

    args = Namespace(
        features_dir=features_dir,
        output_dir=output_dir,
        dry_run=True,
        create_missing=True,
        update_existing=False,
    )

    rc = module.run_sync(args)
    out = capsys.readouterr().out

    assert rc == 0
    assert "DRY-RUN create" in out
    assert "issue=#43" in out
