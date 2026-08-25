#!/usr/bin/env python3
"""Deterministic local controller for the Deep Agents incident-remediation workflow."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import secrets
import shlex
import shutil
import signal
import stat
import subprocess
import sys
import time
import unittest
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
FIXTURES = PACKAGE_ROOT / "fixtures"
ARTIFACTS = PACKAGE_ROOT / "artifacts"
WORKFLOW_POLICY_PATH = PACKAGE_ROOT / "config" / "workflow.json"
try:
    WORKFLOW_POLICY = json.loads(WORKFLOW_POLICY_PATH.read_text(encoding="utf-8"))
except (OSError, json.JSONDecodeError) as exc:
    raise RuntimeError(f"cannot load trusted workflow policy: {type(exc).__name__}") from exc


def _exact_policy_keys(value: Any, expected: set[str], label: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != expected:
        raise RuntimeError(f"trusted workflow policy {label} fields are invalid")
    return value


def _policy_string_list(value: Any, label: str) -> tuple[str, ...]:
    if (
        not isinstance(value, list)
        or not value
        or any(not isinstance(item, str) or not item or "\x00" in item for item in value)
        or len(value) != len(set(value))
    ):
        raise RuntimeError(f"trusted workflow policy {label} is invalid")
    return tuple(value)


def _bounded_policy_int(value: Any, minimum: int, maximum: int, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise RuntimeError(f"trusted workflow policy {label} is outside compiled limits")
    return value


WORKFLOW_POLICY = _exact_policy_keys(
    WORKFLOW_POLICY,
    {"schema_version", "repository", "evidence", "validation", "deepagents", "limits"},
    "root",
)
if WORKFLOW_POLICY["schema_version"] != 1:
    raise RuntimeError("unsupported trusted workflow policy schema")

REPOSITORY_POLICY = _exact_policy_keys(
    WORKFLOW_POLICY["repository"],
    {"id", "allowed_services", "allowed_environments", "allowed_patch_prefixes"},
    "repository",
)
EVIDENCE_POLICY = _exact_policy_keys(
    WORKFLOW_POLICY["evidence"],
    {
        "maximum_window_minutes",
        "maximum_log_records",
        "maximum_database_rows",
        "allowed_database_views",
    },
    "evidence",
)
VALIDATION_POLICY = _exact_policy_keys(
    WORKFLOW_POLICY["validation"], {"required_test_argv"}, "validation"
)
DEEPAGENTS_POLICY = _exact_policy_keys(
    WORKFLOW_POLICY["deepagents"],
    {
        "sdk_version",
        "worker",
        "allowed_filesystem_tools",
        "maximum_attempt_seconds",
    },
    "deepagents",
)
LIMIT_POLICY = _exact_policy_keys(
    WORKFLOW_POLICY["limits"],
    {"hard_maximum_attempts", "hard_maximum_remediation_seconds"},
    "limits",
)

EXPECTED_REPOSITORY = REPOSITORY_POLICY["id"]
if not isinstance(EXPECTED_REPOSITORY, str) or not re.fullmatch(
    r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", EXPECTED_REPOSITORY
):
    raise RuntimeError("trusted workflow policy repository id is invalid")
ALLOWED_SERVICES = _policy_string_list(REPOSITORY_POLICY["allowed_services"], "allowed services")
ALLOWED_ENVIRONMENTS = _policy_string_list(
    REPOSITORY_POLICY["allowed_environments"], "allowed environments"
)
ALLOWED_PATCH_PREFIXES = _policy_string_list(
    REPOSITORY_POLICY["allowed_patch_prefixes"], "allowed patch prefixes"
)
if any(
    prefix.startswith(("/", ".")) or not prefix.endswith("/") or ".." in Path(prefix).parts
    for prefix in ALLOWED_PATCH_PREFIXES
):
    raise RuntimeError("trusted workflow policy allowed patch prefix is unsafe")
ALLOWED_DATABASE_VIEWS = _policy_string_list(
    EVIDENCE_POLICY["allowed_database_views"], "allowed database views"
)
MAX_EVIDENCE_WINDOW_MINUTES = _bounded_policy_int(
    EVIDENCE_POLICY["maximum_window_minutes"], 1, 60, "maximum evidence window"
)
MAX_LOG_RECORDS = _bounded_policy_int(
    EVIDENCE_POLICY["maximum_log_records"], 1, 1000, "maximum log records"
)
MAX_DATABASE_ROWS = _bounded_policy_int(
    EVIDENCE_POLICY["maximum_database_rows"], 1, 1000, "maximum database rows"
)
MAX_SEMANTIC_ATTEMPTS = _bounded_policy_int(
    LIMIT_POLICY["hard_maximum_attempts"], 1, 5, "maximum attempts"
)
MAX_REMEDIATION_SECONDS = float(
    _bounded_policy_int(
        LIMIT_POLICY["hard_maximum_remediation_seconds"],
        1,
        1500,
        "maximum remediation seconds",
    )
)
CANDIDATE_CONTRACT_VERSION = 1
DEEPAGENTS_SDK_VERSION = DEEPAGENTS_POLICY["sdk_version"]
if (
    not isinstance(DEEPAGENTS_SDK_VERSION, str)
    or re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", DEEPAGENTS_SDK_VERSION) is None
):
    raise RuntimeError("trusted workflow policy Deep Agents SDK version is invalid")
DEEPAGENTS_WORKER_VALUE = DEEPAGENTS_POLICY["worker"]
if not isinstance(DEEPAGENTS_WORKER_VALUE, str) or not re.fullmatch(
    r"[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)*", DEEPAGENTS_WORKER_VALUE
):
    raise RuntimeError("trusted workflow policy Deep Agents worker is invalid")
DEEPAGENTS_WORKER = PACKAGE_ROOT / DEEPAGENTS_WORKER_VALUE
try:
    DEEPAGENTS_WORKER.relative_to(PACKAGE_ROOT)
except (TypeError, ValueError) as exc:
    raise RuntimeError("trusted workflow policy Deep Agents worker is invalid") from exc
if not DEEPAGENTS_WORKER.is_file() or DEEPAGENTS_WORKER.is_symlink():
    raise RuntimeError("trusted workflow policy Deep Agents worker is missing")
DEEPAGENTS_ALLOWED_FILESYSTEM_TOOLS = _policy_string_list(
    DEEPAGENTS_POLICY["allowed_filesystem_tools"], "Deep Agents filesystem tools"
)
if DEEPAGENTS_ALLOWED_FILESYSTEM_TOOLS != (
    "ls",
    "read_file",
    "write_file",
    "edit_file",
    "glob",
    "grep",
):
    raise RuntimeError("trusted workflow policy Deep Agents tool surface is invalid")
DEEPAGENTS_REQUEST_VERSION = 1
MAX_DEEPAGENTS_ATTEMPT_SECONDS = float(
    _bounded_policy_int(
        DEEPAGENTS_POLICY["maximum_attempt_seconds"], 1, 900, "maximum attempt seconds"
    )
)
MAX_DEEPAGENTS_REQUEST_BYTES = 128 * 1024
MAX_DEEPAGENTS_PATCH_BYTES = 128 * 1024
MAX_DEEPAGENTS_CHANGED_PATHS = 20
MAX_DEEPAGENTS_FEEDBACK_ITEMS = 4
MAX_DEEPAGENTS_FEEDBACK_OUTPUT = 2000
DEEPAGENTS_REQUIRED_TEST_ARGV = _policy_string_list(
    VALIDATION_POLICY["required_test_argv"], "required test argv"
)
if len(DEEPAGENTS_REQUIRED_TEST_ARGV) > 20 or any(
    len(item) > 200 for item in DEEPAGENTS_REQUIRED_TEST_ARGV
):
    raise RuntimeError("trusted workflow policy required test argv is too large")
DEEPAGENTS_REQUIRED_TEST = shlex.join(DEEPAGENTS_REQUIRED_TEST_ARGV)
CANDIDATE_TEST_IMAGE = (
    "python:3.12-alpine@sha256:6d43704baacd1bfbe7c295d7f13079d5d8104ed33568873133f8fc69980419df"
)
CANDIDATE_TEST_ENVIRONMENT = (
    "HOME=/tmp",
    "LANG=C.UTF-8",
    "PATH=/usr/local/bin:/usr/bin:/bin",
    "PYTHONDONTWRITEBYTECODE=1",
    "PYTHONHASHSEED=0",
    "PYTHONPATH=/workspace",
    "PYTHONUNBUFFERED=1",
    "TMPDIR=/tmp",
    "USER=nobody",
)
CANDIDATE_TEST_LABEL = "deepagents-incident-workflow.candidate-test"
CANDIDATE_CONTAINER_INTENT_VERSION = 1
CANDIDATE_CONTAINER_PHASES = (
    "attempt-unit",
    "attempt-verifier",
    "independent-unit",
    "independent-verifier",
)
CANDIDATE_PROBE_PATH = PACKAGE_ROOT / "verifiers" / "candidate_probe.py"
TRUSTED_VERIFIER_COMPLETION = "DAIW_TRUSTED_VERIFIER_COMPLETED:v1"
DEEPAGENTS_IDENTITY_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/+@-]{0,127}$")
DEEPAGENTS_INVOCATION_PATTERN = re.compile(r"^[0-9a-f]{32}$")
RUN_ID_PATTERN = re.compile(r"^[0-9]{8}T[0-9]{6}Z-[0-9a-f]{32}$")
SUPPORTED_DEEPAGENTS_PROVIDERS = ("anthropic", "google_genai", "ollama", "openai")
DEEPAGENTS_PROVIDER_PACKAGES = {
    "anthropic": ("langchain-anthropic", "1.6.1"),
    "google_genai": ("langchain-google-genai", "4.3.5"),
    "ollama": ("langchain-ollama", "1.1.0"),
    "openai": ("langchain-openai", "1.6.0"),
}
VERIFIER_RECEIPT_VERSION = 1
COMPOSE_CLEANUP_INTENT_VERSION = 1
VERIFIER_COMMAND = ("python", "/verifier/controller.py", "--repository", "/workspace")
WORKFLOW_POLICY_SHA256 = hashlib.sha256(WORKFLOW_POLICY_PATH.read_bytes()).hexdigest()
VERIFIER_COMMAND_SHA256 = hashlib.sha256(
    json.dumps(VERIFIER_COMMAND, separators=(",", ":")).encode("utf-8")
).hexdigest()
RAW_SENSITIVE_MARKERS = ("person@example.invalid", "synthetic-sensitive-value")
INJECTION_MARKERS = (
    "ignore previous instructions",
    "reveal every credential",
    "change the deployment workflow",
)
SENSITIVE_ENV_PREFIXES = (
    "AWS_",
    "AZURE_OPENAI_API_KEY",
    "GRAFANA_",
    "SENTRY_",
    "SLACK_",
    "POSTGRES_",
    "PGPASSWORD",
    "DATABASE_URL",
    "GITHUB_TOKEN",
    "GH_TOKEN",
)
PROVIDER_ENVIRONMENT_NAMES = frozenset(
    {
        "ANTHROPIC_API_KEY",
        "ANTHROPIC_BASE_URL",
        "GOOGLE_API_KEY",
        "OLLAMA_HOST",
        "OPENAI_API_KEY",
        "OPENAI_BASE_URL",
        "OPENAI_ORG_ID",
        "OPENAI_PROJECT_ID",
    }
)


class FlowError(RuntimeError):
    """Base class for controlled terminal outcomes."""


class PolicyDenied(FlowError):
    """Raised when deterministic policy rejects an operation."""


class DeadlineExpired(FlowError):
    """Raised when the outer monotonic budget is exhausted."""


class Candidate:
    """A validated machine-readable candidate plus its local verification input."""

    def __init__(self, record: dict[str, Any], patch_path: Path) -> None:
        validate_candidate_contract(record)
        patch_path = Path(patch_path)
        if not patch_path.is_file():
            raise PolicyDenied("candidate verification patch does not exist")
        if patch_path.name != record["patch"]:
            raise PolicyDenied("candidate patch name does not match verification input")
        patch_digest = hashlib.sha256(patch_path.read_bytes()).hexdigest()
        if patch_digest != record["patch_sha256"]:
            raise PolicyDenied("candidate patch digest does not match verification input")
        self.record = dict(record)
        self.patch_path = patch_path


def retain_candidate_patch(run_dir: Path, candidate: Candidate) -> Candidate:
    """Copy the exact candidate patch into the controller-owned run artifacts."""
    attempt = candidate.record["attempt"]
    source = candidate.record["source"]
    suffix = "deepagents" if source == "deepagents-real-model" else "fixture"
    target = run_dir / f"attempt-{attempt}-{suffix}.patch"
    source_path = candidate.patch_path
    if source_path.is_symlink() or not source_path.is_file():
        raise PolicyDenied("candidate patch source must be a regular file")
    payload = source_path.read_bytes()
    _text, changed_paths = validate_deepagents_patch_bytes(payload)
    digest = hashlib.sha256(payload).hexdigest()
    if digest != candidate.record["patch_sha256"]:
        raise PolicyDenied("candidate patch changed before artifact retention")
    if changed_paths != candidate.record["changed_paths"]:
        raise PolicyDenied("candidate patch paths changed before artifact retention")
    if Path(os.path.abspath(source_path)) != Path(os.path.abspath(target)):
        if target.exists() or target.is_symlink():
            raise PolicyDenied("candidate patch artifact already exists")
        target.write_bytes(payload)
    record = {**candidate.record, "patch": target.name}
    return Candidate(record, target)


class CandidateProvider(Protocol):
    """Boundary for producing a candidate without granting it acceptance authority."""

    source: str

    def has_candidate(self, attempt: int) -> bool:
        """Return whether this provider can produce the requested semantic attempt."""
        ...

    def create_candidate(
        self,
        *,
        attempt: int,
        workspace: Path,
        deadline: float,
        request: dict[str, Any] | None = None,
    ) -> Candidate:
        """Modify the workspace and return a versioned candidate contract."""
        ...


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(redact(value), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def append_event(run_dir: Path, event: str, **details: Any) -> None:
    record = {"at": utc_now(), "event": event, **redact(details)}
    with (run_dir / "events.jsonl").open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(record, sort_keys=True) + "\n")


def redact_text(value: str) -> str:
    for name in PROVIDER_ENVIRONMENT_NAMES:
        secret_value = os.environ.get(name)
        if secret_value and len(secret_value) >= 8:
            value = value.replace(secret_value, "[REDACTED_PROVIDER_VALUE]")
    value = re.sub(r"(?i)\b[\w.+-]+@[\w.-]+\.[a-z]{2,}\b", "[REDACTED_EMAIL]", value)
    value = re.sub(
        r"(?i)(authorization\s*:\s*bearer\s+)[^\s,;]+",
        r"\1[REDACTED]",
        value,
    )
    value = re.sub(
        r"""(?i)(["'](?:api[_-]?key|token|password|secret)["']\s*:\s*["'])[^"']+""",
        r"\1[REDACTED]",
        value,
    )
    value = re.sub(
        r"(?i)\b(token|api[_-]?key|password|secret)=([^\s,;]+)",
        lambda match: f"{match.group(1)}=[REDACTED]",
        value,
    )
    for pattern in (
        r"sk-(?:proj-|ant-)?[A-Za-z0-9_-]{20,}",
        r"AIza[0-9A-Za-z_-]{35}",
        r"xox[baprs]-[A-Za-z0-9-]{20,}",
        r"glpat-[A-Za-z0-9_-]{20,}",
    ):
        value = re.sub(pattern, "[REDACTED_TOKEN]", value)
    for marker in RAW_SENSITIVE_MARKERS:
        value = value.replace(marker, "[REDACTED]")
    return value


def redact(value: Any) -> Any:
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, list):
        return [redact(item) for item in value]
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key, item in value.items():
            if key.lower() in {"api_key", "token", "password", "secret", "customer_email"}:
                result[key] = "[REDACTED]"
            else:
                result[key] = redact(item)
        return result
    return value


def sensitive_environment_names() -> list[str]:
    names = []
    for name in os.environ:
        if any(name == prefix or name.startswith(prefix) for prefix in SENSITIVE_ENV_PREFIXES):
            names.append(name)
    return sorted(names)


def subprocess_environment(extra: dict[str, str] | None = None) -> dict[str, str]:
    environment = dict(os.environ)
    for name in list(environment):
        if (
            name in PROVIDER_ENVIRONMENT_NAMES
            or name.startswith("GIT_")
            or any(name == prefix or name.startswith(prefix) for prefix in SENSITIVE_ENV_PREFIXES)
        ):
            environment.pop(name, None)
    if extra:
        environment.update(extra)
    return environment


def command(
    args: list[str],
    *,
    cwd: Path,
    timeout: float,
    extra_env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        cwd=cwd,
        env=subprocess_environment(extra_env),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=max(0.1, timeout),
        check=False,
    )


def remaining_seconds(deadline: float) -> float:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise DeadlineExpired("remediation deadline expired")
    return remaining


def bounded_controller_feedback(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return only the small, redacted verifier feedback surface exposed to Deep Agents."""
    bounded: list[dict[str, Any]] = []
    allowed = (
        "attempt",
        "stage",
        "candidate_digest",
        "command",
        "exit_code",
        "passed",
        "reason",
        "output",
    )
    for item in items[-MAX_DEEPAGENTS_FEEDBACK_ITEMS:]:
        if not isinstance(item, dict):
            continue
        record = {key: item[key] for key in allowed if key in item}
        if "output" in record:
            record["output"] = str(record["output"])[-MAX_DEEPAGENTS_FEEDBACK_OUTPUT:]
        if "reason" in record:
            record["reason"] = str(record["reason"])[:1000]
        bounded.append(redact(record))
    return bounded


def build_deepagents_request(
    *,
    run_id: str,
    attempt: int,
    incident: dict[str, Any],
    evidence: dict[str, Any],
    feedback: list[dict[str, Any]],
    deadline: float,
    diagnosis: dict[str, Any] | None = None,
    execution_plan: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the exact, bounded data packet mounted read-only for one attempt."""
    incident_fields = (
        "schema_version",
        "issue_id",
        "repository",
        "base_revision",
        "service",
        "component",
        "environment",
        "summary",
        "instructions",
    )
    packet = {
        "schema_version": DEEPAGENTS_REQUEST_VERSION,
        "run_id": run_id,
        "attempt": attempt,
        "remaining_budget_seconds": round(
            min(MAX_DEEPAGENTS_ATTEMPT_SECONDS, remaining_seconds(deadline)), 3
        ),
        "incident": {
            **{key: incident[key] for key in incident_fields if key in incident},
            "content_trust": "untrusted_data",
        },
        "evidence": {
            "content_trust": "untrusted_data",
            "packet": evidence,
        },
        "feedback": bounded_controller_feedback(feedback),
        "policy": {
            "allowed_paths": list(ALLOWED_PATCH_PREFIXES),
            "controller_is_sole_acceptor": True,
            "maximum_changed_paths": MAX_DEEPAGENTS_CHANGED_PATHS,
            "required_test": DEEPAGENTS_REQUIRED_TEST,
            "workspace_root": "/",
            "model_must_not_claim_acceptance": True,
        },
        "output_contract": {
            "authority": "advisory-only",
            "candidate_patch": "derived-by-controller-from-workspace",
            "acceptance": "controller-owned-verification-only",
        },
    }
    if diagnosis is not None:
        packet["diagnosis"] = {
            "content_trust": "untrusted_prior_model_output",
            "packet": diagnosis,
        }
    if execution_plan is not None:
        if execution_plan.get("controller_approved") is not True:
            raise PolicyDenied("Deep Agents execution plan is not controller-approved")
        if execution_plan.get("issue_id") != incident.get("issue_id"):
            raise PolicyDenied("Deep Agents execution plan does not match the incident")
        if execution_plan.get("required_test") != DEEPAGENTS_REQUIRED_TEST:
            raise PolicyDenied("Deep Agents execution plan changed the required test")
        edits = execution_plan.get("edits")
        if not isinstance(edits, list) or not edits or len(edits) > MAX_DEEPAGENTS_CHANGED_PATHS:
            raise PolicyDenied("Deep Agents execution plan edits are invalid")
        for edit in edits:
            if not isinstance(edit, dict) or set(edit) != {
                "path",
                "old_fragment",
                "new_fragment",
            }:
                raise PolicyDenied("Deep Agents execution plan edit fields are invalid")
            path = edit["path"]
            if not isinstance(path, str) or not path.startswith(ALLOWED_PATCH_PREFIXES):
                raise PolicyDenied("Deep Agents execution plan contains a forbidden path")
            if not all(
                isinstance(edit[key], str) and edit[key] for key in ("old_fragment", "new_fragment")
            ):
                raise PolicyDenied("Deep Agents execution plan contains an invalid edit")
        packet["controller_approved_execution_plan"] = execution_plan
    packet = redact(packet)
    encoded = json.dumps(packet, sort_keys=True, separators=(",", ":")).encode("utf-8")
    if len(encoded) > MAX_DEEPAGENTS_REQUEST_BYTES:
        raise PolicyDenied("Deep Agents request packet exceeds 128 KiB")
    return packet


def validate_deepagents_workspace(root: Path) -> None:
    """Reject links and non-regular filesystem objects before producing a diff."""
    try:
        root_mode = root.lstat().st_mode
    except FileNotFoundError as exc:
        raise PolicyDenied("Deep Agents sandbox workspace is missing") from exc
    if stat.S_ISLNK(root_mode) or not stat.S_ISDIR(root_mode):
        raise PolicyDenied("Deep Agents sandbox workspace must be a real directory")
    for current, directory_names, file_names in os.walk(root, followlinks=False):
        current_path = Path(current)
        for name in directory_names:
            mode = (current_path / name).lstat().st_mode
            if stat.S_ISLNK(mode) or not stat.S_ISDIR(mode):
                raise PolicyDenied("Deep Agents sandbox contains a linked or irregular directory")
        for name in file_names:
            mode = (current_path / name).lstat().st_mode
            if stat.S_ISLNK(mode) or not stat.S_ISREG(mode):
                raise PolicyDenied("Deep Agents sandbox contains a linked or irregular file")


def remove_candidate_caches(root: Path) -> None:
    for current, directory_names, file_names in os.walk(root, topdown=False, followlinks=False):
        current_path = Path(current)
        for name in file_names:
            if Path(name).suffix in {".pyc", ".pyo"}:
                (current_path / name).unlink(missing_ok=True)
        for name in directory_names:
            if name == "__pycache__":
                shutil.rmtree(current_path / name, ignore_errors=True)


def remove_identical_editor_backups(root: Path, baseline: Path) -> list[str]:
    """Discard only recognized editor backups that exactly match the baseline file."""
    removed: list[str] = []
    for suffix in (".bak", ".bak2", ".bug", ".orig"):
        for backup in sorted(root.rglob(f"*{suffix}")):
            relative = backup.relative_to(root)
            original_relative = Path(relative.as_posix()[: -len(suffix)])
            original = baseline / original_relative
            if (
                not backup.is_file()
                or backup.is_symlink()
                or not original.is_file()
                or original.is_symlink()
                or backup.read_bytes() != original.read_bytes()
            ):
                raise PolicyDenied("Deep Agents sandbox contains an unexpected editor backup")
            backup.unlink()
            removed.append(relative.as_posix())
    return removed


def validate_deepagents_patch_bytes(payload: bytes) -> tuple[str, list[str]]:
    if not payload:
        raise PolicyDenied("Deep Agents candidate produced no patch")
    if len(payload) > MAX_DEEPAGENTS_PATCH_BYTES:
        raise PolicyDenied("Deep Agents candidate patch exceeds 128 KiB")
    try:
        patch_text = payload.decode("utf-8")
    except UnicodeError as exc:
        raise PolicyDenied("Deep Agents candidate patch is not UTF-8 text") from exc
    if "GIT binary patch" in patch_text:
        raise PolicyDenied("Deep Agents candidate contains a binary patch")
    for line in patch_text.splitlines():
        if line.startswith(("old mode ", "new mode ")):
            raise PolicyDenied("Deep Agents candidate contains a file mode change")
        if line.startswith(("new file mode ", "deleted file mode ")):
            mode = line.rsplit(" ", 1)[-1]
            if mode != "100644":
                raise PolicyDenied("Deep Agents candidate contains an unsupported file mode")
    changed_paths = validate_patch(patch_text)
    if len(changed_paths) > MAX_DEEPAGENTS_CHANGED_PATHS:
        raise PolicyDenied("Deep Agents candidate changes more than 20 paths")
    return patch_text, changed_paths


def validate_incident(incident: dict[str, Any]) -> None:
    required = {
        "schema_version",
        "issue_id",
        "repository",
        "base_revision",
        "service",
        "environment",
        "evidence_window_minutes",
        "summary",
        "instructions",
    }
    missing = sorted(required - set(incident))
    if missing:
        raise PolicyDenied(f"incident missing fields: {', '.join(missing)}")
    if incident["schema_version"] != 1:
        raise PolicyDenied("unsupported incident schema")
    if incident["repository"] != EXPECTED_REPOSITORY:
        raise PolicyDenied("repository is not allowlisted")
    if (
        incident["service"] not in ALLOWED_SERVICES
        or incident["environment"] not in ALLOWED_ENVIRONMENTS
    ):
        raise PolicyDenied("service or environment is not allowlisted")
    window = incident["evidence_window_minutes"]
    if not isinstance(window, int) or not 1 <= window <= MAX_EVIDENCE_WINDOW_MINUTES:
        raise PolicyDenied(
            f"evidence window must be between 1 and {MAX_EVIDENCE_WINDOW_MINUTES} minutes"
        )
    untrusted_text = f"{incident['summary']}\n{incident['instructions']}".lower()
    if any(marker in untrusted_text for marker in INJECTION_MARKERS):
        raise PolicyDenied("incident contains a known instruction-injection marker")


def collect_evidence(
    incident: dict[str, Any],
    source_path: Path | None = None,
) -> dict[str, Any]:
    source = read_json(source_path or FIXTURES / "evidence.json")
    logs = [
        entry
        for entry in source["logs"]
        if entry.get("labels", {}).get("service") == incident["service"]
        and entry.get("labels", {}).get("environment") == incident["environment"]
    ][:MAX_LOG_RECORDS]
    database = source["database"]
    if database["view"] not in ALLOWED_DATABASE_VIEWS:
        raise PolicyDenied("database view is not allowlisted")
    if len(database["rows"]) > MAX_DATABASE_ROWS:
        raise PolicyDenied("database row limit exceeded")
    query_policy = source.get("query_policy")
    if query_policy is not None:
        if query_policy.get("database", {}).get("operation") != "SELECT":
            raise PolicyDenied("database evidence operation is not SELECT-only")
        if query_policy.get("database", {}).get("view") != database["view"]:
            raise PolicyDenied("database evidence view differs from its query policy")
    packet = {
        "schema_version": 1,
        "data_classification": source.get("data_classification", "synthetic-only"),
        "query_policy": query_policy
        or {
            "logs": {
                "service": incident["service"],
                "environment": incident["environment"],
                "window_minutes": incident["evidence_window_minutes"],
                "limit": 100,
            },
            "database": {
                "operation": "SELECT",
                "view": "incident_context",
                "limit": 20,
            },
        },
        "logs": logs,
        "database": database,
    }
    return redact(packet)


def patch_paths(patch_text: str) -> list[str]:
    paths: list[str] = []
    diff_paths: list[str] = []
    for line in patch_text.splitlines():
        if line.startswith(
            (
                "rename from ",
                "rename to ",
                "copy from ",
                "copy to ",
                "similarity index ",
                "dissimilarity index ",
            )
        ):
            raise PolicyDenied("candidate patch contains rename or copy metadata")
        if line.startswith("diff --git "):
            match = re.fullmatch(r"diff --git a/([^\s]+) b/([^\s]+)", line)
            if match is None or match.group(1) != match.group(2):
                raise PolicyDenied("candidate patch contains an unsupported diff header")
            diff_paths.append(match.group(1))
        if line.startswith("--- ") or line.startswith("+++ "):
            raw_path = line[4:].split("\t", 1)[0]
            if raw_path == "/dev/null":
                continue
            if raw_path.startswith(("a/", "b/")):
                paths.append(raw_path[2:])
                continue
            raise PolicyDenied("candidate patch contains an unsupported path header")
    if not paths or not diff_paths:
        raise PolicyDenied("candidate patch has no changed paths")
    if set(paths) != set(diff_paths):
        raise PolicyDenied("candidate patch path headers do not match its diff headers")
    for changed_path in paths:
        candidate = Path(changed_path)
        if candidate.is_absolute() or ".." in candidate.parts:
            raise PolicyDenied("candidate path escapes the workspace")
        if not changed_path.startswith(ALLOWED_PATCH_PREFIXES):
            raise PolicyDenied(f"candidate path is not allowlisted: {changed_path}")
    return sorted(set(paths))


def validate_patch(patch_text: str) -> list[str]:
    lowered = patch_text.lower()
    if any(marker.lower() in lowered for marker in RAW_SENSITIVE_MARKERS):
        raise PolicyDenied("candidate patch contains fixture-sensitive data")
    if "private key" in lowered or ".github/workflows" in lowered:
        raise PolicyDenied("candidate patch contains a forbidden surface")
    for line in patch_text.splitlines():
        if line.startswith(("old mode ", "new mode ")):
            raise PolicyDenied("candidate patch contains a file mode change")
        if line.startswith(("new file mode ", "deleted file mode ")):
            mode = line.rsplit(" ", 1)[-1]
            if mode != "100644":
                raise PolicyDenied("candidate patch contains an unsupported file mode")
    return patch_paths(patch_text)


def validate_candidate_contract(record: dict[str, Any]) -> None:
    required = {
        "schema_version",
        "source",
        "attempt",
        "patch",
        "patch_sha256",
        "changed_paths",
        "candidate_digest",
    }
    if not isinstance(record, dict):
        raise PolicyDenied("candidate contract must be an object")
    if set(record) != required:
        raise PolicyDenied("candidate contract fields are invalid")
    if record["schema_version"] != CANDIDATE_CONTRACT_VERSION:
        raise PolicyDenied("unsupported candidate contract schema")
    if not isinstance(record["source"], str) or not 1 <= len(record["source"]) <= 100:
        raise PolicyDenied("candidate source must be a non-empty string")
    if (
        isinstance(record["attempt"], bool)
        or not isinstance(record["attempt"], int)
        or not 1 <= record["attempt"] <= MAX_SEMANTIC_ATTEMPTS
    ):
        raise PolicyDenied("candidate attempt is outside the controller limit")
    if (
        not isinstance(record["patch"], str)
        or re.fullmatch(r"[A-Za-z0-9._-]+\.patch", record["patch"]) is None
    ):
        raise PolicyDenied("candidate patch must be a local file name")
    for field in ("patch_sha256", "candidate_digest"):
        value = record[field]
        if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None:
            raise PolicyDenied(f"candidate {field} must be a SHA-256 digest")
    changed_paths = record["changed_paths"]
    if (
        not isinstance(changed_paths, list)
        or not changed_paths
        or len(changed_paths) > MAX_DEEPAGENTS_CHANGED_PATHS
        or any(not isinstance(path, str) for path in changed_paths)
        or any(not 1 <= len(path) <= 300 for path in changed_paths)
        or changed_paths != sorted(set(changed_paths))
    ):
        raise PolicyDenied("candidate changed paths must be a sorted unique list")
    for changed_path in changed_paths:
        candidate = Path(changed_path)
        if candidate.is_absolute() or ".." in candidate.parts:
            raise PolicyDenied("candidate path escapes the workspace")
        if not changed_path.startswith(ALLOWED_PATCH_PREFIXES):
            raise PolicyDenied(f"candidate path is not allowlisted: {changed_path}")


def tree_digest(root: Path) -> str:
    digest = hashlib.sha256()
    files = (
        item
        for item in root.rglob("*")
        if item.is_file()
        and "__pycache__" not in item.parts
        and item.suffix not in {".pyc", ".pyo"}
    )
    for path in sorted(files):
        digest.update(path.relative_to(root).as_posix().encode())
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def workspace_file_digests(root: Path) -> dict[str, str]:
    """Snapshot regular workspace files for post-apply path reconciliation."""
    validate_deepagents_workspace(root)
    return {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*"))
        if path.is_file()
        and "__pycache__" not in path.parts
        and path.suffix not in {".pyc", ".pyo"}
    }


def verifier_bundle_digest(verifier: Path) -> str:
    """Bind the scenario verifier and candidate supervisor as one trusted input."""
    verifier = verifier.resolve(strict=True)
    candidate_probe = CANDIDATE_PROBE_PATH.resolve(strict=True)
    digest = hashlib.sha256()
    for label, path in (("controller", verifier), ("candidate-probe", candidate_probe)):
        if not path.is_file() or path.is_symlink():
            raise PolicyDenied(f"trusted {label} verifier input is irregular")
        digest.update(label.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def _is_sha256(value: Any) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def create_workspace(
    run_dir: Path,
    name: str,
    repository: Path | None = None,
) -> Path:
    source = (repository or FIXTURES / "repository").resolve(strict=True)
    validate_deepagents_workspace(source)
    workspace = run_dir / name / "workspace"
    shutil.copytree(
        source,
        workspace,
        symlinks=True,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo"),
    )
    validate_deepagents_workspace(workspace)
    return workspace


def scoped_package_path(relative: str, *, root: Path = PACKAGE_ROOT) -> Path:
    candidate = (root / relative).resolve()
    resolved_root = root.resolve()
    if candidate != resolved_root and resolved_root not in candidate.parents:
        raise PolicyDenied("scenario path escapes the package")
    return candidate


def scenario_repository(scenario: dict[str, Any]) -> Path:
    relative = scenario.get("repository", "repository")
    repository = scoped_package_path(str(relative), root=FIXTURES)
    if not repository.is_dir():
        raise PolicyDenied("scenario repository does not exist")
    return repository


def scenario_evidence_path(scenario: dict[str, Any]) -> Path:
    relative = scenario.get("evidence", "evidence.json")
    evidence_path = scoped_package_path(str(relative), root=FIXTURES)
    if not evidence_path.is_file():
        raise PolicyDenied("scenario evidence does not exist")
    return evidence_path


def scenario_diagnosis(scenario: dict[str, Any]) -> dict[str, Any] | None:
    relative = scenario.get("diagnosis")
    if relative is None:
        return None
    diagnosis_path = scoped_package_path(str(relative), root=FIXTURES)
    if not diagnosis_path.is_file():
        raise PolicyDenied("scenario diagnosis does not exist")
    return read_json(diagnosis_path)


def scenario_execution_plan(scenario: dict[str, Any]) -> dict[str, Any] | None:
    relative = scenario.get("execution_plan")
    if relative is None:
        return None
    plan_path = scoped_package_path(str(relative), root=FIXTURES)
    if not plan_path.is_file():
        raise PolicyDenied("scenario execution plan does not exist")
    plan = read_json(plan_path)
    if not isinstance(plan, dict) or plan.get("controller_approved") is not True:
        raise PolicyDenied("scenario execution plan is not controller-approved")
    return plan


def scenario_controller_verifier(scenario: dict[str, Any]) -> Path | None:
    relative = scenario.get("controller_verifier")
    if relative is None:
        return None
    verifier = scoped_package_path(str(relative))
    if not verifier.is_file():
        raise PolicyDenied("scenario controller verifier does not exist")
    return verifier


def validate_scenario_candidate_paths(
    scenario: dict[str, Any],
    changed_paths: list[str],
) -> None:
    allowed = scenario.get("allowed_changed_paths")
    if (
        not isinstance(allowed, list)
        or not allowed
        or any(not isinstance(path, str) or not path for path in allowed)
        or allowed != sorted(set(allowed))
    ):
        raise PolicyDenied("scenario exact changed-path policy is missing or invalid")
    for path in allowed:
        candidate = Path(path)
        if candidate.is_absolute() or ".." in candidate.parts:
            raise PolicyDenied("scenario exact changed-path policy is unsafe")
        if not path.startswith(ALLOWED_PATCH_PREFIXES):
            raise PolicyDenied("scenario exact changed-path policy exceeds workflow policy")
    unexpected = sorted(set(changed_paths) - set(allowed))
    if unexpected:
        raise PolicyDenied(
            f"candidate path is outside the scenario policy: {', '.join(unexpected)}"
        )


def apply_candidate(workspace: Path, patch_path: Path, deadline: float) -> dict[str, Any]:
    patch_text = patch_path.read_text(encoding="utf-8")
    paths = validate_patch(patch_text)
    baseline_files = workspace_file_digests(workspace)
    baseline_digest = tree_digest(workspace)
    # The package may itself live below a larger Git worktree. Prevent Git
    # from discovering that parent repository and silently ignoring paths
    # outside the current subdirectory.
    git_env = git_environment(workspace)
    safe_git_prefix = [
        "git",
        "-c",
        "core.hooksPath=/dev/null",
        "-c",
        "core.attributesFile=/dev/null",
    ]
    check = command(
        [*safe_git_prefix, "apply", "--check", str(patch_path)],
        cwd=workspace,
        timeout=min(30, remaining_seconds(deadline)),
        extra_env=git_env,
    )
    if check.returncode != 0:
        raise PolicyDenied(f"candidate patch does not apply: {redact_text(check.stdout)[:1000]}")
    applied = command(
        [*safe_git_prefix, "apply", str(patch_path)],
        cwd=workspace,
        timeout=min(30, remaining_seconds(deadline)),
        extra_env=git_env,
    )
    if applied.returncode != 0:
        raise PolicyDenied(f"candidate patch failed: {redact_text(applied.stdout)[:1000]}")
    candidate_files = workspace_file_digests(workspace)
    applied_paths = sorted(
        path
        for path in set(baseline_files) | set(candidate_files)
        if baseline_files.get(path) != candidate_files.get(path)
    )
    if applied_paths != paths:
        raise PolicyDenied("applied workspace paths do not match candidate patch headers")
    candidate_digest = tree_digest(workspace)
    if candidate_digest == baseline_digest:
        raise PolicyDenied("candidate patch produced no workspace change")
    return {
        "patch": patch_path.name,
        "changed_paths": paths,
        "candidate_digest": candidate_digest,
    }


class FixtureCandidateProvider:
    """Provide reviewed fixture patches through the same contract as future providers."""

    source = "fixture-simulated-deepagents"

    def __init__(self, patches: list[Path], *, repeat_last_patch: bool) -> None:
        self._patches = tuple(patches)
        self._repeat_last_patch = repeat_last_patch

    def _patch_for_attempt(self, attempt: int) -> Path | None:
        if attempt < 1:
            raise ValueError("attempt must be a positive integer")
        if not self._patches:
            return None
        if attempt > len(self._patches) and not self._repeat_last_patch:
            return None
        return self._patches[min(attempt - 1, len(self._patches) - 1)]

    def has_candidate(self, attempt: int) -> bool:
        return self._patch_for_attempt(attempt) is not None

    def create_candidate(
        self,
        *,
        attempt: int,
        workspace: Path,
        deadline: float,
        request: dict[str, Any] | None = None,
    ) -> Candidate:
        patch_path = self._patch_for_attempt(attempt)
        if patch_path is None:
            raise FlowError(f"fixture provider has no candidate for attempt {attempt}")
        applied = apply_candidate(workspace, patch_path, deadline)
        record = {
            "schema_version": CANDIDATE_CONTRACT_VERSION,
            "source": self.source,
            "attempt": attempt,
            "patch": applied["patch"],
            "patch_sha256": hashlib.sha256(patch_path.read_bytes()).hexdigest(),
            "changed_paths": applied["changed_paths"],
            "candidate_digest": applied["candidate_digest"],
        }
        return Candidate(record, patch_path)


def run_deepagents_process(
    args: list[str],
    *,
    cwd: Path,
    environment: dict[str, str],
    timeout: float,
) -> subprocess.CompletedProcess[str]:
    process = subprocess.Popen(
        args,
        cwd=cwd,
        env=environment,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
    )
    try:
        stdout, stderr = process.communicate(timeout=max(0.1, timeout))
    except subprocess.TimeoutExpired as exc:
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            process.terminate()
        try:
            stdout, stderr = process.communicate(timeout=3)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                process.kill()
            stdout, stderr = process.communicate()
        raise subprocess.TimeoutExpired(
            args,
            timeout,
            output=stdout or exc.output,
            stderr=stderr or exc.stderr,
        ) from exc
    return subprocess.CompletedProcess(args, process.returncode, stdout, stderr)


def deepagents_process_environment(
    *,
    home_dir: Path,
    provider: str,
) -> dict[str, str]:
    """Build a minimal SDK-worker environment with provider-scoped credentials."""
    provider_environment = {
        "anthropic": ("ANTHROPIC_API_KEY",),
        "google_genai": ("GOOGLE_API_KEY",),
        "ollama": (),
        "openai": (
            "OPENAI_API_KEY",
            "OPENAI_ORG_ID",
            "OPENAI_PROJECT_ID",
        ),
    }
    if provider not in provider_environment:
        raise PolicyDenied(
            "unsupported Deep Agents provider; use anthropic, google_genai, ollama, or openai"
        )
    environment = {
        "PATH": os.environ.get("PATH", ""),
        "HOME": str(home_dir.resolve()),
        "USER": os.environ.get("USER", "user"),
        "SHELL": os.environ.get("SHELL", "/bin/sh"),
        "TMPDIR": os.environ.get("TMPDIR", "/tmp"),
        "LANG": os.environ.get("LANG", "C.UTF-8"),
        "NO_COLOR": "1",
        "LANGSMITH_TRACING": "false",
        "LANGCHAIN_TRACING_V2": "false",
        "LANGGRAPH_CLI_NO_ANALYTICS": "1",
        "DEEPAGENTS_CODE_NO_UPDATE_CHECK": "1",
        "DEEPAGENTS_CODE_AUTO_UPDATE": "0",
        "DEEPAGENTS_CODE_PLUGIN_AUTO_UPDATE": "0",
        "DEEPAGENTS_CODE_PRICES_AUTO_UPDATE": "0",
        "DEEPAGENTS_CODE_MEMORY_AUTO_SAVE": "0",
        "DEEPAGENTS_CODE_READ_PROJECT_DOTENV": "0",
        "DEEPAGENTS_CODE_OLLAMA_DISCOVERY": "0",
        "DEEPAGENTS_CODE_OFFLINE": "1",
    }
    for name in provider_environment[provider]:
        if name in os.environ:
            environment[name] = os.environ[name]
    return environment


def checked_git(
    args: list[str],
    *,
    cwd: Path,
    timeout: float,
    text: bool = True,
) -> subprocess.CompletedProcess[Any]:
    if not args or args[0] != "git":
        raise ValueError("checked_git requires an explicit git command")
    safe_args = [
        "git",
        "-c",
        "core.hooksPath=/dev/null",
        "-c",
        "core.attributesFile=/dev/null",
        *args[1:],
    ]
    result = subprocess.run(
        safe_args,
        cwd=cwd,
        env=subprocess_environment(git_environment(cwd)),
        text=text,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=max(0.1, timeout),
        check=False,
    )
    if result.returncode != 0:
        error = (
            result.stderr
            if isinstance(result.stderr, str)
            else result.stderr.decode("utf-8", "replace")
        )
        raise FlowError(f"Git baseline operation failed: {redact_text(error)[-1000:]}")
    return subprocess.CompletedProcess(args, result.returncode, result.stdout, result.stderr)


def git_environment(workspace: Path) -> dict[str, str]:
    """Return the complete controller-owned environment for every Git subprocess."""
    return {
        "GIT_CEILING_DIRECTORIES": str(workspace.parent),
        "GIT_CONFIG_GLOBAL": "/dev/null",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_TERMINAL_PROMPT": "0",
    }


def initialize_shadow_git(workspace: Path, git_repository: Path, deadline: float) -> Path:
    checked_git(
        ["git", "init", "--quiet", str(git_repository)],
        cwd=workspace.parent,
        timeout=min(20, remaining_seconds(deadline)),
    )
    git_dir = git_repository / ".git"
    prefix = ["git", f"--git-dir={git_dir}", f"--work-tree={workspace}"]
    checked_git(
        [*prefix, "add", "--all"],
        cwd=workspace.parent,
        timeout=min(20, remaining_seconds(deadline)),
    )
    checked_git(
        [
            *prefix,
            "-c",
            "user.name=Deep Agents Incident Workflow",
            "-c",
            "user.email=local-only@example.invalid",
            "commit",
            "--quiet",
            "--no-gpg-sign",
            "--allow-empty",
            "-m",
            "baseline",
        ],
        cwd=workspace.parent,
        timeout=min(20, remaining_seconds(deadline)),
    )
    return git_dir


def shadow_git_diff(workspace: Path, git_dir: Path, deadline: float) -> bytes:
    prefix = ["git", f"--git-dir={git_dir}", f"--work-tree={workspace}"]
    untracked_result = checked_git(
        [*prefix, "ls-files", "--others", "--exclude-standard", "-z"],
        cwd=workspace.parent,
        timeout=min(20, remaining_seconds(deadline)),
        text=False,
    )
    untracked = [item.decode("utf-8") for item in untracked_result.stdout.split(b"\0") if item]
    if untracked:
        checked_git(
            [*prefix, "add", "-N", "--", *untracked],
            cwd=workspace.parent,
            timeout=min(20, remaining_seconds(deadline)),
        )
    diff = checked_git(
        [*prefix, "diff", "--binary", "--no-ext-diff", "--full-index", "HEAD", "--"],
        cwd=workspace.parent,
        timeout=min(30, remaining_seconds(deadline)),
        text=False,
    )
    return bytes(diff.stdout)


class DeepAgentsCandidateProvider:
    """Run a fresh Deep Agents SDK worker while retaining acceptance outside it."""

    source = "deepagents-real-model"

    def __init__(
        self,
        *,
        provider: str,
        model: str,
        runtime_python: str = sys.executable,
        max_turns: int = 20,
    ) -> None:
        if isinstance(model, str) and ":" in model:
            raise ValueError(
                "Deep Agents model identifiers must not contain ':'; "
                "use an untagged provider model identifier"
            )
        for label, value in (("provider", provider), ("model", model)):
            if not isinstance(value, str) or DEEPAGENTS_IDENTITY_PATTERN.fullmatch(value) is None:
                raise ValueError(f"invalid Deep Agents {label}")
        if provider not in SUPPORTED_DEEPAGENTS_PROVIDERS:
            raise ValueError(
                "unsupported Deep Agents provider; use " + ", ".join(SUPPORTED_DEEPAGENTS_PROVIDERS)
            )
        if not 1 <= max_turns <= 20:
            raise ValueError("Deep Agents max turns must be between one and twenty")
        resolved_python = shutil.which(runtime_python)
        if resolved_python is None:
            raise ValueError("Deep Agents runtime Python is not executable")
        self.provider = provider
        self.model = model
        self.runtime_python = str(Path(resolved_python).absolute())
        self.max_turns = max_turns

    def has_candidate(self, attempt: int) -> bool:
        return 1 <= attempt <= MAX_SEMANTIC_ATTEMPTS

    def create_candidate(
        self,
        *,
        attempt: int,
        workspace: Path,
        deadline: float,
        request: dict[str, Any] | None = None,
    ) -> Candidate:
        if not isinstance(request, dict) or set(request) != {"artifact_dir", "packet"}:
            raise FlowError("Deep Agents candidate request context is missing")
        packet = request["packet"]
        if not isinstance(packet, dict) or packet.get("attempt") != attempt:
            raise PolicyDenied("Deep Agents request attempt does not match controller state")
        artifact_dir = Path(request["artifact_dir"]).resolve()
        workspace = workspace.resolve()
        if not artifact_dir.is_dir() or artifact_dir not in workspace.parents:
            raise PolicyDenied("Deep Agents workspace is outside its artifact directory")

        request_path = artifact_dir / f"attempt-{attempt}-deepagents-request.json"
        execution_path = artifact_dir / f"attempt-{attempt}-deepagents-execution.json"
        patch_path = artifact_dir / f"attempt-{attempt}-deepagents.patch"
        worker_root = workspace.parent / "deepagents-worker"
        sandbox_workspace = worker_root / "workspace"
        git_repository = worker_root / "baseline-repository"
        home_dir = worker_root / "home"
        worker_result_path = worker_root / "result.json"
        if worker_root.exists():
            raise PolicyDenied("Deep Agents worker directory already exists")
        validate_deepagents_workspace(workspace)
        worker_root.mkdir(parents=True)
        home_dir.mkdir(mode=0o700)
        shutil.copytree(
            workspace,
            sandbox_workspace,
            symlinks=True,
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo"),
        )
        validate_deepagents_workspace(sandbox_workspace)
        write_json(request_path, packet)
        git_dir = initialize_shadow_git(sandbox_workspace, git_repository, deadline)
        invocation_id = uuid.uuid4().hex
        model_spec = f"{self.provider}:{self.model}"
        invocation = [
            self.runtime_python,
            "-I",
            str(DEEPAGENTS_WORKER),
            "--workspace",
            str(sandbox_workspace),
            "--request",
            str(request_path),
            "--result",
            str(worker_result_path),
            "--model",
            model_spec,
            "--invocation-id",
            invocation_id,
            "--max-turns",
            str(self.max_turns),
        ]
        environment = deepagents_process_environment(
            home_dir=home_dir,
            provider=self.provider,
        )
        started = time.monotonic()
        completed: subprocess.CompletedProcess[str] | None = None
        worker_result: dict[str, Any] | None = None
        execution: dict[str, Any] = {
            "schema_version": 1,
            "kind": "deepagents-candidate-execution",
            "attempt": attempt,
            "invocation_id": invocation_id,
            "provider": self.provider,
            "model": self.model,
            "model_spec_sha256": hashlib.sha256(model_spec.encode()).hexdigest(),
            "runtime_version": DEEPAGENTS_SDK_VERSION,
            "worker_sha256": hashlib.sha256(DEEPAGENTS_WORKER.read_bytes()).hexdigest(),
            "allowed_filesystem_tools": list(DEEPAGENTS_ALLOWED_FILESYSTEM_TOOLS),
            "memory_enabled": False,
            "checkpointer_enabled": False,
            "store_enabled": False,
            "subagents_enabled": False,
            "shell_enabled": False,
            "langsmith_tracing_enabled": False,
            "profile_plugins_enabled": False,
            "fresh_session": True,
            "controller_is_sole_acceptor": True,
            "outcome": "RUNNING",
        }
        try:
            completed = run_deepagents_process(
                invocation,
                cwd=PACKAGE_ROOT,
                environment=environment,
                timeout=min(MAX_DEEPAGENTS_ATTEMPT_SECONDS, remaining_seconds(deadline)),
            )
            if completed.returncode != 0:
                raise FlowError(
                    "Deep Agents candidate invocation failed: "
                    f"{redact_text(completed.stderr)[-1000:]}"
                )
            try:
                worker_result = read_json(worker_result_path)
            except (OSError, UnicodeError, json.JSONDecodeError) as exc:
                raise FlowError(
                    f"Deep Agents worker result is invalid: {type(exc).__name__}"
                ) from exc
            expected_worker_fields = {
                "schema_version",
                "runtime",
                "runtime_version",
                "provider_package",
                "provider_package_version",
                "profile_plugins_enabled",
                "outcome",
                "invocation_id",
                "tool_names",
                "final_response_bytes",
                "final_response_sha256",
            }
            if not isinstance(worker_result, dict) or set(worker_result) != expected_worker_fields:
                raise PolicyDenied("Deep Agents worker result fields are invalid")
            if (
                worker_result["schema_version"] != 1
                or worker_result["runtime"] != "deepagents"
                or worker_result["runtime_version"] != DEEPAGENTS_SDK_VERSION
                or worker_result["provider_package"]
                != DEEPAGENTS_PROVIDER_PACKAGES[self.provider][0]
                or worker_result["provider_package_version"]
                != DEEPAGENTS_PROVIDER_PACKAGES[self.provider][1]
                or worker_result["profile_plugins_enabled"] is not False
                or worker_result["outcome"] != "completed"
                or worker_result["invocation_id"] != invocation_id
                or worker_result["tool_names"] != list(DEEPAGENTS_ALLOWED_FILESYSTEM_TOOLS)
                or not isinstance(worker_result["final_response_bytes"], int)
                or not 0 <= worker_result["final_response_bytes"] <= 32 * 1024
                or not isinstance(worker_result["final_response_sha256"], str)
                or re.fullmatch(r"[0-9a-f]{64}", worker_result["final_response_sha256"]) is None
            ):
                raise PolicyDenied("Deep Agents worker result did not satisfy the runtime contract")

            validate_deepagents_workspace(sandbox_workspace)
            removed_backups = remove_identical_editor_backups(
                sandbox_workspace,
                workspace,
            )
            remove_candidate_caches(sandbox_workspace)
            validate_deepagents_workspace(sandbox_workspace)
            patch_payload = shadow_git_diff(sandbox_workspace, git_dir, deadline)
            validate_deepagents_patch_bytes(patch_payload)
            patch_path.write_bytes(patch_payload)
            applied = apply_candidate(workspace, patch_path, deadline)
            record = {
                "schema_version": CANDIDATE_CONTRACT_VERSION,
                "source": self.source,
                "attempt": attempt,
                "patch": applied["patch"],
                "patch_sha256": hashlib.sha256(patch_payload).hexdigest(),
                "changed_paths": applied["changed_paths"],
                "candidate_digest": applied["candidate_digest"],
            }
            candidate = Candidate(record, patch_path)
            execution["outcome"] = "CANDIDATE_RETURNED"
            execution["worker_result"] = worker_result
            execution["patch_sha256"] = record["patch_sha256"]
            execution["candidate_digest"] = record["candidate_digest"]
            execution["discarded_identical_editor_backups"] = removed_backups
            return candidate
        except Exception as exc:
            execution["outcome"] = "FAILED"
            execution["failure"] = redact_text(f"{type(exc).__name__}: {exc}")
            if isinstance(exc, subprocess.TimeoutExpired):
                timeout_stdout = exc.output or ""
                timeout_stderr = exc.stderr or ""
                if isinstance(timeout_stdout, bytes):
                    timeout_stdout = timeout_stdout.decode("utf-8", "replace")
                if isinstance(timeout_stderr, bytes):
                    timeout_stderr = timeout_stderr.decode("utf-8", "replace")
                execution["stdout_tail"] = redact_text(timeout_stdout)[-4000:]
                execution["stderr_tail"] = redact_text(timeout_stderr)[-4000:]
            raise
        finally:
            shutil.rmtree(worker_root, ignore_errors=True)
            cleanup = {
                "worker_directory_removed": not worker_root.exists(),
                "complete": not worker_root.exists(),
            }
            cleanup_failure = not cleanup["complete"] and sys.exc_info()[0] is None
            if cleanup_failure:
                execution["outcome"] = "FAILED"
                execution["failure"] = "FlowError: Deep Agents worker cleanup did not complete"
            execution["elapsed_seconds"] = round(time.monotonic() - started, 3)
            execution["cleanup"] = cleanup
            if completed is not None:
                execution["returncode"] = completed.returncode
                execution["stdout_tail"] = redact_text(completed.stdout)[-4000:]
                execution["stderr_tail"] = redact_text(completed.stderr)[-4000:]
            write_json(execution_path, redact(execution))
            if cleanup_failure:
                raise FlowError("Deep Agents worker cleanup did not complete")


def _candidate_test_bind_mount(source: Path, destination: str) -> str:
    resolved = source.resolve(strict=True)
    serialized = str(resolved)
    if any(character in serialized for character in (",", "\n", "\r", "\x00")):
        raise PolicyDenied("candidate test bind source contains an unsupported character")
    return f"type=bind,src={serialized},dst={destination},readonly"


def candidate_container_identity(
    run_id: str,
    attempt: int,
    phase: str,
) -> tuple[str, str]:
    """Derive a candidate-container name and ownership label from controller state."""
    if RUN_ID_PATTERN.fullmatch(run_id) is None:
        raise PolicyDenied("candidate container run ID is invalid")
    if not 1 <= attempt <= MAX_SEMANTIC_ATTEMPTS:
        raise PolicyDenied("candidate container attempt is invalid")
    if phase not in CANDIDATE_CONTAINER_PHASES:
        raise PolicyDenied("candidate container phase is invalid")
    nonce = run_id.rsplit("-", 1)[1]
    sandbox_id = hashlib.sha256(
        (
            f"candidate-container-v{CANDIDATE_CONTAINER_INTENT_VERSION}:"
            f"{run_id}:{attempt}:{phase}:{CANDIDATE_TEST_IMAGE}"
        ).encode("utf-8")
    ).hexdigest()
    return f"daiw-candidate-test-{nonce}-a{attempt}-{phase}", sandbox_id


def candidate_container_intent(
    run_dir: Path,
    run_id: str,
    attempt: int,
    phase: str,
) -> tuple[dict[str, Any], Path]:
    """Create the exact recovery record written before a candidate container starts."""
    if run_dir.name != run_id:
        raise PolicyDenied("candidate container run directory does not match its run ID")
    container_name, sandbox_id = candidate_container_identity(run_id, attempt, phase)
    cidfile_name = f"attempt-{attempt}-{phase}-candidate-container.cid"
    return (
        {
            "schema_version": CANDIDATE_CONTAINER_INTENT_VERSION,
            "kind": "candidate-container-cleanup-intent",
            "run_id": run_id,
            "attempt": attempt,
            "phase": phase,
            "container_name": container_name,
            "ownership_label": CANDIDATE_TEST_LABEL,
            "sandbox_id": sandbox_id,
            "cidfile": cidfile_name,
            "image": CANDIDATE_TEST_IMAGE,
        },
        run_dir / cidfile_name,
    )


def validate_candidate_container_intent(
    value: Any,
    *,
    run_dir: Path,
    run_id: str,
    attempt: int,
    phase: str,
) -> tuple[dict[str, Any], Path]:
    """Validate recovery data without allowing artifacts to select a target."""
    expected, cidfile = candidate_container_intent(run_dir, run_id, attempt, phase)
    if not isinstance(value, dict) or set(value) != set(expected):
        raise PolicyDenied("candidate container cleanup intent fields are invalid")
    if value != expected:
        raise PolicyDenied("candidate container cleanup intent does not match controller state")
    if cidfile.is_symlink():
        raise PolicyDenied("candidate container cidfile must not be a symlink")
    if cidfile.exists() and not stat.S_ISREG(cidfile.stat().st_mode):
        raise PolicyDenied("candidate container cidfile must be a regular file")
    return expected, cidfile


def _candidate_test_container_argv(
    workspace: Path,
    test_argv: list[str],
    *,
    sandbox_id: str,
    container_name: str,
    cidfile: Path,
    verifier: Path | None = None,
) -> list[str]:
    """Build the fixed Docker boundary used for every candidate-code test."""
    workspace = workspace.resolve(strict=True)
    if not workspace.is_dir():
        raise PolicyDenied("candidate test workspace is not a directory")
    invocation = [
        "docker",
        "run",
        "--rm",
        "--pull=never",
        f"--name={container_name}",
        f"--label={CANDIDATE_TEST_LABEL}={sandbox_id}",
        f"--cidfile={cidfile}",
        "--init",
        "--stop-timeout=1",
        "--network=none",
        "--read-only",
        "--user=65534:65534",
        "--tmpfs=/tmp:rw,noexec,nosuid,nodev,size=32m,uid=65534,gid=65534,mode=1777",
        "--cap-drop=ALL",
        "--security-opt=no-new-privileges:true",
        "--pids-limit=64",
        "--memory=128m",
        "--memory-swap=128m",
        "--cpus=0.5",
        f"--mount={_candidate_test_bind_mount(workspace, '/workspace')}",
    ]
    if verifier is not None:
        verifier = verifier.resolve(strict=True)
        if not verifier.is_file():
            raise PolicyDenied("controller verifier is not a file")
        candidate_probe = CANDIDATE_PROBE_PATH.resolve(strict=True)
        if not candidate_probe.is_file():
            raise PolicyDenied("trusted candidate probe is not a file")
        invocation.append(
            f"--mount={_candidate_test_bind_mount(verifier, '/verifier/controller.py')}"
        )
        invocation.append(
            f"--mount={_candidate_test_bind_mount(candidate_probe, '/verifier/candidate_probe.py')}"
        )
    return [
        *invocation,
        "--workdir=/workspace",
        "--entrypoint=/usr/bin/env",
        CANDIDATE_TEST_IMAGE,
        "-i",
        *CANDIDATE_TEST_ENVIRONMENT,
        *test_argv,
    ]


def _docker_reference_absent(result: subprocess.CompletedProcess[str]) -> bool:
    output = result.stdout.lower()
    return result.returncode != 0 and ("no such object" in output or "no such container" in output)


def _cleanup_candidate_test_container(
    cidfile: Path,
    *,
    container_name: str,
    sandbox_id: str,
) -> dict[str, Any]:
    """Remove only the container created for this candidate-test invocation."""
    container_reference = container_name
    cidfile_present = cidfile.is_file()
    if cidfile_present:
        try:
            candidate_id = cidfile.read_text(encoding="utf-8").strip()
        except OSError as exc:
            return {
                "complete": False,
                "removed": False,
                "reason": f"candidate test cidfile could not be read: {type(exc).__name__}",
            }
        if re.fullmatch(r"[0-9a-f]{64}", candidate_id) is None:
            return {
                "complete": False,
                "removed": False,
                "reason": "candidate test cidfile was invalid",
            }
        container_reference = candidate_id

    inspect_format = (
        f"{{{{.Id}}}}|{{{{.Name}}}}|{{{{.Config.Image}}}}|"
        f'{{{{index .Config.Labels "{CANDIDATE_TEST_LABEL}"}}}}'
    )
    try:
        inspected = command(
            ["docker", "inspect", f"--format={inspect_format}", container_reference],
            cwd=PACKAGE_ROOT,
            timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {
            "complete": False,
            "removed": False,
            "reason": f"candidate test container inspection failed: {type(exc).__name__}",
        }
    if _docker_reference_absent(inspected):
        return {
            "complete": True,
            "removed": False,
            "container_id": container_reference[:12] if cidfile_present else None,
        }
    if inspected.returncode != 0:
        return {
            "complete": False,
            "removed": False,
            "reason": "candidate test container absence could not be confirmed",
        }

    inspection_parts = inspected.stdout.strip().split("|", 3)
    if (
        len(inspection_parts) != 4
        or re.fullmatch(r"[0-9a-f]{64}", inspection_parts[0]) is None
        or inspection_parts[1] != f"/{container_name}"
        or inspection_parts[2] != CANDIDATE_TEST_IMAGE
        or inspection_parts[3] != sandbox_id
    ):
        return {
            "complete": False,
            "removed": False,
            "reason": "candidate test container ownership identity did not match",
        }
    candidate_id = inspection_parts[0]
    try:
        removed = command(
            ["docker", "rm", "--force", candidate_id],
            cwd=PACKAGE_ROOT,
            timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {
            "complete": False,
            "removed": False,
            "container_id": candidate_id[:12],
            "reason": f"candidate test container removal failed: {type(exc).__name__}",
        }
    if removed.returncode == 0 or _docker_reference_absent(removed):
        return {
            "complete": True,
            "removed": removed.returncode == 0,
            "container_id": candidate_id[:12],
        }
    return {
        "complete": False,
        "removed": False,
        "container_id": candidate_id[:12],
        "reason": "candidate test container removal did not complete",
    }


def candidate_container_intent_records(
    run_dir: Path,
    run_id: str,
    attempts: int,
) -> list[tuple[dict[str, Any], Path]]:
    """Load all candidate-container intents after strict controller validation."""
    records: list[tuple[dict[str, Any], Path]] = []
    pattern = re.compile(
        r"attempt-([1-5])-(attempt-unit|attempt-verifier|"
        r"independent-unit|independent-verifier)-candidate-container-intent\.json"
    )
    for intent_path in sorted(run_dir.glob("attempt-*-candidate-container-intent.json")):
        if intent_path.is_symlink() or not intent_path.is_file():
            raise PolicyDenied("candidate container cleanup intent must be a regular file")
        match = pattern.fullmatch(intent_path.name)
        if match is None:
            raise PolicyDenied("candidate container cleanup intent name is invalid")
        attempt = int(match.group(1))
        phase = match.group(2)
        if attempt > attempts:
            raise PolicyDenied("candidate container cleanup intent exceeds controller state")
        try:
            value = read_json(intent_path)
        except (OSError, json.JSONDecodeError) as exc:
            raise PolicyDenied("candidate container cleanup intent is malformed") from exc
        records.append(
            validate_candidate_container_intent(
                value,
                run_dir=run_dir,
                run_id=run_id,
                attempt=attempt,
                phase=phase,
            )
        )
    return records


def cleanup_candidate_test_containers(
    run_dir: Path,
    run_id: str,
    attempts: int,
) -> dict[str, Any]:
    """Freshly inspect and remove every controller-journaled test container."""
    try:
        records = candidate_container_intent_records(run_dir, run_id, attempts)
    except PolicyDenied as exc:
        return {"complete": False, "results": [], "reason": str(exc)}
    if records and not shutil.which("docker"):
        return {
            "complete": False,
            "results": [],
            "reason": "Docker is unavailable for candidate container cleanup",
        }
    results = [
        {
            "phase": intent["phase"],
            **_cleanup_candidate_test_container(
                cidfile,
                container_name=intent["container_name"],
                sandbox_id=intent["sandbox_id"],
            ),
        }
        for intent, cidfile in records
    ]
    return {
        "complete": all(result.get("complete") is True for result in results),
        "results": results,
    }


def _run_candidate_test_container(
    workspace: Path,
    test_argv: list[str],
    deadline: float,
    *,
    run_dir: Path,
    run_id: str,
    attempt: int,
    phase: str,
    verifier: Path | None = None,
) -> tuple[subprocess.CompletedProcess[str], dict[str, Any]]:
    intent, cidfile = candidate_container_intent(run_dir, run_id, attempt, phase)
    intent_path = run_dir / f"attempt-{attempt}-{phase}-candidate-container-intent.json"
    if intent_path.exists() or intent_path.is_symlink() or cidfile.exists() or cidfile.is_symlink():
        raise PolicyDenied("candidate container recovery artifact already exists")
    write_json(intent_path, intent)
    try:
        result = command(
            _candidate_test_container_argv(
                workspace,
                test_argv,
                sandbox_id=intent["sandbox_id"],
                container_name=intent["container_name"],
                cidfile=cidfile,
                verifier=verifier,
            ),
            cwd=PACKAGE_ROOT,
            timeout=min(60, remaining_seconds(deadline)),
        )
    finally:
        cleanup = _cleanup_candidate_test_container(
            cidfile,
            container_name=intent["container_name"],
            sandbox_id=intent["sandbox_id"],
        )
        if not cleanup["complete"]:
            raise FlowError("candidate test container cleanup did not complete")
    return result, cleanup


def unit_test(
    workspace: Path,
    deadline: float,
    *,
    run_dir: Path,
    run_id: str,
    attempt: int,
    phase: str,
) -> dict[str, Any]:
    test_argv = list(DEEPAGENTS_REQUIRED_TEST_ARGV)
    if test_argv[0] in {"python", "python3"}:
        test_argv[0] = "python"
    result, cleanup = _run_candidate_test_container(
        workspace,
        test_argv,
        deadline,
        run_dir=run_dir,
        run_id=run_id,
        attempt=attempt,
        phase=f"{phase}-unit",
    )
    return {
        "command": DEEPAGENTS_REQUIRED_TEST,
        "exit_code": result.returncode,
        "passed": result.returncode == 0,
        "output": redact_text(result.stdout)[-8000:],
        "cleanup": cleanup,
    }


def controller_test(
    workspace: Path,
    verifier: Path | None,
    deadline: float,
    *,
    run_dir: Path,
    run_id: str,
    attempt: int,
    phase: str,
    fixture_digest: str,
    patch_sha256: str,
) -> dict[str, Any]:
    if not isinstance(run_id, str) or not run_id or len(run_id) > 128:
        raise PolicyDenied("verifier run ID is invalid")
    if not isinstance(attempt, int) or not 1 <= attempt <= MAX_SEMANTIC_ATTEMPTS:
        raise PolicyDenied("verifier attempt is invalid")
    if phase not in {"attempt", "independent"}:
        raise PolicyDenied("verifier phase is invalid")
    if not _is_sha256(fixture_digest) or not _is_sha256(patch_sha256):
        raise PolicyDenied("verifier input digest is invalid")
    if verifier is None:
        return {
            "command": "controller-owned verifier",
            "exit_code": 1,
            "process_exit_code": None,
            "passed": False,
            "trusted_verifier_completed": False,
            "receipt": None,
            "output": "required controller-owned verifier is missing",
            "cleanup": {"complete": True, "removed": False},
        }
    verifier_sha256 = verifier_bundle_digest(verifier)
    candidate_digest = tree_digest(workspace)
    receipt_nonce = secrets.token_hex(32)
    result, cleanup = _run_candidate_test_container(
        workspace,
        list(VERIFIER_COMMAND),
        deadline,
        run_dir=run_dir,
        run_id=run_id,
        attempt=attempt,
        phase=f"{phase}-verifier",
        verifier=verifier,
    )
    output = redact_text(result.stdout)[-8000:]
    output_lines = [line.strip() for line in output.splitlines() if line.strip()]
    trusted_completed = (
        result.returncode == 0
        and output_lines.count(TRUSTED_VERIFIER_COMPLETION) == 1
        and output_lines[-1] == TRUSTED_VERIFIER_COMPLETION
    )
    receipt = (
        {
            "schema_version": VERIFIER_RECEIPT_VERSION,
            "status": "completed",
            "nonce": receipt_nonce,
            "run_id": run_id,
            "attempt": attempt,
            "phase": phase,
            "candidate_digest": candidate_digest,
            "patch_sha256": patch_sha256,
            "fixture_digest": fixture_digest,
            "policy_sha256": WORKFLOW_POLICY_SHA256,
            "verifier_bundle_sha256": verifier_sha256,
            "verifier_command_sha256": VERIFIER_COMMAND_SHA256,
            "candidate_test_image": CANDIDATE_TEST_IMAGE,
            "terminal": {
                "process_exit_code": 0,
                "signaled": False,
                "timed_out": False,
                "completion_marker_count": 1,
            },
        }
        if trusted_completed
        else None
    )
    return {
        "command": f"python {verifier.relative_to(PACKAGE_ROOT)} --repository <workspace>",
        "exit_code": (
            result.returncode if result.returncode != 0 else (0 if trusted_completed else 1)
        ),
        "process_exit_code": result.returncode,
        "passed": trusted_completed,
        "trusted_verifier_completed": trusted_completed,
        "receipt": receipt,
        "output": output,
        "cleanup": cleanup,
    }


def compose_project_name(run_id: str, attempt: int) -> str:
    """Derive the only Compose project name the controller may manage."""
    if not isinstance(run_id, str) or RUN_ID_PATTERN.fullmatch(run_id) is None:
        raise PolicyDenied("controller run ID is invalid for Compose ownership")
    if not isinstance(attempt, int) or not 1 <= attempt <= MAX_SEMANTIC_ATTEMPTS:
        raise PolicyDenied("controller attempt is invalid for Compose ownership")
    nonce = run_id.rsplit("-", 1)[1]
    return f"daiw{nonce}a{attempt}"


def compose_cleanup_intent(
    run_id: str,
    attempt: int,
    scenario_name: str,
    scenario: dict[str, Any],
) -> dict[str, Any]:
    """Bind recovery cleanup to controller-owned inputs before Compose starts."""
    if not isinstance(scenario_name, str) or not scenario_name:
        raise PolicyDenied("Compose cleanup intent scenario is invalid")
    project = compose_project_name(run_id, attempt)
    compose_file, _, _ = compose_context(
        scenario,
        scenario_repository(scenario),
        project,
    )
    return {
        "schema_version": COMPOSE_CLEANUP_INTENT_VERSION,
        "kind": "compose-cleanup-intent",
        "run_id": run_id,
        "attempt": attempt,
        "project": project,
        "scenario": scenario_name,
        "compose_file": str(compose_file.relative_to(PACKAGE_ROOT)),
        "compose_file_sha256": hashlib.sha256(compose_file.read_bytes()).hexdigest(),
    }


def validate_compose_cleanup_intent(
    value: Any,
    *,
    run_id: str,
    attempt: int,
    scenario_name: str,
    scenario: dict[str, Any],
) -> dict[str, Any]:
    """Validate an intent entirely against current controller-owned state."""
    expected = compose_cleanup_intent(run_id, attempt, scenario_name, scenario)
    if not isinstance(value, dict) or set(value) != set(expected):
        raise PolicyDenied("Compose cleanup intent fields are invalid")
    if value != expected:
        raise PolicyDenied("Compose cleanup intent does not match controller state")
    return expected


def validate_cleanup_run_identity(run_dir: Path, control: dict[str, Any]) -> str:
    run_id = control.get("run_id")
    if not isinstance(run_id, str) or RUN_ID_PATTERN.fullmatch(run_id) is None:
        raise PolicyDenied("cleanup requires a valid controller-issued run ID")
    if run_dir.name != run_id:
        raise PolicyDenied("cleanup run directory does not match its controller run ID")
    return run_id


def _compose_resource_inventory(project: str, compose_file: Path) -> dict[str, Any]:
    """List and validate resources before a destructive Compose operation."""
    expected_file = compose_file.resolve()
    expected_root = PACKAGE_ROOT.resolve()
    specifications = (
        (
            "containers",
            [
                "docker",
                "ps",
                "--all",
                "--filter",
                f"label=com.docker.compose.project={project}",
                "--format",
                (
                    '{{.ID}}|{{.Names}}|{{.Label "com.docker.compose.project"}}|'
                    '{{.Label "com.docker.compose.project.config_files"}}|'
                    '{{.Label "com.docker.compose.project.working_dir"}}'
                ),
            ],
            5,
        ),
        (
            "networks",
            [
                "docker",
                "network",
                "ls",
                "--filter",
                f"label=com.docker.compose.project={project}",
                "--format",
                '{{.ID}}|{{.Name}}|{{.Label "com.docker.compose.project"}}',
            ],
            3,
        ),
        (
            "volumes",
            [
                "docker",
                "volume",
                "ls",
                "--filter",
                f"label=com.docker.compose.project={project}",
                "--format",
                '{{.Name}}|{{.Label "com.docker.compose.project"}}',
            ],
            2,
        ),
    )
    inventory: dict[str, list[dict[str, str]]] = {
        "containers": [],
        "networks": [],
        "volumes": [],
    }
    failures: list[str] = []
    for kind, args, field_count in specifications:
        try:
            result = command(args, cwd=PACKAGE_ROOT, timeout=20)
        except (OSError, subprocess.TimeoutExpired) as exc:
            failures.append(f"{kind} inventory failed: {type(exc).__name__}")
            continue
        if result.returncode != 0:
            failures.append(f"{kind} inventory command failed")
            continue
        for line in (item.strip() for item in result.stdout.splitlines() if item.strip()):
            fields = line.split("|")
            if len(fields) != field_count:
                failures.append(f"{kind} inventory was malformed")
                continue
            if kind == "containers":
                identifier, name, label, config_files, working_dir = fields
                try:
                    configured_paths = [
                        Path(item).resolve() for item in config_files.split(",") if item
                    ]
                    config_matches = configured_paths == [expected_file]
                    root_matches = Path(working_dir).resolve() == expected_root
                except (OSError, RuntimeError):
                    config_matches = False
                    root_matches = False
                if (
                    label != project
                    or not name.startswith((f"{project}-", f"{project}_"))
                    or not config_matches
                    or not root_matches
                ):
                    failures.append("container Compose ownership/config identity did not match")
                inventory[kind].append({"id": identifier[:12], "name": name})
            elif kind == "networks":
                identifier, name, label = fields
                if label != project or not name.startswith((f"{project}-", f"{project}_")):
                    failures.append("network Compose ownership did not match")
                inventory[kind].append({"id": identifier[:12], "name": name})
            else:
                name, label = fields
                if label != project or not name.startswith((f"{project}-", f"{project}_")):
                    failures.append("volume Compose ownership did not match")
                inventory[kind].append({"name": name})
    return {
        "verified": not failures,
        "failures": sorted(set(failures)),
        "resources": inventory,
        "resource_count": sum(len(items) for items in inventory.values()),
    }


def compose_context(
    scenario: dict[str, Any],
    workspace: Path,
    project: str,
) -> tuple[Path, str, dict[str, str]]:
    compose_file_value = scenario.get("compose_file")
    if not isinstance(compose_file_value, str) or not compose_file_value:
        raise PolicyDenied("scenario does not define a Compose verifier")
    compose_file = scoped_package_path(compose_file_value)
    if not compose_file.is_file():
        raise PolicyDenied("scenario Compose file does not exist")
    service = str(scenario.get("compose_service", "smoke"))
    if re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_.-]{0,63}", service) is None:
        raise PolicyDenied("scenario Compose service is invalid")
    environment_kind = scenario.get("compose_environment", "default")
    local_passwords = {
        "DAIW_POSTGRES_PASSWORD": hashlib.sha256(
            f"{project}:postgres:local-only".encode("utf-8")
        ).hexdigest(),
        "DAIW_EVIDENCE_READER_PASSWORD": hashlib.sha256(
            f"{project}:evidence-reader:local-only".encode("utf-8")
        ).hexdigest(),
        "DAIW_INCIDENT_APP_PASSWORD": hashlib.sha256(
            f"{project}:incident-app:local-only".encode("utf-8")
        ).hexdigest(),
    }
    if environment_kind == "incident":
        environment = {
            "DAIW_INCIDENT_CANDIDATE": str(workspace),
            "DAIW_INCIDENT_PROJECT_NAME": project,
            **local_passwords,
        }
    elif environment_kind == "default":
        environment = {
            "DAIW_WORKSPACE": str(workspace),
            "DAIW_POSTGRES_PASSWORD": local_passwords["DAIW_POSTGRES_PASSWORD"],
        }
    else:
        raise PolicyDenied("scenario Compose environment is unsupported")
    return compose_file, service, environment


def compose_test(
    workspace: Path,
    project: str,
    deadline: float,
    scenario: dict[str, Any] | None = None,
) -> dict[str, Any]:
    selected = scenario or {}
    compose_file, service, compose_environment = compose_context(
        selected,
        workspace,
        project,
    )
    result = command(
        [
            "docker",
            "compose",
            "-f",
            str(compose_file),
            "-p",
            project,
            "up",
            "--build",
            "--pull",
            "never",
            "--abort-on-container-exit",
            "--exit-code-from",
            service,
            "--attach",
            service,
        ],
        cwd=PACKAGE_ROOT,
        timeout=min(600, remaining_seconds(deadline)),
        extra_env=compose_environment,
    )
    return {
        "command": (
            "docker compose up --build --pull never --abort-on-container-exit "
            f"--exit-code-from {service} --attach {service}"
        ),
        "exit_code": result.returncode,
        "passed": result.returncode == 0,
        "output": redact_text(result.stdout)[-12000:],
        "compose_project": project,
        "compose_file": compose_file.name,
        "compose_service": service,
        "authority": "veto-only",
    }


def compose_cleanup(
    run_id: str,
    attempt: int,
    workspace: Path | None = None,
    scenario: dict[str, Any] | None = None,
) -> dict[str, Any]:
    project = compose_project_name(run_id, attempt)
    selected = scenario or {}
    compose_file, _, compose_environment = compose_context(
        selected,
        workspace or FIXTURES / "repository",
        project,
    )
    before = _compose_resource_inventory(project, compose_file)
    if not before["verified"]:
        return {
            "project": project,
            "compose_file": compose_file.name,
            "exit_code": 1,
            "complete": False,
            "ownership_verified": False,
            "resources_before": before,
            "output": "Compose ownership verification failed; cleanup was not attempted",
        }
    if before["resource_count"] == 0:
        return {
            "project": project,
            "compose_file": compose_file.name,
            "exit_code": 0,
            "complete": True,
            "ownership_verified": True,
            "removed": False,
            "resources_before": before,
            "resources_after": before,
            "output": "No owned Compose resources were present",
        }
    result = command(
        [
            "docker",
            "compose",
            "-f",
            str(compose_file),
            "-p",
            project,
            "down",
            "--volumes",
            "--remove-orphans",
            "--timeout",
            "10",
        ],
        cwd=PACKAGE_ROOT,
        timeout=60,
        extra_env=compose_environment,
    )
    after = _compose_resource_inventory(project, compose_file)
    complete = result.returncode == 0 and after["verified"] and after["resource_count"] == 0
    return {
        "project": project,
        "compose_file": compose_file.name,
        "exit_code": 0 if complete else (result.returncode or 1),
        "complete": complete,
        "ownership_verified": True,
        "removed": complete,
        "resources_before": before,
        "resources_after": after,
        "output": redact_text(result.stdout)[-2000:],
    }


def scenario_test(
    run_dir: Path,
    workspace: Path,
    scenario: dict[str, Any],
    project: str,
    deadline: float,
    *,
    with_docker: bool,
    run_id: str,
    attempt: int,
    patch_sha256: str,
) -> dict[str, Any]:
    fixture_digest = tree_digest(scenario_repository(scenario))
    checks: list[dict[str, Any]] = [
        unit_test(
            workspace,
            deadline,
            run_dir=run_dir,
            run_id=run_id,
            attempt=attempt,
            phase="attempt",
        )
    ]
    checks.append(
        controller_test(
            workspace,
            scenario_controller_verifier(scenario),
            deadline,
            run_dir=run_dir,
            run_id=run_id,
            attempt=attempt,
            phase="attempt",
            fixture_digest=fixture_digest,
            patch_sha256=patch_sha256,
        )
    )
    if with_docker and all(check["passed"] for check in checks):
        checks.append(compose_test(workspace, project, deadline, scenario))
    passed = all(check["passed"] for check in checks)
    return {
        "command": " && ".join(check["command"] for check in checks),
        "exit_code": 0
        if passed
        else next(check["exit_code"] for check in checks if not check["passed"]),
        "passed": passed,
        "output": "\n\n".join(check["output"] for check in checks)[-20000:],
        "checks": checks,
        **(
            {"compose_project": project}
            if any("compose_project" in check for check in checks)
            else {}
        ),
    }


def independent_verify(
    run_dir: Path,
    patch_path: Path,
    expected_digest: str,
    deadline: float,
    *,
    run_id: str,
    attempt: int,
    repository: Path | None = None,
    verifier: Path | None = None,
) -> dict[str, Any]:
    source_repository = (repository or FIXTURES / "repository").resolve(strict=True)
    fixture_digest = tree_digest(source_repository)
    patch_sha256 = hashlib.sha256(patch_path.read_bytes()).hexdigest()
    workspace = create_workspace(
        run_dir,
        "independent-verifier",
        source_repository,
    )
    try:
        candidate = apply_candidate(workspace, patch_path, deadline)
        checks: list[dict[str, Any]] = [
            unit_test(
                workspace,
                deadline,
                run_dir=run_dir,
                run_id=run_id,
                attempt=attempt,
                phase="independent",
            )
        ]
        checks.append(
            controller_test(
                workspace,
                verifier,
                deadline,
                run_dir=run_dir,
                run_id=run_id,
                attempt=attempt,
                phase="independent",
                fixture_digest=fixture_digest,
                patch_sha256=patch_sha256,
            )
        )
        passed = all(check["passed"] for check in checks)
        test_result = {
            "command": " && ".join(check["command"] for check in checks),
            "exit_code": 0
            if passed
            else next(check["exit_code"] for check in checks if not check["passed"]),
            "passed": passed,
            "output": "\n\n".join(check["output"] for check in checks)[-16000:],
            "checks": checks,
        }
        accepted = passed and candidate["candidate_digest"] == expected_digest
        return {
            "accepted": accepted,
            "candidate_digest": candidate["candidate_digest"],
            "tested_digest": expected_digest,
            "test": test_result,
        }
    finally:
        shutil.rmtree(workspace.parent, ignore_errors=True)
        if workspace.parent.exists():
            raise FlowError("independent verifier workspace cleanup did not complete")


def candidate_patch_artifact_issues(
    run_dir: Path,
    candidate: dict[str, Any],
    attempt: int,
) -> list[str]:
    issues: list[str] = []
    suffix = "deepagents" if candidate.get("source") == "deepagents-real-model" else "fixture"
    expected_name = f"attempt-{attempt}-{suffix}.patch"
    if candidate.get("patch") != expected_name:
        return ["candidate patch artifact name is invalid"]
    patch_path = run_dir / expected_name
    if not patch_path.is_file() or patch_path.is_symlink():
        return ["candidate patch artifact is missing or irregular"]
    try:
        payload = patch_path.read_bytes()
        digest = hashlib.sha256(payload).hexdigest()
        _text, paths = validate_deepagents_patch_bytes(payload)
    except (OSError, PolicyDenied):
        return ["candidate patch artifact is invalid"]
    if candidate.get("patch_sha256") != digest:
        issues.append("candidate patch artifact digest does not match")
    if candidate.get("changed_paths") != paths:
        issues.append("candidate patch artifact paths do not match")
    return issues


def delivery_eligibility_issues(
    run_dir: Path,
    control: dict[str, Any],
    candidate: dict[str, Any],
    test_result: dict[str, Any],
    verification: dict[str, Any],
    scenario: dict[str, Any],
) -> tuple[list[str], list[dict[str, Any]]]:
    issues: list[str] = []
    attempt = control.get("attempts")
    if isinstance(attempt, int):
        issues.extend(candidate_patch_artifact_issues(run_dir, candidate, attempt))
    else:
        issues.append("delivery candidate attempt is invalid")
    verifier = scenario_controller_verifier(scenario)
    if verifier is None:
        return ["delivery has no trusted verifier"], []
    fixture_digest = tree_digest(scenario_repository(scenario))
    verifier_sha256 = verifier_bundle_digest(verifier)
    common = {
        "run_id": str(control.get("run_id", "")),
        "attempt": int(control.get("attempts", 0)),
        "candidate_digest": str(candidate.get("candidate_digest", "")),
        "patch_sha256": str(candidate.get("patch_sha256", "")),
        "fixture_digest": fixture_digest,
        "verifier_sha256": verifier_sha256,
    }
    attempt_receipt = _trusted_verifier_receipt(
        test_result,
        phase="attempt",
        **common,
    )
    independent_receipt = _trusted_verifier_receipt(
        verification.get("test"),
        phase="independent",
        **common,
    )
    if attempt_receipt is None:
        issues.append("delivery lacks a valid attempt verifier receipt")
    if independent_receipt is None:
        issues.append("delivery lacks a valid independent verifier receipt")
    if (
        attempt_receipt is not None
        and independent_receipt is not None
        and attempt_receipt["nonce"] == independent_receipt["nonce"]
    ):
        issues.append("delivery verifier receipt nonce was replayed")
    expected_digest = candidate.get("candidate_digest")
    if (
        verification.get("accepted") is not True
        or verification.get("candidate_digest") != expected_digest
        or verification.get("tested_digest") != expected_digest
    ):
        issues.append("delivery candidate was not independently verified")
    if control.get("pre_delivery_cleanup_complete") is not True:
        issues.append("delivery cleanup prerequisite is incomplete")
    receipts = [
        receipt for receipt in (attempt_receipt, independent_receipt) if receipt is not None
    ]
    return sorted(set(issues)), receipts


def mock_publish(
    run_dir: Path,
    control: dict[str, Any],
    candidate: dict[str, Any],
    test_result: dict[str, Any],
    verification: dict[str, Any],
    scenario: dict[str, Any],
) -> None:
    issues, receipts = delivery_eligibility_issues(
        run_dir,
        control,
        candidate,
        test_result,
        verification,
        scenario,
    )
    if issues:
        raise PolicyDenied("draft delivery is ineligible: " + "; ".join(issues))
    payload = {
        "kind": "mock_github_delivery",
        "repository": control["repository"],
        "base": control["base_revision"],
        "head": f"deepagents/{control['issue_id'].lower()}-{control['run_id'][-8:]}",
        "draft": True,
        "candidate_digest": candidate["candidate_digest"],
        "verifier_receipt_sha256": [
            hashlib.sha256(
                json.dumps(receipt, sort_keys=True, separators=(",", ":")).encode("utf-8")
            ).hexdigest()
            for receipt in receipts
        ],
        "operations": ["create_branch", "create_commit", "create_pull_request"],
        "forbidden_operations_exposed": [],
    }
    write_json(run_dir / "mock-github.json", payload)


def mock_notify(run_dir: Path, control: dict[str, Any]) -> None:
    target = run_dir / "mock-slack.json"
    payload = {
        "kind": "mock_slack_delivery",
        "run_id": control["run_id"],
        "issue_id": control.get("issue_id"),
        "outcome": control["outcome"],
        "attempts": control["attempts"],
        "message": (
            "Local Deep Agents incident workflow ended with "
            f"{control['outcome']} after {control['attempts']} attempt(s)."
        ),
    }
    write_json(target, redact(payload))


def remove_workspaces(run_dir: Path) -> dict[str, Any]:
    removed: list[str] = []
    failures: list[str] = []
    for workspace in sorted(run_dir.glob("attempt-*/workspace")):
        parent = workspace.parent.resolve()
        if run_dir.resolve() not in parent.parents:
            failures.append("refused cleanup outside the run directory")
            continue
        try:
            shutil.rmtree(parent)
        except OSError as exc:
            failures.append(f"{parent.name}: {type(exc).__name__}")
        if parent.exists():
            failures.append(f"{parent.name}: still present")
        else:
            removed.append(parent.name)
    verifier = run_dir / "independent-verifier"
    if verifier.exists():
        try:
            shutil.rmtree(verifier)
        except OSError as exc:
            failures.append(f"{verifier.name}: {type(exc).__name__}")
        if verifier.exists():
            failures.append(f"{verifier.name}: still present")
        else:
            removed.append(verifier.name)
    return {
        "complete": not failures,
        "removed": sorted(set(removed)),
        "failures": sorted(set(failures)),
    }


def cleanup_resources(
    run_dir: Path,
    compose_records: list[dict[str, Any]],
) -> dict[str, Any]:
    try:
        control = read_json(run_dir / "control.json")
        run_id = validate_cleanup_run_identity(run_dir, control)
        attempts = control.get("attempts")
        if not isinstance(attempts, int) or not 0 <= attempts <= MAX_SEMANTIC_ATTEMPTS:
            raise PolicyDenied("candidate container cleanup attempt state is invalid")
    except (OSError, json.JSONDecodeError, PolicyDenied, TypeError) as exc:
        return {
            "cleanup_complete": False,
            "workspace_cleanup": {"complete": False, "removed": [], "failures": []},
            "compose_cleanup": [],
            "candidate_container_cleanup": {
                "complete": False,
                "results": [],
                "reason": f"cleanup identity validation failed: {type(exc).__name__}",
            },
            "deepagents_cleanup_complete": False,
        }
    candidate_container_cleanup = cleanup_candidate_test_containers(
        run_dir,
        run_id,
        attempts,
    )
    compose_cleanup_results: list[dict[str, Any]] = []
    scenarios = read_json(FIXTURES / "scenarios.json")
    for record in compose_records:
        if not shutil.which("docker"):
            compose_cleanup_results.append(
                {
                    "project": record.get("project"),
                    "exit_code": 1,
                    "output": "Docker is unavailable for required cleanup",
                }
            )
            continue
        scenario = scenarios.get(record.get("scenario"), {})
        try:
            cleanup = compose_cleanup(
                record["run_id"],
                record["attempt"],
                scenario_repository(scenario),
                scenario,
            )
        except Exception as exc:
            cleanup = {
                "project": record.get("project"),
                "exit_code": 1,
                "output": f"cleanup failed: {type(exc).__name__}",
            }
        record["cleanup"] = cleanup
        compose_cleanup_results.append(cleanup)
    workspace_cleanup = remove_workspaces(run_dir)
    deepagents_cleanup_ok = True
    try:
        deepagents_execution_records = [
            read_json(path) for path in sorted(run_dir.glob("attempt-*-deepagents-execution.json"))
        ]
        deepagents_cleanup_ok = all(
            record.get("cleanup", {}).get("complete") is True
            for record in deepagents_execution_records
        )
    except (OSError, json.JSONDecodeError, TypeError):
        deepagents_cleanup_ok = False
    cleanup_ok = (
        all(
            item.get("exit_code") == 0
            and item.get("complete") is True
            and item.get("ownership_verified") is True
            for item in compose_cleanup_results
        )
        and workspace_cleanup["complete"]
        and candidate_container_cleanup["complete"]
        and deepagents_cleanup_ok
    )
    return {
        "cleanup_complete": cleanup_ok,
        "workspace_cleanup": workspace_cleanup,
        "compose_cleanup": compose_cleanup_results,
        "candidate_container_cleanup": candidate_container_cleanup,
        "deepagents_cleanup_complete": deepagents_cleanup_ok,
    }


def closeout(
    run_dir: Path, control: dict[str, Any], compose_records: list[dict[str, Any]]
) -> dict[str, Any]:
    cleanup = cleanup_resources(run_dir, compose_records)
    cleanup_ok = cleanup["cleanup_complete"]
    closeout_record = {
        "at": utc_now(),
        "cleanup_complete": cleanup_ok,
        **cleanup,
        "retained": [
            "control.json",
            "events.jsonl",
            "evidence.json when collected",
            "attempt result packets",
            "Deep Agents request, execution, and exact patch evidence when used",
            "verification.json on success",
            "mock delivery payloads",
        ],
    }
    if not cleanup_ok or control.get("outcome") != "SUCCEEDED":
        delivery = run_dir / "mock-github.json"
        try:
            delivery.unlink(missing_ok=True)
        except OSError:
            pass
        closeout_record["draft_delivery_absent"] = not delivery.exists()
    write_json(run_dir / "closeout.json", closeout_record)
    control["cleanup_complete"] = cleanup_ok
    if not cleanup_ok:
        control["outcome"] = "CLEANUP_FAILED"
        control["failure_reason"] = "cleanup postconditions did not complete"
    control["state"] = "CLOSED" if cleanup_ok else "CLEANUP_FAILED"
    write_json(run_dir / "control.json", control)
    append_event(run_dir, control["state"], cleanup_complete=cleanup_ok)
    return closeout_record


def run_flow(
    scenario_name: str,
    *,
    with_docker: bool = False,
    budget_seconds: float = MAX_REMEDIATION_SECONDS,
    max_attempts: int = MAX_SEMANTIC_ATTEMPTS,
    artifact_root: Path = ARTIFACTS,
    candidate_provider: CandidateProvider | None = None,
) -> tuple[Path, dict[str, Any]]:
    if not 0 < budget_seconds <= MAX_REMEDIATION_SECONDS:
        raise ValueError("budget must be greater than zero and at most 1500 seconds")
    if not 1 <= max_attempts <= MAX_SEMANTIC_ATTEMPTS:
        raise ValueError("max attempts must be between one and five")
    scenarios = read_json(FIXTURES / "scenarios.json")
    if scenario_name not in scenarios:
        raise ValueError(f"unknown scenario: {scenario_name}")
    scenario = scenarios[scenario_name]
    incident = read_json(FIXTURES / scenario["incident"])
    repository = scenario_repository(scenario)
    evidence_path = scenario_evidence_path(scenario)
    diagnosis = scenario_diagnosis(scenario)
    execution_plan = scenario_execution_plan(scenario)
    verifier = scenario_controller_verifier(scenario)
    provider = candidate_provider
    if provider is None:
        provider = FixtureCandidateProvider(
            [FIXTURES / item for item in scenario["patches"]],
            repeat_last_patch=scenario["repeat_last_patch"],
        )
    provider_source = getattr(provider, "source", None)
    if not isinstance(provider_source, str) or not provider_source:
        raise ValueError("candidate provider source must be a non-empty string")
    run_id = f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex}"
    run_dir = artifact_root / run_id
    run_dir.mkdir(parents=True)
    deadline = time.monotonic() + budget_seconds
    control: dict[str, Any] = {
        "schema_version": 1,
        "run_id": run_id,
        "scenario": scenario_name,
        "state": "RECEIVED",
        "outcome": "RUNNING",
        "issue_id": incident.get("issue_id"),
        "repository": incident.get("repository"),
        "base_revision": incident.get("base_revision"),
        "idempotency_key": hashlib.sha256(
            f"{incident.get('issue_id')}:{incident.get('base_revision')}".encode()
        ).hexdigest(),
        "started_at": utc_now(),
        "budget_seconds": budget_seconds,
        "max_attempts": max_attempts,
        "attempts": 0,
        "candidate_digest": None,
        "failure_reason": None,
        "cleanup_complete": False,
        "pre_delivery_cleanup_complete": False,
        "candidate_source": provider_source,
    }
    write_json(run_dir / "control.json", control)
    append_event(run_dir, "RECEIVED", scenario=scenario_name)
    compose_records: list[dict[str, Any]] = []

    try:
        validate_incident(incident)
        remaining_seconds(deadline)
        control["state"] = "VALIDATED"
        write_json(run_dir / "control.json", control)
        append_event(run_dir, "VALIDATED", idempotency_key=control["idempotency_key"])

        if scenario.get("simulate_delay_seconds"):
            time.sleep(float(scenario["simulate_delay_seconds"]))
            remaining_seconds(deadline)

        evidence = collect_evidence(incident, evidence_path)
        remaining_seconds(deadline)
        write_json(run_dir / "evidence.json", evidence)
        control["state"] = "COLLECTING_EVIDENCE"
        write_json(run_dir / "control.json", control)
        append_event(
            run_dir,
            "EVIDENCE_COLLECTED",
            log_count=len(evidence["logs"]),
            row_count=len(evidence["database"]["rows"]),
        )

        accepted_candidate: dict[str, Any] | None = None
        accepted_test_result: dict[str, Any] | None = None
        accepted_verification: dict[str, Any] | None = None
        controller_feedback: list[dict[str, Any]] = []
        for attempt in range(1, max_attempts + 1):
            remaining_seconds(deadline)
            if not provider.has_candidate(attempt):
                break
            control["attempts"] = attempt
            control["state"] = "PATCHING"
            write_json(run_dir / "control.json", control)
            append_event(run_dir, "PATCHING", attempt=attempt, candidate_source=provider_source)

            workspace = create_workspace(
                run_dir,
                f"attempt-{attempt}",
                repository,
            )
            candidate_packet = build_deepagents_request(
                run_id=run_id,
                attempt=attempt,
                incident=incident,
                evidence=evidence,
                feedback=controller_feedback,
                deadline=deadline,
                diagnosis=diagnosis,
                execution_plan=execution_plan,
            )
            provided_candidate = provider.create_candidate(
                attempt=attempt,
                workspace=workspace,
                deadline=deadline,
                request={"artifact_dir": run_dir, "packet": candidate_packet},
            )
            if not isinstance(provided_candidate, Candidate):
                raise PolicyDenied("candidate provider returned an unsupported object")
            provided_candidate = retain_candidate_patch(run_dir, provided_candidate)
            candidate = provided_candidate.record
            validate_candidate_contract(candidate)
            validate_scenario_candidate_paths(scenario, candidate["changed_paths"])
            if candidate["source"] != provider_source:
                raise PolicyDenied("candidate source does not match its provider")
            if candidate["attempt"] != attempt:
                raise PolicyDenied("candidate attempt does not match controller state")
            write_json(run_dir / f"attempt-{attempt}-candidate.json", candidate)
            control["state"] = "TESTING"
            write_json(run_dir / "control.json", control)
            append_event(
                run_dir, "TESTING", attempt=attempt, candidate_digest=candidate["candidate_digest"]
            )

            project = compose_project_name(run_id, attempt)
            if with_docker:
                intent = compose_cleanup_intent(
                    run_id,
                    attempt,
                    scenario_name,
                    scenario,
                )
                write_json(
                    run_dir / f"attempt-{attempt}-compose-intent.json",
                    intent,
                )
                compose_records.append(
                    {
                        "run_id": run_id,
                        "attempt": attempt,
                        "project": project,
                        "workspace": str(workspace),
                        "scenario": scenario_name,
                    }
                )
            test_result = scenario_test(
                run_dir,
                workspace,
                scenario,
                project,
                deadline,
                with_docker=with_docker,
                run_id=run_id,
                attempt=attempt,
                patch_sha256=candidate["patch_sha256"],
            )
            if with_docker:
                compose_result = compose_cleanup(run_id, attempt, workspace, scenario)
                compose_records[-1]["cleanup"] = compose_result
                if compose_result["exit_code"] != 0:
                    raise FlowError("disposable service cleanup did not complete")
            result_packet = {
                "run_id": run_id,
                "attempt": attempt,
                "candidate_digest": candidate["candidate_digest"],
                "test": test_result,
            }
            write_json(run_dir / f"attempt-{attempt}-result.json", result_packet)
            append_event(
                run_dir,
                "TEST_RESULT",
                attempt=attempt,
                passed=test_result["passed"],
                candidate_digest=candidate["candidate_digest"],
            )

            if test_result["passed"]:
                verification = independent_verify(
                    run_dir,
                    provided_candidate.patch_path,
                    candidate["candidate_digest"],
                    deadline,
                    run_id=run_id,
                    attempt=attempt,
                    repository=repository,
                    verifier=verifier,
                )
                write_json(run_dir / "verification.json", verification)
                if verification["accepted"]:
                    control["candidate_digest"] = candidate["candidate_digest"]
                    pre_delivery_cleanup = cleanup_resources(run_dir, compose_records)
                    write_json(
                        run_dir / "pre-delivery-cleanup.json",
                        pre_delivery_cleanup,
                    )
                    control["pre_delivery_cleanup_complete"] = pre_delivery_cleanup[
                        "cleanup_complete"
                    ]
                    write_json(run_dir / "control.json", control)
                    if not pre_delivery_cleanup["cleanup_complete"]:
                        raise FlowError("pre-delivery cleanup did not complete")
                    eligibility_issues, _receipts = delivery_eligibility_issues(
                        run_dir,
                        control,
                        candidate,
                        test_result,
                        verification,
                        scenario,
                    )
                    if eligibility_issues:
                        raise PolicyDenied(
                            "trusted delivery eligibility failed: " + "; ".join(eligibility_issues)
                        )
                    accepted_candidate = candidate
                    accepted_test_result = test_result
                    accepted_verification = verification
                    break
                controller_feedback.append(
                    {
                        "attempt": attempt,
                        "stage": "independent_verification",
                        "candidate_digest": candidate["candidate_digest"],
                        "command": verification["test"]["command"],
                        "exit_code": verification["test"]["exit_code"],
                        "passed": False,
                        "reason": "independent verifier rejected the exact candidate digest",
                        "output": verification["test"]["output"],
                    }
                )
            else:
                controller_feedback.append(
                    {
                        "attempt": attempt,
                        "stage": "controller_test",
                        "candidate_digest": candidate["candidate_digest"],
                        "command": test_result["command"],
                        "exit_code": test_result["exit_code"],
                        "passed": False,
                        "reason": "required controller test failed",
                        "output": test_result["output"],
                    }
                )
            attempt_cleanup = remove_workspaces(run_dir)
            if not attempt_cleanup["complete"]:
                raise FlowError("attempt workspace cleanup did not complete")

        if accepted_candidate:
            if accepted_test_result is None or accepted_verification is None:
                raise FlowError("accepted candidate is missing verification evidence")
            control["state"] = "READY_TO_PUBLISH"
            control["outcome"] = "SUCCEEDED"
            control["candidate_digest"] = accepted_candidate["candidate_digest"]
            write_json(run_dir / "control.json", control)
            append_event(
                run_dir, "READY_TO_PUBLISH", candidate_digest=accepted_candidate["candidate_digest"]
            )
            mock_publish(
                run_dir,
                control,
                accepted_candidate,
                accepted_test_result,
                accepted_verification,
                scenario,
            )
            append_event(
                run_dir,
                "MOCK_PUBLISHED",
                operations=["create_branch", "create_commit", "create_pull_request"],
            )
        else:
            control["state"] = "FAILED"
            control["outcome"] = "FAILED"
            control["failure_reason"] = "semantic attempts exhausted or no candidate remained"
            write_json(run_dir / "control.json", control)
            append_event(run_dir, "FAILED", reason=control["failure_reason"])

    except PolicyDenied as exc:
        control["state"] = "REJECTED"
        control["outcome"] = "REJECTED"
        control["failure_reason"] = redact_text(str(exc))
        write_json(run_dir / "control.json", control)
        append_event(run_dir, "REJECTED", reason=redact_text(str(exc)))
    except (DeadlineExpired, subprocess.TimeoutExpired) as exc:
        control["state"] = "TIMED_OUT"
        control["outcome"] = "TIMED_OUT"
        control["failure_reason"] = redact_text(str(exc))
        write_json(run_dir / "control.json", control)
        append_event(run_dir, "TIMED_OUT", reason=redact_text(str(exc)))
    except Exception as exc:
        control["state"] = "FAILED"
        control["outcome"] = "FAILED"
        control["failure_reason"] = redact_text(
            f"infrastructure error: {type(exc).__name__}: {exc}"
        )
        write_json(run_dir / "control.json", control)
        append_event(run_dir, "FAILED", reason=control["failure_reason"])
    finally:
        closeout(run_dir, control, compose_records)
        mock_notify(run_dir, control)
        append_event(run_dir, "MOCK_NOTIFIED", outcome=control["outcome"])

    expected = scenario["expected_outcome"]
    if control["outcome"] != expected:
        raise FlowError(
            f"scenario expected {expected}, got {control['outcome']}: {control['failure_reason']}"
        )
    return run_dir, control


def latest_run(artifact_root: Path = ARTIFACTS) -> Path:
    candidates = (
        [
            item
            for item in artifact_root.iterdir()
            if item.is_dir() and (item / "control.json").is_file()
        ]
        if artifact_root.exists()
        else []
    )
    if not candidates:
        raise FlowError("no local runs found")
    return max(candidates, key=lambda item: item.stat().st_mtime_ns)


def verify_deepagents_real_model_artifacts(
    run_dir: Path,
    control: dict[str, Any],
) -> list[str]:
    """Verify the accepted real-model candidate as one linked evidence chain."""
    issues: list[str] = []
    if control.get("outcome") != "SUCCEEDED":
        return issues
    attempt = control.get("attempts")
    if not isinstance(attempt, int) or attempt < 1:
        return ["Deep Agents accepted attempt is invalid"]

    def artifact_object(path: Path, label: str) -> dict[str, Any] | None:
        if not path.is_file() or path.is_symlink():
            issues.append(f"missing or irregular Deep Agents {label} artifact")
            return None
        try:
            value = read_json(path)
        except (OSError, UnicodeError, json.JSONDecodeError):
            issues.append(f"Deep Agents {label} artifact is not valid JSON")
            return None
        if not isinstance(value, dict):
            issues.append(f"Deep Agents {label} artifact must be an object")
            return None
        return value

    stem = f"attempt-{attempt}"
    candidate = artifact_object(run_dir / f"{stem}-candidate.json", "candidate")
    execution = artifact_object(
        run_dir / f"{stem}-deepagents-execution.json",
        "execution",
    )
    result = artifact_object(run_dir / f"{stem}-result.json", "result")
    verification = artifact_object(run_dir / "verification.json", "verification")
    if candidate is None:
        return sorted(set(issues))

    try:
        validate_candidate_contract(candidate)
    except PolicyDenied:
        issues.append("Deep Agents candidate contract is invalid")
    if candidate.get("source") != "deepagents-real-model":
        issues.append("Deep Agents candidate source is invalid")
    if candidate.get("attempt") != attempt:
        issues.append("Deep Agents candidate attempt does not match accepted attempt")

    expected_patch_name = f"{stem}-deepagents.patch"
    if candidate.get("patch") != expected_patch_name:
        issues.append("Deep Agents candidate patch does not match accepted attempt")
        patch_path = None
    else:
        patch_path = run_dir / expected_patch_name

    patch_sha256: str | None = None
    patch_paths: list[str] | None = None
    if patch_path is None or not patch_path.is_file() or patch_path.is_symlink():
        issues.append("missing or irregular accepted Deep Agents patch")
    else:
        try:
            patch_payload = patch_path.read_bytes()
            patch_sha256 = hashlib.sha256(patch_payload).hexdigest()
            _, patch_paths = validate_deepagents_patch_bytes(patch_payload)
        except (OSError, PolicyDenied):
            issues.append("accepted Deep Agents patch is invalid")
    if patch_sha256 is not None and candidate.get("patch_sha256") != patch_sha256:
        issues.append("Deep Agents patch SHA does not match candidate contract")
    if patch_paths is not None and candidate.get("changed_paths") != patch_paths:
        issues.append("Deep Agents patch paths do not match candidate contract")

    accepted_digest = candidate.get("candidate_digest")
    if accepted_digest != control.get("candidate_digest"):
        issues.append("Deep Agents candidate digest does not match control")

    if execution is not None:
        if execution.get("kind") != "deepagents-candidate-execution":
            issues.append("Deep Agents execution kind is invalid")
        if execution.get("attempt") != attempt:
            issues.append("Deep Agents execution attempt does not match accepted attempt")
        if execution.get("outcome") != "CANDIDATE_RETURNED":
            issues.append("Deep Agents execution did not return the accepted candidate")
        invocation_id = execution.get("invocation_id")
        if (
            not isinstance(invocation_id, str)
            or DEEPAGENTS_INVOCATION_PATTERN.fullmatch(invocation_id) is None
        ):
            issues.append("Deep Agents execution invocation ID is invalid")
        for field in ("provider", "model"):
            value = execution.get(field)
            if not isinstance(value, str) or DEEPAGENTS_IDENTITY_PATTERN.fullmatch(value) is None:
                issues.append(f"Deep Agents execution {field} is invalid")
        provider = execution.get("provider")
        model = execution.get("model")
        if provider not in SUPPORTED_DEEPAGENTS_PROVIDERS:
            issues.append("Deep Agents execution provider is unsupported")
        if isinstance(provider, str) and isinstance(model, str):
            expected_model_hash = hashlib.sha256(f"{provider}:{model}".encode()).hexdigest()
            if execution.get("model_spec_sha256") != expected_model_hash:
                issues.append("Deep Agents execution model specification digest is invalid")
        if execution.get("runtime_version") != DEEPAGENTS_SDK_VERSION:
            issues.append("Deep Agents execution runtime version is invalid")
        if (
            execution.get("worker_sha256")
            != hashlib.sha256(DEEPAGENTS_WORKER.read_bytes()).hexdigest()
        ):
            issues.append("Deep Agents execution worker digest is invalid")
        if execution.get("allowed_filesystem_tools") != list(DEEPAGENTS_ALLOWED_FILESYSTEM_TOOLS):
            issues.append("Deep Agents execution tool policy is invalid")
        for field in (
            "memory_enabled",
            "checkpointer_enabled",
            "store_enabled",
            "subagents_enabled",
            "shell_enabled",
            "langsmith_tracing_enabled",
            "profile_plugins_enabled",
        ):
            if execution.get(field) is not False:
                issues.append(f"Deep Agents execution {field} must be false")
        for field in ("fresh_session", "controller_is_sole_acceptor"):
            if execution.get(field) is not True:
                issues.append(f"Deep Agents execution {field} must be true")
        worker_result = execution.get("worker_result")
        expected_provider_package = DEEPAGENTS_PROVIDER_PACKAGES.get(provider)
        if (
            not isinstance(worker_result, dict)
            or worker_result.get("runtime") != "deepagents"
            or worker_result.get("runtime_version") != DEEPAGENTS_SDK_VERSION
            or expected_provider_package is None
            or worker_result.get("provider_package") != expected_provider_package[0]
            or worker_result.get("provider_package_version") != expected_provider_package[1]
            or worker_result.get("profile_plugins_enabled") is not False
            or worker_result.get("outcome") != "completed"
            or worker_result.get("invocation_id") != invocation_id
            or worker_result.get("tool_names") != list(DEEPAGENTS_ALLOWED_FILESYSTEM_TOOLS)
        ):
            issues.append("Deep Agents execution worker result is invalid")
        cleanup = execution.get("cleanup")
        if not isinstance(cleanup, dict) or cleanup.get("complete") is not True:
            issues.append("Deep Agents execution cleanup did not complete")
        if execution.get("patch_sha256") != candidate.get("patch_sha256"):
            issues.append("Deep Agents execution patch SHA does not match candidate")
        if execution.get("candidate_digest") != accepted_digest:
            issues.append("Deep Agents execution digest does not match candidate")

    if result is not None:
        if result.get("attempt") != attempt:
            issues.append("Deep Agents result attempt does not match accepted attempt")
        if result.get("candidate_digest") != accepted_digest:
            issues.append("Deep Agents result digest does not match candidate")
        result_test = result.get("test")
        if not isinstance(result_test, dict) or result_test.get("passed") is not True:
            issues.append("Deep Agents accepted attempt did not pass controller tests")

    if verification is not None:
        if verification.get("accepted") is not True:
            issues.append("Deep Agents independent verification did not accept candidate")
        if verification.get("candidate_digest") != accepted_digest:
            issues.append("Deep Agents verification digest does not match candidate")
        if verification.get("tested_digest") != accepted_digest:
            issues.append("Deep Agents verification tested digest does not match candidate")
        verification_test = verification.get("test")
        if not isinstance(verification_test, dict) or verification_test.get("passed") is not True:
            issues.append("Deep Agents independent verification tests did not pass")
    return sorted(set(issues))


def _trusted_verifier_receipt(
    value: Any,
    *,
    run_id: str,
    attempt: int,
    phase: str,
    candidate_digest: str,
    patch_sha256: str,
    fixture_digest: str,
    verifier_sha256: str,
) -> dict[str, Any] | None:
    if not isinstance(value, dict) or value.get("passed") is not True:
        return None
    checks = value.get("checks")
    if not isinstance(checks, list):
        return None
    trusted = [
        check
        for check in checks
        if isinstance(check, dict) and "trusted_verifier_completed" in check
    ]
    if len(trusted) != 1:
        return None
    check = trusted[0]
    output = check.get("output")
    if not isinstance(output, str):
        return None
    lines = [line.strip() for line in output.splitlines() if line.strip()]
    if not (
        check.get("passed") is True
        and check.get("trusted_verifier_completed") is True
        and check.get("exit_code") == 0
        and check.get("process_exit_code") == 0
        and lines.count(TRUSTED_VERIFIER_COMPLETION) == 1
        and lines[-1] == TRUSTED_VERIFIER_COMPLETION
    ):
        return None
    receipt = check.get("receipt")
    receipt_fields = {
        "schema_version",
        "status",
        "nonce",
        "run_id",
        "attempt",
        "phase",
        "candidate_digest",
        "patch_sha256",
        "fixture_digest",
        "policy_sha256",
        "verifier_bundle_sha256",
        "verifier_command_sha256",
        "candidate_test_image",
        "terminal",
    }
    if not isinstance(receipt, dict) or set(receipt) != receipt_fields:
        return None
    expected = {
        "schema_version": VERIFIER_RECEIPT_VERSION,
        "status": "completed",
        "run_id": run_id,
        "attempt": attempt,
        "phase": phase,
        "candidate_digest": candidate_digest,
        "patch_sha256": patch_sha256,
        "fixture_digest": fixture_digest,
        "policy_sha256": WORKFLOW_POLICY_SHA256,
        "verifier_bundle_sha256": verifier_sha256,
        "verifier_command_sha256": VERIFIER_COMMAND_SHA256,
        "candidate_test_image": CANDIDATE_TEST_IMAGE,
        "terminal": {
            "process_exit_code": 0,
            "signaled": False,
            "timed_out": False,
            "completion_marker_count": 1,
        },
    }
    if any(receipt.get(field) != expected_value for field, expected_value in expected.items()):
        return None
    nonce = receipt.get("nonce")
    if not isinstance(nonce, str) or re.fullmatch(r"[0-9a-f]{64}", nonce) is None:
        return None
    return receipt


def verify_trusted_completion_artifacts(
    run_dir: Path,
    control: dict[str, Any],
) -> list[str]:
    """Require trusted verifier completion for every successful provider run."""
    issues: list[str] = []
    attempt = control.get("attempts")
    accepted_digest = control.get("candidate_digest")
    if not isinstance(attempt, int) or attempt < 1:
        return ["successful run has no accepted attempt"]
    if not isinstance(accepted_digest, str):
        return ["successful run has no accepted candidate digest"]
    scenarios = read_json(FIXTURES / "scenarios.json")
    scenario = scenarios.get(control.get("scenario"))
    if not isinstance(scenario, dict):
        return ["successful run has no valid scenario identity"]
    verifier = scenario_controller_verifier(scenario)
    if verifier is None:
        return ["successful run has no trusted verifier identity"]
    try:
        fixture_digest = tree_digest(scenario_repository(scenario))
        verifier_sha256 = verifier_bundle_digest(verifier)
    except (OSError, PolicyDenied):
        return ["successful run trusted inputs are unavailable"]

    paths = {
        "candidate": run_dir / f"attempt-{attempt}-candidate.json",
        "result": run_dir / f"attempt-{attempt}-result.json",
        "verification": run_dir / "verification.json",
    }
    records: dict[str, dict[str, Any]] = {}
    for label, path in paths.items():
        if not path.is_file():
            issues.append(f"successful run is missing {label} artifact")
            continue
        try:
            value = read_json(path)
        except (OSError, json.JSONDecodeError):
            issues.append(f"successful run has malformed {label} artifact")
            continue
        if not isinstance(value, dict):
            issues.append(f"successful run has invalid {label} artifact")
            continue
        records[label] = value

    candidate = records.get("candidate")
    if candidate is not None and candidate.get("candidate_digest") != accepted_digest:
        issues.append("accepted candidate artifact digest does not match control")
    patch_sha256 = candidate.get("patch_sha256") if candidate is not None else None
    if not _is_sha256(patch_sha256):
        issues.append("accepted candidate patch digest is invalid")

    result_receipt = None
    result = records.get("result")
    if result is not None:
        if result.get("attempt") != attempt:
            issues.append("accepted result attempt does not match control")
        if result.get("candidate_digest") != accepted_digest:
            issues.append("accepted result digest does not match control")
        result_receipt = _trusted_verifier_receipt(
            result.get("test"),
            run_id=str(control.get("run_id", "")),
            attempt=attempt,
            phase="attempt",
            candidate_digest=accepted_digest,
            patch_sha256=str(patch_sha256 or ""),
            fixture_digest=fixture_digest,
            verifier_sha256=verifier_sha256,
        )
        if result_receipt is None:
            issues.append("accepted result lacks trusted verifier completion")

    verification_receipt = None
    verification = records.get("verification")
    if verification is not None:
        if verification.get("accepted") is not True:
            issues.append("independent verification did not accept candidate")
        if verification.get("candidate_digest") != accepted_digest:
            issues.append("independent verification digest does not match control")
        if verification.get("tested_digest") != accepted_digest:
            issues.append("independent verification tested digest does not match control")
        verification_receipt = _trusted_verifier_receipt(
            verification.get("test"),
            run_id=str(control.get("run_id", "")),
            attempt=attempt,
            phase="independent",
            candidate_digest=accepted_digest,
            patch_sha256=str(patch_sha256 or ""),
            fixture_digest=fixture_digest,
            verifier_sha256=verifier_sha256,
        )
        if verification_receipt is None:
            issues.append("independent verification lacks trusted verifier completion")
    if (
        result_receipt is not None
        and verification_receipt is not None
        and result_receipt["nonce"] == verification_receipt["nonce"]
    ):
        issues.append("trusted verifier receipt nonce was replayed")
    return issues


def verify_run(run_dir: Path) -> list[str]:
    issues: list[str] = []
    control_path = run_dir / "control.json"
    if not control_path.exists():
        return ["missing control.json"]
    control = read_json(control_path)
    if control["attempts"] > MAX_SEMANTIC_ATTEMPTS:
        issues.append("attempt limit exceeded")
    github_path = run_dir / "mock-github.json"
    if control["outcome"] == "SUCCEEDED":
        issues.extend(verify_trusted_completion_artifacts(run_dir, control))
        attempt = control.get("attempts")
        if isinstance(attempt, int):
            candidate_path = run_dir / f"attempt-{attempt}-candidate.json"
            try:
                candidate = read_json(candidate_path)
            except (OSError, json.JSONDecodeError):
                candidate = None
            if isinstance(candidate, dict):
                issues.extend(candidate_patch_artifact_issues(run_dir, candidate, attempt))
            else:
                issues.append("successful run is missing its candidate patch linkage")
        pre_delivery_cleanup_path = run_dir / "pre-delivery-cleanup.json"
        if control.get("pre_delivery_cleanup_complete") is not True:
            issues.append("successful run lacks the cleanup eligibility prerequisite")
        if not pre_delivery_cleanup_path.is_file():
            issues.append("successful run is missing pre-delivery cleanup evidence")
        else:
            pre_delivery_cleanup = read_json(pre_delivery_cleanup_path)
            if pre_delivery_cleanup.get("cleanup_complete") is not True:
                issues.append("pre-delivery cleanup evidence is incomplete")
        if not github_path.exists():
            issues.append("successful run has no mock GitHub delivery")
        else:
            try:
                github = read_json(github_path)
                if not isinstance(github, dict):
                    raise TypeError("mock GitHub delivery is not an object")
                allowed = {"create_branch", "create_commit", "create_pull_request"}
                operations = github.get("operations")
                if not isinstance(operations, list) or set(operations) != allowed:
                    issues.append("mock GitHub operations differ from allowlist")
                if github.get("kind") != "mock_github_delivery":
                    issues.append("mock GitHub delivery kind is invalid")
                if github.get("repository") != control.get("repository"):
                    issues.append("mock GitHub repository does not match control state")
                if github.get("base") != control.get("base_revision"):
                    issues.append("mock GitHub base does not match control state")
                expected_head = f"deepagents/{control['issue_id'].lower()}-{control['run_id'][-8:]}"
                if github.get("head") != expected_head:
                    issues.append("mock GitHub head does not match control state")
                if github.get("draft") is not True:
                    issues.append("mock pull request is not a draft")
                if github.get("forbidden_operations_exposed") != []:
                    issues.append("mock delivery exposed a forbidden operation")
                if github.get("candidate_digest") != control.get("candidate_digest"):
                    issues.append("published digest does not match accepted digest")
                attempt = control["attempts"]
                result = read_json(run_dir / f"attempt-{attempt}-result.json")
                verification = read_json(run_dir / "verification.json")
                receipts = [
                    next(
                        check["receipt"]
                        for check in packet["test"]["checks"]
                        if check.get("trusted_verifier_completed") is True
                    )
                    for packet in (result, verification)
                ]
                receipt_hashes = [
                    hashlib.sha256(
                        json.dumps(
                            receipt,
                            sort_keys=True,
                            separators=(",", ":"),
                        ).encode("utf-8")
                    ).hexdigest()
                    for receipt in receipts
                ]
                if github.get("verifier_receipt_sha256") != receipt_hashes:
                    issues.append("draft delivery verifier receipt digests do not match")
            except (
                AttributeError,
                KeyError,
                StopIteration,
                OSError,
                json.JSONDecodeError,
                TypeError,
            ):
                issues.append("draft delivery verifier receipt linkage is invalid")
    elif github_path.exists():
        issues.append("non-successful run emitted a mock GitHub delivery")
    if control.get("candidate_source") == "deepagents-real-model":
        issues.extend(verify_deepagents_real_model_artifacts(run_dir, control))
    notification_path = run_dir / "mock-slack.json"
    if not notification_path.exists():
        issues.append("missing mock Slack delivery")
    else:
        try:
            notification = read_json(notification_path)
            expected_notification = {
                "kind": "mock_slack_delivery",
                "run_id": control["run_id"],
                "issue_id": control.get("issue_id"),
                "outcome": control["outcome"],
                "attempts": control["attempts"],
                "message": (
                    "Local Deep Agents incident workflow ended with "
                    f"{control['outcome']} after {control['attempts']} attempt(s)."
                ),
            }
            if notification != expected_notification:
                issues.append("mock Slack delivery does not match final control state")
        except (KeyError, OSError, json.JSONDecodeError, TypeError):
            issues.append("mock Slack delivery is invalid")
    closeout_path = run_dir / "closeout.json"
    if not closeout_path.exists() or not read_json(closeout_path)["cleanup_complete"]:
        issues.append("cleanup did not complete")
    if list(run_dir.glob("attempt-*/workspace")):
        issues.append("workspace remains after closeout")
    for path in run_dir.rglob("*"):
        if path.is_file():
            text = path.read_text(encoding="utf-8", errors="replace")
            for marker in RAW_SENSITIVE_MARKERS:
                if marker in text:
                    issues.append(f"sensitive marker retained in {path.relative_to(run_dir)}")
    return sorted(set(issues))


def cleanup_existing(run_dir: Path) -> dict[str, Any]:
    try:
        control = read_json(run_dir / "control.json")
        run_id = validate_cleanup_run_identity(run_dir, control)
    except (OSError, json.JSONDecodeError, PolicyDenied, TypeError) as exc:
        return {
            "cleanup_complete": False,
            "workspace_cleanup": {"complete": False, "removed": [], "failures": []},
            "compose_cleanup": [],
            "deepagents_cleanup_complete": False,
            "refused": True,
            "reason": f"cleanup identity validation failed: {type(exc).__name__}",
        }
    scenario_name = control.get("scenario")
    scenarios = read_json(FIXTURES / "scenarios.json")
    if not isinstance(scenario_name, str) or scenario_name not in scenarios:
        return {
            "cleanup_complete": False,
            "workspace_cleanup": {"complete": False, "removed": [], "failures": []},
            "compose_cleanup": [],
            "deepagents_cleanup_complete": False,
            "refused": True,
            "reason": "cleanup scenario state is invalid",
        }
    scenario = scenarios[scenario_name]
    attempts = control.get("attempts")
    if not isinstance(attempts, int) or not 0 <= attempts <= MAX_SEMANTIC_ATTEMPTS:
        return {
            "cleanup_complete": False,
            "workspace_cleanup": {"complete": False, "removed": [], "failures": []},
            "compose_cleanup": [],
            "deepagents_cleanup_complete": False,
            "refused": True,
            "reason": "cleanup attempt state is invalid",
        }
    try:
        candidate_container_intent_records(run_dir, run_id, attempts)
    except PolicyDenied as exc:
        return {
            "cleanup_complete": False,
            "workspace_cleanup": {"complete": False, "removed": [], "failures": []},
            "compose_cleanup": [],
            "candidate_container_cleanup": {"complete": False, "results": []},
            "deepagents_cleanup_complete": False,
            "refused": True,
            "reason": f"candidate container cleanup intent validation failed: {exc}",
        }
    records: list[dict[str, Any]] = []
    intents: dict[int, dict[str, Any]] = {}
    for intent_path in sorted(run_dir.glob("attempt-*-compose-intent.json")):
        match = re.fullmatch(r"attempt-([1-5])-compose-intent\.json", intent_path.name)
        if match is None:
            return {
                "cleanup_complete": False,
                "workspace_cleanup": {"complete": False, "removed": [], "failures": []},
                "compose_cleanup": [],
                "deepagents_cleanup_complete": False,
                "refused": True,
                "reason": "cleanup intent artifact name is invalid",
            }
        attempt = int(match.group(1))
        if attempt > attempts:
            return {
                "cleanup_complete": False,
                "workspace_cleanup": {"complete": False, "removed": [], "failures": []},
                "compose_cleanup": [],
                "deepagents_cleanup_complete": False,
                "refused": True,
                "reason": "cleanup intent attempt exceeds controller state",
            }
        try:
            intent = validate_compose_cleanup_intent(
                read_json(intent_path),
                run_id=run_id,
                attempt=attempt,
                scenario_name=scenario_name,
                scenario=scenario,
            )
        except (OSError, json.JSONDecodeError, PolicyDenied, TypeError) as exc:
            return {
                "cleanup_complete": False,
                "workspace_cleanup": {"complete": False, "removed": [], "failures": []},
                "compose_cleanup": [],
                "deepagents_cleanup_complete": False,
                "refused": True,
                "reason": f"cleanup intent validation failed: {type(exc).__name__}",
            }
        intents[attempt] = intent
        records.append(
            {
                "run_id": run_id,
                "attempt": attempt,
                "project": intent["project"],
                "workspace": str(FIXTURES / "repository"),
                "scenario": scenario_name,
            }
        )
    for result_path in sorted(run_dir.glob("attempt-*-result.json")):
        match = re.fullmatch(r"attempt-([1-5])-result\.json", result_path.name)
        if match is None:
            return {
                "cleanup_complete": False,
                "workspace_cleanup": {"complete": False, "removed": [], "failures": []},
                "compose_cleanup": [],
                "deepagents_cleanup_complete": False,
                "refused": True,
                "reason": "cleanup result artifact name is invalid",
            }
        attempt = int(match.group(1))
        if attempt > attempts:
            return {
                "cleanup_complete": False,
                "workspace_cleanup": {"complete": False, "removed": [], "failures": []},
                "compose_cleanup": [],
                "deepagents_cleanup_complete": False,
                "refused": True,
                "reason": "cleanup result attempt exceeds controller state",
            }
        try:
            result = read_json(result_path)
        except (OSError, json.JSONDecodeError):
            return {
                "cleanup_complete": False,
                "workspace_cleanup": {"complete": False, "removed": [], "failures": []},
                "compose_cleanup": [],
                "deepagents_cleanup_complete": False,
                "refused": True,
                "reason": "cleanup result artifact is malformed",
            }
        project = result.get("test", {}).get("compose_project")
        if project:
            expected_project = compose_project_name(run_id, attempt)
            if project != expected_project:
                return {
                    "cleanup_complete": False,
                    "workspace_cleanup": {"complete": False, "removed": [], "failures": []},
                    "compose_cleanup": [],
                    "deepagents_cleanup_complete": False,
                    "refused": True,
                    "reason": "cleanup Compose project does not match controller derivation",
                }
            if attempt not in intents:
                return {
                    "cleanup_complete": False,
                    "workspace_cleanup": {"complete": False, "removed": [], "failures": []},
                    "compose_cleanup": [],
                    "deepagents_cleanup_complete": False,
                    "refused": True,
                    "reason": "cleanup result is missing its controller intent",
                }
    cleanup = closeout(run_dir, control, records)
    mock_notify(run_dir, control)
    return cleanup


def preflight(
    with_docker: bool,
    require_deepagents: bool = False,
    deepagents_python: str = sys.executable,
) -> dict[str, Any]:
    problems = []
    if Path.cwd().resolve() != PACKAGE_ROOT:
        problems.append("run from the package root through scripts/run-local.sh")
    sensitive = sensitive_environment_names()
    if sensitive:
        problems.append(f"sensitive environment names are present: {', '.join(sensitive)}")
    for binary in ("git", "python3"):
        if not shutil.which(binary):
            problems.append(f"missing required command: {binary}")
    deepagents_version = "unavailable"
    runtime_python = shutil.which(deepagents_python)
    if require_deepagents and runtime_python is None:
        problems.append("Deep Agents runtime Python is not executable")
    elif runtime_python is not None:
        result = command(
            [
                runtime_python,
                "-c",
                "from importlib.metadata import version; print(version('deepagents'))",
            ],
            cwd=PACKAGE_ROOT,
            timeout=20,
        )
        if result.returncode == 0:
            deepagents_version = result.stdout.strip()
        elif require_deepagents:
            problems.append("Deep Agents SDK is not installed in the selected runtime")
        if require_deepagents and deepagents_version != DEEPAGENTS_SDK_VERSION:
            problems.append(
                f"Deep Agents SDK {DEEPAGENTS_SDK_VERSION} is required; found {deepagents_version}"
            )
    docker_status = "not requested"
    if with_docker:
        if not shutil.which("docker"):
            problems.append("missing required command: docker")
        else:
            result = command(
                ["docker", "info", "--format", "{{.ServerVersion}}|{{.Architecture}}"],
                cwd=PACKAGE_ROOT,
                timeout=20,
            )
            docker_status = result.stdout.strip()
            if result.returncode != 0:
                problems.append("Docker daemon is not ready")
            scenarios = read_json(FIXTURES / "scenarios.json")
            for scenario_name, scenario in sorted(scenarios.items()):
                if "compose_file" not in scenario:
                    continue
                repository = scenario_repository(scenario)
                compose_file, _, compose_environment = compose_context(
                    scenario,
                    repository,
                    f"daiw-preflight-{scenario_name}",
                )
                config = command(
                    [
                        "docker",
                        "compose",
                        "-f",
                        str(compose_file),
                        "config",
                        "--quiet",
                    ],
                    cwd=PACKAGE_ROOT,
                    timeout=30,
                    extra_env=compose_environment,
                )
                if config.returncode != 0:
                    problems.append(
                        f"Compose configuration is invalid for {scenario_name}: "
                        f"{config.stdout[-1000:]}"
                    )
    return {
        "ok": not problems,
        "package_root": str(PACKAGE_ROOT),
        "deepagents": deepagents_version,
        "docker": docker_status,
        "sensitive_environment_names": sensitive,
        "problems": problems,
    }


def qualified_deepagents_runtime(value: str) -> str:
    """Require real-model CLI runs to use the rebuilt repository-local runtime."""
    candidate = Path(value)
    if not candidate.is_absolute():
        candidate = PACKAGE_ROOT / candidate
    candidate = Path(os.path.abspath(candidate))
    expected = PACKAGE_ROOT / ".deepagents-runtime" / "bin" / "python"
    runtime_root = PACKAGE_ROOT / ".deepagents-runtime"
    if runtime_root.is_symlink() or candidate != expected or not candidate.is_file():
        raise ValueError(
            "real-model runs require .deepagents-runtime/bin/python from "
            "scripts/install-deepagents-runtime.sh"
        )
    return str(candidate)


def dump_policy() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "policy_source": str(WORKFLOW_POLICY_PATH),
        "package_root": str(PACKAGE_ROOT),
        "repository": {
            "id": EXPECTED_REPOSITORY,
            "allowed_services": list(ALLOWED_SERVICES),
            "allowed_environments": list(ALLOWED_ENVIRONMENTS),
            "allowed_patch_prefixes": list(ALLOWED_PATCH_PREFIXES),
        },
        "evidence": {
            "maximum_window_minutes": MAX_EVIDENCE_WINDOW_MINUTES,
            "maximum_log_records": MAX_LOG_RECORDS,
            "maximum_database_rows": MAX_DATABASE_ROWS,
            "allowed_database_views": list(ALLOWED_DATABASE_VIEWS),
            "connector_policy": "bounded-redacted-broker-output-only",
        },
        "validation": {
            "required_test_argv": list(DEEPAGENTS_REQUIRED_TEST_ARGV),
            "required_test": DEEPAGENTS_REQUIRED_TEST,
            "candidate_code_execution": "network-disabled-pinned-docker-sandbox",
            "clean_reapply_required": True,
        },
        "deepagents": {
            "sdk_version": DEEPAGENTS_SDK_VERSION,
            "worker": DEEPAGENTS_WORKER.relative_to(PACKAGE_ROOT).as_posix(),
            "allowed_filesystem_tools": list(DEEPAGENTS_ALLOWED_FILESYSTEM_TOOLS),
            "maximum_attempt_seconds": int(MAX_DEEPAGENTS_ATTEMPT_SECONDS),
            "shell": False,
            "subagents": False,
            "memory": False,
            "checkpointer": False,
            "store": False,
            "langsmith_tracing": False,
            "proposal_authority": "reporting-only",
        },
        "limits": {
            "hard_maximum_attempts": MAX_SEMANTIC_ATTEMPTS,
            "hard_maximum_remediation_seconds": int(MAX_REMEDIATION_SECONDS),
            "maximum_patch_bytes": MAX_DEEPAGENTS_PATCH_BYTES,
            "maximum_changed_paths": MAX_DEEPAGENTS_CHANGED_PATHS,
        },
        "delivery": {
            "mode": "draft-artifacts-only",
            "merge": False,
            "deployment": False,
            "incident_state_mutation": False,
        },
        "safety_modes": {
            "current": "synthetic-draft",
            "available_pattern": [
                "synthetic",
                "dry-run",
                "shadow-readonly",
                "live-evidence-readonly",
                "draft-pr-only",
            ],
        },
        "authority_boundary": "ai-proposes-controller-decides",
    }


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description=__doc__)
    subcommands = root.add_subparsers(dest="command", required=True)

    preflight_parser = subcommands.add_parser("preflight")
    preflight_parser.add_argument("--with-docker", action="store_true")
    preflight_parser.add_argument("--require-deepagents", action="store_true")
    preflight_parser.add_argument("--deepagents-python", default=sys.executable)

    run_parser = subcommands.add_parser("run")
    run_parser.add_argument(
        "--scenario",
        choices=tuple(read_json(FIXTURES / "scenarios.json")),
        default="retry-success",
    )
    run_parser.add_argument("--with-docker", action="store_true")
    run_parser.add_argument("--budget-seconds", type=float, default=MAX_REMEDIATION_SECONDS)
    run_parser.add_argument("--max-attempts", type=int, default=MAX_SEMANTIC_ATTEMPTS)
    run_parser.add_argument(
        "--candidate-provider",
        choices=("fixture", "deepagents"),
        default="fixture",
    )
    run_parser.add_argument("--deepagents-provider")
    run_parser.add_argument("--deepagents-model")
    run_parser.add_argument("--deepagents-python", default=sys.executable)
    run_parser.add_argument("--deepagents-max-turns", type=int, default=20)

    verify_parser = subcommands.add_parser("verify")
    verify_target = verify_parser.add_mutually_exclusive_group(required=True)
    verify_target.add_argument("--latest", action="store_true")
    verify_target.add_argument("--run-dir", type=Path)

    cleanup_parser = subcommands.add_parser("cleanup")
    cleanup_target = cleanup_parser.add_mutually_exclusive_group(required=True)
    cleanup_target.add_argument("--latest", action="store_true")
    cleanup_target.add_argument("--run-dir", type=Path)

    subcommands.add_parser("dump-policy")
    subcommands.add_parser("test")
    return root


def main() -> int:
    args = parser().parse_args()
    if args.command == "preflight":
        result = preflight(
            args.with_docker,
            args.require_deepagents,
            args.deepagents_python,
        )
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0 if result["ok"] else 1
    if args.command == "run":
        candidate_provider: CandidateProvider | None = None
        if args.candidate_provider == "deepagents":
            if not args.deepagents_provider or not args.deepagents_model:
                print(
                    "--deepagents-provider and --deepagents-model are required "
                    "for a Deep Agents run",
                    file=sys.stderr,
                )
                return 2
            try:
                runtime_python = qualified_deepagents_runtime(args.deepagents_python)
            except ValueError as exc:
                print(str(exc), file=sys.stderr)
                return 2
            candidate_provider = DeepAgentsCandidateProvider(
                provider=args.deepagents_provider,
                model=args.deepagents_model,
                runtime_python=runtime_python,
                max_turns=args.deepagents_max_turns,
            )
        run_dir, control = run_flow(
            args.scenario,
            with_docker=args.with_docker,
            budget_seconds=args.budget_seconds,
            max_attempts=args.max_attempts,
            candidate_provider=candidate_provider,
        )
        print(
            json.dumps(
                {
                    "run_dir": str(run_dir),
                    "outcome": control["outcome"],
                    "attempts": control["attempts"],
                },
                indent=2,
            )
        )
        return 0
    if args.command == "verify":
        run_dir = latest_run() if args.latest else args.run_dir.resolve()
        issues = verify_run(run_dir)
        print(json.dumps({"run_dir": str(run_dir), "ok": not issues, "issues": issues}, indent=2))
        return 0 if not issues else 1
    if args.command == "cleanup":
        run_dir = latest_run() if args.latest else args.run_dir.resolve()
        result = cleanup_existing(run_dir)
        print(json.dumps({"run_dir": str(run_dir), **result}, indent=2, sort_keys=True))
        return 0 if result["cleanup_complete"] else 1
    if args.command == "dump-policy":
        print(json.dumps(dump_policy(), indent=2, sort_keys=True))
        return 0
    if args.command == "test":
        suite = unittest.defaultTestLoader.discover(str(PACKAGE_ROOT / "tests"))
        result = unittest.TextTestRunner(verbosity=2).run(suite)
        return 0 if result.wasSuccessful() else 1
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
