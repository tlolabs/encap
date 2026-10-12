#!/usr/bin/env python3
"""Fail-closed tests for independent AVID Core platform release acquisition."""
import copy
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import platform_runtime as runtime
import ffmpeg_runtime as app_runtime


class PlatformRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.target = 'macos-arm64'
        self.record, self.base = runtime.record_for(self.target)

    def test_each_target_is_independently_pinned(self):
        pins = runtime.obj(runtime.PINS)
        self.assertEqual(set(pins['targets']), runtime.TARGETS)
        for target in runtime.TARGETS:
            record, base = runtime.record_for(target, pins)
            self.assertIn(target, record['release_tag'])
            self.assertIn(target, base)
            self.assertEqual(record['build_run'], 38185320964)
            self.assertEqual(runtime.plan_for(target)['targets'][target]['checksums_sha256'],
                             record['checksums_sha256'])
        changed = copy.deepcopy(pins)
        changed['targets']['windows-arm64']['version'] = '10.0.0'
        with self.assertRaisesRegex(ValueError, 'Invalid platform release identity'):
            runtime.record_for('windows-arm64', changed)
        self.assertEqual(runtime.record_for('linux-x86_64', changed)[0]['version'], '9.0.1')
        target_only = copy.deepcopy(pins)
        target_only['targets'] = {'linux-x86_64': pins['targets']['linux-x86_64']}
        self.assertEqual(runtime.record_for('linux-x86_64', target_only)[0]['release_tag'],
                         pins['targets']['linux-x86_64']['release_tag'])

    def test_release_origin_checks_are_target_local(self):
        record = self.record
        tag = record['release_tag']
        run = record['build_run']
        assets = [{'name': name, 'id': asset['id'], 'state': 'uploaded',
                   'size': asset['size'], 'digest': 'sha256:' + asset['sha256']}
                  for name, asset in record['assets'].items()]
        response = {
            f'repos/{runtime.REPOSITORY}/releases/tags/{tag}': {
                'id': record['release_id'], 'tag_name': tag, 'immutable': True,
                'draft': False, 'prerelease': False, 'assets': assets},
            f'repos/{runtime.REPOSITORY}/git/ref/tags/{tag}': {
                'object': {'type': 'commit', 'sha': record['release_revision']}},
            f'repos/{runtime.REPOSITORY}/actions/runs/{run}': {
                'id': run, 'run_attempt': record['build_attempt'],
                'head_sha': record['build_revision'], 'head_branch': 'main',
                'event': 'push', 'path': '.github/workflows/ffmpeg.yml',
                'repository': {'full_name': runtime.REPOSITORY},
                'head_repository': {'full_name': runtime.REPOSITORY},
                'conclusion': 'failure'},  # An unrelated platform may have failed.
            f'repos/{runtime.REPOSITORY}/actions/runs/{run}/jobs?per_page=100': {
                'jobs': [{'id': record['native_job_id'], 'name': f'build ({self.target})',
                          'conclusion': 'success', 'steps': [
                              {'name': 'Build and validate native Unix runtime', 'conclusion': 'success'},
                              {'name': 'Upload validated Core runtime candidate and corresponding source',
                               'conclusion': 'success'}]}]},
            f'repos/{runtime.REPOSITORY}/actions/runs/{run}/artifacts?per_page=100': {
                'artifacts': [{'id': record['artifact_id'], 'name': f'core-runtime-candidate-{self.target}',
                               'expired': False, 'digest': 'sha256:' + record['artifact_zip_sha256'],
                               'workflow_run': {'id': run, 'head_sha': record['build_revision']}}]}}
        runtime.verify_origin(self.target, record, response.__getitem__)
        durable = {key: value for key, value in response.items() if '/actions/' not in key}
        runtime.verify_origin(self.target, record, durable.__getitem__, audit_live_build=False)
        changed = copy.deepcopy(response)
        changed[f'repos/{runtime.REPOSITORY}/releases/tags/{tag}']['immutable'] = False
        with self.assertRaisesRegex(ValueError, 'mutable'):
            runtime.verify_origin(self.target, record, changed.__getitem__)
        changed = copy.deepcopy(response)
        changed[f'repos/{runtime.REPOSITORY}/releases/tags/{tag}']['assets'].pop()
        with self.assertRaisesRegex(ValueError, 'Unexpected release assets'):
            runtime.verify_origin(self.target, record, changed.__getitem__)
        changed = copy.deepcopy(response)
        changed[f'repos/{runtime.REPOSITORY}/actions/runs/{run}/jobs?per_page=100']['jobs'][0]['conclusion'] = 'failure'
        with self.assertRaisesRegex(ValueError, 'native validation'):
            runtime.verify_origin(self.target, record, changed.__getitem__)
        changed = copy.deepcopy(response)
        changed[f'repos/{runtime.REPOSITORY}/actions/runs/{run}/artifacts?per_page=100']['artifacts'][0]['digest'] = 'sha256:' + '0' * 64
        with self.assertRaisesRegex(ValueError, 'origin'):
            runtime.verify_origin(self.target, record, changed.__getitem__)
        changed = copy.deepcopy(response)
        changed[f'repos/{runtime.REPOSITORY}/git/ref/tags/{tag}']['object']['sha'] = '0' * 40
        with self.assertRaisesRegex(ValueError, 'Release tag changed'):
            runtime.verify_origin(self.target, record, changed.__getitem__)
        changed = copy.deepcopy(response)
        changed[f'repos/{runtime.REPOSITORY}/actions/runs/{run}']['head_sha'] = '0' * 40
        with self.assertRaisesRegex(ValueError, 'Untrusted build run'):
            runtime.verify_origin(self.target, record, changed.__getitem__)
        changed = copy.deepcopy(response)
        changed[f'repos/{runtime.REPOSITORY}/actions/runs/{run}']['path'] = '.github/workflows/untrusted.yml'
        with self.assertRaisesRegex(ValueError, 'Untrusted build run'):
            runtime.verify_origin(self.target, record, changed.__getitem__)

    def test_invalid_provenance_and_checksums(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            name = 'platform-release.json'
            (directory / name).write_text('{}')
            with self.assertRaisesRegex(ValueError, 'differs from pin'):
                runtime.verify_provenance(self.target, self.record, self.base, directory / name)
            authentic = {'schema': 1, 'kind': 'direct-download-platform',
                         'repository': runtime.REPOSITORY, 'target': self.target,
                         'build_run': self.record['build_run'], 'build_attempt': self.record['build_attempt'],
                         'build_revision': self.record['build_revision'],
                         'native_job_id': self.record['native_job_id'], 'artifact_id': self.record['artifact_id'],
                         'artifact_zip_sha256': self.record['artifact_zip_sha256'],
                         'spec_sha256': self.record['spec_sha256'],
                         'runtime_archive': self.base + '.tar.gz',
                         'runtime_sha256': self.record['assets'][self.base + '.tar.gz']['sha256'],
                         'source_archive': self.base + '-sources.tar.gz',
                         'source_sha256': self.record['assets'][self.base + '-sources.tar.gz']['sha256']}
            for field, value in [('target', 'windows-arm64'), ('build_revision', '0' * 40),
                                 ('build_run', 0), ('runtime_sha256', '0' * 64)]:
                altered = dict(authentic, **{field: value})
                (directory / name).write_text(__import__('json').dumps(altered))
                with self.assertRaisesRegex(ValueError, 'differs from pin'):
                    runtime.verify_provenance(self.target, self.record, self.base, directory / name)
            for asset_name in self.record['assets']:
                (directory / asset_name).write_bytes(b'corrupt')
            with self.assertRaisesRegex(ValueError, 'differs from pin'):
                runtime.checked_asset(self.record, name, directory)
            (directory / 'SHA256SUMS').write_text('0' * 64 + '  extra\n')
            with self.assertRaisesRegex(ValueError, 'missing or extra'):
                runtime.verify_checksums(self.record, self.base, directory)

    def test_wrong_executable_architecture_is_rejected(self):
        from core_runtime import machine
        with tempfile.TemporaryDirectory() as temporary:
            executable = Path(temporary) / 'ffmpeg'
            executable.write_bytes(b'\xcf\xfa\xed\xfe' + (0x1000007).to_bytes(4, 'little'))
            with self.assertRaisesRegex(ValueError, 'Wrong executable architecture'):
                machine(executable, 'macos-arm64')

    def test_missing_attestation_stops_before_binary_download(self):
        calls = []
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary) / 'runtime'
            def fake_download(tag, name, directory):
                calls.append(name)
                if name == 'platform-release.json':
                    # The real file is pinned, but attestation failure must be decisive.
                    (directory / name).write_bytes(b'metadata')
            with patch.object(runtime, 'verify_origin'), patch.object(runtime, 'download', fake_download), \
                 patch.object(runtime, 'checked_asset', return_value=Path(temporary) / 'platform-release.json'), \
                 patch.object(runtime, 'verify_attestation', side_effect=subprocess.CalledProcessError(1, 'gh')):
                with self.assertRaises(subprocess.CalledProcessError):
                    runtime.acquire(self.target, destination)
            self.assertEqual(calls, ['platform-release.json'])
            self.assertFalse(destination.exists())
            destination.mkdir()
            with self.assertRaisesRegex(ValueError, 'Fresh platform acquisition'):
                runtime.acquire(self.target, destination)

    def test_network_failure_does_not_leave_partial_destination(self):
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary) / 'runtime'
            def partial_download(_tag, name, staging):
                (staging / name).write_bytes(b'partial')
                raise subprocess.CalledProcessError(1, 'gh')
            with patch.object(runtime, 'verify_origin'), \
                 patch.object(runtime, 'download', side_effect=partial_download):
                with self.assertRaises(subprocess.CalledProcessError):
                    runtime.acquire(self.target, destination)
            self.assertFalse(destination.exists())

    def test_cached_manifest_is_checked_before_reuse(self):
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary)
            (destination / 'platform-release.json').write_bytes(b'changed manifest')
            with patch.object(runtime, 'verify_origin'):
                with self.assertRaisesRegex(ValueError, 'differs from pin'):
                    runtime.verify_cached(self.target, destination)

    def test_legacy_fallback_requires_explicit_selection(self):
        with patch.dict(os.environ, {'ENCAP_CORE_RUNTIME_SOURCE': 'platform'}):
            self.assertEqual(app_runtime.selected_plan(self.target)['targets'][self.target]['sha256'],
                             self.record['assets'][self.base + '.tar.gz']['sha256'])
        with patch.dict(os.environ, {'ENCAP_CORE_RUNTIME_SOURCE': 'legacy'}):
            self.assertIs(app_runtime.selected_plan(self.target), app_runtime.PIN)
        with patch.dict(os.environ, {'ENCAP_CORE_RUNTIME_SOURCE': 'untrusted'}):
            with self.assertRaisesRegex(ValueError, 'Unknown AVID Core runtime source'):
                app_runtime.selected_plan(self.target)

    def test_attestation_command_is_bound_to_pinned_source(self):
        with patch.object(runtime.subprocess, 'run') as run:
            runtime.verify_attestation(self.record, Path('/tmp/platform-release.json'))
        command = run.call_args.args[0]
        self.assertEqual(command[:3], ['gh', 'attestation', 'verify'])
        self.assertEqual(command[command.index('--source-digest') + 1], self.record['release_revision'])
        self.assertEqual(command[command.index('--source-ref') + 1], 'refs/heads/main')
        self.assertIn('--deny-self-hosted-runners', command)


if __name__ == '__main__':
    unittest.main()
