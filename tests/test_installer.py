from pathlib import Path
import plistlib
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import install_macos_app as installer


class InstallerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="go-claude-installer-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.destination = self.root / "Applications"
        self.destination.mkdir()
        self.target = self.destination / installer.APP.name
        self.candidate = self.root / "build" / installer.APP.name

    def make_app(self, path, marker, bundle=installer.BUNDLE_ID):
        (path / "Contents").mkdir(parents=True)
        (path / "Contents/Info.plist").write_bytes(plistlib.dumps({"CFBundleIdentifier": bundle}))
        (path / "marker.txt").write_text(marker)

    def test_unrelated_app_is_preserved(self):
        self.make_app(self.target, "keep unrelated app", bundle="different.application")
        with patch.object(installer, "build") as build:
            with self.assertRaises(SystemExit):
                installer.install(self.destination, replace=True)
        build.assert_not_called()
        self.assertEqual((self.target / "marker.txt").read_text(), "keep unrelated app")

    def test_running_app_is_not_replaced(self):
        self.make_app(self.target, "keep active app")
        executable = str(self.target / "Contents/MacOS/ClaudeHandoff")
        with patch.object(installer.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, executable + "\n", "")), \
             patch.object(installer, "build") as build:
            with self.assertRaisesRegex(SystemExit, "退出"):
                installer.install(self.destination, replace=True)
        build.assert_not_called()
        self.assertEqual((self.target / "marker.txt").read_text(), "keep active app")

    def test_failed_installed_signature_restores_previous_app(self):
        self.make_app(self.target, "previous working app")
        self.make_app(self.candidate, "new candidate")
        failure = subprocess.CalledProcessError(1, ["codesign", "--verify"])
        with patch.object(installer.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, "", "")), \
             patch.object(installer, "build", return_value=self.candidate), \
             patch.object(installer, "run", side_effect=[None, failure]):
            with self.assertRaises(subprocess.CalledProcessError):
                installer.install(self.destination, replace=True)
        self.assertEqual((self.target / "marker.txt").read_text(), "previous working app")
        self.assertEqual((self.candidate / "marker.txt").read_text(), "new candidate")


if __name__ == "__main__":
    unittest.main(verbosity=2)
