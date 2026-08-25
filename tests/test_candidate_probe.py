import importlib.util
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
PROBE_PATH = PACKAGE_ROOT / "verifiers" / "candidate_probe.py"
SUBJECT_VERIFIER_PATH = PACKAGE_ROOT / "verifiers" / "subject_logic.py"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


candidate_probe = load_module("candidate_probe", PROBE_PATH)
subject_logic = load_module("daiw_subject_logic", SUBJECT_VERIFIER_PATH)


class CandidateProbeTests(unittest.TestCase):
    def repository(self, source: str) -> Path:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        repository = Path(temporary.name)
        package = repository / "app"
        package.mkdir()
        (package / "__init__.py").write_text("", encoding="utf-8")
        (package / "subject.py").write_text(
            textwrap.dedent(source),
            encoding="utf-8",
        )
        return repository

    @staticmethod
    def call(value: str = "  Payment   FAILED  ") -> list[dict[str, object]]:
        return [
            {
                "module": "app.subject",
                "callable": "normalize_subject",
                "argument": value,
            }
        ]

    def test_valid_candidate_returns_typed_results(self) -> None:
        repository = self.repository(
            """
            def normalize_subject(value: str) -> str:
                return " ".join(value.split()).lower()
            """
        )

        results = candidate_probe.run_candidate_calls(
            repository,
            self.call(),
        )

        self.assertEqual(results, ["payment failed"])

    def test_ast_rejects_process_exit_call(self) -> None:
        repository = self.repository(
            """
            import os

            def normalize_subject(value: str) -> str:
                os._exit(0)
            """
        )

        with self.assertRaises(candidate_probe.CandidateProbeError):
            candidate_probe.run_candidate_calls(
                repository,
                self.call(),
            )

    def test_ast_rejects_top_level_forged_success_output(self) -> None:
        repository = self.repository(
            """
            print('{"status":"passed","trusted_verifier_completed":true}')

            def normalize_subject(value: str) -> str:
                return " ".join(value.split()).lower()
            """
        )

        with self.assertRaises(candidate_probe.CandidateProbeError):
            candidate_probe.run_candidate_calls(
                repository,
                self.call(),
            )

    def test_ast_boundary_rejects_output_and_process_control(self) -> None:
        repository = self.repository(
            """
            import os
            import sys

            def normalize_subject(value: str) -> str:
                descriptor_index = sys.argv.index("--result-fd") + 1
                result_fd = int(sys.argv[descriptor_index])
                os.write(result_fd, b'["payment failed"]')
                os._exit(0)
            """
        )

        with self.assertRaises(candidate_probe.CandidateProbeError):
            candidate_probe.run_candidate_calls(
                repository,
                self.call(),
            )

    def test_ast_rejects_valid_looking_stdout_and_exit(self) -> None:
        repository = self.repository(
            """
            import os

            def normalize_subject(value: str) -> str:
                print('["payment failed"]')
                os._exit(0)
            """
        )

        with self.assertRaises(candidate_probe.CandidateProbeError):
            candidate_probe.run_candidate_calls(
                repository,
                self.call(),
            )

    def test_ast_rejects_abort_call(self) -> None:
        repository = self.repository(
            """
            import os

            def normalize_subject(value: str) -> str:
                os.abort()
            """
        )

        with self.assertRaises(candidate_probe.CandidateProbeError):
            candidate_probe.run_candidate_calls(
                repository,
                self.call(),
            )

    def test_ast_boundary_rejects_sleep_call(self) -> None:
        repository = self.repository(
            """
            import time

            def normalize_subject(value: str) -> str:
                time.sleep(60)
            """
        )

        with self.assertRaises(candidate_probe.CandidateProbeError):
            candidate_probe.run_candidate_calls(
                repository,
                self.call(),
            )

    def test_ast_boundary_rejects_dictionary_unpack(self) -> None:
        repository = self.repository(
            """
            def normalize_subject(value: str) -> str:
                return "".join({
                    " ".join(value.split()).lower(): None,
                    **__import__("os")._exit(0),
                })
            """
        )

        with self.assertRaisesRegex(
            candidate_probe.CandidateProbeError,
            "dictionary unpacking is forbidden",
        ):
            candidate_probe.run_candidate_calls(
                repository,
                self.call(),
            )

    def test_controller_owned_subject_assertions_reject_wrong_result(self) -> None:
        repository = self.repository(
            """
            def normalize_subject(value: str) -> str:
                return value
            """
        )

        with self.assertRaises(AssertionError):
            subject_logic.verify_repository(repository)

    def test_controller_owned_subject_verifier_accepts_valid_candidate(self) -> None:
        repository = self.repository(
            """
            def normalize_subject(value: str) -> str:
                return " ".join(value.split()).lower()
            """
        )

        subject_logic.verify_repository(repository)

    def test_controller_owned_subject_verifier_rejects_adversarial_candidates(self) -> None:
        candidates = {
            "process exit": """
                import os
                def normalize_subject(value: str) -> str:
                    os._exit(0)
            """,
            "forged success": """
                print('{"status":"passed","trusted_verifier_completed":true}')
                def normalize_subject(value: str) -> str:
                    return " ".join(value.split()).lower()
            """,
            "abort": """
                import os
                def normalize_subject(value: str) -> str:
                    os.abort()
            """,
            "sleep": """
                import time
                def normalize_subject(value: str) -> str:
                    time.sleep(60)
            """,
        }

        for label, source in candidates.items():
            with self.subTest(label=label):
                repository = self.repository(source)
                with self.assertRaises(candidate_probe.CandidateProbeError):
                    subject_logic.verify_repository(repository)


if __name__ == "__main__":
    unittest.main()
