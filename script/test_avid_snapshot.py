"""Authenticate the full vendored source tree, including unmanifested inputs."""
from contextlib import contextmanager
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class SnapshotTests(unittest.TestCase):
    @contextmanager
    def snapshot(self):
        with tempfile.TemporaryDirectory(prefix="encap-source-identity-") as directory:
            root = Path(directory)
            (root / "script").mkdir()
            shutil.copy2(ROOT / "script/verify_avid_snapshot.rb", root / "script/verify_avid_snapshot.rb")
            shutil.copytree(ROOT / "vendor", root / "vendor", ignore=shutil.ignore_patterns(".build", ".swiftpm", "__pycache__"))
            yield root, root / "vendor/avid-core-transcription"

    def verify(self, root):
        return subprocess.run(["ruby", str(root / "script/verify_avid_snapshot.rb")], capture_output=True, text=True)

    def test_unmanifested_swift_and_resources_cannot_enter_an_authenticated_build(self):
        with self.snapshot() as (root, source):
            self.assertEqual(self.verify(root).returncode, 0)
            for relative in ("apple/AVIDTranscription/Sources/AVIDTranscription/Injected.swift",
                             "apple/AVIDTranscription/Sources/AVIDTranscription/Resources/injected.json"):
                extra = source / relative
                extra.write_text("unmanifested source input")
                check = self.verify(root)
                self.assertNotEqual(check.returncode, 0)
                self.assertIn("Unexpected shared source file: " + relative, check.stderr)
                extra.unlink()

    def test_only_explicit_generated_roots_are_excluded(self):
        with self.snapshot() as (root, source):
            for relative in ("apple/AVIDTranscription/.build", "apple/AVIDTranscriptionEngines/.swiftpm", "script/__pycache__"):
                output = source / relative
                output.mkdir(parents=True)
                (output / "generated.swift").write_text("generated output")
            self.assertEqual(self.verify(root).returncode, 0)
            hidden_source = source / "apple/AVIDTranscription/Sources/AVIDTranscription/.build"
            hidden_source.mkdir()
            (hidden_source / "hidden.swift").write_text("not an approved generated root")
            self.assertNotEqual(self.verify(root).returncode, 0)

    def test_linked_extra_source_is_rejected_without_following_it(self):
        with self.snapshot() as (root, source):
            external = root / "unowned.swift"
            external.write_text("unowned source remains untouched")
            link = source / "apple/AVIDTranscription/Sources/AVIDTranscription/linked.swift"
            link.symlink_to(external)
            check = self.verify(root)
            self.assertNotEqual(check.returncode, 0)
            self.assertIn("Linked shared source/output path", check.stderr)
            self.assertEqual(external.read_text(), "unowned source remains untouched")


if __name__ == "__main__":
    unittest.main()
