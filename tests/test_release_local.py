"""Offline unit simulations; no signing, notarization, GitHub, or physical UI proof."""
import importlib.util
import io
import tarfile
import zipfile
import json
from pathlib import Path
import plistlib
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / "native-host/release-local.py"
spec = importlib.util.spec_from_file_location("release_local", SCRIPT)
r = importlib.util.module_from_spec(spec)
spec.loader.exec_module(r)


class ReleaseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.stage = Path(self.temp.name)
        (self.stage / "evidence").mkdir()
        self.state = dict(tag="v3.7.5-mason.1", source_sha="a" * 40,
                          app_version="3.7.5", extension_version="3.7.4",
                          phase="signed", identity="B" * 40, profile="TabSwitcher")

    def test_help_and_invalid_cli_need_no_credentials(self):
        for command in [[], ["prepare"], ["resume"], ["publish"]]:
            result = subprocess.run([sys.executable, str(SCRIPT), *command, "--help"], capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
        for args in [[], ["prepare", "../../escape"], ["resume", "v3.7.5-mason.1", "--wait-seconds", "999"]]:
            self.assertNotEqual(subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True).returncode, 0)

    def test_dirty_source_and_unsafe_tag_paths(self):
        for status in [" M README.md", "?? untracked", "A  staged"]:
            with self.assertRaises(r.ReleaseError):
                r.clean_source(status)
        r.clean_source("")
        for tag in ["../v3.7.5-mason.1", "v3.7.5-mason.0", "--help", "v3.7.5-mason.1/x", "v3.7.5-mason.1\n"]:
            with self.assertRaises(r.ReleaseError):
                r.stage_path(self.stage, tag)
        (self.stage / "dist").symlink_to(self.stage / "evidence", target_is_directory=True)
        with self.assertRaises(r.ReleaseError):
            r.stage_path(self.stage, self.state["tag"])

    def test_identity_requires_explicit_sha(self):
        for identity in [None, "Developer ID Application: Mason", "-", "a" * 39]:
            with self.assertRaises(r.ReleaseError):
                r.identity_value(identity)
        self.assertEqual(r.identity_value("b" * 40), "B" * 40)

    def test_versions_are_independent_and_pairing_is_enforced(self):
        source = self.stage / "fixture-source"
        main = source / "native-host/Sources/tab-switcher/main.swift"
        main.parent.mkdir(parents=True)
        main.write_text('let APP_VERSION = "3.7.5"')
        (source / "manifest.json").write_text('{"version":"3.7.4"}')
        self.assertEqual(r.versions(source, self.state["tag"]), ("3.7.5", "3.7.4"))
        with self.assertRaises(r.ReleaseError):
            r.versions(source, "v3.7.4-mason.1")
        main.write_text('let APP_VERSION = "9.2.1"')
        (source / "manifest.json").write_text('{"version":"6.0.0"}')
        self.assertEqual(r.versions(source, "v9.2.1-mason.2"), ("9.2.1", "6.0.0"))
        app = self.stage / "app"
        (app / "Contents").mkdir(parents=True)
        ext = self.stage / "extension"
        ext.mkdir()
        key = (r.ROOT / "native-host/local-extension/public-key.txt").read_text().strip()
        manifest = dict(version="3.7.4", key=key)
        (ext / "manifest.json").write_text(json.dumps(manifest))
        (ext / "mainsw.js").write_text(f'connectNative("{r.HOST}")')
        info = dict(CFBundleIdentifier=r.HOST, TabSwitcherLocalBuild=True,
                    TabSwitcherLocalExtensionID=r.EXTENSION_ID, CFBundleVersion="3.7.5",
                    CFBundleShortVersionString="3.7.5", SUEnableAutomaticChecks=False, SUAutomaticallyUpdate=False)
        (app / "Contents/Info.plist").write_bytes(plistlib.dumps(info))
        r.pairing(r.ROOT, app, ext, self.state)
        for field, value in [("CFBundleVersion", "3.7.4"), ("TabSwitcherLocalExtensionID", "a" * 32)]:
            altered = dict(info, **{field: value})
            (app / "Contents/Info.plist").write_bytes(plistlib.dumps(altered))
            with self.assertRaises(r.ReleaseError):
                r.pairing(r.ROOT, app, ext, self.state)
        (app / "Contents/Info.plist").write_bytes(plistlib.dumps(info))
        (ext / "manifest.json").write_text(json.dumps(dict(manifest, key="AAAA")))
        with self.assertRaises(r.ReleaseError):
            r.pairing(r.ROOT, app, ext, self.state)

    def test_snapshot_rejects_extra_build_inputs_but_allows_caches(self):
        source = self.stage / "source"
        source.mkdir()
        name = "native-host/Sources/main.swift"
        payload = b"let example = 1"
        with tarfile.open(self.stage / "source.tar", "w") as archive:
            info = tarfile.TarInfo(name)
            info.size = len(payload)
            archive.addfile(info, io.BytesIO(payload))
        path = source / name
        path.parent.mkdir(parents=True)
        path.write_bytes(payload)
        self.state["source_archive_sha256"] = r.sha256(self.stage / "source.tar")
        cache = source / "native-host/.build-local/generated.swift"
        cache.parent.mkdir(parents=True)
        cache.write_text("generated")
        r.verify_snapshot(self.stage, self.state)
        (path.parent / "extra.swift").write_text("unexpected build input")
        with self.assertRaisesRegex(r.ReleaseError, "additional or missing"):
            r.verify_snapshot(self.stage, self.state)

    def test_packaging_is_bound_to_submitted_app_and_tested_extension(self):
        assets = self.stage / "assets"
        assets.mkdir()
        app_entry = "Tab Switcher Local/" + r.APP + "/Contents/MacOS/tab-switcher"
        ticket = "Tab Switcher Local/" + r.APP + "/Contents/CodeResources"
        upload = self.stage / "notary-upload.zip"
        def write_zip(path, files):
            with zipfile.ZipFile(path, "w") as archive:
                for name, content in files.items(): archive.writestr(name, content)
        write_zip(upload, {app_entry: b"signed original"})
        self.state["archive_sha256"] = r.sha256(upload)
        extension = self.stage / "tested-extension"
        extension.mkdir()
        (extension / "popup.js").write_text("tested javascript")
        self.state["extension_files"] = r.file_manifest(extension)
        app_zip = assets / r.asset_names(self.state)[0]
        ext_zip = assets / r.asset_names(self.state)[1]
        write_zip(app_zip, {app_entry: b"signed original", ticket: b"stapled ticket"})
        write_zip(ext_zip, {"extension-local/popup.js": b"tested javascript"})
        r.validate_payloads(self.stage, self.state)
        write_zip(ext_zip, {"extension-local/popup.js": b"later edit"})
        with self.assertRaisesRegex(r.ReleaseError, "extension payload"):
            r.validate_payloads(self.stage, self.state)
        write_zip(ext_zip, {"extension-local/popup.js": b"tested javascript"})
        write_zip(app_zip, {app_entry: b"different signed app", ticket: b"stapled ticket"})
        with self.assertRaisesRegex(r.ReleaseError, "app payload"):
            r.validate_payloads(self.stage, self.state)

    def test_accepted_log_must_bind_archive_and_submission(self):
        self.state["archive_sha256"] = "c" * 64
        log = dict(jobId="submission", status="Accepted", sha256="c" * 64)
        r.validate_accepted(log, self.state, "submission")
        for altered in [dict(log, sha256="d" * 64), dict(log, jobId="other"), dict(log, status="Invalid")]:
            with self.assertRaises(r.ReleaseError):
                r.validate_accepted(altered, self.state, "submission")
        (self.stage / "notary-upload.zip").write_bytes(b"changed")
        with patch.object(r, "run") as external:
            with self.assertRaises(r.ReleaseError):
                r.finish(self.stage, self.state, "submission", 1)  # Missing/changed upload cannot reach service.
            external.assert_not_called()

    def test_recovered_accepted_id_with_wrong_archive_never_staples(self):
        (self.stage / "notary-upload.zip").write_bytes(b"archive")
        self.state["archive_sha256"] = r.sha256(self.stage / "notary-upload.zip")
        self.state["phase"] = "submission-intent"
        log = dict(jobId="recovered", status="Accepted", sha256="0" * 64)
        with patch.object(r, "run", side_effect=[subprocess.CompletedProcess([], 0, b"{}", b""),
                                                subprocess.CompletedProcess([], 0, json.dumps(log).encode(), b"")]) as external:
            with self.assertRaisesRegex(r.ReleaseError, "match both"):
                r.finish(self.stage, self.state, "recovered", 1)
            self.assertEqual(external.call_count, 2)  # Wait/log only; no staple, packaging or submit.
        self.assertEqual(self.state["phase"], "submission-intent")

    def test_ambiguous_upload_has_durable_intent_and_never_resubmits(self):
        archive = self.stage / "notary-upload.zip"
        archive.write_bytes(b"archive")
        self.state["archive_sha256"] = r.sha256(archive)
        def ambiguous(*args, **kwargs):
            saved = json.loads((self.stage / "state.json").read_text())
            self.assertEqual(saved["phase"], "submission-intent")
            return subprocess.CompletedProcess(args, 1, b'{"id":"maybe"}', b"connection lost")
        with patch.object(r, "run", side_effect=ambiguous) as external:
            with self.assertRaisesRegex(r.ReleaseError, "ambiguous"):
                r.submit(self.stage, self.state)
            with self.assertRaisesRegex(r.ReleaseError, "intent already exists"):
                r.submit(self.stage, self.state)
            self.assertEqual(external.call_count, 1)
        self.assertEqual((self.stage / "submission-response.json").read_bytes(), b'{"id":"maybe"}')

    def test_tampered_assets_stop_publish_before_services(self):
        assets = self.stage / "assets"
        assets.mkdir()
        self.state["phase"] = "ready"
        self.state["assets"] = {}
        for name in r.asset_names(self.state):
            (assets / name).write_bytes(name.encode())
            self.state["assets"][name] = dict(sha256=r.sha256(assets / name), size=(assets / name).stat().st_size)
        r.validate_assets(self.stage, self.state)
        (assets / "INSTALL.md").write_text("tampered")
        with patch.object(r, "api") as service, patch.object(r, "run") as command:
            with self.assertRaisesRegex(r.ReleaseError, "Asset changed"):
                r.publish(self.stage, self.state)
            service.assert_not_called()
            command.assert_not_called()

    def test_mismatched_draft_source_tag_and_published_release(self):
        draft = dict(draft=True, tag_name=self.state["tag"], target_commitish=self.state["source_sha"], body="marker", prerelease=False)
        r.validate_draft(draft, self.state, "marker")
        for field, value in [("draft", False), ("target_commitish", "b" * 40), ("tag_name", "v3.7.5-mason.2"), ("body", "other")]:
            with self.assertRaises(r.ReleaseError):
                r.validate_draft(dict(draft, **{field: value}), self.state, "marker")

    def test_remote_source_and_tag_must_match(self):
        source = self.state["source_sha"]
        r.validate_remote_source(source, source, None)
        r.validate_remote_source(source, source, source)
        for remote_commit, tag in [("b" * 40, None), (source, "b" * 40)]:
            with self.assertRaises(r.ReleaseError):
                r.validate_remote_source(source, remote_commit, tag)

    def test_intel_and_rosetta_rejected(self):
        with patch.object(r.platform, "system", return_value="Darwin"), patch.object(r.platform, "machine", return_value="x86_64"):
            with self.assertRaises(r.ReleaseError):
                r.host_check()


if __name__ == "__main__":
    unittest.main()
