#!/usr/bin/env python3
"""Guard EnCAP-owned official sources, immutable pins and package-only discovery."""
import json
from pathlib import Path
import re
import unittest
import subprocess
import tomllib

ROOT = Path(__file__).resolve().parents[1]


class OwnershipTests(unittest.TestCase):
    def test_source_and_core_pins(self):
        spec = json.loads((ROOT / 'runtime/ffmpeg/dependency.json').read_text())
        self.assertRegex(spec['source']['version'], r'^\d+\.\d+(\.\d+)?$')
        self.assertEqual(spec['source']['url'], 'https://ffmpeg.org/releases/ffmpeg-' + spec['source']['version'] + '.tar.xz')
        for record in [spec['source'], *spec['external_libraries'].values()]:
            self.assertRegex(record['sha256'], r'^[0-9a-f]{64}$')
        pin = tomllib.loads((ROOT / 'Cargo.toml').read_text())['workspace']['dependencies']['avid-core']
        self.assertEqual(pin['version'], '=0.3.0')
        self.assertEqual(pin['rev'], '3fb68807bc7c350359e1634b32af477ea3042c16')
        metadata = json.loads(subprocess.check_output(['cargo', 'metadata', '--locked', '--format-version', '1'], cwd=ROOT))
        core, = [p for p in metadata['packages'] if p['name'] == 'avid-core']
        self.assertEqual(core['version'], pin['version'][1:])
        self.assertEqual(core['source'], f"git+{pin['git']}?rev={pin['rev']}#{pin['rev']}")
        self.assertEqual(len(spec['targets']), 6)

    def test_production_ownership(self):
        for name in ['prepare_ffmpeg.sh']:
            text = (ROOT / 'script' / name).read_text()
            self.assertIn('ffmpeg_runtime.py', text)
            self.assertIn('provision', text)
            self.assertNotIn('--candidate', text)
        for directory in ['script', '.github', 'crates', 'macos', 'linux', 'windows']:
            for path in (ROOT / directory).rglob('*'):
                if not path.is_file() or path.suffix not in {'.py', '.sh', '.ps1', '.rs', '.yml', '.toml'} or path == Path(__file__):
                    continue
                if any(part in {'target', '.build', 'bin', 'obj'} for part in path.parts):
                    continue
                text = path.read_text()
                self.assertNotRegex(text, r'BtbN|martin-riedl|evermeet|johnvansickle|ffbinaries|scripts/ffmpeg/acquire|from_managed_layout|acquire_core_runtime|package_core_candidate|core_runtime.py', str(path))
        discovery = (ROOT / 'crates/encap-ffmpeg/src/runtime.rs').read_text()
        self.assertIn('MediaTools::from_paths(', discovery)
        self.assertNotIn('MediaTools::discover', discovery)
        self.assertIn('DEPENDENCY.as_bytes()', discovery)


if __name__ == '__main__':
    unittest.main()
