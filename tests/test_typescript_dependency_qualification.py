import copy
import importlib.util
import json
import tempfile
import unittest
import urllib.request
from pathlib import Path
from unittest import mock

SCRIPT_PATH = (
    Path(__file__).resolve().parents[1] / "scripts" / "typescript_dependency_qualification.py"
)
SPEC = importlib.util.spec_from_file_location("typescript_dependency_qualification", SCRIPT_PATH)
assert SPEC and SPEC.loader
qualification = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(qualification)


class TypeScriptDependencyQualificationTests(unittest.TestCase):
    def test_committed_lock_and_evidence_are_qualified(self) -> None:
        result = qualification.validate()
        self.assertTrue(result["ok"])
        self.assertEqual(result["node_version"], "22.23.2")
        self.assertEqual(result["deepagents_version"], "1.13.1")
        self.assertEqual(result["package_count"], 82)

    def test_lock_rejects_non_registry_source(self) -> None:
        lock = qualification.read_json(qualification.PACKAGE_LOCK)
        tampered = copy.deepcopy(lock)
        name = sorted(key for key in tampered["packages"] if key)[0]
        tampered["packages"][name]["resolved"] = "https://example.invalid/package.tgz"
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "package-lock.json"
            path.write_text(json.dumps(tampered), encoding="utf-8")
            with (
                mock.patch.object(qualification, "PACKAGE_LOCK", path),
                self.assertRaisesRegex(
                    qualification.QualificationError, "non-registry package source"
                ),
            ):
                qualification.validate()

    def test_lock_rejects_install_scripts(self) -> None:
        lock = qualification.read_json(qualification.PACKAGE_LOCK)
        tampered = copy.deepcopy(lock)
        name = sorted(key for key in tampered["packages"] if key)[0]
        tampered["packages"][name]["hasInstallScript"] = True
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "package-lock.json"
            path.write_text(json.dumps(tampered), encoding="utf-8")
            with (
                mock.patch.object(qualification, "PACKAGE_LOCK", path),
                self.assertRaisesRegex(
                    qualification.QualificationError, "lock evidence does not match"
                ),
            ):
                qualification.validate()

    def test_installer_checks_versions_and_symlink_before_replacement(self) -> None:
        installer = (
            qualification.ROOT / "scripts" / "install-deepagents-typescript-runtime.sh"
        ).read_text(encoding="utf-8")
        self.assertIn('node_version}" != "22.23.2"', installer)
        self.assertIn('npm_version}" != "10.9.8"', installer)
        symlink_guard = installer.index('if [[ -L "${runtime_dir}" ]]')
        replacement = installer.index('rm -rf -- "${runtime_dir}"')
        self.assertLess(symlink_guard, replacement)
        self.assertIn(
            '"${npm_bin}" ci --ignore-scripts --engine-strict --no-audit --no-fund',
            installer,
        )
        self.assertIn(
            '"${npm_bin}" prune --omit=dev --ignore-scripts --no-audit --no-fund',
            installer,
        )
        self.assertIn('"${npm_bin}" ls --omit=dev --all --json', installer)

    def test_online_sources_are_restricted_to_official_hosts(self) -> None:
        qualification.validated_upstream_url("https://registry.npmjs.org/deepagents/latest")
        qualification.validated_upstream_url(
            "https://api.github.com/repos/langchain-ai/deepagentsjs/git/tags/" + "a" * 40
        )
        qualification.validated_upstream_url(
            "https://docs.langchain.com/oss/javascript/deepagents/overview.md"
        )
        for url in (
            "http://registry.npmjs.org/deepagents/latest",
            "https://example.invalid/deepagents/latest",
            "https://api.github.com/repos/unrelated/project/git/tags/" + "a" * 40,
        ):
            with self.subTest(url=url), self.assertRaises(qualification.QualificationError):
                qualification.validated_upstream_url(url)

    def test_redirect_rejects_an_unapproved_host(self) -> None:
        handler = qualification.ValidatingRedirectHandler()
        request = urllib.request.Request(
            "https://docs.langchain.com/oss/deepagents/code/overview.md"
        )
        with self.assertRaises(qualification.QualificationError):
            handler.redirect_request(
                request,
                None,
                302,
                "Found",
                {},
                "https://example.invalid/untrusted",
            )


if __name__ == "__main__":
    unittest.main()
