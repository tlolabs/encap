"""Stable tag policy does not depend on a Git signing key."""

import os
from pathlib import Path
import subprocess
import tempfile
import unittest


SCRIPT = Path(__file__).with_name('verify_release_tag.sh')


class ReleaseTagPolicy(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.git('init', '-q')
        self.git('config', 'user.name', 'Release test')
        self.git('config', 'user.email', 'release@example.invalid')
        self.git('config', 'commit.gpgsign', 'false')
        self.git('config', 'tag.gpgsign', 'false')
        (self.root / 'Cargo.toml').write_text('[workspace.package]\nversion = "2.0.5"\n')
        self.git('add', 'Cargo.toml')
        self.git('commit', '-qm', 'test release')

    def git(self, *args):
        return subprocess.check_output(['git', *args], cwd=self.root, text=True).strip()

    def verify(self, tag):
        return subprocess.run(['bash', str(SCRIPT)], cwd=self.root,
                              env={**os.environ, 'GITHUB_REF_NAME': tag},
                              text=True, capture_output=True)

    def test_unsigned_annotated_tag_is_accepted(self):
        self.git('tag', '-a', 'v2.0.5', '-m', 'release')
        self.assertEqual(self.verify('v2.0.5').returncode, 0)

    def test_lightweight_tag_is_rejected(self):
        self.git('tag', 'v2.0.5')
        self.assertIn('annotated tag', self.verify('v2.0.5').stderr)

    def test_tag_at_different_commit_is_rejected(self):
        self.git('tag', '-a', 'v2.0.5', '-m', 'release')
        (self.root / 'Cargo.toml').write_text('[workspace.package]\nversion = "2.0.5"\n# later\n')
        self.git('add', 'Cargo.toml')
        self.git('commit', '-qm', 'later')
        self.assertIn('does not name this checkout', self.verify('v2.0.5').stderr)


if __name__ == '__main__':
    unittest.main()
