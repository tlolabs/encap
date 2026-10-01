#!/usr/bin/env python3
"""Core owns the exact matched runtime; host acquisition is pinned and shared."""
import hashlib,json,subprocess,tomllib,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
class OwnershipTests(unittest.TestCase):
    def test_core_pin_and_shared_acquirer(self):
        pin=json.loads((ROOT/'runtime/core-runtime.json').read_text())
        dependency=tomllib.loads((ROOT/'Cargo.toml').read_text())['workspace']['dependencies']['avid-core']
        self.assertEqual(dependency['rev'],pin['build_revision'])
        self.assertEqual(set(pin['targets']),{'macos-arm64','macos-x86_64','windows-arm64','windows-x86_64','linux-arm64','linux-x86_64'})
        verifier=json.loads((ROOT/'runtime/core-acquirer.json').read_text())
        self.assertEqual(hashlib.sha256((ROOT/'script/core_runtime.py').read_bytes()).hexdigest(),verifier['sha256'])
        self.assertEqual(verifier['owner'],'tlolabs/avid-core')
        metadata=json.loads(subprocess.check_output(['cargo','metadata','--locked','--format-version','1'],cwd=ROOT))
        core,=[p for p in metadata['packages'] if p['name']=='avid-core']
        self.assertEqual(core['version'],dependency['version'][1:])
        self.assertEqual(core['source'],f"git+{dependency['git']}?rev={dependency['rev']}#{dependency['rev']}")
    def test_no_independent_ffmpeg_builder_or_fallback(self):
        self.assertFalse((ROOT/'script/ffmpeg_build.py').exists())
        self.assertFalse((ROOT/'runtime/ffmpeg/dependency.json').exists())
        adapter=(ROOT/'script/ffmpeg_runtime.py').read_text()
        self.assertIn('from core_runtime import candidate, release',adapter)
        self.assertNotIn("gh', 'run', 'download'",adapter)
        self.assertIn('qualification_only',adapter)
        discovery=(ROOT/'crates/encap-ffmpeg/src/runtime.rs').read_text()
        self.assertNotIn('MediaTools::discover',discovery)
        self.assertIn('FFMPEG_RUNTIME_SPECIFICATION',discovery)
if __name__=='__main__':unittest.main()
