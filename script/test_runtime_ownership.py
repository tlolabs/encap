#!/usr/bin/env python3
"""Check independently immutable Core library and authenticated runtime pins."""
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import tomllib
import unittest
from unittest.mock import patch

import ffmpeg_runtime as app_runtime

ROOT = Path(__file__).resolve().parents[1]


class OwnershipTests(unittest.TestCase):
    def test_core_library_and_runtime_pins(self):
        artifacts = json.loads((ROOT / 'runtime/core-runtime.json').read_text())
        pin = tomllib.loads((ROOT / 'Cargo.toml').read_text())['workspace']['dependencies']['avid-core']
        self.assertEqual(pin['git'], 'https://github.com/tlolabs/avid-core.git')
        self.assertRegex(pin['rev'], r'^[0-9a-f]{40}$')
        self.assertRegex(pin['version'], r'^=\d+\.\d+\.\d+$')
        self.assertNotIn('path', pin)
        # A library release can consume the already qualified runtime. Moving
        # this source pin must not silently select a different media artifact.
        self.assertEqual(artifacts['revision'], artifacts['build_revision'])
        self.assertRegex(artifacts['build_revision'], r'^[0-9a-f]{40}$')
        self.assertEqual(artifacts['acquisition'], 'release')
        self.assertFalse(artifacts['qualification_only'])
        self.assertRegex(artifacts['release_tag'], r'^ffmpeg-\d+\.\d+\.\d+-r\d+\.\d+$')
        self.assertRegex(artifacts['release_revision'], r'^[0-9a-f]{40}$')
        self.assertRegex(artifacts['manifest_sha256'], r'^[0-9a-f]{64}$')
        self.assertEqual(set(artifacts['targets']), {
            'macos-arm64', 'macos-x86_64', 'windows-arm64',
            'windows-x86_64', 'linux-arm64', 'linux-x86_64',
        })
        verifier = json.loads((ROOT / 'runtime/core-acquirer.json').read_text())
        self.assertEqual(verifier['owner'], 'tlolabs/avid-core')
        self.assertEqual(hashlib.sha256((ROOT / 'script/core_runtime.py').read_bytes()).hexdigest(),
                         verifier['sha256'])
        for record in artifacts['targets'].values():
            for key in ['sha256', 'checksums_sha256', 'source_sha256']:
                self.assertRegex(record[key], r'^[0-9a-f]{64}$')
        metadata = json.loads(subprocess.check_output(['cargo', 'metadata', '--locked', '--format-version', '1'], cwd=ROOT))
        core, = [p for p in metadata['packages'] if p['name'] == 'avid-core']
        self.assertEqual(core['version'], pin['version'][1:])
        self.assertEqual(core['source'], f"git+{pin['git']}?rev={pin['rev']}#{pin['rev']}")

    def test_packaging_library_identity_is_independent_of_runtime_build(self):
        expected = app_runtime.core_identity()
        with patch.object(app_runtime, 'PIN', {'revision': '0' * 40}):
            self.assertEqual(app_runtime.core_identity(), expected)

    def test_packaging_rejects_library_lock_mismatches(self):
        revision = '1' * 40
        source = f'git+https://github.com/tlolabs/avid-core.git?rev={revision}#{revision}'
        manifest = ('[workspace.dependencies]\n'
                    f'avid-core = {{ git = "https://github.com/tlolabs/avid-core.git", '
                    f'rev = "{revision}", version = "=0.3.1" }}\n')
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'Cargo.toml').write_text(manifest)
            for version, locked_source in [('0.3.0', source), ('0.3.1', source.replace(revision, '2' * 40))]:
                (root / 'Cargo.lock').write_text(
                    f'[[package]]\nname = "avid-core"\nversion = "{version}"\nsource = "{locked_source}"\n')
                with self.subTest(version=version, source=locked_source), patch.object(app_runtime, 'ROOT', root):
                    with self.assertRaisesRegex(ValueError, 'immutable library pin'):
                        app_runtime.core_identity()

    def test_no_application_source_builder(self):
        self.assertFalse((ROOT / 'script/ffmpeg_build.py').exists())
        self.assertFalse((ROOT / 'runtime/ffmpeg/dependency.json').exists())
        self.assertFalse((ROOT / '.github/actions/source-ffmpeg').exists())
        discovery = (ROOT / 'crates/encap-ffmpeg/src/runtime.rs').read_text()
        self.assertNotIn('MediaTools::discover', discovery)
        self.assertIn('avid_core::FFMPEG_RUNTIME_SPECIFICATION', discovery)


if __name__ == '__main__':
    unittest.main()
