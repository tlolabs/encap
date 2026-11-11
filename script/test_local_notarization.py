"""Local notarization policy regression checks; never invokes signing or Apple."""
import hashlib
import json
import os
from pathlib import Path
import plistlib
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[1]
SIGN_VARIABLE='ENCAP_SIGN_IDENTITY'
NOTARY_VARIABLE='ENCAP_NOTARY_PROFILE'
FINAL_SIGN_VARIABLE='ENCAP_SIGN_IDENTITY'
FINAL_NOTARY_VARIABLE='ENCAP_NOTARY_PROFILE'
APP_VARIABLE='ENCAP_APP_BUNDLE'
BUILD_SCRIPT='build_and_run.sh'
BUILD_ARGS=('--package',)
DEVELOPMENT_OPTION='--package-development'



class NotarizationDefaults(unittest.TestCase):
    def run_without_credentials(self, script, args=(), extra=None):
        env = {k: v for k, v in os.environ.items()
               if k not in ('APPLE_SIGN_IDENTITY', 'APPLE_NOTARY_PROFILE',
                            'ATIV_SIGN_IDENTITY', 'ATIV_NOTARY_PROFILE', 'ATIV_APP_BUNDLE',
                            'ENCAP_SIGN_IDENTITY', 'ENCAP_NOTARY_PROFILE')}
        env.update(extra or {})
        result = subprocess.run(['bash', str(ROOT / 'script' / script), *args],
                                env=env, capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        return result.stderr

    def test_default_distribution_requires_signing_before_build(self):
        self.assertIn(SIGN_VARIABLE, self.run_without_credentials(BUILD_SCRIPT, BUILD_ARGS))

    def test_default_distribution_requires_notary_before_build(self):
        self.assertIn(NOTARY_VARIABLE, self.run_without_credentials(
            BUILD_SCRIPT, BUILD_ARGS, {SIGN_VARIABLE: 'Developer ID Application: Test'}))

    def test_final_signer_requires_notary_before_reading_bundle(self):
        self.assertIn(FINAL_NOTARY_VARIABLE, self.run_without_credentials(
            'sign_macos_release.sh', extra={FINAL_SIGN_VARIABLE: 'Developer ID Application: Test',
                                            APP_VARIABLE: '/not/a/real/app'}))

    def test_invalid_profile_fails_before_build_or_bundle_mutation(self):
        with tempfile.TemporaryDirectory() as directory:
            stub = Path(directory)
            security = stub / 'security'
            security.write_text("#!/bin/sh\nprintf '%s\\n' 'Developer ID Application: Test'\n")
            security.chmod(0o755)
            xcrun = stub / 'xcrun'
            xcrun.write_text('#!/bin/sh\nprintf "%s\\n" "$*" > "$NOTARY_TEST_LOG"\nexit 67\n')
            xcrun.chmod(0o755)
            log = stub / 'calls'
            for script, args, credentials in [
                (BUILD_SCRIPT, BUILD_ARGS, {SIGN_VARIABLE: 'Developer ID Application: Test',
                                           NOTARY_VARIABLE: 'missing-test-profile'}),
                ('sign_macos_release.sh', (), {FINAL_SIGN_VARIABLE: 'Developer ID Application: Test',
                                              FINAL_NOTARY_VARIABLE: 'missing-test-profile',
                                              APP_VARIABLE: '/not/a/real/app'})]:
                env = dict(os.environ, PATH=f'{stub}:{os.environ["PATH"]}',
                           NOTARY_TEST_LOG=str(log), **credentials)
                result = subprocess.run(['bash', str(ROOT / 'script' / script), *args],
                                        env=env, capture_output=True, text=True)
                self.assertEqual(result.returncode, 67, result.stderr)
                self.assertEqual(log.read_text().strip(),
                                 'notarytool history --keychain-profile missing-test-profile --output-format json')

    def test_final_archive_is_validated_after_extraction(self):
        text = (ROOT / 'script/sign_macos_release.sh').read_text()
        self.assertIn("report.get('status') != 'Accepted'", text)
        self.assertIn('ditto -x -k "$ZIP" "$VERIFY"', text)
        self.assertIn('xcrun stapler validate "$VERIFY/', text)
        self.assertIn('spctl --assess --type execute --verbose=2 "$VERIFY/', text)
        self.assertNotIn('Signed only:', text)

    def test_transcription_qualification_runs_after_nested_signing_before_app_signing(self):
        text = (ROOT / 'script/sign_macos_release.sh').read_text()
        finish = text.index('python3 "$ROOT/script/ffmpeg_runtime.py" finish ')
        qualify = text.index('python3 "$ROOT/script/qualify_transcription.py" --engine ')
        enclosing_signature = text.index('sign "$APP"')
        self.assertLess(text.index('sign "$FRAMEWORK"'), finish)
        self.assertLess(finish, qualify)
        self.assertLess(qualify, enclosing_signature)

    @unittest.skipUnless(Path('/usr/libexec/PlistBuddy').is_file(), 'native macOS plist reader required')
    def test_signed_archive_qualification_covers_final_nested_payload(self):
        # Exercise the real qualification hash inventory with an explicitly
        # unavailable fixture engine. All signing/notary/network tools are mocks.
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            script = root / 'script'
            script.mkdir()
            for name in ('sign_macos_release.sh', 'qualify_transcription.py'):
                shutil.copy2(ROOT / 'script' / name, script / name)
            (script / 'ffmpeg_runtime.py').write_text(
                'import sys\nfrom pathlib import Path\n'
                'if sys.argv[1] == "finish":\n'
                '    Path(sys.argv[sys.argv.index("--metadata") + 1], "signed-payload.json").write_text("finished")\n')
            app = root / 'dist/EnCap.app'
            binaries = app / 'Contents/MacOS'
            resources = app / 'Contents/Resources'
            binaries.mkdir(parents=True)
            (resources / 'FFmpeg').mkdir(parents=True)
            bundle = resources / 'AVIDTranscription.bundle'
            bundle.mkdir()
            (bundle / 'models.json').write_text('{}')
            (resources / 'FFmpeg/build.json').write_text('{"target":"macos-arm64"}')
            (app / 'Contents/Info.plist').write_bytes(plistlib.dumps({'CFBundleShortVersionString': '0.0.1'}))
            for name in ('EnCap', 'avid-transcriber', 'ffmpeg', 'ffprobe'):
                (binaries / name).write_text('#!/bin/sh\nexit 0\n')
                (binaries / name).chmod(0o755)
            engine = binaries / 'encap-engine'
            engine.write_text('#!/bin/sh\ncase "$1" in\n'
                              'transcription-status) printf \'%s\\n\' \'{"available":false,"reason":"fixture unsupported platform"}\';;\n'
                              'validate-tools) printf \'%s\\n\' \'{}\';;\n*) exit 9;;\nesac\n')
            engine.chmod(0o755)
            qualification = resources / 'transcription-qualification.json'
            qualification.write_text('{"status":"stale-before-signing","runtime_files":{}}')
            framework = app / 'Contents/Frameworks/Sparkle.framework/Versions/B'
            for relative in ('XPCServices/Installer.xpc', 'XPCServices/Downloader.xpc', 'Updater.app'):
                (framework / relative).mkdir(parents=True)
            (framework / 'Autoupdate').write_text('updater')
            stub = root / 'tools'
            stub.mkdir()
            command = '#!' + sys.executable + '\n' + '''import hashlib, json, os, sys, zipfile
from pathlib import Path
name = Path(sys.argv[0]).name
args = sys.argv[1:]
if name == 'lipo': print('arm64')
elif name == 'security': print('Developer ID Application: Test')
elif name == 'file': print('Mach-O 64-bit executable arm64')
elif name == 'xcrun':
    if args[:2] == ['notarytool', 'submit']: print('{"status":"Accepted","id":"mock-submission"}')
    elif args[:2] == ['notarytool', 'history']: print('{}')
elif name == 'codesign':
    path = Path(args[-1])
    if '--verify' not in args:
        if path == Path(os.environ['ENCAP_APP_BUNDLE']):
            contents = path / 'Contents'
            report = json.loads((contents / 'Resources/transcription-qualification.json').read_text())
            assert report['status'] == 'unavailable'
            assert report['engine_sha256'] == hashlib.sha256((contents / 'MacOS/encap-engine').read_bytes()).hexdigest()
            assert report['runtime_files']['Resources/AVIDTranscription.bundle/_CodeSignature/CodeResources']
            for relative, expected in report['runtime_files'].items():
                assert hashlib.sha256((contents / relative).read_bytes()).hexdigest() == expected
            assert (contents / 'Resources/FFmpeg/signed-payload.json').read_text() == 'finished'
        if path.is_file():
            with path.open('a') as output: output.write('\\n# mocked nested signature\\n')
        else:
            signature = path / '_CodeSignature/CodeResources'
            signature.parent.mkdir(parents=True, exist_ok=True)
            signature.write_text('mocked nested signature')
elif name == 'ditto':
    source, destination = map(Path, args[-2:])
    if '-c' in args:
        with zipfile.ZipFile(destination, 'w') as archive:
            for item in source.rglob('*'):
                if item.is_file(): archive.write(item, str(Path(source.name) / item.relative_to(source)))
    else:
        with zipfile.ZipFile(source) as archive: archive.extractall(destination)
elif name != 'spctl': raise SystemExit('unexpected tool ' + name)
'''
            for name in ('lipo', 'security', 'file', 'xcrun', 'codesign', 'ditto', 'spctl'):
                path = stub / name
                path.write_text(command)
                path.chmod(0o755)
            env = dict(os.environ, PATH=f'{stub}:{os.environ["PATH"]}',
                       ENCAP_SIGN_IDENTITY='Developer ID Application: Test',
                       ENCAP_NOTARY_PROFILE='mock-profile', ENCAP_APP_BUNDLE=str(app))
            result = subprocess.run(['bash', str(script / 'sign_macos_release.sh')],
                                    env=env, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            archive = root / 'dist/EnCap-0.0.1-macos-arm64-signed.zip'
            with zipfile.ZipFile(archive) as package:
                prefix = 'EnCap.app/Contents/'
                report = json.loads(package.read(prefix + 'Resources/transcription-qualification.json'))
                self.assertEqual(report['status'], 'unavailable')
                self.assertEqual(report['engine_sha256'], hashlib.sha256(package.read(prefix + 'MacOS/encap-engine')).hexdigest())
                self.assertIn('Resources/AVIDTranscription.bundle/_CodeSignature/CodeResources', report['runtime_files'])
                for relative, expected in report['runtime_files'].items():
                    self.assertEqual(hashlib.sha256(package.read(prefix + relative)).hexdigest(), expected, relative)

    def test_explicit_development_archive_is_labeled(self):
        text = (ROOT / 'script' / BUILD_SCRIPT).read_text()
        self.assertIn(DEVELOPMENT_OPTION, text)
        self.assertIn('development-unnotarized', text)


if __name__ == '__main__':
    unittest.main()
