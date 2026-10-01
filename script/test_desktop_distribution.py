"""Regression checks for internal reference / production distribution isolation."""
import json
import plistlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile
import update_config

ROOT = Path(__file__).resolve().parents[1]

class DesktopDistributionTests(unittest.TestCase):
    def test_reference_target_cannot_get_production_identity(self):
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaisesRegex(ValueError, 'Unknown target'):
                update_config.configure(Path(folder), 'osx-arm64-reference')
            self.assertFalse((Path(folder) / 'update-config.json').exists())

    def test_reference_bundle_cannot_be_relabelled_by_production_configurator(self):
        with tempfile.TemporaryDirectory() as folder:
            contents = Path(folder) / 'Reference.app/Contents'
            resources = contents / 'Resources'
            resources.mkdir(parents=True)
            original = plistlib.dumps({'CFBundleIdentifier': 'com.tlolabs.encap.avalonia-reference',
                                      'EnCapDistribution': 'internal-reference'})
            (contents / 'Info.plist').write_bytes(original)
            with self.assertRaisesRegex(ValueError, 'native production'):
                update_config.configure(resources, 'macos-arm64')
            self.assertEqual((contents / 'Info.plist').read_bytes(), original)
            self.assertFalse((resources / 'update-config.json').exists())

    def test_production_bundle_keeps_native_identity(self):
        with tempfile.TemporaryDirectory() as folder:
            contents = Path(folder) / 'EnCap.app/Contents'
            resources = contents / 'Resources'
            resources.mkdir(parents=True)
            (contents / 'Info.plist').write_bytes(plistlib.dumps({'CFBundleIdentifier': 'com.tlolabs.encap'}))
            with patch.dict('os.environ', {'ENCAP_UPDATE_PUBLIC_KEY': '', 'ENCAP_RELEASE': '0'}):
                update_config.configure(resources, 'macos-arm64')
            self.assertEqual(json.loads((resources / 'update-config.json').read_text())['target'], 'macos-arm64')

    def test_built_reference_archive_has_no_production_updater(self):
        archives = list((ROOT / 'dist/internal').glob('*-INTERNAL-Avalonia-Reference-osx-arm64.zip'))
        if not archives:
            self.skipTest('Reference archive is only built on Apple Silicon')
        for path in archives:
            with zipfile.ZipFile(path) as archive:
                names = archive.namelist()
                info_name = next(n for n in names if n.endswith('.app/Contents/Info.plist'))
                info = plistlib.loads(archive.read(info_name))
                self.assertEqual(info['CFBundleIdentifier'], 'com.tlolabs.encap.avalonia-reference')
                self.assertEqual(info['EnCapDistribution'], 'internal-reference')
                self.assertFalse(any(k.startswith('SU') for k in info))
                self.assertTrue(any(n.endswith('/EnCap.dll') for n in names))
                for forbidden in ('update-config.json', 'encap-update', 'encap-portable-update', 'Sparkle.framework'):
                    self.assertFalse(any(forbidden in n for n in names), forbidden)

if __name__ == '__main__':
    unittest.main()
