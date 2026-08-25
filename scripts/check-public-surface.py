#!/usr/bin/env python3
"""Fail closed on common disclosure and packaging mistakes."""

from __future__ import annotations

import json
import os
import re
import stat
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKIP_PARTS = {
    ".deepagents-runtime",
    ".git",
    ".ruff_cache",
    ".venv",
    "artifacts",
    "__pycache__",
    "dist",
    "build",
}
REQUIRED = {
    "README.md",
    "LICENSE",
    "NOTICE",
    "SECURITY.md",
    "CONTRIBUTING.md",
    "THIRD_PARTY_NOTICES.md",
    "config/workflow.json",
    "docs/deepagents-research-2026-08-25.md",
    "docs/implementation-plan.md",
    "schemas/workflow.schema.json",
    "security/image-vulnerability-baseline.json",
    "scripts/check-image-vulnerabilities.py",
    "scripts/deepagents_sdk_smoke.py",
    "scripts/deepagents_worker.py",
    "scripts/install-deepagents-runtime.sh",
    "scripts/runner.py",
}
SECRET_PATTERNS = (
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"ASIA[0-9A-Z]{16}"),
    re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}"),
    re.compile(r"github_pat_[A-Za-z0-9_]{20,}"),
    re.compile(r"sk-(?:proj-|ant-)?[A-Za-z0-9_-]{20,}"),
    re.compile(r"AIza[0-9A-Za-z_-]{35}"),
    re.compile(r"xox[baprs]-[A-Za-z0-9-]{20,}"),
    re.compile(r"glpat-[A-Za-z0-9_-]{20,}"),
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(r"(?<![A-Za-z0-9])/(?:Users|home)/[A-Za-z0-9._-]+/"),
    re.compile(r"[A-Za-z]:\\\\Users\\\\[A-Za-z0-9._-]+\\\\"),
)


def source_files() -> list[Path]:
    files: list[Path] = []
    for current, directory_names, file_names in os.walk(ROOT, followlinks=False):
        current_path = Path(current)
        retained_directories: list[str] = []
        for name in directory_names:
            child = current_path / name
            mode = child.lstat().st_mode
            if stat.S_ISLNK(mode) or not stat.S_ISDIR(mode):
                files.append(child)
            elif name in SKIP_PARTS or name.endswith(".egg-info"):
                continue
            else:
                retained_directories.append(name)
        directory_names[:] = retained_directories
        for name in file_names:
            path = current_path / name
            relative = path.relative_to(ROOT)
            if any(part in SKIP_PARTS for part in relative.parts):
                continue
            files.append(path)
    return sorted(files)


def text_content(path: Path) -> str | None:
    payload = path.read_bytes()
    if b"\x00" in payload:
        return None
    try:
        return payload.decode("utf-8")
    except UnicodeDecodeError:
        return None


def main() -> int:
    issues: list[str] = []
    present = {path.relative_to(ROOT).as_posix() for path in source_files()}
    for missing in sorted(REQUIRED - present):
        issues.append(f"missing required public file: {missing}")

    if (ROOT / ".git").exists():
        tracked = subprocess.run(
            ["git", "ls-files", "-z"],
            cwd=ROOT,
            text=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        if tracked.returncode != 0:
            issues.append("could not inspect tracked public files")
        else:
            for raw_path in tracked.stdout.split(b"\0"):
                if not raw_path:
                    continue
                relative = Path(raw_path.decode("utf-8", "strict"))
                if any(part in SKIP_PARTS or part.endswith(".egg-info") for part in relative.parts):
                    issues.append(f"ignored runtime path is tracked: {relative.as_posix()}")

    for path in source_files():
        relative = path.relative_to(ROOT).as_posix()
        mode = path.lstat().st_mode
        if stat.S_ISLNK(mode) or not stat.S_ISREG(mode):
            issues.append(f"irregular public file: {relative}")
            continue
        if path.stat().st_size > 1_000_000:
            issues.append(f"public file exceeds 1 MB: {relative}")
        text = text_content(path)
        if text is None:
            issues.append(f"unexpected non-UTF-8 or binary public file: {relative}")
            continue
        lowered = text.lower()
        for pattern in SECRET_PATTERNS:
            if pattern.search(text):
                issues.append(f"credential-like value found in {relative}: {pattern.pattern}")
        if ("[" + "to" + "do") in lowered or ("to" + "do:") in lowered:
            issues.append(f"unfinished placeholder found in {relative}")
        if relative.endswith(".json"):
            try:
                json.loads(text)
            except json.JSONDecodeError as exc:
                issues.append(f"invalid JSON in {relative}: {exc}")

    try:
        workflow = json.loads((ROOT / "config" / "workflow.json").read_text())
        template = json.loads((ROOT / "customer-pack-template" / "workflow.json").read_text())
        schema = json.loads((ROOT / "schemas" / "workflow.schema.json").read_text())
        expected_deepagents_fields = {
            "sdk_version",
            "worker",
            "allowed_filesystem_tools",
            "maximum_attempt_seconds",
        }
        for label, value in (
            ("workflow", workflow.get("deepagents")),
            ("customer-pack template", template.get("deepagents")),
        ):
            if not isinstance(value, dict) or set(value) != expected_deepagents_fields:
                issues.append(f"{label} Deep Agents policy fields are out of sync")
        deepagents_schema = schema["properties"]["deepagents"]
        if set(deepagents_schema.get("required", [])) != expected_deepagents_fields:
            issues.append("workflow schema Deep Agents required fields are out of sync")
        for field in ("sdk_version", "worker", "allowed_filesystem_tools"):
            expected = workflow["deepagents"][field]
            if template["deepagents"].get(field) != expected:
                issues.append(f"customer-pack Deep Agents {field} differs from public policy")
            if deepagents_schema["properties"][field].get("const") != expected:
                issues.append(f"workflow schema Deep Agents {field} differs from public policy")
    except (KeyError, TypeError, json.JSONDecodeError, OSError) as exc:
        issues.append(f"Deep Agents policy/schema consistency check failed: {type(exc).__name__}")

    for executable in (
        "scripts/run-local.sh",
        "scripts/bootstrap-pinned-images.sh",
        "scripts/install-deepagents-runtime.sh",
        "scripts/deepagents_sdk_smoke.py",
        "scripts/deepagents_worker.py",
        "scripts/check-public-surface.py",
        "scripts/check-image-vulnerabilities.py",
        "integration/postgres-init/001-incident-schema.sh",
    ):
        path = ROOT / executable
        if path.is_file() and not os.access(path, os.X_OK):
            issues.append(f"script is not executable: {executable}")

    result = {"ok": not issues, "files_checked": len(present), "issues": sorted(set(issues))}
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if not issues else 1


if __name__ == "__main__":
    raise SystemExit(main())
