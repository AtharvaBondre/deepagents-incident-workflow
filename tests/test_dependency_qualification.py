import copy
import importlib.util
import tempfile
import unittest
import urllib.request
from datetime import timedelta
from pathlib import Path
from unittest import mock

SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "dependency_qualification.py"
SPEC = importlib.util.spec_from_file_location("dependency_qualification", SCRIPT_PATH)
assert SPEC and SPEC.loader
qualification = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(qualification)


class DependencyQualificationTests(unittest.TestCase):
    def test_installer_places_env_options_before_assignments(self) -> None:
        installer = (qualification.ROOT / "scripts" / "install-deepagents-runtime.sh").read_text(
            encoding="utf-8"
        )
        command_start = installer.index("env \\\n  -u PIP_EXTRA_INDEX_URL")
        command_end = installer.index('"${runtime_dir}/bin/python"', command_start)
        command = installer[command_start:command_end]
        self.assertLess(command.rindex("-u PIP_TRUSTED_HOST"), command.index('"HOME='))
        self.assertIn("PIP_CONFIG_FILE=/dev/null", command)

    def test_installer_rejects_symlink_before_destructive_clear(self) -> None:
        installer = (qualification.ROOT / "scripts" / "install-deepagents-runtime.sh").read_text(
            encoding="utf-8"
        )
        symlink_guard = installer.index('if [[ -L "${runtime_dir}" ]]')
        destructive_clear = installer.index('-m venv --clear "${runtime_dir}"')
        self.assertLess(symlink_guard, destructive_clear)

    def test_committed_qualification_matches_locks_and_policy(self) -> None:
        snapshot = qualification.load_snapshot(qualification.QUALIFICATION_PATH)
        self.assertEqual(qualification.validate_snapshot(snapshot), [])

    def test_lock_parser_requires_exact_well_formed_hashes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "runtime.lock"
            path.write_text(
                "example==1.2.3 \\\n    --hash=sha256:" + "a" * 64 + "\n",
                encoding="utf-8",
            )
            packages, hashes = qualification.parse_lock(path)
            self.assertEqual(packages, {"example": "1.2.3"})
            self.assertEqual(hashes, {"example": ["a" * 64]})

            path.write_text(
                "example==1.2.3 \\\n    --hash=sha256:not-a-digest\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(
                qualification.QualificationError,
                "unrecognized lock continuation",
            ):
                qualification.parse_lock(path)

    def test_provenance_tamper_fails_closed(self) -> None:
        snapshot = qualification.load_snapshot(qualification.QUALIFICATION_PATH)
        tampered = copy.deepcopy(snapshot)
        name = sorted(tampered["package_provenance"])[0]
        tampered["package_provenance"][name]["selected_lock_artifact_sha256"] = ["0" * 64]
        issues = qualification.validate_snapshot(tampered)
        self.assertIn(f"selected lock artifact provenance mismatch for {name}", issues)

    def test_source_tags_follow_locked_runtime_versions(self) -> None:
        refs = set(
            qualification.tracked_git_refs(
                {"deepagents": "9.8.7", "langgraph": "6.5.4"},
                {
                    "deepagents-code": "3.2.1",
                    "langgraph-checkpoint-sqlite": "4.3.2",
                },
            )
        )
        self.assertIn(
            ("langchain-ai/deepagents", "refs/tags/deepagents==9.8.7"),
            refs,
        )
        self.assertIn(("langchain-ai/langgraph", "refs/tags/6.5.4"), refs)
        self.assertIn(
            ("langchain-ai/deepagents", "refs/tags/deepagents-code==3.2.1"),
            refs,
        )
        self.assertIn(
            ("langchain-ai/langgraph", "refs/tags/checkpointsqlite==4.3.2"),
            refs,
        )

    def test_license_conclusion_must_be_derived_from_evidence(self) -> None:
        snapshot = qualification.load_snapshot(qualification.QUALIFICATION_PATH)
        tampered = copy.deepcopy(snapshot)
        self.assertEqual(tampered["licenses"]["certifi"]["conclusion"], "MPL-2.0")
        tampered["licenses"]["certifi"]["conclusion"] = "MIT"
        issues = qualification.validate_snapshot(tampered)
        self.assertIn("license conclusion does not match evidence for certifi", issues)

    def test_bool_and_malformed_timestamp_cannot_satisfy_snapshot_contract(self) -> None:
        snapshot = qualification.load_snapshot(qualification.QUALIFICATION_PATH)
        mutations = (
            (("schema_version",), True, "invalid top-level contract"),
            (("resolver", "universal"), 1, "controlled lock procedure"),
            (("captured_at",), "not-a-timestamp", "capture timestamp is invalid"),
        )
        page_url = sorted(snapshot["upstream"]["documentation"]["pages"])[0]
        mutations += (
            (
                ("upstream", "documentation", "pages", page_url, "bytes"),
                True,
                "invalid documentation byte count",
            ),
        )
        for path, value, expected_issue in mutations:
            tampered = copy.deepcopy(snapshot)
            target = tampered
            for key in path[:-1]:
                target = target[key]
            target[path[-1]] = value
            with self.subTest(path=path):
                self.assertTrue(
                    any(
                        expected_issue in issue
                        for issue in qualification.validate_snapshot(tampered)
                    )
                )

    def test_policy_cannot_switch_to_an_unapproved_package_index(self) -> None:
        snapshot = qualification.load_snapshot(qualification.QUALIFICATION_PATH)
        tampered_policy = dict(qualification.RESOLVER_POLICY)
        tampered_policy["index"] = "https://example.com/simple"
        snapshot["resolver"] = tampered_policy
        with mock.patch.object(qualification, "RESOLVER_POLICY", tampered_policy):
            issues = qualification.validate_snapshot(snapshot)
        self.assertIn("dependency resolver policy values are invalid", issues)

    def test_atomic_write_preserves_last_known_good_on_replace_failure(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "snapshot.json"
            path.write_text("last-known-good\n", encoding="utf-8")
            with (
                mock.patch.object(qualification.os, "replace", side_effect=OSError("blocked")),
                self.assertRaisesRegex(OSError, "blocked"),
            ):
                qualification.write_snapshot_atomic(path, {"candidate": True})
            self.assertEqual(path.read_text(encoding="utf-8"), "last-known-good\n")
            self.assertEqual(list(path.parent.glob(".snapshot.json.*.tmp")), [])

    def test_documentation_inventory_rejects_wrong_subtree(self) -> None:
        snapshot = qualification.load_snapshot(qualification.QUALIFICATION_PATH)
        tampered = copy.deepcopy(snapshot)
        code_inventory = tampered["upstream"]["documentation"]["inventories"]["code"]
        code_inventory[0] = "https://docs.langchain.com/oss/python/deepagents/overview.md"
        code_inventory.sort()
        issues = qualification.validate_snapshot(tampered)
        self.assertIn("qualified code documentation inventory is invalid", issues)

    def test_package_timestamps_and_versions_must_be_nonempty_and_bounded(self) -> None:
        snapshot = qualification.load_snapshot(qualification.QUALIFICATION_PATH)
        resolution_cutoff = qualification.parse_utc_timestamp(qualification.RESOLUTION_CUTOFF)
        self.assertIsNotNone(resolution_cutoff)
        after_cutoff = (resolution_cutoff + timedelta(seconds=1)).isoformat().replace("+00:00", "Z")
        cases = (
            (
                ("package_provenance", "deepagents", "release_latest_upload"),
                after_cutoff,
                "release-upload provenance exceeds cutoff for deepagents",
            ),
            (
                ("upstream", "pypi_latest", "deepagents", "latest_upload"),
                "",
                "invalid tracked PyPI record for deepagents",
            ),
            (
                ("upstream", "pypi_latest", "deepagents", "version"),
                "",
                "invalid tracked PyPI record for deepagents",
            ),
        )
        for path, value, expected_issue in cases:
            tampered = copy.deepcopy(snapshot)
            target = tampered
            for key in path[:-1]:
                target = target[key]
            target[path[-1]] = value
            with self.subTest(path=path):
                self.assertIn(expected_issue, qualification.validate_snapshot(tampered))

    def test_network_evidence_is_restricted_to_official_hosts(self) -> None:
        qualification._validated_upstream_url("https://pypi.org/pypi/deepagents/json")
        qualification._validated_upstream_url(
            "https://github.com/langchain-ai/deepagents/blob/main/libs/code/CHANGELOG.md"
        )
        qualification._validated_upstream_url(
            "https://api.github.com/repos/langchain-ai/deepagents/commits"
        )
        for url in (
            "http://pypi.org/pypi/deepagents/json",
            "https://example.com/pypi/deepagents/json",
            "https://github.com/unrelated/project/blob/main/README.md",
            "https://api.github.com/repos/unrelated/project/commits",
        ):
            with self.subTest(url=url), self.assertRaises(qualification.QualificationError):
                qualification._validated_upstream_url(url)

    def test_redirect_is_rejected_before_following_an_unapproved_host(self) -> None:
        handler = qualification.ValidatingRedirectHandler()
        request = urllib.request.Request("https://docs.langchain.com/llms.txt")
        with self.assertRaises(qualification.QualificationError):
            handler.redirect_request(
                request,
                None,
                302,
                "Found",
                {},
                "https://example.com/untrusted",
            )


if __name__ == "__main__":
    unittest.main()
