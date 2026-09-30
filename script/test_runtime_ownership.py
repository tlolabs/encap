#!/usr/bin/env python3
"""Check that application dependencies and runtime artifacts share an immutable Core pin."""
import json
from pathlib import Path
import subprocess
import tomllib
import unittest

ROOT = Path(__file__).resolve().parents[1]


class OwnershipTests(unittest.TestCase):
    def test_core_pins(self):
        artifacts = json.loads((ROOT / 'runtime/core-runtime.json').read_text())
        pin = tomllib.loads((ROOT / 'Cargo.toml').read_text())['workspace']['dependencies']['avid-core']
        self.assertEqual(pin['rev'], artifacts['revision'])
        self.assertEqual(len(artifacts['targets']), 6)
        for record in artifacts['targets'].values():
            for key in ['sha256', 'checksums_sha256', 'source_sha256']:
                self.assertRegex(record[key], r'^[0-9a-f]{64}$')
        metadata = json.loads(subprocess.check_output(['cargo', 'metadata', '--locked', '--format-version', '1'], cwd=ROOT))
        core, = [p for p in metadata['packages'] if p['name'] == 'avid-core']
        self.assertEqual(core['version'], pin['version'][1:])
        self.assertEqual(core['source'], f"git+{pin['git']}?rev={pin['rev']}#{pin['rev']}")

    def test_no_application_source_builder(self):
        self.assertFalse((ROOT / 'script/ffmpeg_build.py').exists())
        self.assertFalse((ROOT / 'runtime/ffmpeg/dependency.json').exists())
        self.assertFalse((ROOT / '.github/actions/source-ffmpeg').exists())
        discovery = (ROOT / 'crates/encap-ffmpeg/src/runtime.rs').read_text()
        self.assertNotIn('MediaTools::discover', discovery)
        self.assertIn('avid_core::FFMPEG_RUNTIME_SPECIFICATION', discovery)


if __name__ == '__main__':
    unittest.main()
