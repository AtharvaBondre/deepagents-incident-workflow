import importlib.util
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "deepagents_sdk_smoke.py"
SPEC = importlib.util.spec_from_file_location("deepagents_sdk_smoke", SCRIPT_PATH)
assert SPEC and SPEC.loader
smoke = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(smoke)


class DeepAgentsSdkSmokeTests(unittest.TestCase):
    def test_sdk_import_and_model_construction_are_inside_network_guard(self) -> None:
        def import_with_network_attempt() -> object:
            smoke.socket.getaddrinfo("example.invalid", 443)
            raise AssertionError("network denial did not stop SDK import")

        with (
            mock.patch.object(smoke, "_load_worker", side_effect=import_with_network_attempt),
            self.assertRaisesRegex(RuntimeError, "network access is disabled during the SDK smoke"),
        ):
            smoke.run_smoke()

    def test_worker_policy_has_exact_bounded_tool_surface(self) -> None:
        worker = smoke._load_worker()
        self.assertEqual(
            worker.ALLOWED_TOOLS,
            ["ls", "read_file", "write_file", "edit_file", "glob", "grep"],
        )
        self.assertTrue(
            {"delete", "execute", "task", "write_todos"}.isdisjoint(worker.ALLOWED_TOOLS)
        )
        self.assertEqual(
            worker.EXCLUDED_PROFILE_TOOLS,
            frozenset({"delete", "execute", "write_todos"}),
        )

    def test_smoke_fails_closed_after_any_network_attempt(self) -> None:
        tools = ["edit_file", "glob", "grep", "ls", "read_file", "write_file"]
        self.assertFalse(
            smoke._smoke_passed(
                workspace_edit_succeeded=True,
                out_of_scope_write_denied=True,
                traversal_write_denied=True,
                traversal_read_denied=True,
                tool_names=tools,
                expected_tools=tools,
                network_attempts=["socket.connect"],
            )
        )

    def test_smoke_fails_closed_if_a_traversal_probe_is_not_denied(self) -> None:
        tools = ["edit_file", "glob", "grep", "ls", "read_file", "write_file"]
        for field in ("traversal_write_denied", "traversal_read_denied"):
            boundaries = {
                "out_of_scope_write_denied": True,
                "traversal_write_denied": True,
                "traversal_read_denied": True,
            }
            boundaries[field] = False
            with self.subTest(field=field):
                self.assertFalse(
                    smoke._smoke_passed(
                        workspace_edit_succeeded=True,
                        tool_names=tools,
                        expected_tools=tools,
                        network_attempts=[],
                        **boundaries,
                    )
                )

    def test_os_network_guard_accepts_expected_denials(self) -> None:
        probe = mock.Mock()
        probe.connect.side_effect = OSError("network unreachable")
        with (
            mock.patch.object(smoke.socket, "getaddrinfo", side_effect=OSError("no DNS")),
            mock.patch.object(smoke.socket, "socket", return_value=probe),
        ):
            smoke._assert_os_network_disabled()
        probe.settimeout.assert_called_once_with(1)
        probe.close.assert_called_once_with()

    def test_os_network_guard_rejects_unexpected_dns_success(self) -> None:
        probe = mock.Mock()
        probe.connect.side_effect = OSError("network unreachable")
        with (
            mock.patch.object(smoke.socket, "getaddrinfo", return_value=[object()]),
            mock.patch.object(smoke.socket, "socket", return_value=probe),
            self.assertRaisesRegex(RuntimeError, "DNS resolution unexpectedly succeeded"),
        ):
            smoke._assert_os_network_disabled()

    def test_scripted_model_exercises_openai_codex_profile(self) -> None:
        try:
            model = smoke._scripted_model()
        except ModuleNotFoundError:
            self.skipTest("optional Deep Agents runtime is not installed")
        self.assertEqual(model._llm_type, "openai")
        self.assertEqual(
            model._get_ls_params(),
            {"ls_provider": "openai", "ls_model_name": "gpt-5.2-codex"},
        )

    def test_worker_scripted_model_requires_controller_plan(self) -> None:
        worker = smoke._load_worker()
        try:
            with self.assertRaisesRegex(ValueError, "controller-approved"):
                worker.build_scripted_smoke_model({"schema_version": 1})
        except ModuleNotFoundError:
            self.skipTest("optional Deep Agents runtime is not installed")

    def test_scripted_worker_blocks_network_during_graph_construction(self) -> None:
        worker = smoke._load_worker()
        packet = {
            "schema_version": 1,
            "run_id": "network-construction-test",
            "attempt": 1,
            "remaining_budget_seconds": 30,
            "incident": {},
            "evidence": {},
            "feedback": [],
            "policy": {
                "controller_is_sole_acceptor": True,
                "allowed_paths": ["app/"],
            },
            "output_contract": {},
        }
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = root / "workspace"
            workspace.mkdir()
            request_path = root / "request.json"
            request_path.write_text(worker.json.dumps(packet), encoding="utf-8")

            def construct_with_network_attempt(**_: object) -> object:
                worker.socket.create_connection(("example.invalid", 443))
                raise AssertionError("network denial did not stop graph construction")

            def package_version(name: str) -> str:
                if name == "deepagents":
                    return worker.EXPECTED_DEEPAGENTS_VERSION
                return worker.EXPECTED_PROVIDER_PACKAGES["openai"][1]

            with (
                mock.patch.object(worker, "version", side_effect=package_version),
                mock.patch.object(worker, "build_scripted_smoke_model", return_value=object()),
                mock.patch.object(
                    worker,
                    "build_bounded_agent",
                    side_effect=construct_with_network_attempt,
                ),
                mock.patch.object(
                    worker.socket,
                    "create_connection",
                    side_effect=AssertionError("network interception was installed too late"),
                ),
                self.assertRaisesRegex(
                    RuntimeError,
                    "network access is disabled during the scripted worker smoke",
                ),
            ):
                worker.run(
                    workspace=workspace,
                    request_path=request_path,
                    result_path=root / "result.json",
                    provider="openai",
                    model="scripted-smoke",
                    invocation_id="a" * 32,
                    max_turns=4,
                    scripted_smoke=True,
                )

    def test_third_party_profile_entry_point_is_rejected_before_loading(self) -> None:
        worker = smoke._load_worker()
        entry_point = SimpleNamespace(
            name="synthetic-plugin",
            value="synthetic:register",
            dist=SimpleNamespace(name="synthetic-distribution"),
        )
        with (
            mock.patch.object(
                worker.importlib.metadata,
                "entry_points",
                return_value=[entry_point],
            ),
            self.assertRaisesRegex(RuntimeError, "profile plugins are forbidden"),
        ):
            worker.reject_third_party_profile_plugins()

    def test_permissions_end_with_explicit_default_denies(self) -> None:
        worker = smoke._load_worker()
        permissions = worker._permission_specs(
            {
                "policy": {
                    "controller_is_sole_acceptor": True,
                    "allowed_paths": ["app/"],
                }
            }
        )
        self.assertEqual(permissions[0]["mode"], "allow")
        self.assertEqual(permissions[0]["paths"], ["/app/**"])
        self.assertEqual(
            permissions[1], {"operations": ["write"], "paths": ["/**"], "mode": "deny"}
        )
        self.assertEqual(
            permissions[-1], {"operations": ["read"], "paths": ["/**"], "mode": "deny"}
        )

    def test_system_prompt_denies_acceptance_and_external_authority(self) -> None:
        worker = smoke._load_worker()
        prompt = " ".join(worker.SYSTEM_PROMPT.lower().split())
        for phrase in (
            "untrusted candidate-authoring",
            "no shell",
            "no network",
            "no mcp",
            "persistent memory",
            "do not claim that tests passed",
            "independent controller",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, prompt)


if __name__ == "__main__":
    unittest.main()
