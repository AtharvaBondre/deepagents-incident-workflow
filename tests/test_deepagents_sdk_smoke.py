import importlib.util
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
