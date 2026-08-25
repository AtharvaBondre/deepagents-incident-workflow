import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest import mock

CHECKER_PATH = Path(__file__).resolve().parents[1] / "scripts" / "check-public-surface.py"
SPEC = importlib.util.spec_from_file_location("daiw_public_surface", CHECKER_PATH)
assert SPEC and SPEC.loader
checker = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(checker)


class PublicSurfaceTests(unittest.TestCase):
    def test_directory_symlink_is_included_for_irregular_path_rejection(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = root / "target"
            target.mkdir()
            linked = root / "linked-directory"
            linked.symlink_to(target, target_is_directory=True)
            with mock.patch.object(checker, "ROOT", root):
                discovered = checker.source_files()
            self.assertIn(linked, discovered)
            self.assertTrue(linked.is_symlink())

    def test_ignored_runtime_symlink_is_still_inspected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = root / "target"
            target.mkdir()
            runtime = root / ".deepagents-runtime"
            runtime.symlink_to(target, target_is_directory=True)
            with mock.patch.object(checker, "ROOT", root):
                discovered = checker.source_files()
            self.assertIn(runtime, discovered)

    def test_common_provider_token_shapes_are_detected(self) -> None:
        examples = (
            "ASIA" + "E" * 16,
            "github_" + "pat_" + "f" * 24,
            "sk-proj-" + "a" * 24,
            "sk-ant-" + "b" * 24,
            "xoxb-" + "c" * 24,
            "glpat-" + "d" * 24,
        )
        for value in examples:
            with self.subTest(prefix=value.split("-")[0]):
                self.assertTrue(any(pattern.search(value) for pattern in checker.SECRET_PATTERNS))


if __name__ == "__main__":
    unittest.main()
