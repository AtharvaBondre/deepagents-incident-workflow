#!/usr/bin/env python3
"""No-cost end-to-end smoke for the controller and actual Deep Agents worker."""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
RUNNER_PATH = PACKAGE_ROOT / "scripts" / "runner.py"
ARTIFACTS = PACKAGE_ROOT / "artifacts"


def _load_runner() -> Any:
    spec = importlib.util.spec_from_file_location("deepagents_e2e_runner", RUNNER_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load workflow controller")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run_smoke(
    runtime_python: str,
    *,
    sdk_language: str = "python",
    runtime_node: str = "node",
) -> dict[str, Any]:
    runner = _load_runner()
    provider_options: dict[str, Any] = {
        "provider": "openai",
        "model": "scripted-smoke",
        "sdk_language": sdk_language,
        "max_turns": 10,
        "scripted_smoke": True,
    }
    if sdk_language == "python":
        provider_options["runtime_python"] = runtime_python
    elif sdk_language == "typescript":
        qualified_node, worker = runner.qualified_deepagents_typescript_runtime(runtime_node)
        provider_options["runtime_node"] = qualified_node
        provider_options["typescript_worker"] = worker
    else:
        raise ValueError("SDK language must be python or typescript")
    provider = runner.DeepAgentsCandidateProvider(**provider_options)
    with tempfile.TemporaryDirectory(prefix="daiw-e2e-sdk-") as temporary:
        run_dir, control = runner.run_flow(
            "retry-success",
            budget_seconds=120,
            max_attempts=1,
            artifact_root=Path(temporary),
            candidate_provider=provider,
        )
        issues = runner.verify_run(run_dir)
        execution = runner.read_json(run_dir / "attempt-1-deepagents-execution.json")
        worker_result = execution.get("worker_result", {})
        passed = (
            control.get("outcome") == "SUCCEEDED"
            and control.get("attempts") == 1
            and control.get("cleanup_complete") is True
            and not issues
            and execution.get("outcome") == "CANDIDATE_RETURNED"
            and execution.get("sdk_language") == sdk_language
            and execution.get("scripted_smoke") is True
            and execution.get("model_transport") == "scripted-no-transport"
            and worker_result.get("network_attempts") == 0
            and worker_result.get("tool_names") == list(runner.DEEPAGENTS_ALLOWED_FILESYSTEM_TOOLS)
        )
        record = {
            "schema_version": 1,
            "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "runtime": "deepagents-controller-e2e",
            "sdk_language": sdk_language,
            "runtime_version": runner.DEEPAGENTS_SDK_VERSIONS[sdk_language],
            "scenario": "retry-success",
            "candidate_source": control.get("candidate_source"),
            "attempts": control.get("attempts"),
            "outcome": control.get("outcome"),
            "worker_subprocess_completed": execution.get("returncode") == 0,
            "model_transport": worker_result.get("model_transport"),
            "network_attempts": worker_result.get("network_attempts"),
            "exact_tools": worker_result.get("tool_names"),
            "controller_verification_passed": not issues,
            "cleanup_complete": control.get("cleanup_complete") is True,
            "passed": passed,
        }
    ARTIFACTS.mkdir(exist_ok=True)
    output_name = (
        "deepagents-e2e-smoke.json"
        if sdk_language == "python"
        else "deepagents-typescript-e2e-smoke.json"
    )
    output = ARTIFACTS / output_name
    output.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return {"artifact": str(output), **record}


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description=__doc__)
    value.add_argument("--python", default=sys.executable, dest="runtime_python")
    value.add_argument("--node", default="node", dest="runtime_node")
    value.add_argument("--language", choices=("python", "typescript"), default="python")
    return value


def main() -> int:
    args = parser().parse_args()
    result = run_smoke(
        args.runtime_python,
        sdk_language=args.language,
        runtime_node=args.runtime_node,
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
