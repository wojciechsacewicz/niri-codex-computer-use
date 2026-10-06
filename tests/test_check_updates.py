"""Offline tests for the read-only upstream reporter."""

from contextlib import redirect_stdout
import http.client
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import urllib.error


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "check-updates.py"
spec = importlib.util.spec_from_file_location("check_updates", SCRIPT)
updates = importlib.util.module_from_spec(spec)
spec.loader.exec_module(updates)
PIN = "a" * 40
STABLE = "b" * 40
MAIN = "c" * 40


class CheckUpdatesTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.lock_path = Path(self.directory.name) / "sources.lock.json"
        self.lock = {"schema": 1, **{
            name: {"repository": f"https://github.com/example/{name}", "revision": PIN}
            for name in updates.COMPONENTS
        }}
        self.responses = {}
        for name in updates.COMPONENTS:
            base = f"https://api.github.com/repos/example/{name}"
            self.responses[base + "/commits/HEAD"] = {"sha": PIN}
        base = "https://api.github.com/repos/example/niri"
        self.responses[base + "/releases/latest"] = {
            "tag_name": "v26.04", "draft": False, "prerelease": False,
            "target_commitish": "main", "sha": "d" * 40,
        }
        self.responses[base + "/commits/v26.04"] = {"sha": STABLE}
        self.responses[base + "/commits/main"] = {"sha": MAIN}
        self.calls = []

    def fetch(self, url):
        self.calls.append(url)
        response = self.responses[url]
        if isinstance(response, Exception):
            raise response
        return response

    def write_lock(self):
        self.lock_path.write_text(json.dumps(self.lock), encoding="utf-8")

    def report(self):
        self.write_lock()
        return updates.check_updates(self.lock_path, self.fetch)

    def test_stable_commit_and_development_are_separate(self):
        report = self.report()
        niri = report["components"][1]
        self.assertEqual(report["errors"], [])
        self.assertEqual(niri["stable"], {
            "tag": "v26.04", "revision": STABLE, "update_available": True,
        })
        self.assertEqual(niri["development"]["revision"], MAIN)
        self.assertEqual(niri["development"]["ref"], "main")
        self.assertIn("https://api.github.com/repos/example/niri/commits/v26.04", self.calls)
        self.assertEqual(len(self.calls), 5)
        for component in (report["components"][0], report["components"][2]):
            self.assertEqual(component["default_head"]["ref"], "HEAD")
            self.assertFalse(component["default_head"]["update_available"])

    def test_prerelease_and_draft_cannot_be_reported_as_stable(self):
        release = self.responses["https://api.github.com/repos/example/niri/releases/latest"]
        for flag in ("prerelease", "draft"):
            with self.subTest(flag=flag):
                release[flag] = True
                self.calls.clear()
                report = self.report()
                niri = report["components"][1]
                self.assertNotIn("stable", niri)
                self.assertEqual(niri["development"]["revision"], MAIN)
                self.assertEqual(report["errors"][0]["channel"], "stable")
                self.assertNotIn("https://api.github.com/repos/example/niri/commits/v26.04", self.calls)
                release[flag] = False

    def test_matching_revisions_are_case_insensitive(self):
        self.lock["niri"]["revision"] = STABLE.upper()
        self.responses["https://api.github.com/repos/example/niri/commits/main"] = {"sha": STABLE}
        niri = self.report()["components"][1]
        self.assertFalse(niri["stable"]["update_available"])
        self.assertFalse(niri["development"]["update_available"])

    def test_tag_is_encoded_as_a_single_ref(self):
        self.responses["https://api.github.com/repos/example/niri/releases/latest"]["tag_name"] = "release/26.04"
        self.responses["https://api.github.com/repos/example/niri/commits/release%2F26.04"] = {"sha": STABLE}
        self.assertEqual(self.report()["components"][1]["stable"]["revision"], STABLE)

    def test_network_errors_continue_for_every_component_and_channel(self):
        for suffix in ("upstream_patches/commits/HEAD", "niri/releases/latest",
                       "niri/commits/main", "codex_desktop_linux/commits/HEAD"):
            with self.subTest(suffix=suffix):
                url = "https://api.github.com/repos/example/" + suffix
                old = self.responses[url]
                self.responses[url] = urllib.error.URLError("offline")
                report = self.report()
                self.assertEqual(len(report["components"]), 3)
                self.assertEqual(len(report["errors"]), 1)
                self.assertIn("offline", report["errors"][0]["message"])
                if suffix.startswith("niri/"):
                    other = "development" if "releases" in suffix else "stable"
                    self.assertIn(other, report["components"][1])
                else:
                    self.assertIn("stable", report["components"][1])
                self.responses[url] = old

    def test_invalid_repository_is_rejected_before_fetch(self):
        invalid = ("http://github.com/o/r", "https://evil.test/o/r",
                   "https://github.com.evil.test/o/r", "https://github.com/o/r/extra",
                   "https://user@github.com/o/r", "https://github.com/o/r?x=1",
                   "https://github.com/o/r#main", "https://github.com/o/..",
                   "https://github.com/o/r.git", "https://github.com/o/r/", None, 42)
        for repository in invalid:
            with self.subTest(repository=repository):
                self.lock["upstream_patches"]["repository"] = repository
                self.calls.clear()
                report = self.report()
                self.assertEqual(report["errors"][0]["channel"], "validation")
                self.assertEqual(len(report["components"]), 2)
                self.assertFalse(any("upstream_patches" in url for url in self.calls))

    def test_transport_failures_accumulate_without_aborting(self):
        for suffix, error in (
            ("upstream_patches/commits/HEAD", urllib.error.HTTPError("url", 429, "rate limit", {}, None)),
            ("niri/releases/latest", http.client.IncompleteRead(b"{", 100)),
            ("codex_desktop_linux/commits/HEAD", json.JSONDecodeError("bad JSON", "{", 1)),
        ):
            self.responses["https://api.github.com/repos/example/" + suffix] = error
        report = self.report()
        self.assertEqual(len(report["errors"]), 3)
        self.assertEqual(report["components"][1]["development"]["revision"], MAIN)

    def test_missing_release_fields_are_errors(self):
        url = "https://api.github.com/repos/example/niri/releases/latest"
        for release in ([], {}, {"draft": False, "prerelease": False},
                        {"draft": False, "prerelease": False, "tag_name": ""}):
            with self.subTest(release=release):
                self.responses[url] = release
                report = self.report()
                self.assertEqual(report["errors"][0]["channel"], "stable")
                self.assertIn("development", report["components"][1])

    def test_invalid_revision_and_missing_component(self):
        for revision in (None, 123, "main", "a" * 39, "a" * 41, "g" * 40):
            with self.subTest(revision=revision):
                self.lock["upstream_patches"]["revision"] = revision
                self.assertEqual(self.report()["errors"][0]["channel"], "validation")
        del self.lock["upstream_patches"]
        self.assertEqual(self.report()["errors"][0]["component"], "upstream_patches")

    def test_invalid_lock_schema(self):
        for lock in ([], {}, {"schema": True}, {"schema": "1"}, {"schema": 2}):
            with self.subTest(lock=lock):
                self.lock = lock
                self.calls.clear()
                report = self.report()
                self.assertEqual(report["components"], [])
                self.assertEqual(report["errors"][0]["component"], "lock")
                self.assertEqual(self.calls, [])

    def test_malformed_upstream_data_is_a_channel_error(self):
        url = "https://api.github.com/repos/example/niri/commits/v26.04"
        for data in ([], {}, {"sha": "tag-object"}):
            with self.subTest(data=data):
                self.responses[url] = data
                report = self.report()
                self.assertEqual(report["errors"][0]["channel"], "stable")
                self.assertIn("development", report["components"][1])

    def run_cli(self, *args):
        output = io.StringIO()

        def urlopen(request, timeout):
            self.assertEqual(timeout, updates.TIMEOUT)
            return io.StringIO(json.dumps(self.fetch(request.full_url)))

        with patch.object(updates.urllib.request, "urlopen", side_effect=urlopen), redirect_stdout(output):
            status = updates.main(["--lock", str(self.lock_path), *args])
        return status, output.getvalue()

    def test_cli_json_is_one_document_and_never_modifies_lock(self):
        self.write_lock()
        before = self.lock_path.read_bytes()
        status, output = self.run_cli("--json")
        self.assertEqual(status, 0)
        self.assertEqual(json.loads(output)["errors"], [])
        self.assertEqual(self.lock_path.read_bytes(), before)
        self.assertEqual(list(Path(self.directory.name).iterdir()), [self.lock_path])

    def test_cli_json_contains_network_errors_and_exits_nonzero(self):
        self.write_lock()
        self.responses["https://api.github.com/repos/example/upstream_patches/commits/HEAD"] = TimeoutError("timed out")
        status, output = self.run_cli("--json")
        report = json.loads(output)
        self.assertEqual(status, 1)
        self.assertEqual(report["errors"][0]["component"], "upstream_patches")
        self.assertIn("default_head", report["components"][2])

    def test_cli_readable_default(self):
        self.write_lock()
        status, output = self.run_cli()
        self.assertEqual(status, 0)
        self.assertIn("stable (v26.04)", output)
        self.assertIn("development (main)", output)
        self.assertIn("matches pin", output)

    def test_cli_default_lock_is_repository_relative(self):
        output = io.StringIO()
        with patch.object(updates, "check_updates", return_value={"components": [], "errors": []}) as check:
            with redirect_stdout(output):
                self.assertEqual(updates.main(["--json"]), 0)
        check.assert_called_once_with(SCRIPT.parents[1] / "sources.lock.json")

    def test_cli_json_lock_errors_in_subprocess(self):
        for contents in (None, "{", "[]"):
            with self.subTest(contents=contents):
                if contents is not None:
                    self.lock_path.write_text(contents, encoding="utf-8")
                result = subprocess.run(
                    [sys.executable, "-B", str(SCRIPT), "--json", "--lock", str(self.lock_path)],
                    capture_output=True, text=True, timeout=5,
                )
                self.assertEqual(result.returncode, 1)
                self.assertEqual(result.stderr, "")
                self.assertEqual(json.loads(result.stdout)["errors"][0]["component"], "lock")


if __name__ == "__main__":
    unittest.main()
