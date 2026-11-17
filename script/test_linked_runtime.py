import copy
import hashlib
import io
import json
from pathlib import Path
import tempfile
import tarfile
import types
import unittest
from unittest.mock import patch

import linked_runtime as linked


class LinkedRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.source = self.root / 'source'
        self.prefix = self.root / 'prefix'
        self.spec = {
            'ffmpeg': {'version': '9.0.1', 'revision': 'immutable-ffmpeg', 'sha256': ''},
            'targets': [{'id': 'macos-arm64', 'rust_target': 'aarch64-apple-darwin',
                         'platform': 'macos', 'arch': 'arm64', 'minimum': '13.0'}],
            'profiles': {'gpl-software': {'platforms': ['macos'], 'dependencies': ['zlib'], 'encoders': ['libx264']}},
            'libraries': ['avformat', 'avcodec', 'avfilter', 'avutil', 'swscale', 'swresample'],
            'dependencies': {'zlib': {'sha256': ''}}, 'encoders': ['aac'],
        }
        self.metadata = {'schema': 1, 'kind': 'avid-linked-ffmpeg', 'target': 'aarch64-apple-darwin',
                         'target_id': 'macos-arm64', 'platform': 'macos', 'arch': 'arm64',
                         'minimum': '13.0', 'profile': 'gpl-software', 'linkage': 'static',
                         'source_revision': 'immutable-ffmpeg', 'ffmpeg_version': '9.0.1',
                         'source_provenance': {'status': 'verified', 'archive_sha256': ''},
                         'libraries': {}, 'sources': {}, 'components': {'encoder': ['aac', 'libx264'], 'protocol': ['file']},
                         'spec_sha256': 'earlier-spec'}
        for name in self.spec['libraries']:
            path = self.prefix / 'lib' / ('lib' + name + '.a')
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(('test library ' + name).encode())
            self.metadata['libraries'][path.relative_to(self.prefix).as_posix()] = linked.digest(path)
        for name in ('ffmpeg', 'zlib'):
            archive = self.prefix / 'corresponding-source' / (name + '.tar')
            archive.parent.mkdir(parents=True, exist_ok=True)
            archive.write_bytes(('corresponding ' + name).encode())
            sha = linked.digest(archive)
            (self.spec['ffmpeg'] if name == 'ffmpeg' else self.spec['dependencies'][name])['sha256'] = sha
            self.metadata['sources'][name] = {'archive': archive.name, 'sha256': sha}
            notices = self.prefix / 'licenses' / name / 'LICENSE'
            notices.parent.mkdir(parents=True, exist_ok=True)
            notices.write_text('original notice')
        self.metadata['source_provenance']['archive_sha256'] = self.spec['ffmpeg']['sha256']
        (self.source / 'runtime/linked').mkdir(parents=True)
        self.write()
        binary = types.SimpleNamespace(validate_file=lambda *_: {'format': 'archive'})
        runtime = types.SimpleNamespace(verify_sdk_spec=lambda *_: None, verified_runtime_dependencies=lambda *_: {})
        self.patcher = patch.object(linked, 'upstream', return_value=(binary, runtime))
        self.patcher.start()
        self.addCleanup(self.patcher.stop)

    def write(self):
        (self.source / 'runtime/linked/spec.json').write_text(json.dumps(self.spec))
        (self.prefix / 'linked-ffmpeg.json').write_text(json.dumps(self.metadata))

    def validate(self):
        return linked.validate_sdk(self.prefix, 'macos-arm64', 'gpl-software', self.source)

    def test_valid_override_keeps_original_sdk_and_current_spec_identity(self):
        result = self.validate()
        self.assertEqual(result['rust_target'], 'aarch64-apple-darwin')
        self.assertEqual(result['sdk_original_spec_sha256'], 'earlier-spec')
        self.assertEqual(result['native_qualification'], 'not_run')

    def test_corrupt_library_and_source_are_rejected(self):
        library = self.prefix / next(iter(self.metadata['libraries']))
        original = library.read_bytes()
        library.write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError, 'library hash mismatch'):
            self.validate()
        library.write_bytes(original)
        (self.prefix / 'corresponding-source/ffmpeg.tar').write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError, 'source hash mismatch'):
            self.validate()

    def test_wrong_target_profile_minimum_and_network_protocol_are_rejected(self):
        before = copy.deepcopy(self.metadata)
        for key, value in [('target', 'x86_64-apple-darwin'), ('profile', 'apple-lgpl'),
                           ('minimum', '14.0'), ('linkage', 'shared')]:
            self.metadata = copy.deepcopy(before)
            self.metadata[key] = value
            self.write()
            with self.assertRaisesRegex(ValueError, 'identity/profile/target'):
                self.validate()
        self.metadata = before
        self.metadata['components']['protocol'].append('http')
        self.write()
        with self.assertRaisesRegex(ValueError, 'network protocol'):
            self.validate()

    def test_missing_original_notices_and_source_inventory_are_rejected(self):
        (self.prefix / 'licenses/zlib/LICENSE').unlink()
        with self.assertRaisesRegex(ValueError, 'notices missing'):
            self.validate()

    def test_symlink_library_and_unsafe_receipt_path_are_rejected(self):
        library = self.prefix / next(iter(self.metadata['libraries']))
        saved = library.with_suffix('.saved')
        library.rename(saved)
        library.symlink_to(saved)
        with self.assertRaisesRegex(ValueError, 'linked or escaping'):
            self.validate()
        for name in ('../outside', '/absolute', 'lib\\outside', 'lib//empty'):
            with self.assertRaisesRegex(ValueError, 'Unsafe receipt path'):
                linked.checked_path(self.prefix, name)

    def test_duplicate_json_keys_are_rejected(self):
        path = self.root / 'duplicate.json'
        path.write_text('{"schema":1,"schema":2}')
        with self.assertRaisesRegex(ValueError, 'Duplicate JSON key'):
            linked.obj(path)

    def test_application_pin_matches_cargo_and_validator_is_immutable(self):
        import tomllib
        manifest = tomllib.loads((linked.ROOT / 'Cargo.toml').read_text())
        dependency = manifest['workspace']['dependencies']['avid-core']
        pin = linked.obj(linked.PIN)
        self.assertEqual(dependency['git'], pin['repository'])
        self.assertEqual(dependency['rev'], pin['revision'])
        self.assertEqual(dependency['version'], '=' + pin['version'])
        self.assertEqual(pin['abi_version'], 1)
        self.assertEqual(len(pin['binary_validator_sha256']), 64)


class OfflineStageTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        self.metadata = self.directory / 'EnCAPLinked'
        self.metadata.mkdir()
        validator = b"def validate_file(path, target):\n return {'format':'mach-o','arch':'arm64','dependencies':[]}\n"
        (self.metadata / 'validator').mkdir()
        (self.metadata / 'validator/binary.py').write_bytes(validator)
        specification = {'targets': [{'id': 'macos-arm64'}]}
        (self.metadata / 'linked-spec.json').write_text(json.dumps(specification))
        pin = {'revision': '1' * 40, 'binary_validator_sha256': hashlib.sha256(validator).hexdigest(),
               'spec_sha256': linked.digest(self.metadata / 'linked-spec.json')}
        (self.metadata / 'core-source.json').write_text(json.dumps(pin))
        self.pin = self.directory / 'pin.json'
        self.pin.write_text(json.dumps(pin))
        (self.metadata / 'linked-ffmpeg.json').write_text('{}')
        self.library = self.directory / 'libencap_app.dylib'
        self.library.write_bytes(b'original ad-hoc signed binary fixture')
        receipt = {'schema': 1, 'kind': 'encap-linked-application-build', 'core': pin,
                   'sdk': {'target': 'macos-arm64', 'rust_target': 'aarch64-apple-darwin',
                           'metadata_sha256': linked.digest(self.metadata / 'linked-ffmpeg.json')},
                   'source': {'files': {}, 'sha256': hashlib.sha256(b'{}').hexdigest()},
                   'library': {'sha256': linked.digest(self.library), 'code_sha256': 'same-code',
                               'identity': {'format': 'mach-o', 'arch': 'arm64', 'dependencies': []}}}
        (self.metadata / 'build-receipt.json').write_text(json.dumps(receipt))
        (self.metadata / 'corresponding-source').mkdir()
        with tarfile.open(self.metadata / 'corresponding-source/avid-core.tar', 'w') as archive:
            member = tarfile.TarInfo('scripts/linked/binary.py')
            member.size = len(validator)
            archive.addfile(member, io.BytesIO(validator))
        (self.metadata / 'qualification.json').write_text('{"status":"development-unqualified"}')
        files = {path.relative_to(self.metadata).as_posix(): linked.digest(path)
                 for path in self.metadata.rglob('*') if path.is_file()}
        (self.metadata / 'SHA256.json').write_text(json.dumps(files))
        self.arguments = types.SimpleNamespace(directory=self.directory, bind_signature=False, require_qualified=False)
        patcher = patch.object(linked, 'PIN', self.pin)
        patcher.start()
        self.addCleanup(patcher.stop)
        patcher = patch.object(linked, 'normalized_code', return_value='same-code')
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_repeated_offline_verification_does_not_write_into_sealed_metadata(self):
        before = {path.relative_to(self.metadata).as_posix(): linked.digest(path)
                  for path in self.metadata.rglob('*') if path.is_file()}
        self.assertEqual(linked.verify_stage(self.arguments)['status'], 'verified')
        self.assertEqual(linked.verify_stage(self.arguments)['status'], 'verified')
        after = {path.relative_to(self.metadata).as_posix(): linked.digest(path)
                 for path in self.metadata.rglob('*') if path.is_file()}
        self.assertEqual(before, after)
        (self.metadata / 'validator/extra.pyc').write_bytes(b'unexpected')
        with self.assertRaisesRegex(ValueError, 'inventory differs'):
            linked.verify_stage(self.arguments)

    def test_signature_rebinding_requires_matching_code_and_preserves_bound_raw_hash(self):
        self.library.write_bytes(b'same-code fixture with a new signature')
        with self.assertRaisesRegex(ValueError, 'raw hash differs'):
            linked.verify_stage(self.arguments)
        self.arguments.bind_signature = True
        with patch.object(linked.subprocess, 'run') as signing:
            self.assertTrue(linked.verify_stage(self.arguments)['signed_hash_bound'])
        signing.assert_called_once()
        self.arguments.bind_signature = False
        self.assertEqual(linked.verify_stage(self.arguments)['status'], 'verified')
        self.library.write_bytes(b'changed after signature binding')
        with self.assertRaisesRegex(ValueError, 'raw hash differs'):
            linked.verify_stage(self.arguments)

    def test_changed_code_cannot_be_blessed_by_signature_binding(self):
        self.arguments.bind_signature = True
        with patch.object(linked, 'normalized_code', return_value='different-code'), \
             patch.object(linked.subprocess, 'run') as signing:
            with self.assertRaisesRegex(ValueError, 'code differs'):
                linked.verify_stage(self.arguments)
        signing.assert_not_called()

    def test_unqualified_stage_cannot_be_distribution_qualified(self):
        self.arguments.require_qualified = True
        with self.assertRaisesRegex(ValueError, 'migration is unqualified'):
            linked.verify_stage(self.arguments)

    def test_macos_bundle_keeps_only_code_in_frameworks_and_metadata_in_resources(self):
        contents = self.directory / 'EnCap.app/Contents'
        frameworks = contents / 'Frameworks'
        resources = contents / 'Resources'
        frameworks.mkdir(parents=True)
        resources.mkdir()
        self.library = self.library.rename(frameworks / self.library.name)
        self.metadata = self.metadata.rename(resources / 'EnCAPLinked')
        self.arguments.directory = frameworks
        self.assertEqual(linked.metadata_directory(frameworks), resources / 'EnCAPLinked')
        self.assertEqual(linked.verify_stage(self.arguments)['status'], 'verified')
        self.assertEqual(linked.verify_stage(self.arguments)['status'], 'verified')
        self.assertEqual({path.name for path in frameworks.iterdir()}, {'libencap_app.dylib'})
        self.assertFalse((frameworks / 'EnCAPLinked').exists())

    def test_non_bundle_library_metadata_remains_adjacent(self):
        self.assertEqual(linked.metadata_directory(self.directory), self.directory / 'EnCAPLinked')


if __name__ == '__main__':
    unittest.main()
