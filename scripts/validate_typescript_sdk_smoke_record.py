#!/usr/bin/env python3
"""Strictly validate the controller-owned TypeScript SDK smoke result."""

from __future__ import annotations

import argparse
import json
import stat
from datetime import datetime
from pathlib import Path
from typing import Any

EXPECTED_TOOLS = ["edit_file", "glob", "grep", "ls", "read_file", "write_file"]
EXPECTED_FIELDS = {
    "schema_version",
    "at",
    "runtime",
    "sdk_language",
    "runtime_version",
    "node_version",
    "model",
    "profile_provider",
    "model_transport",
    "network_request_made",
    "network_attempts",
    "observed_tools",
    "forbidden_tools_absent",
    "forbidden_tool_calls_rejected",
    "workspace_edit_succeeded",
    "out_of_scope_write_denied",
    "traversal_write_denied",
    "traversal_read_denied",
    "final_response_present",
    "passed",
}
TRUE_FIELDS = (
    "forbidden_tools_absent",
    "forbidden_tool_calls_rejected",
    "workspace_edit_succeeded",
    "out_of_scope_write_denied",
    "traversal_write_denied",
    "traversal_read_denied",
    "final_response_present",
    "passed",
)
MAX_RECORD_BYTES = 32_768


def validate_record(record: Any) -> list[str]:
    if type(record) is not dict or set(record) != EXPECTED_FIELDS:
        return ["TypeScript SDK smoke record fields do not match the strict contract"]
    issues: list[str] = []
    if type(record["schema_version"]) is not int or record["schema_version"] != 1:
        issues.append("TypeScript SDK smoke schema version is invalid")
    if type(record["at"]) is not str:
        issues.append("TypeScript SDK smoke timestamp is invalid")
    else:
        try:
            captured_at = datetime.fromisoformat(record["at"].replace("Z", "+00:00"))
        except ValueError:
            issues.append("TypeScript SDK smoke timestamp is invalid")
        else:
            if captured_at.utcoffset() is None or captured_at.utcoffset().total_seconds() != 0:
                issues.append("TypeScript SDK smoke timestamp must be UTC")
    expected_strings = {
        "runtime": "deepagents",
        "sdk_language": "typescript",
        "runtime_version": "1.13.2",
        "node_version": "22.23.2",
        "model": "openai:scripted-smoke (scripted, no transport)",
        "profile_provider": "openai",
        "model_transport": "scripted-no-transport",
    }
    for field, expected in expected_strings.items():
        if type(record[field]) is not str or record[field] != expected:
            issues.append(f"TypeScript SDK smoke {field} is invalid")
    if record["observed_tools"] != EXPECTED_TOOLS:
        issues.append("TypeScript SDK smoke tool surface is invalid")
    if record["network_request_made"] is not False:
        issues.append("TypeScript SDK smoke observed a network request")
    if type(record["network_attempts"]) is not int or record["network_attempts"] != 0:
        issues.append("TypeScript SDK smoke network-attempt count is invalid")
    for field in TRUE_FIELDS:
        if record[field] is not True:
            issues.append(f"TypeScript SDK smoke {field} is not true")
    return sorted(set(issues))


def load_record(path: Path) -> Any:
    mode = path.lstat().st_mode
    if not stat.S_ISREG(mode):
        raise ValueError("TypeScript SDK smoke record must be a regular file")
    size = path.stat().st_size
    if size <= 0 or size > MAX_RECORD_BYTES:
        raise ValueError("TypeScript SDK smoke record size is invalid")
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("record", type=Path)
    args = parser.parse_args()
    try:
        issues = validate_record(load_record(args.record))
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as exc:
        issues = [f"{type(exc).__name__}: {exc}"]
    print(json.dumps({"ok": not issues, "issues": issues}, indent=2, sort_keys=True))
    return 0 if not issues else 1


if __name__ == "__main__":
    raise SystemExit(main())
