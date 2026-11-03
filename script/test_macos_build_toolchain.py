"""Check build entrypoint discovery without compiling or packaging an app."""

import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


class MacBuildToolchainTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        script = self.root / "script"
        script.mkdir()
        shutil.copyfile(Path(__file__).with_name("build_and_run.sh"), script / "build_and_run.sh")
        policy = script / "check_no_python.sh"
        policy.write_text("#!/bin/bash\nexit 0\n")
        policy.chmod(0o755)
        self.bin = self.root / "bin"
        self.bin.mkdir()
        for name in ("cargo", "custom-cargo"):
            binary = self.bin / name
            binary.write_text("#!/bin/bash\nexit 0\n")
            binary.chmod(0o755)
        self.env = os.environ.copy()
        self.env.pop("CARGO", None)
        self.env["PATH"] = f"{self.bin}:/usr/bin:/bin"
        self.env["ENCAP_BUILD_ARCH"] = "arm64"

    def run_entrypoint(self, cargo=None):
        if cargo is not None:
            self.env["CARGO"] = cargo
        return subprocess.run(
            ["/bin/bash", str(self.root / "script/build_and_run.sh"), "--package"],
            cwd=self.root,
            env=self.env,
            text=True,
            capture_output=True,
            check=False,
        )

    def assert_toolchain_found(self, result):
        # The isolated fixture intentionally stops at the next prerequisite.
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Missing update public key:", result.stderr)
        self.assertNotIn("Missing Rust toolchain:", result.stderr)

    def test_default_cargo_uses_path(self):
        self.assert_toolchain_found(self.run_entrypoint())

    def test_command_override_uses_path(self):
        self.assert_toolchain_found(self.run_entrypoint("custom-cargo"))

    def test_absolute_override_with_spaces(self):
        binary = self.bin / "custom cargo"
        shutil.copyfile(self.bin / "cargo", binary)
        binary.chmod(0o755)
        self.assert_toolchain_found(self.run_entrypoint(str(binary)))

    def test_missing_explicit_override_does_not_fall_back(self):
        result = self.run_entrypoint(str(self.bin / "missing-cargo"))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Missing Rust toolchain:", result.stderr)
        self.assertNotIn("Missing update public key:", result.stderr)


if __name__ == "__main__":
    unittest.main()
