import importlib.util
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

CHECKER_PATH = Path(__file__).resolve().parents[1] / "scripts" / "check-public-surface.py"
SPEC = importlib.util.spec_from_file_location("daiw_public_surface", CHECKER_PATH)
assert SPEC and SPEC.loader
checker = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(checker)

IMAGE_CHECKER_PATH = (
    Path(__file__).resolve().parents[1] / "scripts" / "check-image-vulnerabilities.py"
)
IMAGE_SPEC = importlib.util.spec_from_file_location("daiw_image_check", IMAGE_CHECKER_PATH)
assert IMAGE_SPEC and IMAGE_SPEC.loader
image_checker = importlib.util.module_from_spec(IMAGE_SPEC)
IMAGE_SPEC.loader.exec_module(image_checker)


class PublicSurfaceTests(unittest.TestCase):
    def test_internal_coordination_paths_are_forbidden(self) -> None:
        self.assertIn("docs/implementation-plan.md", checker.FORBIDDEN_INTERNAL_PATHS)
        self.assertIn("docs/product-roadmap.md", checker.FORBIDDEN_INTERNAL_PATHS)
        self.assertTrue(
            any(
                pattern.fullmatch("continuation-handoff-2026-08-25.md")
                for pattern in checker.FORBIDDEN_INTERNAL_NAMES
            )
        )
        self.assertTrue(
            any(
                pattern.fullmatch("deepagents-research-2026-08-25.md")
                for pattern in checker.FORBIDDEN_INTERNAL_NAMES
            )
        )

    def test_image_scan_has_a_bounded_extended_analysis_window(self) -> None:
        completed = SimpleNamespace(returncode=0, stdout='{"Results": []}', stderr="")
        with mock.patch.object(image_checker.subprocess, "run", return_value=completed) as run:
            image_checker.scan("example.invalid/image@sha256:" + "a" * 64)
        command = run.call_args.args[0]
        self.assertEqual(command[command.index("--timeout") + 1], "10m")
        self.assertEqual(run.call_args.kwargs["timeout"], 660)

    def test_every_dockerfile_is_in_the_vulnerability_pin_sources(self) -> None:
        expected = set(checker.ROOT.glob("docker/**/Dockerfile"))
        self.assertEqual(
            expected, {path for path in image_checker.PIN_SOURCES if path.name == "Dockerfile"}
        )

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
