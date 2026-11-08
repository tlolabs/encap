"""Keep CI tooling exceptions narrow without restoring application Python."""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class NativeSourcePolicyTests(unittest.TestCase):
    def test_weekly_tools_allowed_but_other_python_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "script").mkdir()
            for name in ("check_no_python.sh", "verify_avid_snapshot.rb"):
                shutil.copy2(ROOT / "script" / name, root / "script" / name)
            shutil.copytree(ROOT / "vendor", root / "vendor",
                            ignore=shutil.ignore_patterns("__pycache__"))
            tools = root / ".github/scripts"
            tools.mkdir(parents=True)
            for name in ("weekly_release_smoke.py", "test_weekly_release_smoke.py"):
                (tools / name).write_text("# CI tooling fixture\n")
            cache = tools / "__pycache__"
            cache.mkdir()
            (cache / "weekly_release_smoke.pyc").write_bytes(b"cache")
            subprocess.run(["git", "init", "-q", str(root)], check=True)
            subprocess.run(["git", "-C", str(root), "add", ".github/scripts/weekly_release_smoke.py",
                            ".github/scripts/test_weekly_release_smoke.py"], check=True)

            def check():
                return subprocess.run(["bash", "script/check_no_python.sh"], cwd=root,
                                      capture_output=True, text=True)

            self.assertEqual(check().returncode, 0)
            unexpected = tools / "application.py"
            unexpected.write_text("print('unexpected application')\n")
            self.assertNotEqual(check().returncode, 0)
            subprocess.run(["git", "-C", str(root), "add", str(unexpected)], check=True)
            unexpected.unlink()
            # Even a missing tracked source must remain visible to the index scan.
            self.assertNotEqual(check().returncode, 0)


if __name__ == "__main__":
    unittest.main()
