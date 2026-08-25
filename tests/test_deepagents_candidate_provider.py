import contextlib
import importlib.util
import io
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

RUNNER_PATH = Path(__file__).resolve().parents[1] / "scripts" / "runner.py"
SPEC = importlib.util.spec_from_file_location("daiw_candidate_runner", RUNNER_PATH)
assert SPEC and SPEC.loader
runner = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runner)


def worker_result(invocation_id: str, **changes: object) -> dict:
    value = {
        "schema_version": 1,
        "runtime": "deepagents",
        "runtime_version": runner.DEEPAGENTS_SDK_VERSION,
        "provider_package": "langchain-openai",
        "provider_package_version": "1.6.0",
        "profile_plugins_enabled": False,
        "outcome": "completed",
        "invocation_id": invocation_id,
        "tool_names": list(runner.DEEPAGENTS_ALLOWED_FILESYSTEM_TOOLS),
        "final_response_bytes": 4,
        "final_response_sha256": runner.hashlib.sha256(b"done").hexdigest(),
    }
    value.update(changes)
    return value


class DeepAgentsCandidateProviderTests(unittest.TestCase):
    def fixture_context(
        self, artifact_dir: Path, attempt: int = 1, feedback: list[dict] | None = None
    ) -> dict:
        incident = runner.read_json(runner.FIXTURES / "incidents" / "retry-success.json")
        packet = runner.build_deepagents_request(
            run_id="synthetic-test-run",
            attempt=attempt,
            incident=incident,
            evidence=runner.collect_evidence(incident),
            feedback=feedback or [],
            deadline=time.monotonic() + 30,
        )
        return {"artifact_dir": artifact_dir, "packet": packet}

    def verified_deepagents_run(self, artifact_root: Path) -> Path:
        patch_payload = (runner.FIXTURES / "patches" / "correct.patch").read_bytes()
        patch_sha256 = runner.hashlib.sha256(patch_payload).hexdigest()
        changed_paths = runner.validate_deepagents_patch_bytes(patch_payload)[1]
        digest_root = artifact_root / "digest-work"
        digest_workspace = runner.create_workspace(digest_root, "candidate")
        applied = runner.apply_candidate(
            digest_workspace,
            runner.FIXTURES / "patches" / "correct.patch",
            time.monotonic() + 10,
        )
        candidate_digest = applied["candidate_digest"]
        runner.shutil.rmtree(digest_root)

        run_id = "20260825T120000Z-" + "a" * 32
        run_dir = artifact_root / run_id
        run_dir.mkdir()
        patch_name = "attempt-1-deepagents.patch"
        invocation_id = "a" * 32
        fixture_digest = runner.tree_digest(runner.FIXTURES / "repository")
        verifier_sha256 = runner.verifier_bundle_digest(
            runner.PACKAGE_ROOT / "verifiers" / "subject_logic.py"
        )

        def trusted_test(phase: str, nonce: str) -> dict:
            return {
                "passed": True,
                "checks": [
                    {
                        "exit_code": 0,
                        "process_exit_code": 0,
                        "passed": True,
                        "trusted_verifier_completed": True,
                        "receipt": {
                            "schema_version": runner.VERIFIER_RECEIPT_VERSION,
                            "status": "completed",
                            "nonce": nonce,
                            "run_id": run_id,
                            "attempt": 1,
                            "phase": phase,
                            "candidate_digest": candidate_digest,
                            "patch_sha256": patch_sha256,
                            "fixture_digest": fixture_digest,
                            "policy_sha256": runner.WORKFLOW_POLICY_SHA256,
                            "verifier_bundle_sha256": verifier_sha256,
                            "verifier_command_sha256": runner.VERIFIER_COMMAND_SHA256,
                            "candidate_test_image": runner.CANDIDATE_TEST_IMAGE,
                            "terminal": {
                                "process_exit_code": 0,
                                "signaled": False,
                                "timed_out": False,
                                "completion_marker_count": 1,
                            },
                        },
                        "output": runner.TRUSTED_VERIFIER_COMPLETION + "\n",
                    }
                ],
            }

        attempt_test = trusted_test("attempt", "1" * 64)
        independent_test = trusted_test("independent", "2" * 64)
        (run_dir / patch_name).write_bytes(patch_payload)
        runner.write_json(
            run_dir / "control.json",
            {
                "attempts": 1,
                "run_id": run_id,
                "scenario": "retry-success",
                "issue_id": "INC-1001",
                "repository": runner.EXPECTED_REPOSITORY,
                "base_revision": "fixture-base-v1",
                "outcome": "SUCCEEDED",
                "candidate_source": "deepagents-real-model",
                "candidate_digest": candidate_digest,
                "pre_delivery_cleanup_complete": True,
            },
        )
        runner.write_json(
            run_dir / "attempt-1-candidate.json",
            {
                "schema_version": runner.CANDIDATE_CONTRACT_VERSION,
                "source": "deepagents-real-model",
                "attempt": 1,
                "patch": patch_name,
                "patch_sha256": patch_sha256,
                "changed_paths": changed_paths,
                "candidate_digest": candidate_digest,
            },
        )
        runner.write_json(
            run_dir / "attempt-1-deepagents-execution.json",
            {
                "schema_version": 1,
                "kind": "deepagents-candidate-execution",
                "attempt": 1,
                "invocation_id": invocation_id,
                "provider": "openai",
                "model": "example-model",
                "model_spec_sha256": runner.hashlib.sha256(b"openai:example-model").hexdigest(),
                "runtime_version": runner.DEEPAGENTS_SDK_VERSION,
                "worker_sha256": runner.hashlib.sha256(
                    runner.DEEPAGENTS_WORKER.read_bytes()
                ).hexdigest(),
                "allowed_filesystem_tools": list(runner.DEEPAGENTS_ALLOWED_FILESYSTEM_TOOLS),
                "memory_enabled": False,
                "checkpointer_enabled": False,
                "store_enabled": False,
                "subagents_enabled": False,
                "shell_enabled": False,
                "langsmith_tracing_enabled": False,
                "profile_plugins_enabled": False,
                "fresh_session": True,
                "controller_is_sole_acceptor": True,
                "worker_result": worker_result(invocation_id),
                "outcome": "CANDIDATE_RETURNED",
                "patch_sha256": patch_sha256,
                "candidate_digest": candidate_digest,
                "cleanup": {"complete": True, "worker_directory_removed": True},
            },
        )
        runner.write_json(
            run_dir / "attempt-1-result.json",
            {"attempt": 1, "candidate_digest": candidate_digest, "test": attempt_test},
        )
        runner.write_json(
            run_dir / "verification.json",
            {
                "accepted": True,
                "candidate_digest": candidate_digest,
                "tested_digest": candidate_digest,
                "test": independent_test,
            },
        )
        receipts = [
            attempt_test["checks"][0]["receipt"],
            independent_test["checks"][0]["receipt"],
        ]
        runner.write_json(
            run_dir / "mock-github.json",
            {
                "kind": "mock_github_delivery",
                "repository": runner.EXPECTED_REPOSITORY,
                "base": "fixture-base-v1",
                "head": f"deepagents/inc-1001-{run_id[-8:]}",
                "draft": True,
                "candidate_digest": candidate_digest,
                "operations": ["create_branch", "create_commit", "create_pull_request"],
                "forbidden_operations_exposed": [],
                "verifier_receipt_sha256": [
                    runner.hashlib.sha256(
                        json.dumps(
                            receipt,
                            sort_keys=True,
                            separators=(",", ":"),
                        ).encode("utf-8")
                    ).hexdigest()
                    for receipt in receipts
                ],
            },
        )
        runner.write_json(
            run_dir / "mock-slack.json",
            {
                "kind": "mock_slack_delivery",
                "run_id": run_id,
                "issue_id": "INC-1001",
                "outcome": "SUCCEEDED",
                "attempts": 1,
                "message": (
                    "Local Deep Agents incident workflow ended with SUCCEEDED after 1 attempt(s)."
                ),
            },
        )
        runner.write_json(
            run_dir / "pre-delivery-cleanup.json",
            {"cleanup_complete": True},
        )
        runner.write_json(run_dir / "closeout.json", {"cleanup_complete": True})
        return run_dir

    def test_request_packet_is_redacted_bounded_and_controller_owned(self) -> None:
        incident = runner.read_json(runner.FIXTURES / "incidents" / "retry-success.json")
        feedback = [
            {
                "attempt": number,
                "stage": "controller_test",
                "output": "person@example.invalid token=synthetic-sensitive-value " + "x" * 4000,
                "extra_untrusted_field": "must not cross the boundary",
            }
            for number in range(1, 8)
        ]
        packet = runner.build_deepagents_request(
            run_id="bounded-request",
            attempt=2,
            incident=incident,
            evidence=runner.read_json(runner.FIXTURES / "evidence.json"),
            feedback=feedback,
            deadline=time.monotonic() + 30,
        )
        serialized = json.dumps(packet)
        self.assertTrue(packet["policy"]["controller_is_sole_acceptor"])
        self.assertTrue(packet["policy"]["model_must_not_claim_acceptance"])
        self.assertEqual(len(packet["feedback"]), runner.MAX_DEEPAGENTS_FEEDBACK_ITEMS)
        self.assertNotIn("extra_untrusted_field", serialized)
        self.assertNotIn("person@example.invalid", serialized)
        self.assertNotIn("synthetic-sensitive-value", serialized)
        self.assertEqual(packet["policy"]["allowed_paths"], list(runner.ALLOWED_PATCH_PREFIXES))

    def test_execution_plan_is_bound_to_incident_test_and_path_policy(self) -> None:
        incident = runner.read_json(runner.FIXTURES / "incidents" / "event-indexing-collision.json")
        evidence = runner.read_json(runner.FIXTURES / "evidence" / "event-indexing-collision.json")
        original = runner.read_json(
            runner.FIXTURES / "execution-plans" / "event-indexing-collision.json"
        )
        valid = runner.build_deepagents_request(
            run_id="plan-binding",
            attempt=1,
            incident=incident,
            evidence=evidence,
            feedback=[],
            deadline=time.monotonic() + 30,
            execution_plan=original,
        )
        self.assertEqual(
            valid["controller_approved_execution_plan"]["issue_id"], incident["issue_id"]
        )
        for message, mutate in (
            ("does not match", lambda plan: plan.update(issue_id="OTHER")),
            ("changed the required test", lambda plan: plan.update(required_test="true")),
            ("forbidden path", lambda plan: plan["edits"][0].update(path=".github/ci.yml")),
        ):
            plan = json.loads(json.dumps(original))
            mutate(plan)
            with (
                self.subTest(message=message),
                self.assertRaisesRegex(runner.PolicyDenied, message),
            ):
                runner.build_deepagents_request(
                    run_id="plan-binding",
                    attempt=1,
                    incident=incident,
                    evidence=evidence,
                    feedback=[],
                    deadline=time.monotonic() + 30,
                    execution_plan=plan,
                )

    def test_environment_is_ephemeral_and_provider_scoped(self) -> None:
        with (
            tempfile.TemporaryDirectory() as temporary,
            mock.patch.dict(
                os.environ,
                {
                    "OPENAI_API_KEY": "synthetic-openai-key",
                    "OPENAI_BASE_URL": "https://untrusted.invalid",
                    "ANTHROPIC_API_KEY": "synthetic-anthropic-key",
                    "OLLAMA_HOST": "http://untrusted.invalid",
                    "GITHUB_TOKEN": "synthetic-github-token",
                    "PATH": "/usr/bin",
                },
                clear=True,
            ),
        ):
            environment = runner.deepagents_process_environment(
                home_dir=Path(temporary), provider="openai"
            )
        self.assertEqual(environment["HOME"], str(Path(temporary).resolve()))
        self.assertEqual(environment["OPENAI_API_KEY"], "synthetic-openai-key")
        self.assertNotIn("ANTHROPIC_API_KEY", environment)
        self.assertNotIn("OPENAI_BASE_URL", environment)
        self.assertNotIn("OLLAMA_HOST", environment)
        self.assertNotIn("GITHUB_TOKEN", environment)
        self.assertEqual(environment["LANGSMITH_TRACING"], "false")
        with (
            tempfile.TemporaryDirectory() as temporary,
            self.assertRaisesRegex(runner.PolicyDenied, "unsupported"),
        ):
            runner.deepagents_process_environment(
                home_dir=Path(temporary), provider="untrusted-provider"
            )

    def test_provider_constructor_rejects_unsupported_provider(self) -> None:
        with self.assertRaisesRegex(ValueError, "unsupported Deep Agents provider"):
            runner.DeepAgentsCandidateProvider(
                provider="untrusted-provider",
                model="example-model",
                runtime_python=sys.executable,
            )

    def test_provider_constructor_rejects_colon_in_model_identifier(self) -> None:
        with self.assertRaisesRegex(ValueError, "must not contain ':'"):
            runner.DeepAgentsCandidateProvider(
                provider="ollama",
                model="llama3.2:latest",
                runtime_python=sys.executable,
            )

    def test_patch_and_workspace_policy_reject_unsafe_candidates(self) -> None:
        mode_change = (
            "diff --git a/app/subject.py b/app/subject.py\nold mode 100644\nnew mode 100755\n"
        ).encode()
        with self.assertRaisesRegex(runner.PolicyDenied, "mode change"):
            runner.validate_deepagents_patch_bytes(mode_change)
        with self.assertRaisesRegex(runner.PolicyDenied, "128 KiB"):
            runner.validate_deepagents_patch_bytes(b"x" * (runner.MAX_DEEPAGENTS_PATCH_BYTES + 1))
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary) / "workspace"
            workspace.mkdir()
            (workspace / "regular.py").write_text("value = 1\n", encoding="utf-8")
            (workspace / "linked.py").symlink_to(workspace / "regular.py")
            with self.assertRaisesRegex(runner.PolicyDenied, "linked or irregular"):
                runner.validate_deepagents_workspace(workspace)

    def test_shadow_git_ignores_ambient_global_hooks(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = root / "workspace"
            runner.shutil.copytree(runner.FIXTURES / "repository", workspace)
            hooks = root / "hooks"
            hooks.mkdir()
            sentinel = root / "hook-ran"
            hook = hooks / "pre-commit"
            hook.write_text(f"#!/bin/sh\ntouch '{sentinel}'\n", encoding="utf-8")
            hook.chmod(0o755)
            global_config = root / "gitconfig"
            global_config.write_text(
                f"[core]\n\thooksPath = {hooks}\n",
                encoding="utf-8",
            )
            repository = root / "baseline"

            with mock.patch.dict(
                os.environ,
                {
                    "GIT_CONFIG_GLOBAL": str(global_config),
                    "GIT_CONFIG_NOSYSTEM": "0",
                },
                clear=False,
            ):
                runner.initialize_shadow_git(
                    workspace,
                    repository,
                    time.monotonic() + 20,
                )

            self.assertFalse(sentinel.exists())

    def test_real_provider_host_derives_and_applies_patch(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            artifact_dir = Path(temporary) / "run"
            artifact_dir.mkdir()
            workspace = runner.create_workspace(artifact_dir, "attempt-1")
            provider = runner.DeepAgentsCandidateProvider(
                provider="openai", model="example-model", runtime_python=sys.executable
            )
            observed: dict[str, object] = {}

            def invoke(args, *, cwd, environment, timeout):
                del cwd, timeout
                observed["args"] = args
                observed["environment"] = environment
                sandbox = Path(args[args.index("--workspace") + 1])
                result_path = Path(args[args.index("--result") + 1])
                invocation_id = args[args.index("--invocation-id") + 1]
                subject = sandbox / "app" / "subject.py"
                subject.write_text(
                    subject.read_text(encoding="utf-8").replace(
                        "    return value.strip()\n",
                        '    return " ".join(value.split()).lower()\n',
                    ),
                    encoding="utf-8",
                )
                runner.write_json(result_path, worker_result(invocation_id))
                return subprocess.CompletedProcess(args, 0, "", "")

            with mock.patch.object(runner, "run_deepagents_process", side_effect=invoke):
                candidate = provider.create_candidate(
                    attempt=1,
                    workspace=workspace,
                    deadline=time.monotonic() + 30,
                    request=self.fixture_context(artifact_dir),
                )

            self.assertEqual(candidate.record["changed_paths"], ["app/subject.py"])
            self.assertTrue(candidate.patch_path.is_file())
            execution = runner.read_json(artifact_dir / "attempt-1-deepagents-execution.json")
            self.assertEqual(execution["outcome"], "CANDIDATE_RETURNED")
            self.assertTrue(execution["cleanup"]["complete"])
            self.assertFalse((artifact_dir / "attempt-1" / "deepagents-worker").exists())
            command = observed["args"]
            self.assertEqual(command[0], str(Path(sys.executable).absolute()))
            self.assertEqual(command[1], "-I")
            self.assertEqual(command[command.index("--model") + 1], "openai:example-model")
            self.assertNotIn("dcode", command)

    def test_success_claim_without_patch_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            artifact_dir = Path(temporary) / "run"
            artifact_dir.mkdir()
            workspace = runner.create_workspace(artifact_dir, "attempt-1")
            before = runner.tree_digest(workspace)
            provider = runner.DeepAgentsCandidateProvider(provider="openai", model="example-model")

            def invoke(args, **_):
                result_path = Path(args[args.index("--result") + 1])
                invocation_id = args[args.index("--invocation-id") + 1]
                runner.write_json(result_path, worker_result(invocation_id))
                return subprocess.CompletedProcess(args, 0, "claimed success", "")

            with mock.patch.object(runner, "run_deepagents_process", side_effect=invoke):
                with self.assertRaisesRegex(runner.PolicyDenied, "no patch"):
                    provider.create_candidate(
                        attempt=1,
                        workspace=workspace,
                        deadline=time.monotonic() + 30,
                        request=self.fixture_context(artifact_dir),
                    )
            self.assertEqual(runner.tree_digest(workspace), before)
            execution = runner.read_json(artifact_dir / "attempt-1-deepagents-execution.json")
            self.assertEqual(execution["outcome"], "FAILED")
            self.assertTrue(execution["cleanup"]["complete"])

    def test_forged_worker_result_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            artifact_dir = Path(temporary) / "run"
            artifact_dir.mkdir()
            workspace = runner.create_workspace(artifact_dir, "attempt-1")
            provider = runner.DeepAgentsCandidateProvider(provider="openai", model="example-model")

            def invoke(args, **_):
                sandbox = Path(args[args.index("--workspace") + 1])
                target = sandbox / "app" / "subject.py"
                target.write_text("forged = True\n", encoding="utf-8")
                result_path = Path(args[args.index("--result") + 1])
                runner.write_json(result_path, worker_result("0" * 32))
                return subprocess.CompletedProcess(args, 0, "", "")

            with mock.patch.object(runner, "run_deepagents_process", side_effect=invoke):
                with self.assertRaisesRegex(runner.PolicyDenied, "runtime contract"):
                    provider.create_candidate(
                        attempt=1,
                        workspace=workspace,
                        deadline=time.monotonic() + 30,
                        request=self.fixture_context(artifact_dir),
                    )

    def test_timeout_terminates_worker_process_group(self) -> None:
        process = mock.Mock(pid=4321, returncode=-15)
        process.communicate.side_effect = [
            subprocess.TimeoutExpired(["python"], 0.1),
            ("partial stdout", "partial stderr"),
        ]
        with (
            mock.patch.object(runner.subprocess, "Popen", return_value=process) as popen,
            mock.patch.object(runner.os, "killpg") as killpg,
        ):
            with self.assertRaises(subprocess.TimeoutExpired) as raised:
                runner.run_deepagents_process(
                    ["python"], cwd=runner.PACKAGE_ROOT, environment={"PATH": ""}, timeout=0.1
                )
        self.assertEqual(raised.exception.output, "partial stdout")
        self.assertEqual(raised.exception.stderr, "partial stderr")
        killpg.assert_called_once_with(4321, runner.signal.SIGTERM)
        self.assertTrue(popen.call_args.kwargs["start_new_session"])

    def test_controller_feedback_is_carried_to_second_attempt(self) -> None:
        class RecordingFixtureProvider(runner.FixtureCandidateProvider):
            def __init__(self) -> None:
                super().__init__(
                    [
                        runner.FIXTURES / "patches" / "incomplete.patch",
                        runner.FIXTURES / "patches" / "correct.patch",
                    ],
                    repeat_last_patch=False,
                )
                self.requests: list[dict] = []

            def create_candidate(self, **kwargs):
                self.requests.append(kwargs["request"])
                return super().create_candidate(**kwargs)

        with tempfile.TemporaryDirectory() as temporary:
            provider = RecordingFixtureProvider()
            run_dir, control = runner.run_flow(
                "retry-success", artifact_root=Path(temporary), candidate_provider=provider
            )
            self.assertEqual(control["outcome"], "SUCCEEDED")
            self.assertEqual(len(provider.requests), 2)
            self.assertEqual(provider.requests[0]["packet"]["feedback"], [])
            self.assertFalse(provider.requests[1]["packet"]["feedback"][0]["passed"])
            self.assertEqual(runner.verify_run(run_dir), [])

    def test_verified_real_model_artifact_chain_is_accepted(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            self.assertEqual(runner.verify_run(self.verified_deepagents_run(Path(temporary))), [])

    def test_real_model_verifier_detects_linkage_tampering(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            run_dir = self.verified_deepagents_run(Path(temporary))
            execution_path = run_dir / "attempt-1-deepagents-execution.json"
            execution = runner.read_json(execution_path)
            execution.update(
                {
                    "outcome": "FAILED",
                    "invocation_id": "bad",
                    "provider": "",
                    "model": "bad model",
                    "runtime_version": "0.0.0",
                    "worker_sha256": "0" * 64,
                    "allowed_filesystem_tools": ["execute"],
                    "memory_enabled": True,
                    "worker_result": {},
                    "patch_sha256": "0" * 64,
                    "candidate_digest": "1" * 64,
                    "cleanup": {"complete": False},
                }
            )
            runner.write_json(execution_path, execution)
            issues = runner.verify_run(run_dir)
        for expected in (
            "Deep Agents execution did not return the accepted candidate",
            "Deep Agents execution invocation ID is invalid",
            "Deep Agents execution provider is invalid",
            "Deep Agents execution model is invalid",
            "Deep Agents execution runtime version is invalid",
            "Deep Agents execution worker digest is invalid",
            "Deep Agents execution tool policy is invalid",
            "Deep Agents execution memory_enabled must be false",
            "Deep Agents execution worker result is invalid",
            "Deep Agents execution cleanup did not complete",
            "Deep Agents execution patch SHA does not match candidate",
            "Deep Agents execution digest does not match candidate",
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected, issues)

    def test_cli_exposes_real_provider_without_changing_default(self) -> None:
        default = runner.parser().parse_args(["run"])
        selected = runner.parser().parse_args(
            [
                "run",
                "--candidate-provider",
                "deepagents",
                "--deepagents-provider",
                "openai",
                "--deepagents-model",
                "example-model",
                "--deepagents-python",
                sys.executable,
            ]
        )
        self.assertEqual(default.candidate_provider, "fixture")
        self.assertEqual(selected.candidate_provider, "deepagents")
        self.assertEqual(selected.deepagents_provider, "openai")
        self.assertEqual(selected.deepagents_model, "example-model")
        self.assertEqual(selected.deepagents_python, sys.executable)

    def test_cli_forwards_runtime_to_provider(self) -> None:
        provider = mock.Mock(source="deepagents-real-model")
        control = {"outcome": "SUCCEEDED", "attempts": 1}
        with (
            mock.patch.object(
                runner.sys,
                "argv",
                [
                    "runner.py",
                    "run",
                    "--candidate-provider",
                    "deepagents",
                    "--deepagents-provider",
                    "openai",
                    "--deepagents-model",
                    "example-model",
                    "--deepagents-python",
                    sys.executable,
                ],
            ),
            mock.patch.object(
                runner, "DeepAgentsCandidateProvider", return_value=provider
            ) as constructor,
            mock.patch.object(
                runner,
                "qualified_deepagents_runtime",
                return_value=sys.executable,
            ),
            mock.patch.object(
                runner,
                "run_flow",
                return_value=(Path("/tmp/deepagents-incident-workflow-test-run"), control),
            ),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            self.assertEqual(runner.main(), 0)
        constructor.assert_called_once_with(
            provider="openai",
            model="example-model",
            runtime_python=sys.executable,
            max_turns=20,
        )

    def test_real_model_cli_rejects_an_unqualified_interpreter(self) -> None:
        with self.assertRaisesRegex(ValueError, "require .deepagents-runtime"):
            runner.qualified_deepagents_runtime(sys._base_executable)


if __name__ == "__main__":
    unittest.main()
