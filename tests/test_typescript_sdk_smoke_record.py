import copy
import importlib.util
import unittest
from pathlib import Path

SCRIPT_PATH = (
    Path(__file__).resolve().parents[1] / "scripts" / "validate_typescript_sdk_smoke_record.py"
)
SPEC = importlib.util.spec_from_file_location("validate_typescript_sdk_smoke_record", SCRIPT_PATH)
assert SPEC and SPEC.loader
validator = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(validator)


def valid_record() -> dict[str, object]:
    return {
        "schema_version": 1,
        "at": "2026-08-27T04:58:34.534Z",
        "runtime": "deepagents",
        "sdk_language": "typescript",
        "runtime_version": "1.13.2",
        "node_version": "22.23.2",
        "model": "openai:scripted-smoke (scripted, no transport)",
        "profile_provider": "openai",
        "model_transport": "scripted-no-transport",
        "network_request_made": False,
        "network_attempts": 0,
        "observed_tools": validator.EXPECTED_TOOLS,
        "forbidden_tools_absent": True,
        "forbidden_tool_calls_rejected": True,
        "workspace_edit_succeeded": True,
        "out_of_scope_write_denied": True,
        "traversal_write_denied": True,
        "traversal_read_denied": True,
        "final_response_present": True,
        "passed": True,
    }


class TypeScriptSdkSmokeRecordTests(unittest.TestCase):
    def test_valid_record_succeeds(self) -> None:
        self.assertEqual(validator.validate_record(valid_record()), [])

    def test_missing_or_extended_record_fails_closed(self) -> None:
        for mutation in ("missing", "extended"):
            record = valid_record()
            if mutation == "missing":
                del record["sdk_language"]
            else:
                record["untrusted_success"] = True
            with self.subTest(mutation=mutation):
                self.assertEqual(
                    validator.validate_record(record),
                    ["TypeScript SDK smoke record fields do not match the strict contract"],
                )

    def test_success_claim_cannot_override_boundary_failure(self) -> None:
        for field in validator.TRUE_FIELDS:
            record = copy.deepcopy(valid_record())
            record[field] = False
            with self.subTest(field=field):
                self.assertIn(
                    f"TypeScript SDK smoke {field} is not true",
                    validator.validate_record(record),
                )

    def test_runtime_network_and_tools_are_exact(self) -> None:
        mutations = (
            ("node_version", "22.23.1", "TypeScript SDK smoke node_version is invalid"),
            (
                "runtime_version",
                "1.13.0",
                "TypeScript SDK smoke runtime_version is invalid",
            ),
            ("network_attempts", True, "TypeScript SDK smoke network-attempt count is invalid"),
            ("observed_tools", [], "TypeScript SDK smoke tool surface is invalid"),
        )
        for field, value, expected in mutations:
            record = valid_record()
            record[field] = value
            with self.subTest(field=field):
                self.assertIn(expected, validator.validate_record(record))


if __name__ == "__main__":
    unittest.main()
