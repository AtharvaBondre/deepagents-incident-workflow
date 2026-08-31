import copy
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "validate_sdk_smoke_record.py"
SPEC = importlib.util.spec_from_file_location("validate_sdk_smoke_record", SCRIPT_PATH)
assert SPEC and SPEC.loader
validator = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(validator)


def valid_record() -> dict[str, object]:
    return {
        "schema_version": 1,
        "at": "2026-08-25T16:41:17+00:00",
        "runtime": "deepagents",
        "runtime_version": "0.7.11",
        "network_request_made": False,
        "network_attempts": 0,
        "model": "openai:gpt-5.2-codex (scripted, no transport)",
        "profile_provider": "openai",
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


class SdkSmokeRecordTests(unittest.TestCase):
    def test_valid_record_succeeds(self) -> None:
        self.assertEqual(validator.validate_record(valid_record()), [])

    def test_missing_or_extended_record_fails_closed(self) -> None:
        for mutate in ("missing", "extended"):
            record = valid_record()
            if mutate == "missing":
                del record["runtime"]
            else:
                record["untrusted_success"] = True
            with self.subTest(mutate=mutate):
                self.assertEqual(
                    validator.validate_record(record),
                    ["SDK smoke record fields do not match the strict contract"],
                )

    def test_success_claim_cannot_override_failed_boundary(self) -> None:
        for field in validator.TRUE_FIELDS:
            record = copy.deepcopy(valid_record())
            record[field] = False
            with self.subTest(field=field):
                self.assertIn(
                    f"SDK smoke {field} is not true",
                    validator.validate_record(record),
                )

    def test_network_count_rejects_boolean_or_nonzero_values(self) -> None:
        for value in (True, 1):
            record = valid_record()
            record["network_attempts"] = value
            with self.subTest(value=value):
                self.assertIn(
                    "SDK smoke network-attempt count is invalid",
                    validator.validate_record(record),
                )

    def test_runtime_and_tool_surface_are_exact(self) -> None:
        mutations = (
            ("runtime_version", "0.7.9", "SDK smoke runtime_version is invalid"),
            ("observed_tools", [], "SDK smoke tool surface is invalid"),
            ("observed_tools", True, "SDK smoke tool surface is invalid"),
        )
        for field, value, expected in mutations:
            record = valid_record()
            record[field] = value
            with self.subTest(field=field, value=value):
                self.assertIn(expected, validator.validate_record(record))

    def test_loader_rejects_symlinked_record(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = root / "record.json"
            target.write_text(json.dumps(valid_record()), encoding="utf-8")
            link = root / "record-link.json"
            link.symlink_to(target)
            with self.assertRaisesRegex(ValueError, "regular file"):
                validator.load_record(link)


if __name__ == "__main__":
    unittest.main()
