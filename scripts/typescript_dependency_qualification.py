#!/usr/bin/env python3
"""Offline qualification gate for the pinned TypeScript Deep Agents runtime."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
PACKAGE_JSON = ROOT / "typescript-runtime" / "package.json"
PACKAGE_LOCK = ROOT / "typescript-runtime" / "package-lock.json"
TSCONFIG = ROOT / "typescript-runtime" / "tsconfig.json"
WORKER_SOURCE = ROOT / "typescript-runtime" / "src" / "deepagents_worker.ts"
WORKFLOW = ROOT / "config" / "workflow.json"
EVIDENCE = ROOT / "security" / "typescript-dependency-qualification.json"
ALLOWED_LICENSES = {"Apache-2.0", "ISC", "MIT", "Unlicense"}
ALLOWED_UPSTREAM_HOSTS = {"api.github.com", "docs.langchain.com", "registry.npmjs.org"}
MAX_UPSTREAM_BYTES = 2 * 1024 * 1024
EXPECTED_DEPENDENCIES = {
    "@langchain/anthropic": "1.5.8",
    "@langchain/core": "1.2.9",
    "@langchain/google-genai": "2.3.0",
    "@langchain/langgraph": "1.4.13",
    "@langchain/langgraph-checkpoint": "1.1.5",
    "@langchain/langgraph-sdk": "1.10.0",
    "@langchain/ollama": "1.3.0",
    "@langchain/openai": "1.5.10",
    "deepagents": "1.13.1",
    "langchain": "1.5.10",
    "langsmith": "0.9.0",
}
EXPECTED_DEV_DEPENDENCIES = {"@types/node": "22.20.1", "typescript": "7.0.2"}
EXPECTED_SOURCE = {
    "repository": "https://github.com/langchain-ai/deepagentsjs",
    "tag": "refs/tags/deepagents@1.13.1",
    "tag_object": "f04ab62269356eaa5d400154dbf819371467cd4d",
    "commit": "c0bc7692304f591526eadf9172c60a594f2a933f",
    "tarball": "https://registry.npmjs.org/deepagents/-/deepagents-1.13.1.tgz",
    "integrity": (
        "sha512-DB8dkbrd4cqejroU90qAGTtY7ZvIchsMSaOMjE7TWnsi/6IrpBPxg3xN0Vxjuq/"
        "x8jkufkIqk3I57RbZmdSJFw=="
    ),
}


class QualificationError(RuntimeError):
    """Raised when pinned TypeScript dependency evidence is inconsistent."""


def validated_upstream_url(url: str) -> urllib.parse.ParseResult:
    parsed = urllib.parse.urlparse(url)
    if (
        parsed.scheme != "https"
        or parsed.hostname not in ALLOWED_UPSTREAM_HOSTS
        or parsed.username is not None
        or parsed.password is not None
        or parsed.port not in (None, 443)
    ):
        raise QualificationError(f"upstream URL is outside the allowlist: {url}")
    if parsed.hostname == "api.github.com" and not parsed.path.startswith(
        "/repos/langchain-ai/deepagentsjs/"
    ):
        raise QualificationError(f"GitHub API URL is outside the qualified repository: {url}")
    return parsed


class ValidatingRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: Any,
        code: int,
        msg: str,
        headers: Any,
        newurl: str,
    ) -> urllib.request.Request | None:
        validated_upstream_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def upstream_bytes(url: str) -> bytes:
    validated_upstream_url(url)
    request = urllib.request.Request(
        url,
        headers={"Accept": "application/json, text/markdown", "User-Agent": "daiw-qualification/1"},
    )
    opener = urllib.request.build_opener(ValidatingRedirectHandler())
    with opener.open(request, timeout=30) as response:
        final_url = response.geturl()
        validated_upstream_url(final_url)
        payload = response.read(MAX_UPSTREAM_BYTES + 1)
    if not payload or len(payload) > MAX_UPSTREAM_BYTES:
        raise QualificationError(f"upstream response size is invalid: {url}")
    return payload


def upstream_json(url: str) -> dict[str, Any]:
    try:
        value = json.loads(upstream_bytes(url))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise QualificationError(f"invalid upstream JSON: {url}") from exc
    if not isinstance(value, dict):
        raise QualificationError(f"upstream JSON must be an object: {url}")
    return value


def read_json(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise QualificationError(f"missing or irregular qualification input: {path.name}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise QualificationError(f"invalid JSON in {path.name}") from exc
    if not isinstance(value, dict):
        raise QualificationError(f"{path.name} must contain an object")
    return value


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def exact_object(value: Any, fields: set[str], label: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != fields:
        raise QualificationError(f"{label} fields are invalid")
    return value


def validate() -> dict[str, Any]:
    package = read_json(PACKAGE_JSON)
    lock = read_json(PACKAGE_LOCK)
    tsconfig = read_json(TSCONFIG)
    workflow = read_json(WORKFLOW)
    evidence = exact_object(
        read_json(EVIDENCE),
        {
            "schema_version",
            "captured_at",
            "runtime",
            "lock",
            "source",
            "documentation",
            "audit",
        },
        "TypeScript qualification evidence",
    )
    if evidence["schema_version"] != 1:
        raise QualificationError("unsupported TypeScript qualification evidence schema")

    if package.get("private") is not True or package.get("type") != "module":
        raise QualificationError("TypeScript runtime package must be private ESM")
    if package.get("dependencies") != EXPECTED_DEPENDENCIES:
        raise QualificationError("TypeScript runtime direct dependencies changed")
    if package.get("devDependencies") != EXPECTED_DEV_DEPENDENCIES:
        raise QualificationError("TypeScript runtime build dependencies changed")
    if package.get("engines") != {"node": ">=22 <23"}:
        raise QualificationError("TypeScript runtime Node engine range changed")
    if package.get("scripts") != {
        "build": "tsc --project tsconfig.json --pretty false",
        "test": "npm run build && node --test dist/deepagents_worker.test.js",
        "typecheck": "tsc --project tsconfig.json --noEmit --pretty false",
    }:
        raise QualificationError("TypeScript runtime scripts changed")

    if lock.get("lockfileVersion") != 3 or lock.get("requires") is not True:
        raise QualificationError("TypeScript runtime requires an npm lockfile v3")
    packages = lock.get("packages")
    if not isinstance(packages, dict) or "" not in packages:
        raise QualificationError("TypeScript lock package inventory is invalid")
    root_entry = packages[""]
    if not isinstance(root_entry, dict):
        raise QualificationError("TypeScript lock root entry is invalid")
    if root_entry.get("dependencies") != EXPECTED_DEPENDENCIES:
        raise QualificationError("TypeScript lock direct dependencies changed")
    if root_entry.get("devDependencies") != EXPECTED_DEV_DEPENDENCIES:
        raise QualificationError("TypeScript lock build dependencies changed")
    if root_entry.get("engines") != {"node": ">=22 <23"}:
        raise QualificationError("TypeScript lock Node engine range changed")

    license_counts: Counter[str] = Counter()
    install_scripts = 0
    for package_path, metadata in sorted(packages.items()):
        if package_path == "":
            continue
        if not isinstance(metadata, dict) or not package_path.startswith("node_modules/"):
            raise QualificationError(f"invalid lock entry: {package_path}")
        version = metadata.get("version")
        resolved = metadata.get("resolved")
        integrity = metadata.get("integrity")
        license_name = metadata.get("license")
        if not isinstance(version, str) or not version:
            raise QualificationError(f"unversioned lock entry: {package_path}")
        if not isinstance(resolved, str):
            raise QualificationError(f"unresolved lock entry: {package_path}")
        parsed = urlparse(resolved)
        if (
            parsed.scheme != "https"
            or parsed.hostname != "registry.npmjs.org"
            or parsed.username is not None
            or parsed.password is not None
            or parsed.port not in (None, 443)
        ):
            raise QualificationError(f"non-registry package source: {package_path}")
        if (
            not isinstance(integrity, str)
            or re.fullmatch(r"sha512-[A-Za-z0-9+/]+={0,2}", integrity) is None
        ):
            raise QualificationError(f"invalid package integrity: {package_path}")
        if license_name not in ALLOWED_LICENSES:
            raise QualificationError(f"unqualified package license: {package_path}")
        license_counts[license_name] += 1
        if metadata.get("hasInstallScript") is True:
            install_scripts += 1
        if any(
            metadata.get(field) for field in ("link", "inBundle", "bundled", "bundledDependencies")
        ):
            raise QualificationError(f"bundled or linked dependency is forbidden: {package_path}")

    lock_evidence = exact_object(
        evidence["lock"],
        {
            "path",
            "sha256",
            "lockfile_version",
            "package_count",
            "registry",
            "install_scripts",
            "license_counts",
        },
        "TypeScript lock evidence",
    )
    observed_lock = {
        "path": "typescript-runtime/package-lock.json",
        "sha256": sha256(PACKAGE_LOCK),
        "lockfile_version": 3,
        "package_count": len(packages) - 1,
        "registry": "https://registry.npmjs.org/",
        "install_scripts": install_scripts,
        "license_counts": dict(sorted(license_counts.items())),
    }
    if lock_evidence != observed_lock:
        raise QualificationError("TypeScript lock evidence does not match the pinned lock")
    if install_scripts != 0:
        raise QualificationError("TypeScript dependency install scripts are forbidden")

    runtime = exact_object(
        evidence["runtime"],
        {"node_version", "npm_version", "deepagents_version"},
        "runtime evidence",
    )
    if runtime != {
        "node_version": "22.23.2",
        "npm_version": "10.9.8",
        "deepagents_version": EXPECTED_DEPENDENCIES["deepagents"],
    }:
        raise QualificationError("TypeScript runtime evidence changed")
    source = exact_object(
        evidence["source"], set(EXPECTED_SOURCE), "Deep Agents TypeScript source evidence"
    )
    if source != EXPECTED_SOURCE:
        raise QualificationError("Deep Agents TypeScript source evidence changed")
    deepagents_entry = packages.get("node_modules/deepagents")
    if not isinstance(deepagents_entry, dict) or any(
        deepagents_entry.get(field) != EXPECTED_SOURCE[evidence_field]
        for field, evidence_field in (("resolved", "tarball"), ("integrity", "integrity"))
    ):
        raise QualificationError("Deep Agents tarball evidence does not match the lock")
    audit = exact_object(
        evidence["audit"], {"command", "production_vulnerabilities"}, "npm audit evidence"
    )
    if audit != {
        "command": "npm audit --package-lock-only --omit=dev --json",
        "production_vulnerabilities": 0,
    }:
        raise QualificationError("npm audit evidence is invalid")

    documentation = evidence["documentation"]
    if not isinstance(documentation, list) or len(documentation) != 2:
        raise QualificationError("TypeScript documentation evidence is invalid")
    expected_urls = {
        "https://docs.langchain.com/oss/deepagents/code/overview.md",
        "https://docs.langchain.com/oss/javascript/deepagents/overview.md",
    }
    observed_urls: set[str] = set()
    for item in documentation:
        record = exact_object(item, {"url", "bytes", "sha256"}, "documentation evidence")
        url = record["url"]
        if not isinstance(url, str):
            raise QualificationError("documentation evidence URL is invalid")
        validated_upstream_url(url)
        if (
            type(record["bytes"]) is not int
            or record["bytes"] <= 0
            or not isinstance(record["sha256"], str)
            or re.fullmatch(r"[0-9a-f]{64}", record["sha256"]) is None
        ):
            raise QualificationError("documentation evidence digest is invalid")
        observed_urls.add(url)
    if observed_urls != expected_urls:
        raise QualificationError("TypeScript documentation inventory is invalid")

    compiler = tsconfig.get("compilerOptions")
    if not isinstance(compiler, dict) or any(
        compiler.get(field) != expected
        for field, expected in {
            "module": "NodeNext",
            "moduleResolution": "NodeNext",
            "strict": True,
            "noUncheckedIndexedAccess": True,
            "noImplicitOverride": True,
            "noEmitOnError": True,
        }.items()
    ):
        raise QualificationError("TypeScript compiler safety settings changed")

    runtime_policy = workflow.get("deepagents", {}).get("runtimes", {}).get("typescript")
    if not isinstance(runtime_policy, dict):
        raise QualificationError("TypeScript workflow runtime policy is missing")
    if runtime_policy.get("sdk_version") != EXPECTED_DEPENDENCIES["deepagents"]:
        raise QualificationError("workflow TypeScript SDK version does not match package.json")
    if runtime_policy.get("node_version") != runtime["node_version"]:
        raise QualificationError("workflow Node version does not match qualification evidence")
    if runtime_policy.get("package_lock") != "typescript-runtime/package-lock.json":
        raise QualificationError("workflow TypeScript lock path is invalid")
    source_text = WORKER_SOURCE.read_text(encoding="utf-8")
    if f'EXPECTED_DEEPAGENTS_VERSION = "{EXPECTED_DEPENDENCIES["deepagents"]}"' not in source_text:
        raise QualificationError("TypeScript worker SDK version constant changed")
    if f'EXPECTED_NODE_VERSION = "{runtime["node_version"]}"' not in source_text:
        raise QualificationError("TypeScript worker Node version constant changed")

    return {
        "ok": True,
        "node_version": runtime["node_version"],
        "deepagents_version": runtime["deepagents_version"],
        "package_count": observed_lock["package_count"],
        "lock_sha256": observed_lock["sha256"],
        "source_commit": source["commit"],
    }


def validate_online() -> dict[str, Any]:
    evidence = read_json(EVIDENCE)
    for package_name, expected_version in sorted(EXPECTED_DEPENDENCIES.items()):
        encoded = urllib.parse.quote(package_name, safe="")
        metadata = upstream_json(f"https://registry.npmjs.org/{encoded}/latest")
        if metadata.get("version") != expected_version:
            raise QualificationError(
                f"new npm release detected for {package_name}: "
                f"expected {expected_version}, found {metadata.get('version')}"
            )
        if package_name == "deepagents":
            distribution = metadata.get("dist")
            if not isinstance(distribution, dict) or any(
                distribution.get(field) != EXPECTED_SOURCE[evidence_field]
                for field, evidence_field in (("tarball", "tarball"), ("integrity", "integrity"))
            ):
                raise QualificationError("published Deep Agents tarball metadata drifted")

    encoded_tag = urllib.parse.quote(EXPECTED_SOURCE["tag"].removeprefix("refs/tags/"), safe="")
    tag_ref = upstream_json(
        "https://api.github.com/repos/langchain-ai/deepagentsjs/git/ref/tags/" + encoded_tag
    )
    tag_object = tag_ref.get("object")
    if (
        not isinstance(tag_object, dict)
        or tag_object.get("type") != "tag"
        or tag_object.get("sha") != EXPECTED_SOURCE["tag_object"]
    ):
        raise QualificationError("Deep Agents TypeScript source tag object drifted")
    tag = upstream_json(
        "https://api.github.com/repos/langchain-ai/deepagentsjs/git/tags/"
        + EXPECTED_SOURCE["tag_object"]
    )
    target = tag.get("object")
    if (
        not isinstance(target, dict)
        or target.get("type") != "commit"
        or target.get("sha") != EXPECTED_SOURCE["commit"]
    ):
        raise QualificationError("Deep Agents TypeScript source tag commit drifted")

    for record in evidence["documentation"]:
        payload = upstream_bytes(record["url"])
        if (
            len(payload) != record["bytes"]
            or hashlib.sha256(payload).hexdigest() != record["sha256"]
        ):
            raise QualificationError(f"official documentation changed: {record['url']}")

    node = shutil.which("node")
    npm = shutil.which("npm")
    if node is None or npm is None:
        raise QualificationError("online npm audit requires the qualified Node and npm runtimes")
    with tempfile.TemporaryDirectory(prefix="daiw-npm-audit-") as temporary:
        audit_root = Path(temporary)
        audit_home = audit_root / "home"
        audit_home.mkdir(mode=0o700)
        shutil.copy2(PACKAGE_JSON, audit_root / "package.json")
        shutil.copy2(PACKAGE_LOCK, audit_root / "package-lock.json")
        path_entries = list(dict.fromkeys((str(Path(node).parent), str(Path(npm).parent))))
        audit_environment = {
            "PATH": os.pathsep.join((*path_entries, "/usr/local/bin", "/usr/bin", "/bin")),
            "HOME": str(audit_home),
            "npm_config_userconfig": os.devnull,
            "npm_config_cache": str(audit_home / "cache"),
            "npm_config_registry": "https://registry.npmjs.org/",
            "npm_config_ignore_scripts": "true",
            "npm_config_audit": "true",
            "npm_config_fund": "false",
            "npm_config_update_notifier": "false",
        }
        for executable, expected in (
            (node, f"v{evidence['runtime']['node_version']}"),
            (npm, evidence["runtime"]["npm_version"]),
        ):
            version_result = subprocess.run(
                [executable, "--version"],
                cwd=audit_root,
                env=audit_environment,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=20,
                check=False,
            )
            if version_result.returncode != 0 or version_result.stdout.strip() != expected:
                raise QualificationError(
                    f"online audit runtime mismatch for {Path(executable).name}"
                )
        audit_result = subprocess.run(
            [npm, "audit", "--package-lock-only", "--omit=dev", "--json"],
            cwd=audit_root,
            env=audit_environment,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=60,
            check=False,
        )
        if len(audit_result.stdout.encode("utf-8")) > MAX_UPSTREAM_BYTES:
            raise QualificationError("npm audit response exceeds the size limit")
        try:
            audit_payload = json.loads(audit_result.stdout)
            vulnerabilities = audit_payload["metadata"]["vulnerabilities"]
            vulnerability_total = vulnerabilities["total"]
        except (KeyError, TypeError, json.JSONDecodeError) as exc:
            raise QualificationError("npm audit returned an invalid result") from exc
        if type(vulnerability_total) is not int:
            raise QualificationError("npm audit vulnerability count is invalid")
        expected_total = evidence["audit"]["production_vulnerabilities"]
        if audit_result.returncode != 0 or vulnerability_total != expected_total:
            raise QualificationError(
                "npm production advisory result changed: "
                f"expected {expected_total}, found {vulnerability_total}"
            )
    return {
        "online_checked": True,
        "packages": len(EXPECTED_DEPENDENCIES),
        "documents": 2,
        "production_vulnerabilities": vulnerability_total,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--online", action="store_true")
    args = parser.parse_args()
    try:
        result = validate()
        if args.online:
            result.update(validate_online())
    except (OSError, QualificationError, subprocess.TimeoutExpired, urllib.error.URLError) as exc:
        print(f"TypeScript dependency qualification failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
