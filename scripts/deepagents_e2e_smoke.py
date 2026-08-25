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


def run_smoke(runtime_python: str) -> dict[str, Any]:
    runner = _load_runner()
    provider = runner.DeepAgentsCandidateProvider(
        provider="openai",
        model="scripted-smoke",
        runtime_python=runtime_python,
        max_turns=10,
        scripted_smoke=True,
    )
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
            and execution.get("scripted_smoke") is True
            and execution.get("model_transport") == "scripted-no-transport"
            and worker_result.get("network_attempts") == 0
            and worker_result.get("tool_names") == list(runner.DEEPAGENTS_ALLOWED_FILESYSTEM_TOOLS)
        )
        record = {
            "schema_version": 1,
            "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "runtime": "deepagents-controller-e2e",
            "runtime_version": runner.DEEPAGENTS_SDK_VERSION,
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
    output = ARTIFACTS / "deepagents-e2e-smoke.json"
    output.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return {"artifact": str(output), **record}


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description=__doc__)
    value.add_argument("--python", default=sys.executable, dest="runtime_python")
    return value


def main() -> int:
    result = run_smoke(parser().parse_args().runtime_python)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
