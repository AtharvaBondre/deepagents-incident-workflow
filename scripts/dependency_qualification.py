#!/usr/bin/env python3
"""Capture and verify the qualified Deep Agents dependency/source snapshot."""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import os
import re
import tempfile
import tomllib
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class QualificationError(RuntimeError):
    """Raised when dependency or upstream qualification evidence is invalid."""


ROOT = Path(__file__).resolve().parents[1]
QUALIFICATION_PATH = ROOT / "security" / "dependency-qualification.json"
CANDIDATE_PATH = ROOT / "security" / "dependency-qualification.candidate.json"
DEPENDENCY_POLICY_PATH = ROOT / "security" / "dependency-policy.json"
LOCK_PATHS = {
    "3.11": ROOT / "requirements" / "deepagents-py311-universal.lock",
    "3.12": ROOT / "requirements" / "deepagents-py312-universal.lock",
}
DEPENDENCY_POLICY = json.loads(DEPENDENCY_POLICY_PATH.read_text(encoding="utf-8"))
RESOLVER_POLICY = DEPENDENCY_POLICY["resolver"]
RESOLUTION_CUTOFF = RESOLVER_POLICY["resolution_cutoff"]
PYTHON_DOC_INDEX = "https://docs.langchain.com/oss/python/deepagents/llms.txt"
ROOT_DOC_INDEX = "https://docs.langchain.com/llms.txt"
PYTHON_DOC_PREFIX = "https://docs.langchain.com/oss/python/deepagents/"
CODE_DOC_PREFIX = "https://docs.langchain.com/oss/deepagents/code/"
EXPECTED_DOC_COUNTS = {"python": 40, "code": 17}
MAX_HTTP_BYTES = 2_000_000
HTTP_TIMEOUT_SECONDS = 30
USER_AGENT = "deepagents-incident-workflow-dependency-qualification/1"
ALLOWED_UPSTREAM_HOSTS = {
    "api.github.com",
    "docs.langchain.com",
    "github.com",
    "pypi.org",
    "raw.githubusercontent.com",
}

TRACKED_PYPI_PACKAGES = (
    "deepagents",
    "deepagents-code",
    "langchain",
    "langchain-anthropic",
    "langchain-google-genai",
    "langchain-ollama",
    "langchain-openai",
    "langgraph",
    "langgraph-checkpoint-sqlite",
    "langsmith",
)
TRACKED_SOURCE_PATHS = (
    ("langchain-ai/deepagents", "libs/deepagents"),
    ("langchain-ai/deepagents", "libs/code"),
    ("langchain-ai/docs", "src/oss/deepagents"),
    ("langchain-ai/docs", "src/oss/langgraph"),
    ("langchain-ai/docs", "src/langsmith/trace-deep-agents.mdx"),
    ("langchain-ai/docs", "src/langsmith/data-storage-and-privacy.mdx"),
)
ALLOWED_LICENSE_CONCLUSIONS = {
    "Apache-2.0",
    "Apache-2.0 AND CNRI-Python",
    "Apache-2.0 OR BSD-2-Clause",
    "Apache-2.0 OR BSD-3-Clause",
    "Apache-2.0 OR MIT",
    "BSD-2-Clause",
    "BSD-3-Clause",
    "MIT",
    "MIT-0",
    "MIT OR Apache-2.0",
    "MPL-2.0",
    "MPL-2.0 AND (Apache-2.0 OR MIT)",
    "PSF-2.0",
}
LICENSE_TEXT_NORMALIZATION = {
    "Apache 2.0": "Apache-2.0",
    "Apache License, Version 2.0": "Apache-2.0",
    "Apache-2.0": "Apache-2.0",
    "BSD-2-Clause": "BSD-2-Clause",
    "BSD-3-Clause": "BSD-3-Clause",
    "MIT": "MIT",
    "MIT License": "MIT",
    "MIT OR Apache-2.0": "MIT OR Apache-2.0",
    "MPL-2.0": "MPL-2.0",
    "Modified BSD License": "BSD-3-Clause",
}
PACKAGE_LICENSE_OVERRIDES = {"pyasn1-modules": "BSD-2-Clause"}
REQUIREMENT_RE = re.compile(r"^([A-Za-z0-9_.-]+)==([^\s;\\]+)(?:\s*;\s*(.*?))?\s*\\?$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
GIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
LOCK_HASH_RE = re.compile(r"^\s+--hash=sha256:([0-9a-f]{64})\s*\\?$")
DOC_URL_RE = re.compile(r"https://docs\.langchain\.com/[^)\s]+?\.md(?:\?[^)\s]*)?")
CAPTURED_AT_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\+00:00$")
DOCUMENTATION_SOURCE_OVERRIDES = {
    "https://docs.langchain.com/oss/deepagents/code/changelog.md": (
        "https://raw.githubusercontent.com/langchain-ai/deepagents/main/libs/code/CHANGELOG.md"
    )
}

TRACKED_GITHUB_REPOSITORIES = {
    "langchain-ai/deepagents",
    "langchain-ai/docs",
    "langchain-ai/langgraph",
}


def normalize_name(value: str) -> str:
    """Return a PEP 503-style distribution name."""
    return re.sub(r"[-_.]+", "-", value).lower()


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def canonical_digest(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return sha256_bytes(payload)


def parse_utc_timestamp(value: Any) -> datetime | None:
    if type(value) is not str or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        return None
    return parsed


def parse_lock(path: Path) -> tuple[dict[str, str], dict[str, list[str]]]:
    """Parse exact requirements and require at least one SHA-256 per entry."""
    text = path.read_text(encoding="utf-8")
    forbidden = ("--index-url", "--extra-index-url", "git+", "file:", "../", " -e ")
    for marker in forbidden:
        if marker in text:
            raise QualificationError(f"forbidden lock content {marker!r} in {path.name}")

    packages: dict[str, str] = {}
    current: str | None = None
    hashes: dict[str, list[str]] = {}
    for line_number, line in enumerate(text.splitlines(), start=1):
        if not line or line.startswith("#"):
            continue
        if line[0].isspace():
            if line.lstrip().startswith("#"):
                continue
            match = LOCK_HASH_RE.fullmatch(line)
            if match is None or current is None:
                raise QualificationError(
                    f"unrecognized lock continuation in {path.name}:{line_number}"
                )
            digest = match.group(1)
            if digest in hashes[current]:
                raise QualificationError(
                    f"duplicate artifact hash for {current} in {path.name}:{line_number}"
                )
            hashes[current].append(digest)
            continue
        match = REQUIREMENT_RE.fullmatch(line)
        if match is None:
            raise QualificationError(f"unrecognized lock entry in {path.name}:{line_number}")
        name = normalize_name(match.group(1))
        version = match.group(2)
        if name in packages and packages[name] != version:
            raise QualificationError(f"multiple versions for {name} in {path.name}")
        packages[name] = version
        current = name
        hashes.setdefault(name, [])

    unhashed = sorted(name for name, values in hashes.items() if not values)
    if unhashed:
        raise QualificationError(f"unhashed requirements in {path.name}: {unhashed}")
    if not packages:
        raise QualificationError(f"empty lock: {path.name}")
    return packages, {name: sorted(values) for name, values in hashes.items()}


def direct_pins() -> dict[str, str]:
    with (ROOT / "pyproject.toml").open("rb") as handle:
        metadata = tomllib.load(handle)
    requirements = metadata["project"]["optional-dependencies"]["deepagents"]
    pins: dict[str, str] = {}
    for requirement in requirements:
        match = re.fullmatch(r"([A-Za-z0-9_.-]+)==([^\s]+)", requirement)
        if match is None:
            raise QualificationError(f"optional dependency is not exactly pinned: {requirement}")
        pins[normalize_name(match.group(1))] = match.group(2)
    return pins


def tracked_git_refs(
    package_versions: dict[str, str], latest_versions: dict[str, str]
) -> tuple[tuple[str, str], ...]:
    try:
        deepagents_version = package_versions["deepagents"]
        langgraph_version = package_versions["langgraph"]
        code_version = latest_versions["deepagents-code"]
        checkpoint_sqlite_version = latest_versions["langgraph-checkpoint-sqlite"]
    except KeyError as exc:
        raise QualificationError(f"source-qualified package is missing from locks: {exc}") from exc
    if any(
        type(version) is not str or not version
        for version in (
            deepagents_version,
            langgraph_version,
            code_version,
            checkpoint_sqlite_version,
        )
    ):
        raise QualificationError("source-qualified package version is empty")
    refs = (
        ("langchain-ai/deepagents", f"refs/tags/deepagents=={deepagents_version}"),
        ("langchain-ai/deepagents", f"refs/tags/deepagents-code=={code_version}"),
        ("langchain-ai/langgraph", f"refs/tags/{langgraph_version}"),
        (
            "langchain-ai/langgraph",
            f"refs/tags/checkpointsqlite=={checkpoint_sqlite_version}",
        ),
    )
    return tuple(sorted(refs))


def _validated_upstream_url(url: str) -> urllib.parse.ParseResult:
    parsed = urllib.parse.urlparse(url)
    if (
        parsed.scheme != "https"
        or parsed.hostname not in ALLOWED_UPSTREAM_HOSTS
        or parsed.username is not None
        or parsed.password is not None
        or parsed.port not in (None, 443)
    ):
        raise QualificationError(f"upstream URL is outside the allowlist: {url}")
    if parsed.hostname in {"github.com", "raw.githubusercontent.com"} and not (
        parsed.path.startswith("/langchain-ai/deepagents/")
    ):
        raise QualificationError(f"GitHub redirect is outside the qualified repository: {url}")
    if parsed.hostname == "api.github.com":
        allowed_prefixes = tuple(
            f"/repos/{repository}/" for repository in TRACKED_GITHUB_REPOSITORIES
        )
        if not parsed.path.startswith(allowed_prefixes):
            raise QualificationError(f"GitHub API URL is outside tracked repositories: {url}")
    return parsed


def _request_headers(url: str) -> dict[str, str]:
    """Use the workflow token only for the allowlisted GitHub API host."""
    parsed = _validated_upstream_url(url)
    headers = {"Accept": "application/json, text/plain;q=0.9", "User-Agent": USER_AGENT}
    github_token = os.environ.get("GITHUB_TOKEN", "").strip()
    if parsed.hostname == "api.github.com" and github_token:
        headers["Authorization"] = f"Bearer {github_token}"
    return headers


class ValidatingRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Reject a redirect target before urllib makes the next request."""

    def redirect_request(
        self,
        request: urllib.request.Request,
        response: Any,
        code: int,
        message: str,
        headers: Any,
        new_url: str,
    ) -> urllib.request.Request | None:
        _validated_upstream_url(new_url)
        redirected = super().redirect_request(
            request,
            response,
            code,
            message,
            headers,
            new_url,
        )
        if redirected is not None and urllib.parse.urlparse(new_url).hostname != "api.github.com":
            redirected.remove_header("Authorization")
        return redirected


def _request_bytes(url: str) -> bytes:
    _validated_upstream_url(url)
    request = urllib.request.Request(url, headers=_request_headers(url))
    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({}),
        ValidatingRedirectHandler(),
    )
    with opener.open(request, timeout=HTTP_TIMEOUT_SECONDS) as response:
        payload = response.read(MAX_HTTP_BYTES + 1)
        final_url = response.url
    if len(payload) > MAX_HTTP_BYTES:
        raise QualificationError(f"upstream response exceeds {MAX_HTTP_BYTES} bytes: {url}")
    _validated_upstream_url(final_url)
    return payload


def _request_json(url: str) -> Any:
    return json.loads(_request_bytes(url))


def pypi_metadata(name: str, version: str | None = None) -> dict[str, Any]:
    suffix = f"/{urllib.parse.quote(version, safe='')}" if version else ""
    encoded_name = urllib.parse.quote(name, safe="")
    payload = _request_json(f"https://pypi.org/pypi/{encoded_name}{suffix}/json")
    info = payload["info"]
    files = payload["urls"] if version else payload["releases"][info["version"]]
    license_classifiers = sorted(
        item.removeprefix("License :: ")
        for item in info.get("classifiers", [])
        if item.startswith("License :: ")
    )
    license_text = (info.get("license") or "").strip().splitlines()
    evidence = {
        "license_expression": info.get("license_expression") or "",
        "license_text": license_text[0][:160] if license_text else "",
        "license_classifiers": license_classifiers,
    }
    return {
        "name": normalize_name(info["name"]),
        "version": info["version"],
        "requires_python": info.get("requires_python") or "",
        "latest_upload": max((item.get("upload_time_iso_8601", "") for item in files), default=""),
        "artifact_sha256": sorted(
            item["digests"]["sha256"] for item in files if item.get("digests", {}).get("sha256")
        ),
        "license_evidence": evidence,
        "license_evidence_sha256": canonical_digest(evidence),
    }


def license_conclusion(name: str, metadata: dict[str, Any]) -> str:
    evidence = metadata["license_evidence"]
    expression = evidence["license_expression"]
    if expression:
        conclusion = expression
    elif name in PACKAGE_LICENSE_OVERRIDES:
        conclusion = PACKAGE_LICENSE_OVERRIDES[name]
    else:
        conclusion = LICENSE_TEXT_NORMALIZATION.get(evidence["license_text"], "")
    if conclusion not in ALLOWED_LICENSE_CONCLUSIONS:
        raise QualificationError(
            f"{name} has unreviewed license metadata: {evidence!r}; add a reviewed conclusion"
        )
    return conclusion


def github_ref(repository: str, ref: str) -> str:
    short_ref = ref.removeprefix("refs/")
    encoded = urllib.parse.quote(short_ref, safe="/")
    payload = _request_json(f"https://api.github.com/repos/{repository}/git/ref/{encoded}")
    target = payload["object"]
    if target["type"] == "tag":
        target = _request_json(target["url"])["object"]
    if target["type"] != "commit" or GIT_SHA_RE.fullmatch(target["sha"]) is None:
        raise QualificationError(f"unexpected Git reference target for {repository}:{ref}")
    return target["sha"]


def github_path_commit(repository: str, scoped_path: str) -> str:
    query = urllib.parse.urlencode({"path": scoped_path, "per_page": 1})
    payload = _request_json(f"https://api.github.com/repos/{repository}/commits?{query}")
    if not isinstance(payload, list) or not payload:
        raise QualificationError(f"no commits returned for {repository}:{scoped_path}")
    commit = payload[0].get("sha", "")
    if GIT_SHA_RE.fullmatch(commit) is None:
        raise QualificationError(f"invalid path commit for {repository}:{scoped_path}")
    return commit


def documentation_urls() -> dict[str, list[str]]:
    root_text = _request_bytes(ROOT_DOC_INDEX).decode("utf-8")
    python_text = _request_bytes(PYTHON_DOC_INDEX).decode("utf-8")
    python_urls = sorted(
        {url for url in DOC_URL_RE.findall(python_text) if url.startswith(PYTHON_DOC_PREFIX)}
    )
    code_urls = sorted(
        {url for url in DOC_URL_RE.findall(root_text) if url.startswith(CODE_DOC_PREFIX)}
    )
    actual_counts = {"python": len(python_urls), "code": len(code_urls)}
    if actual_counts != EXPECTED_DOC_COUNTS:
        raise QualificationError(
            f"official documentation inventory changed: expected {EXPECTED_DOC_COUNTS}, "
            f"found {actual_counts}"
        )
    return {"python": python_urls, "code": code_urls}


def documentation_snapshot() -> dict[str, Any]:
    inventories = documentation_urls()
    all_urls = inventories["python"] + inventories["code"]
    source_urls = [DOCUMENTATION_SOURCE_OVERRIDES.get(url, url) for url in all_urls]
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
        payloads = list(executor.map(_request_bytes, source_urls))
    pages = {
        url: {
            "source": source_url,
            "bytes": len(payload),
            "sha256": sha256_bytes(payload),
        }
        for url, source_url, payload in zip(all_urls, source_urls, payloads, strict=True)
    }
    return {
        "indexes": {"python": PYTHON_DOC_INDEX, "root": ROOT_DOC_INDEX},
        "inventories": inventories,
        "pages": pages,
    }


def capture_snapshot() -> dict[str, Any]:
    lock_targets: dict[str, Any] = {}
    package_versions: dict[str, str] = {}
    selected_artifacts: dict[str, set[str]] = {}
    for python_version, lock_path in LOCK_PATHS.items():
        packages, hashes = parse_lock(lock_path)
        for name, version in packages.items():
            previous = package_versions.setdefault(name, version)
            if previous != version:
                raise QualificationError(
                    f"lock targets disagree for {name}: {previous} vs {version}"
                )
            selected_artifacts.setdefault(name, set()).update(hashes[name])
        lock_targets[python_version] = {
            "path": lock_path.relative_to(ROOT).as_posix(),
            "sha256": sha256_bytes(lock_path.read_bytes()),
            "package_count": len(packages),
            "artifact_hash_count": sum(len(values) for values in hashes.values()),
            "packages": packages,
        }

    for name, version in direct_pins().items():
        if package_versions.get(name) != version:
            raise QualificationError(f"direct pin is absent from lock targets: {name}=={version}")

    names = sorted(package_versions)

    def exact_metadata(name: str) -> dict[str, Any]:
        return pypi_metadata(name, package_versions[name])

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
        exact_rows = list(executor.map(exact_metadata, names))
        latest_rows = list(executor.map(pypi_metadata, TRACKED_PYPI_PACKAGES))
    exact_by_name = {row["name"]: row for row in exact_rows}
    provenance: dict[str, Any] = {}
    for name in names:
        row = exact_by_name[name]
        official_artifacts = set(row["artifact_sha256"])
        unknown_artifacts = selected_artifacts[name] - official_artifacts
        if unknown_artifacts:
            raise QualificationError(
                f"lock contains hashes absent from official PyPI metadata for {name}"
            )
        provenance[name] = {
            "version": row["version"],
            "index": f"https://pypi.org/project/{name}/{row['version']}/",
            "requires_python": row["requires_python"],
            "release_latest_upload": row["latest_upload"],
            "official_artifact_sha256": row["artifact_sha256"],
            "selected_lock_artifact_sha256": sorted(selected_artifacts[name]),
        }
    licenses = {
        row["name"]: {
            "version": package_versions[row["name"]],
            "conclusion": license_conclusion(row["name"], row),
            "evidence": row["license_evidence"],
            "evidence_sha256": row["license_evidence_sha256"],
        }
        for row in exact_rows
    }
    latest = {
        row["name"]: {
            "version": row["version"],
            "latest_upload": row["latest_upload"],
            "artifact_sha256": row["artifact_sha256"],
        }
        for row in latest_rows
    }
    refs = {
        f"{repository}:{ref}": github_ref(repository, ref)
        for repository, ref in tracked_git_refs(
            package_versions,
            {name: record["version"] for name, record in latest.items()},
        )
    }
    source_paths = {
        f"{repository}:{scoped_path}": github_path_commit(repository, scoped_path)
        for repository, scoped_path in TRACKED_SOURCE_PATHS
    }
    return {
        "schema_version": 1,
        "captured_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "resolver": dict(RESOLVER_POLICY),
        "direct_pins": direct_pins(),
        "lock_targets": lock_targets,
        "package_provenance": provenance,
        "allowed_license_conclusions": sorted(ALLOWED_LICENSE_CONCLUSIONS),
        "licenses": licenses,
        "upstream": {
            "pypi_latest": latest,
            "git_refs": refs,
            "source_paths": source_paths,
            "documentation": documentation_snapshot(),
        },
    }


def validate_snapshot(snapshot: dict[str, Any]) -> list[str]:
    issues: list[str] = []
    expected_top = {
        "schema_version",
        "captured_at",
        "resolver",
        "direct_pins",
        "lock_targets",
        "package_provenance",
        "allowed_license_conclusions",
        "licenses",
        "upstream",
    }
    if (
        type(snapshot) is not dict
        or set(snapshot) != expected_top
        or type(snapshot.get("schema_version")) is not int
        or snapshot.get("schema_version") != 1
    ):
        return ["dependency qualification has an invalid top-level contract"]

    captured_at = snapshot.get("captured_at")
    parsed_at = parse_utc_timestamp(captured_at)
    if (
        type(captured_at) is not str
        or CAPTURED_AT_RE.fullmatch(captured_at) is None
        or parsed_at is None
    ):
        issues.append("qualification capture timestamp is invalid")

    resolver = snapshot.get("resolver", {})
    expected_resolver = dict(RESOLVER_POLICY)
    expected_resolver_types = {
        "name": str,
        "version": str,
        "resolution_cutoff": str,
        "index": str,
        "universal": bool,
        "hashes_required": bool,
    }
    if (
        type(DEPENDENCY_POLICY) is not dict
        or set(DEPENDENCY_POLICY) != {"schema_version", "resolver"}
        or type(DEPENDENCY_POLICY.get("schema_version")) is not int
        or DEPENDENCY_POLICY.get("schema_version") != 1
    ):
        issues.append("dependency resolver policy contract is invalid")
    if (
        set(expected_resolver) != set(expected_resolver_types)
        or expected_resolver.get("name") != "uv"
        or type(expected_resolver.get("version")) is not str
        or not expected_resolver.get("version")
        or expected_resolver.get("index") != "https://pypi.org/simple"
        or expected_resolver.get("universal") is not True
        or expected_resolver.get("hashes_required") is not True
        or parse_utc_timestamp(expected_resolver.get("resolution_cutoff")) is None
        or not str(expected_resolver.get("resolution_cutoff", "")).endswith("Z")
    ):
        issues.append("dependency resolver policy values are invalid")
    if (
        type(resolver) is not dict
        or any(
            key not in resolver
            or type(resolver[key]) is not expected_resolver_types.get(key)
            or resolver[key] != expected
            for key, expected in expected_resolver.items()
        )
        or set(resolver) != set(expected_resolver_types)
        or set(expected_resolver) != set(expected_resolver_types)
    ):
        issues.append("resolver qualification does not match the controlled lock procedure")

    qualified_pins = snapshot.get("direct_pins")
    if (
        type(qualified_pins) is not dict
        or any(
            type(name) is not str or type(version) is not str
            for name, version in qualified_pins.items()
        )
        or qualified_pins != direct_pins()
    ):
        issues.append("qualified direct pins differ from pyproject.toml")

    allowed_licenses = snapshot.get("allowed_license_conclusions")
    if (
        type(allowed_licenses) is not list
        or any(type(item) is not str for item in allowed_licenses)
        or allowed_licenses != sorted(ALLOWED_LICENSE_CONCLUSIONS)
    ):
        issues.append("allowed license conclusions differ from controller policy")

    package_versions: dict[str, str] = {}
    selected_artifacts: dict[str, set[str]] = {}
    targets = snapshot.get("lock_targets", {})
    if type(targets) is not dict:
        issues.append("qualified lock target set is invalid")
        targets = {}
    if set(targets) != set(LOCK_PATHS):
        issues.append("qualified lock target set is incomplete")
    for python_version, lock_path in LOCK_PATHS.items():
        try:
            packages, hashes = parse_lock(lock_path)
        except (OSError, UnicodeError, QualificationError) as exc:
            issues.append(str(exc))
            continue
        expected = targets.get(python_version, {})
        actual = {
            "path": lock_path.relative_to(ROOT).as_posix(),
            "sha256": sha256_bytes(lock_path.read_bytes()),
            "package_count": len(packages),
            "artifact_hash_count": sum(len(values) for values in hashes.values()),
            "packages": packages,
        }
        if type(expected) is not dict or expected != actual:
            issues.append(f"lock qualification mismatch for Python {python_version}")
        for name, version in packages.items():
            prior = package_versions.setdefault(name, version)
            if prior != version:
                issues.append(f"lock versions disagree for {name}")
            selected_artifacts.setdefault(name, set()).update(hashes[name])

    for name, version in direct_pins().items():
        if package_versions.get(name) != version:
            issues.append(f"direct pin is absent from lock targets: {name}=={version}")

    provenance = snapshot.get("package_provenance", {})
    if type(provenance) is not dict:
        issues.append("provenance inventory is invalid")
        provenance = {}
    if set(provenance) != set(package_versions):
        issues.append("provenance inventory does not match the transitive package set")
    for name, version in package_versions.items():
        record = provenance.get(name, {})
        if type(record) is not dict:
            issues.append(f"invalid provenance record for {name}")
            record = {}
        official = record.get("official_artifact_sha256", [])
        selected = record.get("selected_lock_artifact_sha256", [])
        expected_selected = sorted(selected_artifacts.get(name, set()))
        if record.get("version") != version:
            issues.append(f"provenance version mismatch for {name}")
        if record.get("index") != f"https://pypi.org/project/{name}/{version}/":
            issues.append(f"provenance index mismatch for {name}")
        if type(record.get("requires_python")) is not str:
            issues.append(f"invalid requires-python provenance for {name}")
        release_upload = parse_utc_timestamp(record.get("release_latest_upload"))
        resolution_cutoff = parse_utc_timestamp(RESOLUTION_CUTOFF)
        if release_upload is None:
            issues.append(f"invalid release-upload provenance for {name}")
        elif resolution_cutoff is None or release_upload > resolution_cutoff:
            issues.append(f"release-upload provenance exceeds cutoff for {name}")
        if (
            type(official) is not list
            or not official
            or any(type(item) is not str for item in official)
            or official != sorted(set(official))
            or any(SHA256_RE.fullmatch(item) is None for item in official)
        ):
            issues.append(f"invalid official artifact provenance for {name}")
        if type(selected) is not list or selected != expected_selected:
            issues.append(f"selected lock artifact provenance mismatch for {name}")
        if (
            type(official) is list
            and all(type(item) is str for item in official)
            and not set(expected_selected).issubset(official)
        ):
            issues.append(f"unrecognized lock artifact provenance for {name}")

    licenses = snapshot.get("licenses", {})
    if type(licenses) is not dict:
        issues.append("license inventory is invalid")
        licenses = {}
    if set(licenses) != set(package_versions):
        issues.append("license inventory does not match the transitive package set")
    for name, version in package_versions.items():
        record = licenses.get(name, {})
        if type(record) is not dict:
            issues.append(f"invalid license record for {name}")
            record = {}
        if record.get("version") != version:
            issues.append(f"license version mismatch for {name}")
        conclusion = record.get("conclusion")
        if type(conclusion) is not str or conclusion not in ALLOWED_LICENSE_CONCLUSIONS:
            issues.append(f"unapproved or missing license conclusion for {name}")
        evidence = record.get("evidence")
        if type(evidence) is not dict or record.get("evidence_sha256") != canonical_digest(
            evidence
        ):
            issues.append(f"license evidence digest mismatch for {name}")
        if type(evidence) is dict:
            try:
                derived_conclusion = license_conclusion(name, {"license_evidence": evidence})
            except (KeyError, TypeError, QualificationError):
                issues.append(f"license evidence cannot be evaluated for {name}")
            else:
                if record.get("conclusion") != derived_conclusion:
                    issues.append(f"license conclusion does not match evidence for {name}")

    upstream = snapshot.get("upstream", {})
    if type(upstream) is not dict:
        issues.append("upstream qualification is invalid")
        upstream = {}
    pypi_latest = upstream.get("pypi_latest", {})
    git_refs = upstream.get("git_refs", {})
    source_paths = upstream.get("source_paths", {})
    if type(pypi_latest) is not dict:
        issues.append("tracked PyPI package inventory is invalid")
        pypi_latest = {}
    if type(git_refs) is not dict:
        issues.append("tracked Git reference inventory is invalid")
        git_refs = {}
    if type(source_paths) is not dict:
        issues.append("tracked source-path inventory is invalid")
        source_paths = {}
    if set(pypi_latest) != {normalize_name(name) for name in TRACKED_PYPI_PACKAGES}:
        issues.append("tracked PyPI package set is incomplete")
    try:
        expected_ref_items = tracked_git_refs(
            package_versions,
            {
                name: record.get("version", "") if type(record) is dict else ""
                for name, record in pypi_latest.items()
            },
        )
    except QualificationError as exc:
        issues.append(str(exc))
        expected_ref_items = ()
    expected_refs = {f"{repository}:{ref}" for repository, ref in expected_ref_items}
    if set(git_refs) != expected_refs:
        issues.append("tracked Git reference set is incomplete")
    if set(source_paths) != {
        f"{repository}:{scoped_path}" for repository, scoped_path in TRACKED_SOURCE_PATHS
    }:
        issues.append("tracked upstream source-path set is incomplete")
    documentation = upstream.get("documentation", {})
    if type(documentation) is not dict:
        issues.append("qualified documentation record is invalid")
        documentation = {}
    if documentation.get("indexes") != {"python": PYTHON_DOC_INDEX, "root": ROOT_DOC_INDEX}:
        issues.append("qualified documentation indexes are invalid")
    inventories = documentation.get("inventories", {})
    if type(inventories) is not dict:
        issues.append("qualified documentation inventories are invalid")
        inventories = {}
    inventory_counts: dict[str, int] = {}
    validated_inventories: dict[str, list[str]] = {}
    for key, prefix in (("python", PYTHON_DOC_PREFIX), ("code", CODE_DOC_PREFIX)):
        values = inventories.get(key)
        if (
            type(values) is not list
            or any(type(item) is not str for item in values)
            or values != sorted(set(values))
            or any(not item.startswith(prefix) for item in values)
        ):
            issues.append(f"qualified {key} documentation inventory is invalid")
            values = []
        inventory_counts[key] = len(values)
        validated_inventories[key] = values
    if set(inventories) != set(EXPECTED_DOC_COUNTS) or inventory_counts != EXPECTED_DOC_COUNTS:
        issues.append("qualified documentation inventory counts are incomplete")
    expected_urls = set(validated_inventories["python"]) | set(validated_inventories["code"])
    pages = documentation.get("pages", {})
    if type(pages) is not dict:
        issues.append("qualified documentation pages are invalid")
        pages = {}
    if set(pages) != expected_urls:
        issues.append("qualified documentation page hashes are incomplete")
    for url, record in pages.items():
        if type(url) is not str or not url.startswith("https://docs.langchain.com/"):
            issues.append(f"non-official documentation URL in qualification: {url}")
            continue
        if type(record) is not dict:
            issues.append(f"invalid documentation page record: {url}")
            continue
        if record.get("source") != DOCUMENTATION_SOURCE_OVERRIDES.get(url, url):
            issues.append(f"invalid documentation evidence source: {url}")
        if type(record.get("bytes")) is not int or record["bytes"] <= 0:
            issues.append(f"invalid documentation byte count: {url}")
        digest = record.get("sha256")
        if type(digest) is not str or SHA256_RE.fullmatch(digest) is None:
            issues.append(f"invalid documentation digest: {url}")
    for value in git_refs.values():
        if type(value) is not str or GIT_SHA_RE.fullmatch(value) is None:
            issues.append("invalid qualified Git reference commit")
    for value in source_paths.values():
        if type(value) is not str or GIT_SHA_RE.fullmatch(value) is None:
            issues.append("invalid qualified source-path commit")
    for name, record in pypi_latest.items():
        if type(name) is not str or type(record) is not dict:
            issues.append(f"invalid tracked PyPI record for {name}")
            continue
        artifacts = record.get("artifact_sha256", [])
        if (
            normalize_name(name) != name
            or type(record.get("version")) is not str
            or not record["version"]
            or parse_utc_timestamp(record.get("latest_upload")) is None
        ):
            issues.append(f"invalid tracked PyPI record for {name}")
        if (
            type(artifacts) is not list
            or not artifacts
            or any(type(item) is not str for item in artifacts)
            or artifacts != sorted(set(artifacts))
            or any(SHA256_RE.fullmatch(item) is None for item in artifacts)
        ):
            issues.append(f"invalid tracked PyPI artifacts for {name}")
    return sorted(set(issues))


def compare_online(snapshot: dict[str, Any]) -> list[str]:
    issues = validate_snapshot(snapshot)
    if issues:
        return issues
    current = capture_snapshot()
    for section in ("pypi_latest", "git_refs", "source_paths", "documentation"):
        if current["upstream"][section] != snapshot["upstream"][section]:
            issues.append(f"upstream drift detected in {section}")
    if current["package_provenance"] != snapshot["package_provenance"]:
        issues.append("exact package provenance drift detected")
    if current["licenses"] != snapshot["licenses"]:
        issues.append("license metadata drift detected")
    return sorted(set(issues))


def load_snapshot(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise QualificationError("dependency qualification root must be an object")
    return payload


def write_snapshot_atomic(path: Path, snapshot: dict[str, Any]) -> None:
    """Replace a snapshot only after its complete payload is durable."""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(snapshot, indent=2, sort_keys=True) + "\n"
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary_path = Path(handle.name)
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary_path, 0o644)
        os.replace(temporary_path, path)
        temporary_path = None
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--online", action="store_true", help="compare current official sources")
    parser.add_argument(
        "--capture",
        action="store_true",
        help="capture a review candidate without replacing trusted evidence",
    )
    parser.add_argument(
        "--replace",
        action="store_true",
        help="replace an existing review candidate",
    )
    parser.add_argument(
        "--promote",
        action="store_true",
        help="online-validate and atomically promote the reviewed candidate",
    )
    args = parser.parse_args()
    if sum((args.capture, args.online, args.promote)) > 1:
        parser.error("--capture, --online, and --promote are mutually exclusive")
    if args.replace and not args.capture:
        parser.error("--replace requires --capture")
    mode = (
        "online"
        if args.online
        else "capture"
        if args.capture
        else "promote"
        if args.promote
        else "offline"
    )
    try:
        if args.capture:
            if CANDIDATE_PATH.exists() and not args.replace:
                raise QualificationError(
                    "review candidate already exists; inspect it or pass --replace"
                )
            snapshot = capture_snapshot()
            issues = validate_snapshot(snapshot)
            if not issues:
                write_snapshot_atomic(CANDIDATE_PATH, snapshot)
        elif args.promote:
            snapshot = load_snapshot(CANDIDATE_PATH)
            issues = compare_online(snapshot)
            if not issues:
                write_snapshot_atomic(QUALIFICATION_PATH, snapshot)
                CANDIDATE_PATH.unlink()
        else:
            snapshot = load_snapshot(QUALIFICATION_PATH)
            issues = compare_online(snapshot) if args.online else validate_snapshot(snapshot)
    except (OSError, UnicodeError, ValueError, KeyError, TypeError, QualificationError) as exc:
        issues = [f"{type(exc).__name__}: {exc}"]
    result = {
        "ok": not issues,
        "mode": mode,
        "issues": issues,
    }
    if args.capture and not issues:
        result["candidate"] = CANDIDATE_PATH.relative_to(ROOT).as_posix()
    if args.promote and not issues:
        result["promoted"] = QUALIFICATION_PATH.relative_to(ROOT).as_posix()
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if not issues else 1


if __name__ == "__main__":
    raise SystemExit(main())
