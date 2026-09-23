#!/usr/bin/env python3
"""Small regression tests for source trust boundaries and cache invalidation."""
import io
import hashlib
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest.mock import patch
import ffmpeg_build as recipe


class SourceTests(unittest.TestCase):
    def test_corrupt_cached_source_is_rejected_without_network(self):
        with tempfile.TemporaryDirectory() as directory:
            archive = Path(directory) / 'source.tar.xz'
            archive.write_bytes(b'corrupt')
            with patch('urllib.request.urlopen') as network:
                with self.assertRaisesRegex(ValueError, 'checksum mismatch'):
                    recipe.fetch('https://ffmpeg.org/releases/source.tar.xz', archive, '0' * 64)
                network.assert_not_called()

    def test_fresh_download_retries_without_relaxing_checksum(self):
        with tempfile.TemporaryDirectory() as directory:
            archive = Path(directory) / 'source.tar.xz'
            expected = hashlib.sha256(b'expected').hexdigest()
            with patch('urllib.request.urlopen', side_effect=[io.BytesIO(b'corrupt'), io.BytesIO(b'expected')]) as network, patch.object(recipe.time, 'sleep'):
                recipe.fetch('https://ffmpeg.org/releases/source.tar.xz', archive, expected)
                self.assertEqual(network.call_count, 2)
                self.assertEqual(archive.read_bytes(), b'expected')

    def test_runner_architecture_survives_msys_environment_rewriting(self):
        with patch.object(recipe.platform, 'system', return_value='MSYS_NT-10.0'), patch.object(recipe.platform, 'machine', return_value='x86_64'), patch.dict(recipe.os.environ, {'RUNNER_OS': 'Windows', 'RUNNER_ARCH': 'ARM64', 'PROCESSOR_ARCHITECTURE': 'AMD64', 'PROCESSOR_ARCHITEW6432': ''}):
            self.assertEqual(recipe.native_target(), 'windows-arm64')

    def test_archive_traversal_and_links_are_rejected(self):
        for name, kind in [('../escape', tarfile.REGTYPE), ('/absolute', tarfile.REGTYPE), ('root/link', tarfile.SYMTYPE)]:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                archive = root / 'source.tar'
                with tarfile.open(archive, 'w') as tar:
                    entry = tarfile.TarInfo(name)
                    entry.type = kind
                    tar.addfile(entry, io.BytesIO(b''))
                with self.assertRaisesRegex(ValueError, 'Unsafe source'):
                    recipe.extract(archive, root / 'unpacked')

    def test_cache_changes_with_recipe_target_and_compiler(self):
        with patch.object(recipe, 'recipe_digest', return_value='recipe-a'), patch.object(recipe, 'toolchain', return_value={'cc': 'compiler-a'}):
            original = recipe.fingerprint('linux-arm64')[0]
            self.assertNotEqual(original, recipe.fingerprint('linux-x86_64')[0])
            with patch.object(recipe, 'recipe_digest', return_value='recipe-b'):
                self.assertNotEqual(original, recipe.fingerprint('linux-arm64')[0])
            with patch.object(recipe, 'toolchain', return_value={'cc': 'compiler-b'}):
                self.assertNotEqual(original, recipe.fingerprint('linux-arm64')[0])

    def test_windows_arm_host_with_emulated_msys_python(self):
        with patch.object(recipe.platform, 'system', return_value='MSYS_NT-10.0'), patch.object(recipe.platform, 'machine', return_value='x86_64'), patch.dict(recipe.os.environ, {'PROCESSOR_ARCHITECTURE': 'AMD64', 'PROCESSOR_ARCHITEW6432': 'ARM64'}):
            self.assertEqual(recipe.native_target(), 'windows-arm64')

    def test_gcc_runtime_notices_support_both_msys_package_layouts(self):
        for name in ['libgcc', 'gcc-libs']:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                (root / 'crt').mkdir()
                (root / name).mkdir()
                for file in ['COPYING3', 'COPYING.RUNTIME']:
                    (root / name / file).write_text('required upstream notice')
                self.assertIn(root / name, recipe.windows_license_dirs(root, 'gcc'))
                (root / name / 'COPYING.RUNTIME').unlink()
                with self.assertRaisesRegex(ValueError, 'Missing GCC runtime license'):
                    recipe.windows_license_dirs(root, 'gcc')

    def test_target_aliases_and_unknown_architectures(self):
        self.assertEqual(recipe.target_id('windows-x64'), 'windows-x86_64')
        self.assertEqual(recipe.target_id('linux-aarch64-appimage'), 'linux-arm64')
        with self.assertRaises(ValueError):
            recipe.target_id('linux-riscv64')


if __name__ == '__main__':
    unittest.main()
