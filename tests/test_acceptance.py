import difflib
import importlib.util
import json
import os
import signal
import subprocess
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

RUNNER_PATH = Path(__file__).resolve().parents[1] / "scripts" / "runner.py"
SPEC = importlib.util.spec_from_file_location("daiw_local_runner", RUNNER_PATH)
assert SPEC and SPEC.loader
runner = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runner)


class LocalFlowAcceptanceTests(unittest.TestCase):
    def artifact_root(self) -> tuple[tempfile.TemporaryDirectory[str], Path]:
        temporary = tempfile.TemporaryDirectory()
        return temporary, Path(temporary.name)

    @staticmethod
    def controller_run(
        artifacts: Path,
        nonce_character: str,
        *,
        scenario: str = "retry-success",
    ) -> tuple[str, Path]:
        run_id = "20260825T120000Z-" + nonce_character * 32
        run_dir = artifacts / run_id
        run_dir.mkdir()
        runner.write_json(
            run_dir / "control.json",
            {
                "run_id": run_id,
                "scenario": scenario,
                "attempts": 1,
                "outcome": "RUNNING",
            },
        )
        return run_id, run_dir

    def test_run_local_forwards_only_the_explicit_provider_allowlist(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            binary_dir = Path(temporary)
            fake_python = binary_dir / "python3"
            fake_python.write_text(
                "#!/bin/sh\nenv | LC_ALL=C sort\n",
                encoding="utf-8",
            )
            fake_python.chmod(0o755)
            environment = {
                "PATH": f"{binary_dir}:/usr/bin:/bin",
                "HOME": str(binary_dir),
                "USER": "synthetic-user",
                "SHELL": "/bin/sh",
                "TMPDIR": temporary,
                "LANG": "C.UTF-8",
                "OPENAI_API_KEY": "synthetic-provider-value",
                "OPENAI_BASE_URL": "https://untrusted.invalid",
                "OLLAMA_HOST": "http://untrusted.invalid",
                "GITHUB_TOKEN": "must-not-cross",
                "UNRELATED_SECRET": "must-not-cross",
            }
            completed = subprocess.run(
                [str(runner.PACKAGE_ROOT / "scripts" / "run-local.sh"), "preflight"],
                cwd=runner.PACKAGE_ROOT,
                env=environment,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("OPENAI_API_KEY=synthetic-provider-value", completed.stdout)
        self.assertNotIn("OPENAI_BASE_URL", completed.stdout)
        self.assertNotIn("OLLAMA_HOST", completed.stdout)
        self.assertNotIn("GITHUB_TOKEN", completed.stdout)
        self.assertNotIn("UNRELATED_SECRET", completed.stdout)

    def test_retry_success_publishes_only_after_second_candidate(self) -> None:
        temporary, artifacts = self.artifact_root()
        self.addCleanup(temporary.cleanup)

        run_dir, control = runner.run_flow("retry-success", artifact_root=artifacts)

        self.assertEqual(control["outcome"], "SUCCEEDED")
        self.assertEqual(control["attempts"], 2)
        self.assertEqual(runner.verify_run(run_dir), [])
        retained_patch = run_dir / "attempt-2-fixture.patch"
        self.assertTrue(retained_patch.is_file())
        candidate = runner.read_json(run_dir / "attempt-2-candidate.json")
        self.assertEqual(candidate["patch"], retained_patch.name)
        github = json.loads((run_dir / "mock-github.json").read_text())
        self.assertTrue(github["draft"])
        self.assertEqual(
            set(github["operations"]),
            {"create_branch", "create_commit", "create_pull_request"},
        )
        self.assertNotIn("merge", github["operations"])

        retained_patch.write_text("tampered\n", encoding="utf-8")
        self.assertIn(
            "candidate patch artifact is invalid",
            runner.verify_run(run_dir),
        )

    def test_delivery_uses_the_validated_incident_base_revision(self) -> None:
        temporary, artifacts = self.artifact_root()
        self.addCleanup(temporary.cleanup)

        run_dir, control = runner.run_flow(
            "event-indexing-collision",
            artifact_root=artifacts,
        )

        delivery = runner.read_json(run_dir / "mock-github.json")
        self.assertEqual(delivery["repository"], control["repository"])
        self.assertEqual(delivery["base"], "fixture-event-indexing-collision-v1")
        self.assertEqual(delivery["base"], control["base_revision"])
        self.assertEqual(runner.verify_run(run_dir), [])

        delivery["base"] = "wrong-base"
        runner.write_json(run_dir / "mock-github.json", delivery)
        self.assertIn(
            "mock GitHub base does not match control state",
            runner.verify_run(run_dir),
        )

    def test_delivery_api_rejects_missing_receipts_and_cleanup(self) -> None:
        temporary, artifacts = self.artifact_root()
        self.addCleanup(temporary.cleanup)
        run_dir, control = runner.run_flow("retry-success", artifact_root=artifacts)
        attempt = control["attempts"]
        candidate = runner.read_json(run_dir / f"attempt-{attempt}-candidate.json")
        test_result = runner.read_json(run_dir / f"attempt-{attempt}-result.json")["test"]
        verification = runner.read_json(run_dir / "verification.json")
        scenario = runner.read_json(runner.FIXTURES / "scenarios.json")["retry-success"]
        delivery = run_dir / "mock-github.json"
        delivery.unlink()

        incomplete_cleanup = dict(control)
        incomplete_cleanup["pre_delivery_cleanup_complete"] = False
        with self.assertRaisesRegex(runner.PolicyDenied, "cleanup prerequisite"):
            runner.mock_publish(
                run_dir,
                incomplete_cleanup,
                candidate,
                test_result,
                verification,
                scenario,
            )
        self.assertFalse(delivery.exists())

        missing_receipt = json.loads(json.dumps(verification))
        trusted = next(
            check
            for check in missing_receipt["test"]["checks"]
            if "trusted_verifier_completed" in check
        )
        trusted["receipt"] = None
        with self.assertRaisesRegex(runner.PolicyDenied, "independent verifier receipt"):
            runner.mock_publish(
                run_dir,
                control,
                candidate,
                test_result,
                missing_receipt,
                scenario,
            )
        self.assertFalse(delivery.exists())

    def test_cleanup_failure_revokes_delivery_and_updates_notification(self) -> None:
        temporary, artifacts = self.artifact_root()
        self.addCleanup(temporary.cleanup)
        real_rmtree = runner.shutil.rmtree

        def leave_accepted_workspace(path, *args, **kwargs):
            if Path(path).name == "attempt-2":
                return None
            return real_rmtree(path, *args, **kwargs)

        with mock.patch.object(runner.shutil, "rmtree", side_effect=leave_accepted_workspace):
            with self.assertRaisesRegex(runner.FlowError, "expected SUCCEEDED"):
                runner.run_flow("retry-success", artifact_root=artifacts)

        run_dir = next(path for path in artifacts.iterdir() if path.is_dir())
        control = runner.read_json(run_dir / "control.json")
        notification = runner.read_json(run_dir / "mock-slack.json")
        self.assertEqual(control["outcome"], "CLEANUP_FAILED")
        self.assertFalse(control["cleanup_complete"])
        self.assertEqual(notification["outcome"], "CLEANUP_FAILED")
        self.assertFalse((run_dir / "mock-github.json").exists())

    def test_post_publish_failure_revokes_draft_delivery(self) -> None:
        temporary, artifacts = self.artifact_root()
        self.addCleanup(temporary.cleanup)
        append_event = runner.append_event

        def fail_after_publish(run_dir, event, **details):
            if event == "MOCK_PUBLISHED":
                raise OSError("synthetic event write failure")
            return append_event(run_dir, event, **details)

        with mock.patch.object(runner, "append_event", side_effect=fail_after_publish):
            with self.assertRaisesRegex(runner.FlowError, "expected SUCCEEDED, got FAILED"):
                runner.run_flow("retry-success", artifact_root=artifacts)

        run_dir = next(path for path in artifacts.iterdir() if path.is_dir())
        control = runner.read_json(run_dir / "control.json")
        self.assertEqual(control["outcome"], "FAILED")
        self.assertFalse((run_dir / "mock-github.json").exists())

    def test_source_symlink_is_rejected_before_workspace_copy(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            (source / "app").mkdir(parents=True)
            outside = root / "outside.txt"
            outside.write_text("must not be copied\n", encoding="utf-8")
            (source / "app" / "linked.txt").symlink_to(outside)
            with self.assertRaisesRegex(runner.PolicyDenied, "linked or irregular"):
                runner.create_workspace(root / "run", "attempt-1", source)
            self.assertFalse((root / "run" / "attempt-1" / "workspace").exists())

    def test_clean_candidate_exit_cannot_reach_delivery(self) -> None:
        temporary, artifacts = self.artifact_root()
        self.addCleanup(temporary.cleanup)
        patch_path = artifacts / "early-exit.patch"
        patch_path.write_text(
            """diff --git a/app/subject.py b/app/subject.py
--- a/app/subject.py
+++ b/app/subject.py
@@ -1,3 +1,3 @@
-def normalize_subject(value: str) -> str:
-    \"\"\"Return the stable subject form used for matching.\"\"\"
-    return value.strip()
+import os
+
+os._exit(0)
""",
            encoding="utf-8",
        )
        provider = runner.FixtureCandidateProvider(
            [patch_path],
            repeat_last_patch=False,
        )

        with self.assertRaisesRegex(
            runner.FlowError,
            "expected SUCCEEDED, got FAILED",
        ):
            runner.run_flow(
                "retry-success",
                max_attempts=1,
                artifact_root=artifacts,
                candidate_provider=provider,
            )

        run_dirs = [path for path in artifacts.iterdir() if path.is_dir()]
        self.assertEqual(len(run_dirs), 1)
        run_dir = run_dirs[0]
        control = runner.read_json(run_dir / "control.json")
        result = runner.read_json(run_dir / "attempt-1-result.json")
        self.assertEqual(control["outcome"], "FAILED")
        self.assertTrue(result["test"]["checks"][0]["passed"])
        self.assertFalse(result["test"]["checks"][1]["passed"])
        self.assertFalse(result["test"]["checks"][1]["trusted_verifier_completed"])
        self.assertFalse((run_dir / "mock-github.json").exists())

    def test_five_failures_do_not_publish(self) -> None:
        temporary, artifacts = self.artifact_root()
        self.addCleanup(temporary.cleanup)

        run_dir, control = runner.run_flow("exhausted", artifact_root=artifacts)

        self.assertEqual(control["outcome"], "FAILED")
        self.assertEqual(control["attempts"], 5)
        self.assertFalse((run_dir / "mock-github.json").exists())
        self.assertTrue((run_dir / "mock-slack.json").exists())
        self.assertEqual(runner.verify_run(run_dir), [])

    def test_injection_is_rejected_before_evidence_or_patching(self) -> None:
        temporary, artifacts = self.artifact_root()
        self.addCleanup(temporary.cleanup)

        run_dir, control = runner.run_flow("reject-injection", artifact_root=artifacts)

        self.assertEqual(control["outcome"], "REJECTED")
        self.assertEqual(control["attempts"], 0)
        self.assertFalse((run_dir / "evidence.json").exists())
        self.assertFalse((run_dir / "mock-github.json").exists())
        self.assertEqual(runner.verify_run(run_dir), [])

    def test_monotonic_deadline_stops_before_evidence(self) -> None:
        temporary, artifacts = self.artifact_root()
        self.addCleanup(temporary.cleanup)

        run_dir, control = runner.run_flow(
            "timeout",
            budget_seconds=0.005,
            artifact_root=artifacts,
        )

        self.assertEqual(control["outcome"], "TIMED_OUT")
        self.assertEqual(control["attempts"], 0)
        self.assertFalse((run_dir / "evidence.json").exists())
        self.assertEqual(runner.verify_run(run_dir), [])

    def test_evidence_is_scoped_and_redacted(self) -> None:
        incident = runner.read_json(runner.FIXTURES / "incidents/retry-success.json")
        packet = runner.collect_evidence(incident)
        serialized = json.dumps(packet)

        self.assertEqual(len(packet["logs"]), 2)
        self.assertEqual(packet["database"]["view"], "incident_context")
        for marker in runner.RAW_SENSITIVE_MARKERS:
            self.assertNotIn(marker, serialized)
        self.assertIn("[REDACTED", serialized)

    def test_fixture_candidate_provider_returns_versioned_contract(self) -> None:
        temporary, artifacts = self.artifact_root()
        self.addCleanup(temporary.cleanup)
        run_dir = artifacts / "provider-contract"
        run_dir.mkdir()
        workspace = runner.create_workspace(run_dir, "attempt-1")
        patch_path = runner.FIXTURES / "patches/correct.patch"
        provider = runner.FixtureCandidateProvider(
            [patch_path],
            repeat_last_patch=False,
        )

        candidate = provider.create_candidate(
            attempt=1,
            workspace=workspace,
            deadline=time.monotonic() + 10,
        )

        self.assertTrue(provider.has_candidate(1))
        self.assertFalse(provider.has_candidate(2))
        self.assertEqual(candidate.patch_path, patch_path)
        self.assertEqual(
            candidate.record,
            {
                "schema_version": runner.CANDIDATE_CONTRACT_VERSION,
                "source": "fixture-simulated-deepagents",
                "attempt": 1,
                "patch": "correct.patch",
                "patch_sha256": runner.hashlib.sha256(patch_path.read_bytes()).hexdigest(),
                "changed_paths": ["app/subject.py"],
                "candidate_digest": candidate.record["candidate_digest"],
            },
        )
        runner.validate_candidate_contract(candidate.record)
        tampered = dict(candidate.record)
        tampered["patch_sha256"] = "0" * 64
        with self.assertRaisesRegex(
            runner.PolicyDenied,
            "candidate patch digest does not match verification input",
        ):
            runner.Candidate(tampered, patch_path)

    def test_dump_policy_exposes_effective_controller_boundary(self) -> None:
        policy = runner.dump_policy()

        self.assertEqual(policy["schema_version"], 1)
        self.assertEqual(policy["repository"]["id"], runner.EXPECTED_REPOSITORY)
        self.assertEqual(
            policy["repository"]["allowed_patch_prefixes"],
            list(runner.ALLOWED_PATCH_PREFIXES),
        )
        self.assertEqual(policy["deepagents"]["proposal_authority"], "reporting-only")
        self.assertEqual(policy["delivery"]["mode"], "draft-artifacts-only")
        self.assertFalse(policy["delivery"]["merge"])
        self.assertFalse(policy["delivery"]["deployment"])
        self.assertEqual(policy["authority_boundary"], "ai-proposes-controller-decides")

    def test_dump_policy_cli_prints_valid_json(self) -> None:
        result = subprocess.run(
            ["bash", "-lc", "./scripts/run-local.sh dump-policy"],
            cwd=runner.PACKAGE_ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=20,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        policy = json.loads(result.stdout)
        self.assertEqual(policy["safety_modes"]["current"], "synthetic-draft")
        self.assertEqual(
            policy["validation"]["candidate_code_execution"],
            "network-disabled-pinned-docker-sandbox",
        )

    def test_run_flow_uses_injected_candidate_provider(self) -> None:
        temporary, artifacts = self.artifact_root()
        self.addCleanup(temporary.cleanup)
        provider = runner.FixtureCandidateProvider(
            [
                runner.FIXTURES / "patches/incomplete.patch",
                runner.FIXTURES / "patches/correct.patch",
            ],
            repeat_last_patch=False,
        )

        with mock.patch.object(
            provider,
            "create_candidate",
            wraps=provider.create_candidate,
        ) as create_candidate:
            run_dir, control = runner.run_flow(
                "retry-success",
                artifact_root=artifacts,
                candidate_provider=provider,
            )

        self.assertEqual(create_candidate.call_count, 2)
        self.assertEqual(control["candidate_source"], provider.source)
        first_candidate = runner.read_json(run_dir / "attempt-1-candidate.json")
        second_candidate = runner.read_json(run_dir / "attempt-2-candidate.json")
        self.assertEqual(first_candidate["schema_version"], 1)
        self.assertEqual(first_candidate["attempt"], 1)
        self.assertEqual(second_candidate["attempt"], 2)
        self.assertEqual(runner.verify_run(run_dir), [])

    def test_candidate_contract_rejects_unsupported_schema(self) -> None:
        record = {
            "schema_version": runner.CANDIDATE_CONTRACT_VERSION + 1,
            "source": "fixture-simulated-deepagents",
            "attempt": 1,
            "patch": "correct.patch",
            "patch_sha256": "0" * 64,
            "changed_paths": ["app/subject.py"],
            "candidate_digest": "1" * 64,
        }

        with self.assertRaisesRegex(
            runner.PolicyDenied,
            "unsupported candidate contract schema",
        ):
            runner.Candidate(record, runner.FIXTURES / "patches/correct.patch")

        extra_field = {**record, "schema_version": runner.CANDIDATE_CONTRACT_VERSION}
        extra_field["untrusted_status"] = "passed"
        with self.assertRaisesRegex(runner.PolicyDenied, "fields are invalid"):
            runner.Candidate(
                extra_field,
                runner.FIXTURES / "patches/correct.patch",
            )

    def test_scenario_path_policy_rejects_an_unverified_module(self) -> None:
        scenario = runner.read_json(runner.FIXTURES / "scenarios.json")["event-indexing-collision"]

        with self.assertRaisesRegex(
            runner.PolicyDenied,
            "outside the scenario policy",
        ):
            runner.validate_scenario_candidate_paths(
                scenario,
                ["app/consumer.py"],
            )

    def test_wrong_repository_and_patch_path_are_denied(self) -> None:
        incident = runner.read_json(runner.FIXTURES / "incidents/retry-success.json")
        incident["repository"] = "Deep Agents Incident Workflow/another-repository"
        with self.assertRaises(runner.PolicyDenied):
            runner.validate_incident(incident)

        malicious = (
            "diff --git a/.github/workflows/ci.yml b/.github/workflows/ci.yml\n"
            "+++ b/.github/workflows/ci.yml\n"
        )
        with self.assertRaises(runner.PolicyDenied):
            runner.validate_patch(malicious)

    def test_mixed_patch_cannot_hide_forbidden_deletion(self) -> None:
        patch_text = (runner.FIXTURES / "patches/mixed-forbidden-delete.patch").read_text(
            encoding="utf-8"
        )

        with self.assertRaisesRegex(
            runner.PolicyDenied,
            "candidate path is not allowlisted: tests/test_subject.py",
        ):
            runner.validate_patch(patch_text)

    def test_mixed_patch_cannot_hide_forbidden_rename_or_copy(self) -> None:
        allowed_hunk = """diff --git a/app/subject.py b/app/subject.py
--- a/app/subject.py
+++ b/app/subject.py
@@ -1 +1 @@
-old
+new
"""
        for operation in ("rename", "copy"):
            hidden_change = f"""diff --git a/tests/test_subject.py b/tests/disabled.py
similarity index 100%
{operation} from tests/test_subject.py
{operation} to tests/disabled.py
"""
            with self.subTest(operation=operation):
                with self.assertRaisesRegex(
                    runner.PolicyDenied,
                    "unsupported diff header|rename or copy metadata",
                ):
                    runner.validate_patch(allowed_hunk + hidden_change)

    def test_subprocess_environment_strips_sensitive_names(self) -> None:
        inherited = {
            "AWS_ACCESS_KEY_ID": "synthetic-aws-value",
            "ANTHROPIC_API_KEY": "synthetic-anthropic-value",
            "GRAFANA_TOKEN": "synthetic-grafana-value",
            "GOOGLE_API_KEY": "synthetic-google-value",
            "GIT_CONFIG_GLOBAL": "/tmp/untrusted-gitconfig",
            "GIT_TERMINAL_PROMPT": "1",
            "OLLAMA_HOST": "http://untrusted.invalid",
            "OPENAI_API_KEY": "synthetic-openai-value",
            "PGPASSWORD": "synthetic-database-value",
            "GITHUB_TOKEN": "synthetic-github-value",
            "SAFE_LOCAL_FLAG": "preserved",
        }
        with mock.patch.dict(os.environ, inherited, clear=True):
            environment = runner.subprocess_environment({"RUN_SCOPE": "fixture-only"})

        for name in inherited:
            if name != "SAFE_LOCAL_FLAG":
                self.assertNotIn(name, environment)
        self.assertEqual(environment["SAFE_LOCAL_FLAG"], "preserved")
        self.assertEqual(environment["RUN_SCOPE"], "fixture-only")

    def test_provider_error_redaction_covers_values_tokens_and_headers(self) -> None:
        bare_token = "sk-" + "x" * 30
        opaque_value = "opaque-provider-value-123"
        source = f'Authorization: Bearer {bare_token} {{"api_key":"{bare_token}"}} {opaque_value}'
        with mock.patch.dict(
            os.environ,
            {"OPENAI_API_KEY": opaque_value},
            clear=False,
        ):
            redacted = runner.redact_text(source)

        self.assertNotIn(bare_token, redacted)
        self.assertNotIn(opaque_value, redacted)
        self.assertIn("Authorization: Bearer [REDACTED]", redacted)

    def test_unit_test_uses_exact_locked_down_container_command(self) -> None:
        temporary, artifacts = self.artifact_root()
        self.addCleanup(temporary.cleanup)
        run_id, run_dir = self.controller_run(artifacts, "0")
        workspace = runner.create_workspace(run_dir, "attempt-1")
        completed = subprocess.CompletedProcess([], 0, "sandbox unit output")
        container_name, sandbox_id = runner.candidate_container_identity(
            run_id,
            1,
            "attempt-unit",
        )
        cleanup_result = {"complete": True, "removed": False}

        with (
            mock.patch.object(
                runner,
                "_cleanup_candidate_test_container",
                return_value=cleanup_result,
            ) as cleanup,
            mock.patch.object(runner, "command", return_value=completed) as execute,
        ):
            result = runner.unit_test(
                workspace,
                time.monotonic() + 10,
                run_dir=run_dir,
                run_id=run_id,
                attempt=1,
                phase="attempt",
            )

        actual = execute.call_args.args[0]
        cidfile_argument = next(item for item in actual if item.startswith("--cidfile="))
        cidfile = Path(cidfile_argument.removeprefix("--cidfile="))
        expected = [
            "docker",
            "run",
            "--rm",
            "--pull=never",
            f"--name={container_name}",
            f"--label=deepagents-incident-workflow.candidate-test={sandbox_id}",
            cidfile_argument,
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
            f"--mount=type=bind,src={workspace.resolve()},dst=/workspace,readonly",
            "--workdir=/workspace",
            "--entrypoint=/usr/bin/env",
            (
                "python:3.12-alpine@sha256:"
                "6d43704baacd1bfbe7c295d7f13079d5d8104ed33568873133f8fc69980419df"
            ),
            "-i",
            "HOME=/tmp",
            "LANG=C.UTF-8",
            "PATH=/usr/local/bin:/usr/bin:/bin",
            "PYTHONDONTWRITEBYTECODE=1",
            "PYTHONHASHSEED=0",
            "PYTHONPATH=/workspace",
            "PYTHONUNBUFFERED=1",
            "TMPDIR=/tmp",
            "USER=nobody",
            "python",
            "-m",
            "unittest",
            "discover",
            "-s",
            "tests",
            "-v",
        ]
        execute.assert_called_once_with(expected, cwd=runner.PACKAGE_ROOT, timeout=mock.ANY)
        cleanup.assert_called_once_with(
            cidfile,
            container_name=container_name,
            sandbox_id=sandbox_id,
        )
        self.assertTrue(result["passed"])
        self.assertEqual(result["output"], "sandbox unit output")
        self.assertEqual(result["cleanup"], cleanup_result)

    def test_controller_test_adds_read_only_trusted_verifier_mounts(self) -> None:
        temporary, artifacts = self.artifact_root()
        self.addCleanup(temporary.cleanup)
        run_id, run_dir = self.controller_run(artifacts, "1")
        workspace = runner.create_workspace(run_dir, "attempt-1")
        verifier = runner.PACKAGE_ROOT / "verifiers" / "event_indexing_logic.py"
        completed = subprocess.CompletedProcess(
            [],
            0,
            f"sandbox verifier output\n{runner.TRUSTED_VERIFIER_COMPLETION}\n",
        )
        container_name, sandbox_id = runner.candidate_container_identity(
            run_id,
            1,
            "attempt-verifier",
        )
        cleanup_result = {"complete": True, "removed": False}

        with (
            mock.patch.object(
                runner,
                "_cleanup_candidate_test_container",
                return_value=cleanup_result,
            ) as cleanup,
            mock.patch.object(runner, "command", return_value=completed) as execute,
        ):
            result = runner.controller_test(
                workspace,
                verifier,
                time.monotonic() + 10,
                run_dir=run_dir,
                run_id=run_id,
                attempt=1,
                phase="attempt",
                fixture_digest=runner.tree_digest(runner.FIXTURES / "repository"),
                patch_sha256="0" * 64,
            )

        actual = execute.call_args.args[0]
        cidfile_argument = next(item for item in actual if item.startswith("--cidfile="))
        cidfile = Path(cidfile_argument.removeprefix("--cidfile="))
        expected = [
            "docker",
            "run",
            "--rm",
            "--pull=never",
            f"--name={container_name}",
            f"--label=deepagents-incident-workflow.candidate-test={sandbox_id}",
            cidfile_argument,
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
            f"--mount=type=bind,src={workspace.resolve()},dst=/workspace,readonly",
            f"--mount=type=bind,src={verifier.resolve()},dst=/verifier/controller.py,readonly",
            (
                "--mount=type=bind,"
                f"src={runner.CANDIDATE_PROBE_PATH.resolve()},"
                "dst=/verifier/candidate_probe.py,readonly"
            ),
            "--workdir=/workspace",
            "--entrypoint=/usr/bin/env",
            (
                "python:3.12-alpine@sha256:"
                "6d43704baacd1bfbe7c295d7f13079d5d8104ed33568873133f8fc69980419df"
            ),
            "-i",
            "HOME=/tmp",
            "LANG=C.UTF-8",
            "PATH=/usr/local/bin:/usr/bin:/bin",
            "PYTHONDONTWRITEBYTECODE=1",
            "PYTHONHASHSEED=0",
            "PYTHONPATH=/workspace",
            "PYTHONUNBUFFERED=1",
            "TMPDIR=/tmp",
            "USER=nobody",
            "python",
            "/verifier/controller.py",
            "--repository",
            "/workspace",
        ]
        execute.assert_called_once_with(expected, cwd=runner.PACKAGE_ROOT, timeout=mock.ANY)
        cleanup.assert_called_once_with(
            cidfile,
            container_name=container_name,
            sandbox_id=sandbox_id,
        )
        self.assertIsNotNone(result)
        assert result is not None
        self.assertTrue(result["passed"])
        self.assertTrue(result["trusted_verifier_completed"])
        self.assertEqual(
            result["output"],
            f"sandbox verifier output\n{runner.TRUSTED_VERIFIER_COMPLETION}\n",
        )
        self.assertEqual(result["cleanup"], cleanup_result)

    def test_missing_controller_verifier_fails_closed(self) -> None:
        temporary, artifacts = self.artifact_root()
        self.addCleanup(temporary.cleanup)
        run_id, run_dir = self.controller_run(artifacts, "2")
        workspace = runner.create_workspace(run_dir, "attempt-1")

        result = runner.controller_test(
            workspace,
            None,
            time.monotonic() + 10,
            run_dir=run_dir,
            run_id=run_id,
            attempt=1,
            phase="attempt",
            fixture_digest=runner.tree_digest(runner.FIXTURES / "repository"),
            patch_sha256="0" * 64,
        )

        self.assertFalse(result["passed"])
        self.assertFalse(result["trusted_verifier_completed"])
        self.assertEqual(result["exit_code"], 1)

    def test_zero_exit_without_trusted_completion_marker_fails_closed(self) -> None:
        temporary, artifacts = self.artifact_root()
        self.addCleanup(temporary.cleanup)
        run_id, run_dir = self.controller_run(artifacts, "3")
        workspace = runner.create_workspace(run_dir, "attempt-1")
        verifier = runner.PACKAGE_ROOT / "verifiers" / "subject_logic.py"

        with mock.patch.object(
            runner,
            "_run_candidate_test_container",
            return_value=(
                subprocess.CompletedProcess([], 0, "candidate says passed\n"),
                {"complete": True, "removed": False},
            ),
        ):
            result = runner.controller_test(
                workspace,
                verifier,
                time.monotonic() + 10,
                run_dir=run_dir,
                run_id=run_id,
                attempt=1,
                phase="attempt",
                fixture_digest=runner.tree_digest(runner.FIXTURES / "repository"),
                patch_sha256="0" * 64,
            )

        self.assertEqual(result["process_exit_code"], 0)
        self.assertEqual(result["exit_code"], 1)
        self.assertFalse(result["passed"])
        self.assertFalse(result["trusted_verifier_completed"])

    def test_marker_cannot_override_nonzero_or_signaled_verifier_exit(self) -> None:
        for index, returncode in enumerate((1, -signal.SIGKILL), start=8):
            with self.subTest(returncode=returncode):
                temporary, artifacts = self.artifact_root()
                self.addCleanup(temporary.cleanup)
                run_id, run_dir = self.controller_run(artifacts, str(index))
                workspace = runner.create_workspace(run_dir, "attempt-1")
                verifier = runner.PACKAGE_ROOT / "verifiers" / "subject_logic.py"
                completed = subprocess.CompletedProcess(
                    [],
                    returncode,
                    runner.TRUSTED_VERIFIER_COMPLETION + "\n",
                )

                with mock.patch.object(
                    runner,
                    "_run_candidate_test_container",
                    return_value=(completed, {"complete": True, "removed": False}),
                ):
                    result = runner.controller_test(
                        workspace,
                        verifier,
                        time.monotonic() + 10,
                        run_dir=run_dir,
                        run_id=run_id,
                        attempt=1,
                        phase="attempt",
                        fixture_digest=runner.tree_digest(runner.FIXTURES / "repository"),
                        patch_sha256="0" * 64,
                    )

                self.assertEqual(result["process_exit_code"], returncode)
                self.assertFalse(result["passed"])
                self.assertFalse(result["trusted_verifier_completed"])
                self.assertIsNone(result["receipt"])

    def test_verifier_timeout_cannot_reach_delivery(self) -> None:
        temporary, artifacts = self.artifact_root()
        self.addCleanup(temporary.cleanup)

        def run_container(_workspace, _argv, _deadline, *, verifier=None, **_kwargs):
            if verifier is None:
                return (
                    subprocess.CompletedProcess([], 0, "unit tests passed\n"),
                    {"complete": True, "removed": False},
                )
            raise subprocess.TimeoutExpired(
                ["docker", "run"],
                1,
                output=runner.TRUSTED_VERIFIER_COMPLETION + "\n",
            )

        with mock.patch.object(
            runner,
            "_run_candidate_test_container",
            side_effect=run_container,
        ):
            with self.assertRaisesRegex(
                runner.FlowError,
                "expected SUCCEEDED, got TIMED_OUT",
            ):
                runner.run_flow("retry-success", artifact_root=artifacts)

        run_dir = next(path for path in artifacts.iterdir() if path.is_dir())
        control = runner.read_json(run_dir / "control.json")
        self.assertEqual(control["outcome"], "TIMED_OUT")
        self.assertTrue(control["cleanup_complete"])
        self.assertFalse((run_dir / "mock-github.json").exists())
        self.assertEqual(runner.verify_run(run_dir), [])

    def test_executable_ast_tricks_cannot_bypass_controller_verifier(self) -> None:
        baseline = (runner.FIXTURES / "repository" / "app" / "subject.py").read_text(
            encoding="utf-8"
        )
        variants = {
            "target annotation": baseline.replace(
                "value: str",
                'value: __import__("os")._exit(0)',
            ).replace(
                "return value.strip()",
                'return " ".join(value.split()).lower()',
            ),
            "unused helper default": (
                'def ignored(value=__import__("os")._exit(0)):\n'
                "    return value\n\n"
                + baseline.replace(
                    "return value.strip()",
                    'return " ".join(value.split()).lower()',
                )
            ),
            "unused helper decorator": (
                '@__import__("os")._exit(0)\n'
                "def ignored(value):\n"
                "    return value\n\n"
                + baseline.replace(
                    "return value.strip()",
                    'return " ".join(value.split()).lower()',
                )
            ),
            "dictionary unpack": baseline.replace(
                "return value.strip()",
                'return "".join({" ".join(value.split()).lower(): None, '
                '**__import__("os")._exit(0)})',
            ),
        }
        for label, replacement in variants.items():
            with self.subTest(label=label), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                patch_path = root / "candidate.patch"
                patch_path.write_text(
                    "diff --git a/app/subject.py b/app/subject.py\n"
                    + "".join(
                        difflib.unified_diff(
                            baseline.splitlines(keepends=True),
                            replacement.splitlines(keepends=True),
                            fromfile="a/app/subject.py",
                            tofile="b/app/subject.py",
                        )
                    ),
                    encoding="utf-8",
                )
                provider = runner.FixtureCandidateProvider(
                    [patch_path],
                    repeat_last_patch=False,
                )
                artifact_root = root / "artifacts"
                with self.assertRaisesRegex(runner.FlowError, "expected SUCCEEDED"):
                    runner.run_flow(
                        "retry-success",
                        artifact_root=artifact_root,
                        candidate_provider=provider,
                    )
                run_dir = next(artifact_root.iterdir())
                control = runner.read_json(run_dir / "control.json")

                result = runner.read_json(run_dir / "attempt-1-result.json")
                self.assertTrue(result["test"]["checks"][0]["passed"])
                self.assertFalse(result["test"]["checks"][1]["passed"])
                self.assertEqual(control["outcome"], "FAILED")
                self.assertFalse((run_dir / "mock-github.json").exists())

    def test_candidate_test_timeout_always_runs_scoped_cleanup(self) -> None:
        temporary, artifacts = self.artifact_root()
        self.addCleanup(temporary.cleanup)
        run_id, run_dir = self.controller_run(artifacts, "4")
        workspace = runner.create_workspace(run_dir, "attempt-1")
        container_name, sandbox_id = runner.candidate_container_identity(
            run_id,
            1,
            "attempt-unit",
        )
        timeout = subprocess.TimeoutExpired(["docker", "run"], 1)

        with (
            mock.patch.object(
                runner,
                "_cleanup_candidate_test_container",
                return_value={"complete": True, "removed": True},
            ) as cleanup,
            mock.patch.object(runner, "command", side_effect=timeout) as execute,
        ):
            with self.assertRaises(subprocess.TimeoutExpired):
                runner.unit_test(
                    workspace,
                    time.monotonic() + 10,
                    run_dir=run_dir,
                    run_id=run_id,
                    attempt=1,
                    phase="attempt",
                )

        actual = execute.call_args.args[0]
        cidfile_argument = next(item for item in actual if item.startswith("--cidfile="))
        cleanup.assert_called_once_with(
            Path(cidfile_argument.removeprefix("--cidfile=")),
            container_name=container_name,
            sandbox_id=sandbox_id,
        )

    def test_cleanup_recovers_candidate_container_after_controller_crash(self) -> None:
        temporary, artifacts = self.artifact_root()
        self.addCleanup(temporary.cleanup)
        run_id, run_dir = self.controller_run(artifacts, "5")
        intent, cidfile = runner.candidate_container_intent(
            run_dir,
            run_id,
            1,
            "attempt-verifier",
        )
        runner.write_json(
            run_dir / "attempt-1-attempt-verifier-candidate-container-intent.json",
            intent,
        )

        with (
            mock.patch.object(runner.shutil, "which", return_value="/usr/bin/docker"),
            mock.patch.object(
                runner,
                "_cleanup_candidate_test_container",
                return_value={"complete": True, "removed": True},
            ) as cleanup,
        ):
            result = runner.cleanup_existing(run_dir)

        self.assertTrue(result["cleanup_complete"])
        cleanup.assert_called_once_with(
            cidfile,
            container_name=intent["container_name"],
            sandbox_id=intent["sandbox_id"],
        )

    def test_cleanup_rejects_tampered_candidate_container_intent(self) -> None:
        temporary, artifacts = self.artifact_root()
        self.addCleanup(temporary.cleanup)
        run_id, run_dir = self.controller_run(artifacts, "6")
        intent, _cidfile = runner.candidate_container_intent(
            run_dir,
            run_id,
            1,
            "attempt-verifier",
        )
        intent["container_name"] = "unrelated-container"
        runner.write_json(
            run_dir / "attempt-1-attempt-verifier-candidate-container-intent.json",
            intent,
        )

        with mock.patch.object(runner, "command") as execute:
            result = runner.cleanup_existing(run_dir)

        self.assertFalse(result["cleanup_complete"])
        self.assertTrue(result["refused"])
        self.assertIn("intent validation failed", result["reason"])
        execute.assert_not_called()

    def test_candidate_test_cleanup_removes_only_owned_container_id(self) -> None:
        temporary, root = self.artifact_root()
        self.addCleanup(temporary.cleanup)
        sandbox_id = "3" * 32
        candidate_id = "a" * 64
        cidfile = root / "container.cid"
        cidfile.write_text(candidate_id + "\n", encoding="utf-8")
        inspect_format = (
            "{{.Id}}|{{.Name}}|{{.Config.Image}}|"
            '{{index .Config.Labels "deepagents-incident-workflow.candidate-test"}}'
        )
        inspected = subprocess.CompletedProcess(
            [],
            0,
            f"{candidate_id}|/daiw-candidate-test-{sandbox_id}|"
            f"{runner.CANDIDATE_TEST_IMAGE}|{sandbox_id}\n",
        )
        removed = subprocess.CompletedProcess([], 0, candidate_id + "\n")

        with mock.patch.object(
            runner,
            "command",
            side_effect=[inspected, removed],
        ) as execute:
            cleanup = runner._cleanup_candidate_test_container(
                cidfile,
                container_name=f"daiw-candidate-test-{sandbox_id}",
                sandbox_id=sandbox_id,
            )

        self.assertEqual(
            execute.call_args_list,
            [
                mock.call(
                    [
                        "docker",
                        "inspect",
                        f"--format={inspect_format}",
                        candidate_id,
                    ],
                    cwd=runner.PACKAGE_ROOT,
                    timeout=15,
                ),
                mock.call(
                    ["docker", "rm", "--force", candidate_id],
                    cwd=runner.PACKAGE_ROOT,
                    timeout=15,
                ),
            ],
        )
        self.assertEqual(
            cleanup,
            {
                "complete": True,
                "removed": True,
                "container_id": candidate_id[:12],
            },
        )

    def test_candidate_test_cleanup_refuses_mismatched_owner_label(self) -> None:
        temporary, root = self.artifact_root()
        self.addCleanup(temporary.cleanup)
        sandbox_id = "4" * 32
        candidate_id = "b" * 64
        cidfile = root / "container.cid"
        cidfile.write_text(candidate_id + "\n", encoding="utf-8")
        inspected = subprocess.CompletedProcess(
            [],
            0,
            f"{candidate_id}|/daiw-candidate-test-{sandbox_id}|"
            f"{runner.CANDIDATE_TEST_IMAGE}|another-owner\n",
        )

        with mock.patch.object(
            runner,
            "command",
            return_value=inspected,
        ) as execute:
            cleanup = runner._cleanup_candidate_test_container(
                cidfile,
                container_name=f"daiw-candidate-test-{sandbox_id}",
                sandbox_id=sandbox_id,
            )

        self.assertEqual(execute.call_count, 1)
        self.assertEqual(
            cleanup,
            {
                "complete": False,
                "removed": False,
                "reason": "candidate test container ownership identity did not match",
            },
        )

    def test_candidate_test_cleanup_refuses_mismatched_name_or_image(self) -> None:
        temporary, root = self.artifact_root()
        self.addCleanup(temporary.cleanup)
        sandbox_id = "5" * 32
        candidate_id = "c" * 64
        cidfile = root / "container.cid"
        cidfile.write_text(candidate_id + "\n", encoding="utf-8")
        expected_name = f"daiw-candidate-test-{sandbox_id}"

        for name, image in (
            ("/unrelated-container", runner.CANDIDATE_TEST_IMAGE),
            (f"/{expected_name}", "python:untrusted"),
        ):
            inspected = subprocess.CompletedProcess(
                [],
                0,
                f"{candidate_id}|{name}|{image}|{sandbox_id}\n",
            )
            with (
                self.subTest(name=name, image=image),
                mock.patch.object(
                    runner,
                    "command",
                    return_value=inspected,
                ) as execute,
            ):
                cleanup = runner._cleanup_candidate_test_container(
                    cidfile,
                    container_name=expected_name,
                    sandbox_id=sandbox_id,
                )
            self.assertEqual(execute.call_count, 1)
            self.assertFalse(cleanup["complete"])
            self.assertEqual(
                cleanup["reason"],
                "candidate test container ownership identity did not match",
            )

    def test_independent_verifier_rejects_wrong_candidate_digest(self) -> None:
        temporary, artifacts = self.artifact_root()
        self.addCleanup(temporary.cleanup)
        run_id, run_dir = self.controller_run(artifacts, "7")

        verification = runner.independent_verify(
            run_dir,
            runner.FIXTURES / "patches/correct.patch",
            "0" * 64,
            time.monotonic() + 10,
            run_id=run_id,
            attempt=1,
            verifier=runner.PACKAGE_ROOT / "verifiers" / "subject_logic.py",
        )

        self.assertTrue(verification["test"]["passed"])
        self.assertFalse(verification["accepted"])
        self.assertNotEqual(
            verification["candidate_digest"],
            verification["tested_digest"],
        )
        self.assertFalse((run_dir / "independent-verifier").exists())

    def test_verifier_rejects_tampered_delivery_and_sensitive_artifact(self) -> None:
        temporary, artifacts = self.artifact_root()
        self.addCleanup(temporary.cleanup)
        run_dir, _ = runner.run_flow("retry-success", artifact_root=artifacts)
        github_path = run_dir / "mock-github.json"
        github = json.loads(github_path.read_text(encoding="utf-8"))
        github["operations"].append("merge")
        github["draft"] = False
        github["candidate_digest"] = "0" * 64
        runner.write_json(github_path, github)
        (run_dir / "unsafe-retained.txt").write_text(
            runner.RAW_SENSITIVE_MARKERS[0],
            encoding="utf-8",
        )

        issues = runner.verify_run(run_dir)

        self.assertIn("mock GitHub operations differ from allowlist", issues)
        self.assertIn("mock pull request is not a draft", issues)
        self.assertIn("published digest does not match accepted digest", issues)
        self.assertIn("sensitive marker retained in unsafe-retained.txt", issues)

    def test_fixture_verifier_requires_trusted_completion_artifacts(self) -> None:
        temporary, artifacts = self.artifact_root()
        self.addCleanup(temporary.cleanup)
        run_dir, control = runner.run_flow("retry-success", artifact_root=artifacts)
        result_path = run_dir / f"attempt-{control['attempts']}-result.json"
        result = runner.read_json(result_path)
        trusted = next(
            check for check in result["test"]["checks"] if "trusted_verifier_completed" in check
        )
        trusted["trusted_verifier_completed"] = False
        runner.write_json(result_path, result)

        issues = runner.verify_run(run_dir)

        self.assertIn("accepted result lacks trusted verifier completion", issues)
        (run_dir / "verification.json").unlink()
        issues = runner.verify_run(run_dir)
        self.assertIn("successful run is missing verification artifact", issues)

    def test_verifier_receipt_rejects_identity_tampering_and_replay(self) -> None:
        temporary, artifacts = self.artifact_root()
        self.addCleanup(temporary.cleanup)
        run_dir, control = runner.run_flow("retry-success", artifact_root=artifacts)
        result_path = run_dir / f"attempt-{control['attempts']}-result.json"
        original = runner.read_json(result_path)
        trusted = next(
            check for check in original["test"]["checks"] if "trusted_verifier_completed" in check
        )
        mutations = {
            "run_id": "another-run",
            "candidate_digest": "0" * 64,
            "patch_sha256": "0" * 64,
            "fixture_digest": "0" * 64,
            "policy_sha256": "0" * 64,
            "verifier_bundle_sha256": "0" * 64,
            "verifier_command_sha256": "0" * 64,
            "candidate_test_image": "untrusted-image",
            "phase": "independent",
            "status": "claimed",
            "nonce": "invalid",
            "terminal": {
                "process_exit_code": 0,
                "signaled": False,
                "timed_out": True,
                "completion_marker_count": 1,
            },
        }
        for field, value in mutations.items():
            with self.subTest(field=field):
                tampered = json.loads(json.dumps(original))
                receipt = next(
                    check["receipt"]
                    for check in tampered["test"]["checks"]
                    if "trusted_verifier_completed" in check
                )
                receipt[field] = value
                runner.write_json(result_path, tampered)
                self.assertIn(
                    "accepted result lacks trusted verifier completion",
                    runner.verify_run(run_dir),
                )
        runner.write_json(result_path, original)

        verification_path = run_dir / "verification.json"
        verification = runner.read_json(verification_path)
        attempt_nonce = trusted["receipt"]["nonce"]
        independent = next(
            check
            for check in verification["test"]["checks"]
            if "trusted_verifier_completed" in check
        )
        independent["receipt"]["nonce"] = attempt_nonce
        runner.write_json(verification_path, verification)
        self.assertIn("trusted verifier receipt nonce was replayed", runner.verify_run(run_dir))

    def test_cleanup_is_idempotent(self) -> None:
        temporary, artifacts = self.artifact_root()
        self.addCleanup(temporary.cleanup)

        run_dir, _ = runner.run_flow("retry-success", artifact_root=artifacts)
        first = runner.cleanup_existing(run_dir)
        second = runner.cleanup_existing(run_dir)

        self.assertTrue(first["cleanup_complete"])
        self.assertTrue(second["cleanup_complete"])
        self.assertEqual(runner.verify_run(run_dir), [])

    def test_recovery_cleanup_refreshes_the_final_notification(self) -> None:
        temporary, artifacts = self.artifact_root()
        self.addCleanup(temporary.cleanup)
        run_dir, _control = runner.run_flow("retry-success", artifact_root=artifacts)

        with (
            mock.patch.object(runner.shutil, "which", return_value="/usr/bin/docker"),
            mock.patch.object(
                runner,
                "_cleanup_candidate_test_container",
                return_value={"complete": False, "removed": False},
            ),
        ):
            cleanup = runner.cleanup_existing(run_dir)

        control = runner.read_json(run_dir / "control.json")
        notification = runner.read_json(run_dir / "mock-slack.json")
        self.assertFalse(cleanup["cleanup_complete"])
        self.assertEqual(control["outcome"], "CLEANUP_FAILED")
        self.assertEqual(notification["outcome"], "CLEANUP_FAILED")
        self.assertFalse((run_dir / "mock-github.json").exists())

    def test_cleanup_rejects_tampered_compose_project_without_docker_command(self) -> None:
        temporary, artifacts = self.artifact_root()
        self.addCleanup(temporary.cleanup)
        run_dir, control = runner.run_flow("retry-success", artifact_root=artifacts)
        result_path = run_dir / f"attempt-{control['attempts']}-result.json"
        result = runner.read_json(result_path)
        result["test"]["compose_project"] = "unrelated-project"
        runner.write_json(result_path, result)

        with mock.patch.object(runner, "command") as execute:
            cleanup = runner.cleanup_existing(run_dir)

        self.assertFalse(cleanup["cleanup_complete"])
        self.assertTrue(cleanup["refused"])
        self.assertIn("does not match controller derivation", cleanup["reason"])
        execute.assert_not_called()

    def test_cleanup_recovers_from_crash_before_attempt_result_is_written(self) -> None:
        temporary, artifacts = self.artifact_root()
        self.addCleanup(temporary.cleanup)
        run_id = "20260825T120000Z-" + "d" * 32
        run_dir = artifacts / run_id
        run_dir.mkdir()
        scenario_name = "event-indexing-collision"
        scenario = runner.read_json(runner.FIXTURES / "scenarios.json")[scenario_name]
        runner.write_json(
            run_dir / "control.json",
            {
                "run_id": run_id,
                "scenario": scenario_name,
                "attempts": 1,
                "outcome": "RUNNING",
            },
        )
        runner.write_json(
            run_dir / "attempt-1-compose-intent.json",
            runner.compose_cleanup_intent(run_id, 1, scenario_name, scenario),
        )
        cleaned = {
            "project": runner.compose_project_name(run_id, 1),
            "exit_code": 0,
            "complete": True,
            "ownership_verified": True,
        }

        with (
            mock.patch.object(runner.shutil, "which", return_value="/usr/bin/docker"),
            mock.patch.object(runner, "compose_cleanup", return_value=cleaned) as cleanup,
        ):
            result = runner.cleanup_existing(run_dir)

        self.assertTrue(result["cleanup_complete"])
        cleanup.assert_called_once_with(
            run_id,
            1,
            runner.scenario_repository(scenario),
            scenario,
        )
        self.assertFalse((run_dir / "attempt-1-result.json").exists())

    def test_cleanup_rejects_tampered_intent_without_docker_command(self) -> None:
        temporary, artifacts = self.artifact_root()
        self.addCleanup(temporary.cleanup)
        run_id = "20260825T120000Z-" + "e" * 32
        run_dir = artifacts / run_id
        run_dir.mkdir()
        scenario_name = "event-indexing-collision"
        scenario = runner.read_json(runner.FIXTURES / "scenarios.json")[scenario_name]
        runner.write_json(
            run_dir / "control.json",
            {
                "run_id": run_id,
                "scenario": scenario_name,
                "attempts": 1,
                "outcome": "RUNNING",
            },
        )
        intent = runner.compose_cleanup_intent(run_id, 1, scenario_name, scenario)
        intent["compose_file_sha256"] = "0" * 64
        runner.write_json(run_dir / "attempt-1-compose-intent.json", intent)

        with mock.patch.object(runner, "command") as execute:
            result = runner.cleanup_existing(run_dir)

        self.assertFalse(result["cleanup_complete"])
        self.assertTrue(result["refused"])
        self.assertIn("intent validation failed", result["reason"])
        execute.assert_not_called()

    def test_compose_project_uses_full_controller_nonce(self) -> None:
        run_id = "20260825T120000Z-" + "a" * 32
        self.assertEqual(
            runner.compose_project_name(run_id, 3),
            "daiw" + "a" * 32 + "a3",
        )
        with self.assertRaises(runner.PolicyDenied):
            runner.compose_project_name("20260825T120000Z-deadbeef", 1)

    def test_compose_cleanup_refuses_mismatched_ownership_labels(self) -> None:
        run_id = "20260825T120000Z-" + "b" * 32
        project = runner.compose_project_name(run_id, 1)
        scenario = runner.read_json(runner.FIXTURES / "scenarios.json")["event-indexing-collision"]
        compose_file = runner.PACKAGE_ROOT / scenario["compose_file"]

        def inventory(args, **_):
            if args[:2] == ["docker", "ps"]:
                return subprocess.CompletedProcess(
                    args,
                    0,
                    (
                        "a" * 64
                        + f"|{project}-smoke-1|different-project|"
                        + f"{compose_file.resolve()}|{runner.PACKAGE_ROOT.resolve()}\n"
                    ),
                )
            return subprocess.CompletedProcess(args, 0, "")

        with mock.patch.object(runner, "command", side_effect=inventory) as execute:
            cleanup = runner.compose_cleanup(
                run_id,
                1,
                runner.scenario_repository(scenario),
                scenario,
            )

        self.assertFalse(cleanup["complete"])
        self.assertFalse(cleanup["ownership_verified"])
        self.assertFalse(
            any(call.args[0][:2] == ["docker", "compose"] for call in execute.call_args_list)
        )

    def test_closeout_rechecks_compose_after_an_earlier_success(self) -> None:
        temporary, artifacts = self.artifact_root()
        self.addCleanup(temporary.cleanup)
        run_id = "20260825T120000Z-" + "c" * 32
        run_dir = artifacts / run_id
        run_dir.mkdir()
        runner.write_json(
            run_dir / "control.json",
            {
                "run_id": run_id,
                "scenario": "retry-success",
                "attempts": 1,
                "outcome": "RUNNING",
            },
        )
        records = [
            {
                "run_id": run_id,
                "attempt": 1,
                "project": runner.compose_project_name(run_id, 1),
                "scenario": "retry-success",
                "cleanup": {
                    "exit_code": 0,
                    "complete": True,
                    "ownership_verified": True,
                },
            }
        ]
        first = {
            "exit_code": 0,
            "complete": True,
            "ownership_verified": True,
        }
        recreated = {
            "exit_code": 1,
            "complete": False,
            "ownership_verified": True,
        }
        with (
            mock.patch.object(runner.shutil, "which", return_value="/usr/bin/docker"),
            mock.patch.object(
                runner,
                "compose_cleanup",
                side_effect=[first, recreated],
            ) as cleanup,
        ):
            self.assertTrue(runner.cleanup_resources(run_dir, records)["cleanup_complete"])
            self.assertFalse(runner.cleanup_resources(run_dir, records)["cleanup_complete"])

        self.assertEqual(cleanup.call_count, 2)

    def test_latest_run_ignores_newer_non_controller_artifacts(self) -> None:
        temporary, artifacts = self.artifact_root()
        self.addCleanup(temporary.cleanup)
        controller_run = artifacts / "controller-run"
        controller_run.mkdir()
        runner.write_json(controller_run / "control.json", {"run_id": "controller-run"})
        sandbox_smoke = artifacts / "sandbox-smoke-newer"
        sandbox_smoke.mkdir()

        self.assertEqual(runner.latest_run(artifacts), controller_run)


if __name__ == "__main__":
    unittest.main()
